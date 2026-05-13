"""Tenant-Isolation-Enforcer: Per-Hotel-State-Boundary [CRUX-MK].

NEGATIVE-LOGIC-TRACE: Prueft Cross-Tenant-Reads aktiv und blockt sie.

Pre-Conditions:
- tenant_id auf TenantContext gesetzt vor jedem Read
- TenantContext immutable nach __post_init__

Post-Conditions:
- read_state(tenant_id) blockiert wenn current_tenant != tenant_id
- raises CrossTenantAccessError bei Verletzung
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional


class CrossTenantAccessError(Exception):
    """Raised when a tenant tries to read another tenant's state.

    Welle-47 NEGATIVE-Test pflichtig:
    - tenant-A read tenant-B → CrossTenantAccessError
    - assert empty result + audit-log-entry
    """


@dataclass(frozen=True)
class TenantContext:
    """Frozen Tenant-Context. Immutable per Session."""

    tenant_id: str
    region: str

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id required")


class TenantIsolationEnforcer:
    """Per-Hotel-State-Boundary enforcer.

    Pattern: thread-local context, alle State-Reads pruefen current_tenant.
    """

    _local = threading.local()

    @classmethod
    def set_context(cls, ctx: TenantContext) -> None:
        cls._local.context = ctx

    @classmethod
    def get_context(cls) -> Optional[TenantContext]:
        return getattr(cls._local, "context", None)

    @classmethod
    def clear_context(cls) -> None:
        if hasattr(cls._local, "context"):
            del cls._local.context

    @classmethod
    def enforce_read(cls, requested_tenant: str) -> None:
        """Block cross-tenant reads.

        Raises CrossTenantAccessError when ctx.tenant_id != requested_tenant.
        NEGATIVE-Logic-Trace per AIV.
        """
        ctx = cls.get_context()
        if ctx is None:
            raise CrossTenantAccessError(
                f"No tenant context set, but attempting read for {requested_tenant}"
            )
        if ctx.tenant_id != requested_tenant:
            raise CrossTenantAccessError(
                f"Cross-tenant access blocked: ctx={ctx.tenant_id}, "
                f"requested={requested_tenant}"
            )


class IsolatedStateStore:
    """Per-tenant-scoped state store. NEGATIVE-Test-verifiziert."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, object]] = {}

    def write(self, tenant_id: str, key: str, value: object) -> None:
        """Write value scoped to tenant_id. Enforces context."""
        TenantIsolationEnforcer.enforce_read(tenant_id)  # also enforces write
        if tenant_id not in self._state:
            self._state[tenant_id] = {}
        self._state[tenant_id][key] = value

    def read(self, tenant_id: str, key: str) -> Optional[object]:
        """Read value scoped to tenant_id. Enforces context.

        NEGATIVE-Test: cross-tenant read → raises CrossTenantAccessError.
        """
        TenantIsolationEnforcer.enforce_read(tenant_id)
        return self._state.get(tenant_id, {}).get(key)

    def list_tenants(self) -> list[str]:
        """Admin: list all tenants with state. NO enforcement (admin-API)."""
        return list(self._state.keys())
