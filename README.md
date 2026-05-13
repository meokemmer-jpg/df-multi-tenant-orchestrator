# DF-Multi-Tenant-Orchestrator [CRUX-MK]

**Welle-47 Foundation-DF** — Orchestriert 5+ Hotels parallel (HeyLou + 9OS + Mosaic) mit Per-Hotel-State-Boundary.

## Purpose

Multi-Hotel-Skaling Foundation: Verwaltet HotelRegistry, ParallelDispatcher und Tenant-Isolation-Enforcer
fuer 5+ Hotels gleichzeitig in Sandbox-Mock-Mode (Hildesheim + Cape-Coral + Munich + 2 weitere).

## Architecture

```
HotelRegistry        → Persistierte Hotel-Metadata (tenant_id, name, region, status)
ParallelDispatcher   → Parallel-Execution mit ThreadPoolExecutor (max 5 concurrent)
TenantIsolationEnforcer → Per-Hotel-State-Boundary (no cross-tenant reads)
AdapterOrchestrator  → LaunchAgent Entry-Point
AuditLogger          → JSONL Audit-Trail
```

## CRUX-Bindung

- **K_0:** Read-Only-Cross-Hotel-Tracking (kein K_0-Touch)
- **Q_0:** Tenant-Isolation gegen Cross-Tenant-Leak
- **W_0:** ENV-Var-Gated-Real-Integration-Default (Sandbox-Mock-Default)

## Sandbox-Mock-Default

```bash
DF_MULTI_TENANT_REAL_HOTELS_ENABLED=false  # default
# 5 Mock-Hotels: hildesheim, cape-coral, munich, mock-4, mock-5
```

## Lose-Coupling (LC1-LC5)

- LC1: Graceful-Degradation in 3 Modi (full / degraded_no_real_hotels / sandbox_mock)
- LC2: Direct-Mode 70% Capability
- LC3: Circuit-Breaker 30s Timeout
- LC4: State-Externalization + Idempotent-Operations
- LC5: Health-Check ohne Dependencies

## Tests

>= 14 Tests in `tests/test_multi_tenant_orchestrator.py`:
- Registry: register, lookup, isolation
- Dispatcher: parallel execution, timeout, error containment
- Tenant-Isolation: cross-tenant-read-blocked (NEGATIVE)
- Audit-Logger: append, format, persistence

## Scheduling

LaunchAgent Daily 02:00 via `scripts/com.kemmer.df-multi-tenant-orchestrator.plist`.

[CRUX-MK]
