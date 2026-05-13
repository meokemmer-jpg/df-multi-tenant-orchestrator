"""Tests for DF-Multi-Tenant-Orchestrator [CRUX-MK].

>= 14 Tests covering:
- HotelRegistry: register, lookup, idempotency, validation
- ParallelDispatcher: parallel exec, timeout, error isolation
- TenantIsolation: cross-tenant-read-blocked (NEGATIVE)
- AuditLogger: append, read, JSONL format
- Adapter: end-to-end run_once
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audit_logger import AuditLogger
from src.multi_tenant_orchestrator import (
    HotelRecord,
    HotelRegistry,
    ParallelDispatcher,
    is_real_mode_enabled,
)
from src.tenant_isolation_enforcer import (
    CrossTenantAccessError,
    IsolatedStateStore,
    TenantContext,
    TenantIsolationEnforcer,
)


# ============================================================
# HotelRegistry Tests (4)
# ============================================================

def test_registry_register_and_lookup() -> None:
    """Test 1: Register hotel + lookup retrieves it."""
    reg = HotelRegistry()
    h = HotelRecord(tenant_id="t1", name="Hotel-1", region="DE")
    reg.register(h)
    assert reg.lookup("t1") == h
    assert reg.lookup("missing") is None


def test_registry_idempotent_register() -> None:
    """Test 2: Re-register same tenant_id with same data = no-op."""
    reg = HotelRegistry()
    h = HotelRecord(tenant_id="t1", name="Hotel-1", region="DE")
    reg.register(h)
    reg.register(h)  # should not raise
    assert reg.count() == 1


def test_registry_rejects_conflicting_data() -> None:
    """Test 3: Re-register with different data raises ValueError."""
    reg = HotelRegistry()
    reg.register(HotelRecord(tenant_id="t1", name="Hotel-1", region="DE"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(HotelRecord(tenant_id="t1", name="Hotel-2", region="DE"))


def test_registry_validates_region() -> None:
    """Test 4: Invalid region rejected at __post_init__."""
    with pytest.raises(ValueError, match="Invalid region"):
        HotelRecord(tenant_id="t1", name="Hotel-1", region="INVALID")


# ============================================================
# ParallelDispatcher Tests (4)
# ============================================================

def test_dispatcher_parallel_execution() -> None:
    """Test 5: All hotels processed in parallel."""
    dispatcher = ParallelDispatcher(max_concurrent=3, timeout_s=10)
    hotels = [
        HotelRecord(tenant_id=f"t{i}", name=f"H-{i}", region="DE") for i in range(3)
    ]

    def task(h: HotelRecord) -> dict:
        return {"tenant_id": h.tenant_id}

    results = dispatcher.dispatch(hotels, task)
    assert len(results) == 3
    for tid in ["t0", "t1", "t2"]:
        assert results[tid]["status"] == "ok"
        assert results[tid]["result"]["tenant_id"] == tid


def test_dispatcher_error_isolation() -> None:
    """Test 6: One hotel's failure does NOT abort others (LC4)."""
    dispatcher = ParallelDispatcher(max_concurrent=3, timeout_s=10)
    hotels = [
        HotelRecord(tenant_id="t1", name="H-1", region="DE"),
        HotelRecord(tenant_id="t2", name="H-2", region="DE"),
    ]

    def task(h: HotelRecord) -> dict:
        if h.tenant_id == "t1":
            raise RuntimeError("simulated failure")
        return {"ok": True}

    results = dispatcher.dispatch(hotels, task)
    assert results["t1"]["status"] == "error"
    assert "simulated failure" in results["t1"]["error"]
    assert results["t2"]["status"] == "ok"


def test_dispatcher_validates_max_concurrent() -> None:
    """Test 7: max_concurrent capped at 10 (K16 protection)."""
    with pytest.raises(ValueError, match="max_concurrent must be 1..10"):
        ParallelDispatcher(max_concurrent=11)
    with pytest.raises(ValueError, match="max_concurrent must be 1..10"):
        ParallelDispatcher(max_concurrent=0)


def test_dispatcher_timeout_validation() -> None:
    """Test 8: timeout_s bounded 5..300."""
    with pytest.raises(ValueError, match="timeout_s must be 5..300"):
        ParallelDispatcher(timeout_s=4)
    with pytest.raises(ValueError, match="timeout_s must be 5..300"):
        ParallelDispatcher(timeout_s=301)


# ============================================================
# TenantIsolation Tests (4) - NEGATIVE-LOGIC-TRACE
# ============================================================

def test_isolation_blocks_cross_tenant_read() -> None:
    """Test 9: NEGATIVE - cross-tenant read raises CrossTenantAccessError."""
    TenantIsolationEnforcer.set_context(TenantContext(tenant_id="t1", region="DE"))
    try:
        with pytest.raises(CrossTenantAccessError, match="Cross-tenant access blocked"):
            TenantIsolationEnforcer.enforce_read("t2")
    finally:
        TenantIsolationEnforcer.clear_context()


