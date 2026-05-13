"""Adapter-Orchestrator: LaunchAgent Entry-Point [CRUX-MK]."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from .audit_logger import AuditLogger
from .multi_tenant_orchestrator import (
    HotelRecord,
    HotelRegistry,
    ParallelDispatcher,
    is_real_mode_enabled,
)
from .tenant_isolation_enforcer import TenantContext, TenantIsolationEnforcer


def load_mock_hotels() -> list[HotelRecord]:
    """Sandbox-Mock-Default: 5 Mock-Hotels."""
    return [
        HotelRecord(tenant_id="hildesheim", name="HeyLou Hildesheim", region="DE", status="mock"),
        HotelRecord(tenant_id="cape-coral", name="HeyLou Cape Coral", region="US", status="mock"),
        HotelRecord(tenant_id="munich", name="HeyLou Munich", region="DE", status="mock"),
        HotelRecord(tenant_id="mock-4", name="HeyLou Mock-4", region="DE", status="mock"),
        HotelRecord(tenant_id="mock-5", name="HeyLou Mock-5", region="AT", status="mock"),
    ]


def task_fn(hotel: HotelRecord) -> dict:
    """Mock-Task: simple per-hotel health-check (Sandbox-Mode)."""
    TenantIsolationEnforcer.set_context(TenantContext(tenant_id=hotel.tenant_id, region=hotel.region))
    try:
        # Mock: no real network call
        time.sleep(0.01)
        return {
            "tenant_id": hotel.tenant_id,
            "name": hotel.name,
            "region": hotel.region,
            "checked_at": int(time.time()),
            "source": "mock",
        }
    finally:
        TenantIsolationEnforcer.clear_context()


def run_once(audit_path: Path) -> dict[str, dict]:
    """LaunchAgent Entry-Point: orchestrate 5 mock hotels in parallel."""
    audit = AuditLogger(audit_path)

    audit.log({
        "event": "run_start",
        "real_mode_enabled": is_real_mode_enabled(),
    })

    registry = HotelRegistry()
    for h in load_mock_hotels():
        registry.register(h)

    dispatcher = ParallelDispatcher(max_concurrent=5, timeout_s=30)
    hotels = registry.list_active()
    results = dispatcher.dispatch(hotels, task_fn)

    audit.log({
        "event": "run_complete",
        "hotels_processed": len(hotels),
        "results_summary": {
            tid: r.get("status") for tid, r in results.items()
        },
    })

    return results


def main() -> int:
    """CLI entry-point."""
    audit_path = Path.home() / ".df-multi-tenant-orchestrator" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    results = run_once(audit_path)
    success = all(r.get("status") == "ok" for r in results.values())
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
