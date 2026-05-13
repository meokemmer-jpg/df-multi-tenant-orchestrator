"""P1+P3 Foundation-Service-Integration-Tests [CRUX-MK]."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from phronesis_gate import (
    check_phronesis_gate,
    build_audit_envelope,
    FOUNDATION_AVAILABLE,
    OPERATION_TYPE,
)


def test_foundation_imports_available():
    assert FOUNDATION_AVAILABLE


def test_p1_phronesis_blocked_without_ticket(monkeypatch):
    monkeypatch.delenv("PHRONESIS_TICKET", raising=False)
    monkeypatch.setenv("PHRONESIS_SECRET", "a" * 32)
    result = check_phronesis_gate()
    assert result["status"] == "blocked"


def test_p1_phronesis_blocked_without_secret(monkeypatch):
    monkeypatch.delenv("PHRONESIS_SECRET", raising=False)
    monkeypatch.setenv("PHRONESIS_TICKET", "fake-ticket-string")
    result = check_phronesis_gate()
    assert result["status"] == "blocked"


def test_p1_phronesis_allowed_with_valid_ticket(monkeypatch):
    if not FOUNDATION_AVAILABLE:
        pytest.skip("Foundation unavailable")
    from _df_common.phronesis_ticket_signer import PhronesisTicketSigner
    secret = "test-secret-min-16-chars-long" + "x" * 8
    monkeypatch.setenv("PHRONESIS_SECRET", secret)
    signer = PhronesisTicketSigner(secret=secret)
    ticket = signer.issue(OPERATION_TYPE, ttl_seconds=3600)
    monkeypatch.setenv("PHRONESIS_TICKET", signer.serialize(ticket))
    result = check_phronesis_gate()
    assert result["status"] == "allowed"


def test_p3_envelope_build(monkeypatch):
    if not FOUNDATION_AVAILABLE:
        pytest.skip("Foundation unavailable")
    monkeypatch.setenv("PHRONESIS_SECRET", "x" * 32)
    env = build_audit_envelope({"tenant": "hotel-001", "action": "dispatch"}, tenant_id="hotel-001")
    assert env is not None
    assert env.tenant_id == "hotel-001"
    assert env.signature