def test_isolation_allows_same_tenant_read() -> None:
    """Test 10: Same-tenant read succeeds."""
    TenantIsolationEnforcer.set_context(TenantContext(tenant_id="t1", region="DE"))
    try:
        TenantIsolationEnforcer.enforce_read("t1")  # no raise
    finally:
        TenantIsolationEnforcer.clear_context()


def test_isolation_blocks_no_context() -> None:
    """Test 11: NEGATIVE - read without context raises CrossTenantAccessError."""
    TenantIsolationEnforcer.clear_context()
    with pytest.raises(CrossTenantAccessError, match="No tenant context"):
        TenantIsolationEnforcer.enforce_read("t1")


def test_isolated_state_store_cross_tenant_blocked() -> None:
    """Test 12: NEGATIVE - IsolatedStateStore prevents cross-tenant read."""
    store = IsolatedStateStore()
    TenantIsolationEnforcer.set_context(TenantContext(tenant_id="t1", region="DE"))
    try:
        store.write("t1", "key1", "value-1")
        assert store.read("t1", "key1") == "value-1"
        # Try cross-tenant read
        with pytest.raises(CrossTenantAccessError):
            store.read("t2", "key1")
    finally:
        TenantIsolationEnforcer.clear_context()


# ============================================================
# AuditLogger Tests (2)
# ============================================================

def test_audit_logger_append_and_read() -> None:
    """Test 13: Append + read JSONL audit-trail."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        audit = AuditLogger(path)
        audit.log({"event": "test_event", "data": "value"})
        audit.log({"event": "test_event_2"})

        entries = audit.read_all()
        assert len(entries) == 2
        assert entries[0]["event"] == "test_event"
        assert entries[0]["df_id"] == "df-multi-tenant-orchestrator"
        assert "ts" in entries[0]
        assert "iso_ts" in entries[0]


def test_audit_logger_thread_safe() -> None:
    """Test 14: Concurrent appends do not corrupt file."""
    from concurrent.futures import ThreadPoolExecutor

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        audit = AuditLogger(path)

        def write_n(n: int) -> None:
            for i in range(10):
                audit.log({"event": f"thread-{n}-iter-{i}"})

        with ThreadPoolExecutor(max_workers=5) as ex:
            for n in range(5):
                ex.submit(write_n, n)

        entries = audit.read_all()
        assert len(entries) == 50


# ============================================================
# Integration Test (1) - end-to-end
# ============================================================

def test_real_mode_default_disabled() -> None:
    """Test 15: ENV-Var-Gated-Real-Integration-Default = false by default."""
    os.environ.pop("DF_MULTI_TENANT_REAL_HOTELS_ENABLED", None)
    assert is_real_mode_enabled() is False
    # Test "true" string activation
    os.environ["DF_MULTI_TENANT_REAL_HOTELS_ENABLED"] = "true"
    assert is_real_mode_enabled() is True
    # Test other truthy strings rejected
    os.environ["DF_MULTI_TENANT_REAL_HOTELS_ENABLED"] = "1"
    assert is_real_mode_enabled() is False
    os.environ.pop("DF_MULTI_TENANT_REAL_HOTELS_ENABLED", None)


# ============================================================
# W49-D K12+K13 Migration Tests
# ============================================================

def test_w49d_k12_envelope_and_k13_anchor() -> None:
    """K12: FullProvenanceEnvelope + K13: RFC3161 anchor written via AuditLogger."""
    from src.audit_logger import W49D_FOUNDATION
    with tempfile.TemporaryDirectory() as tmp:
        audit = AuditLogger(Path(tmp) / "audit.jsonl")
        audit.log({"event": "dispatch", "n_hotels": 5})
        # Build envelope -> returns payload_hash (or None if foundation missing)
        chain_hash = audit.envelope_run(
            run_id="w49d-test-run-001",
            payload={"event": "dispatch", "n_hotels": 5},
        )
        if W49D_FOUNDATION:
            assert chain_hash is not None and len(chain_hash) >= 32
            prov_dir = Path(tmp) / "provenance-full"
            assert prov_dir.exists()
            envs = list(prov_dir.glob("*.envelope.json"))
            assert len(envs) == 1, f"K12 envelope must be persisted, got {len(envs)}"
            # K13 anchor
            ok = audit.anchor_run(chain_hash)
            assert ok is True
            anchor_file = Path(tmp) / "anchors" / "rfc3161-anchors.jsonl"
            assert anchor_file.exists()
            assert anchor_file.read_text().strip()
        else:
            assert chain_hash is None
