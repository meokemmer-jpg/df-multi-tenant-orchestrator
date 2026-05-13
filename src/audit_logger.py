"""Audit-Logger: JSONL Audit-Trail [CRUX-MK].

W49-D K12+K13 Migration:
- K12: optional FullProvenanceEnvelope (HMAC + chain-predecessor) pro Run
- K13: optional RFC3161 External-Anchor (FreeTSA) pro Run
"""

from __future__ import annotations

import json
import logging
import os
import sys as _sys
import time
from dataclasses import asdict
from pathlib import Path
from threading import Lock

# W49-D Foundation
_DF_ROOT = Path(__file__).resolve().parent.parent.parent
_sys.path.insert(0, str(_DF_ROOT))
try:
    from _df_common.full_provenance_envelope import build_full_envelope  # type: ignore
    from _df_common.rfc3161_anchor import rfc3161_timestamp  # type: ignore
    W49D_FOUNDATION = True
except ImportError:
    W49D_FOUNDATION = False

_K12_HMAC_SECRET = os.environ.get(
    "DF_MULTI_TENANT_HMAC_SECRET",
    "df-multi-tenant-orchestrator-dev-hmac-secret-v1",
)
_K12_ENVELOPE_TTL_S = int(os.environ.get("DF_MULTI_TENANT_ENVELOPE_TTL_S", "86400"))

_logger = logging.getLogger(__name__)


class AuditLogger:
    """Append-only JSONL audit-trail. Thread-safe."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def log(self, entry: dict) -> None:
        """Append one JSONL entry. Adds ts + df_id automatically."""
        record = {
            "ts": time.time(),
            "iso_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "df_id": "df-multi-tenant-orchestrator",
            **entry,
        }
        with self._lock:
            with self.path.open("a") as f:
                f.write(json.dumps(record) + "\n")

    def read_all(self) -> list[dict]:
        """Read all entries. For tests + audits."""
        if not self.path.exists():
            return []
        with self.path.open("r") as f:
            return [json.loads(line) for line in f if line.strip()]

    # W49-D K12: FullProvenanceEnvelope
    def envelope_run(
        self,
        run_id: str,
        payload: dict,
        tenant_id: str = "multi-tenant-aggregate",
    ) -> str | None:
        """K12: Persist signed FullProvenanceEnvelope (HMAC + chain-predecessor).

        Returns the envelope's payload_hash (for K13 anchoring), or None if disabled.
        """
        if not W49D_FOUNDATION:
            return None
        try:
            provenance_full_dir = self.path.parent / "provenance-full"
            provenance_full_dir.mkdir(parents=True, exist_ok=True)
            # Chain-predecessor
            predecessor_hash: str | None = None
            files = sorted(
                provenance_full_dir.glob("*.envelope.json"),
                key=lambda p: p.stat().st_mtime,
            )
            if files:
                try:
                    with files[-1].open("r", encoding="utf-8") as f:
                        predecessor_hash = json.load(f).get("payload_hash")
                except (OSError, json.JSONDecodeError) as e:
                    _logger.warning(f"K12 predecessor read failed: {e}")
            envelope = build_full_envelope(
                operation_id=run_id,
                operation_type="df-multi-tenant-dispatch",
                issuer="df-multi-tenant-orchestrator",
                payload_dict=payload,
                secret=_K12_HMAC_SECRET,
                predecessor_hash=predecessor_hash,
                tenant_id=tenant_id,
                ttl_seconds=_K12_ENVELOPE_TTL_S,
            )
            with self._lock:
                env_out = provenance_full_dir / f"{run_id}.envelope.json"
                with env_out.open("w", encoding="utf-8") as f:
                    json.dump(asdict(envelope), f, indent=2, default=str, ensure_ascii=False)
            return envelope.payload_hash
        except Exception as e:
            _logger.warning(f"K12 envelope build failed (non-fatal): {e}")
            return None

    # W49-D K13: RFC3161 External Anchor
    def anchor_run(self, chain_hash: str) -> bool:
        """K13: Append RFC3161-Anchor to anchors/rfc3161-anchors.jsonl."""
        if not W49D_FOUNDATION or not chain_hash:
            return False
        try:
            anchors_dir = self.path.parent / "anchors"
            anchors_dir.mkdir(parents=True, exist_ok=True)
            anchor = rfc3161_timestamp(chain_hash, provider="freetsa")
            with self._lock:
                with (anchors_dir / "rfc3161-anchors.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(anchor)) + "\n")
            return True
        except Exception as e:
            _logger.warning(f"K13 anchor failed (non-fatal): {e}")
            return False
