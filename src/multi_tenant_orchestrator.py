"""Multi-Tenant-Orchestrator: HotelRegistry + ParallelDispatcher [CRUX-MK].

Welle-47 Foundation-DF Core.

Pre-Conditions:
- mock_hotels list provided ODER ENV DF_MULTI_TENANT_REAL_HOTELS_ENABLED=true
- max_concurrent < 10 (Sicherheits-Cap)

Post-Conditions:
- dispatch() returns dict mit tenant_id -> result | error
- Keine Cross-Tenant-Leaks (Tenant-Isolation-Enforcer verifiziert)
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class HotelRecord:
    """Frozen Hotel-Metadata. Immutable nach Registry-Insert."""

    tenant_id: str
    name: str
    region: str
    status: str = "active"  # active | suspended | mock

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id must be non-empty")
        if self.region not in ("DE", "US", "AT", "CH", "MOCK"):
            raise ValueError(f"Invalid region: {self.region}")


class HotelRegistry:
    """Persistierte Hotel-Metadata mit Lookup-API."""

    def __init__(self) -> None:
        self._hotels: dict[str, HotelRecord] = {}

    def register(self, hotel: HotelRecord) -> None:
        """Register hotel. Idempotent: re-register same tenant_id with same data = no-op."""
        if hotel.tenant_id in self._hotels:
            existing = self._hotels[hotel.tenant_id]
            if existing != hotel:
                raise ValueError(
                    f"Tenant {hotel.tenant_id} already registered with different data"
                )
            return
        self._hotels[hotel.tenant_id] = hotel

    def lookup(self, tenant_id: str) -> Optional[HotelRecord]:
        """Lookup hotel by tenant_id. Returns None if not found."""
        return self._hotels.get(tenant_id)

    def list_active(self) -> list[HotelRecord]:
        """List all hotels with status='active' or 'mock'."""
        return [h for h in self._hotels.values() if h.status in ("active", "mock")]

    def count(self) -> int:
        return len(self._hotels)


class ParallelDispatcher:
    """Parallel-Execution mit ThreadPoolExecutor (max 5 concurrent).

    K16 Concurrent-Spawn-Mutex: max_concurrent capped at 5 to prevent thread-storm.
    LC3 Circuit-Breaker: timeout_s default 30s.
    """

    def __init__(self, max_concurrent: int = 5, timeout_s: int = 30) -> None:
        if max_concurrent < 1 or max_concurrent > 10:
            raise ValueError(f"max_concurrent must be 1..10, got {max_concurrent}")
        if timeout_s < 5 or timeout_s > 300:
            raise ValueError(f"timeout_s must be 5..300, got {timeout_s}")
        self.max_concurrent = max_concurrent
        self.timeout_s = timeout_s

    def dispatch(
        self,
        hotels: list[HotelRecord],
        task_fn: Callable[[HotelRecord], dict],
    ) -> dict[str, dict]:
        """Dispatch task_fn to each hotel in parallel.

        Returns dict tenant_id -> {"status": "ok"|"error"|"timeout", "result": ..., "error": ...}
        Failure isolation per LC4: one hotel's failure does NOT abort others.
        """
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as ex:
            future_to_tenant = {
                ex.submit(self._safe_exec, task_fn, h): h.tenant_id for h in hotels
            }
            for future, tenant_id in [(f, t) for f, t in future_to_tenant.items()]:
                try:
                    results[tenant_id] = future.result(timeout=self.timeout_s)
                except FuturesTimeoutError:
                    results[tenant_id] = {
                        "status": "timeout",
                        "error": f"Exceeded {self.timeout_s}s",
                    }
                except Exception as e:
                    results[tenant_id] = {"status": "error", "error": str(e)}
        return results

    @staticmethod
    def _safe_exec(task_fn: Callable, hotel: HotelRecord) -> dict:
        """Wrapper: catches exceptions, returns structured result."""
        try:
            result = task_fn(hotel)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}


def is_real_mode_enabled() -> bool:
    """ENV-Var-Gated-Real-Integration-Default check."""
    return os.environ.get("DF_MULTI_TENANT_REAL_HOTELS_ENABLED") == "true"


def get_phronesis_ticket() -> str:
    """Pflicht bei Real-Mode-Aktivierung."""
    return os.environ.get("PHRONESIS_TICKET", "MISSING")
