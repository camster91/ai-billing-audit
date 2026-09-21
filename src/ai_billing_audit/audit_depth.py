"""Configurable audit depth per claim / per tenant.

Kanban: t_e2c5afab (clinical-impact board).

Three depths:

* ``1`` — quick: Haiku-class model, no RAG, ~2 s. "Is this claim
  obviously broken?"
* ``2`` — standard: Sonnet-class, basic RAG, ~8 s. The default.
* ``3`` — deep: Opus-class, full RAG + chain-of-thought + few-shot,
  ~30 s. The hospital tier.

Per-tenant default stored in the tenant-config log; per-claim
override stored on the encounter. Billers choose depth based on
claim risk. This module owns:

* ``audit_depth_for(claim, tenant_id)`` → int 1|2|3 (claim override
  beats tenant default beats global default)
* ``model_for_depth(depth)`` → provider/model string for the
  underlying LLM call. The values are *suggestions* — the actual
  call site (``llm.complete_json``) honours them.
* ``cost_estimate_usd(depth, n_tokens)`` — rough cost so the
  per-depth cost tracking in the dashboard works.
* ``AuditDepthConfig`` dataclass + ``load_default_config`` /
  ``save_tenant_default`` JSONL-backed store.

We deliberately do NOT route to the model here — that would couple
this module to minimax_client. Callers ask for the model name and
use it.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

AuditDepth = Literal[1, 2, 3]

DEPTH_QUICK: AuditDepth = 1
DEPTH_STANDARD: AuditDepth = 2
DEPTH_DEEP: AuditDepth = 3

DEFAULT_DEPTH: AuditDepth = DEPTH_STANDARD

# Per-depth model + cost assumptions.
#
# Costs are USD per 1M tokens, blended input+output. The numbers
# are the public list prices as of mid-2026 and are deliberately
# conservative (we round up so the dashboard never *under*-reports
# cost).
_DEPTH_TABLE: dict[int, dict[str, object]] = {
    1: {
        "name": "quick",
        "model": "claude-haiku-4-5",
        "uses_rag": False,
        "uses_chain_of_thought": False,
        "approx_latency_s": 2,
        "cost_per_million_tokens_usd": 1.50,
        "description": "Haiku-class, no RAG. Obvious-breakage check.",
    },
    2: {
        "name": "standard",
        "model": "claude-sonnet-4-5",
        "uses_rag": True,
        "uses_chain_of_thought": False,
        "approx_latency_s": 8,
        "cost_per_million_tokens_usd": 9.00,
        "description": "Sonnet, basic RAG. The default for most clinics.",
    },
    3: {
        "name": "deep",
        "model": "claude-opus-4-1",
        "uses_rag": True,
        "uses_chain_of_thought": True,
        "approx_latency_s": 30,
        "cost_per_million_tokens_usd": 45.00,
        "description": "Opus + CoT + few-shot. Hospital tier.",
    },
}


def _validate_depth(depth: int) -> AuditDepth:
    if depth not in (1, 2, 3):
        raise ValueError(f"audit_depth must be 1, 2, or 3; got {depth!r}")
    return depth  # type: ignore[return-value]


def model_for_depth(depth: AuditDepth) -> str:
    """Return the suggested model name for ``depth``."""
    d = _validate_depth(depth)
    row = _DEPTH_TABLE[d]
    return str(row["model"])


def depth_metadata(depth: AuditDepth) -> dict[str, object]:
    """Return the full metadata row for ``depth`` (model, latency, etc.)."""
    d = _validate_depth(depth)
    return dict(_DEPTH_TABLE[d])


def cost_estimate_usd(depth: AuditDepth, n_tokens: int) -> float:
    """Rough cost estimate (USD) for ``n_tokens`` at ``depth``.

    ``n_tokens`` is the total token count (input + output).
    """
    d = _validate_depth(depth)
    rate = float(_DEPTH_TABLE[d]["cost_per_million_tokens_usd"])  # type: ignore[arg-type]
    return round((n_tokens / 1_000_000.0) * rate, 4)


# ---------------------------------------------------------------------------
# Per-claim / per-tenant depth overrides
# ---------------------------------------------------------------------------


@dataclass
class AuditDepthConfig:
    """Resolved audit-depth decision for one claim."""

    tenant_id: str
    claim_id: str
    depth: AuditDepth
    source: Literal["claim_override", "tenant_default", "global_default"]
    model: str
    approx_latency_s: int
    cost_estimate_usd: float
    resolved_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_depth_for(
    *,
    tenant_id: str,
    claim_id: str,
    claim_override: int | None = None,
    tenant_default: int | None = None,
    n_tokens_estimate: int = 4_000,
) -> AuditDepthConfig:
    """Resolve the audit depth for a claim.

    Precedence (highest first):

    1. ``claim_override`` — biller explicitly chose a depth for this claim
    2. ``tenant_default`` — the tenant-config setting
    3. ``DEFAULT_DEPTH`` — global fallback

    Returns an ``AuditDepthConfig`` with model + cost estimate.
    """
    chosen: AuditDepth
    source: str
    if claim_override is not None:
        chosen = _validate_depth(claim_override)
        source = "claim_override"
    elif tenant_default is not None:
        chosen = _validate_depth(tenant_default)
        source = "tenant_default"
    else:
        chosen = DEFAULT_DEPTH
        source = "global_default"
    meta = depth_metadata(chosen)
    return AuditDepthConfig(
        tenant_id=tenant_id,
        claim_id=claim_id,
        depth=chosen,
        source=source,  # type: ignore[arg-type]
        model=str(meta["model"]),
        approx_latency_s=int(str(meta["approx_latency_s"])),
        cost_estimate_usd=cost_estimate_usd(chosen, n_tokens_estimate),
    )


# ---------------------------------------------------------------------------
# Tenant-config JSONL store (audit_depth default per tenant)
# ---------------------------------------------------------------------------


_TENANT_CONFIG_LOG = Path(
    os.environ.get("TENANT_AUDIT_DEPTH_LOG", "/app/logs/tenant_audit_depth.jsonl")
)
_GENESIS_SIG = "0" * 64


def _last_signature(path: Path) -> str:
    if not path.exists():
        return _GENESIS_SIG
    last = _GENESIS_SIG
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            last = row.get("cryptographic_signature") or last
    return last


def _sign(previous: str, row: dict[str, object]) -> str:
    """Digest for a tenant-config row.

    NOTE: this log hashes the *whole row* with the keys sorted, which is a
    different shape from the canonical field-ordered audit chain — it chains
    configuration changes (a tenant's audit depth), not reviewer actions on
    claims, and it is not part of the audit-trail evidence surface. It is
    kept as its own rule deliberately and is documented as such here so a
    future reader does not "unify" it and invalidate every existing row.

    See ai_billing_audit/audit_chain.py for the canonical chain rule that
    the audit-trail, feedback, and feature-flag logs share.
    """
    import hashlib

    payload = "|".join(
        str(row.get(k, ""))
        for k in sorted(row.keys())
        if k != "cryptographic_signature"
    )
    return hashlib.sha256(f"{previous}|{payload}".encode("utf-8")).hexdigest()


def save_tenant_default(tenant_id: str, depth: int) -> dict[str, object]:
    """Persist the default audit-depth for ``tenant_id``.

    Most-recent row per tenant wins.
    """
    d = _validate_depth(depth)
    path = Path(os.environ.get("TENANT_AUDIT_DEPTH_LOG", str(_TENANT_CONFIG_LOG)))
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_sig = _last_signature(path)
    row: dict[str, object] = {
        "event_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tenant_id": tenant_id,
        "default_depth": d,
        "model": model_for_depth(d),
        "previous_signature": prev_sig,
    }
    row["cryptographic_signature"] = _sign(prev_sig, row)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def load_tenant_default(
    tenant_id: str, *, log_path: Path | str | None = None
) -> AuditDepth:
    """Return the most-recent default depth for ``tenant_id`` (or ``DEFAULT_DEPTH``)."""
    path = Path(log_path) if log_path is not None else _TENANT_CONFIG_LOG
    if not path.exists():
        return DEFAULT_DEPTH
    latest: int | None = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("tenant_id") == tenant_id:
                d = row.get("default_depth")
                if isinstance(d, int) and d in (1, 2, 3):
                    latest = d
    return _validate_depth(latest) if latest is not None else DEFAULT_DEPTH


def load_default_config(*, log_path: Path | str | None = None) -> dict[str, AuditDepth]:
    """Return ``{tenant_id: depth}`` for every tenant with a saved default."""
    path = Path(log_path) if log_path is not None else _TENANT_CONFIG_LOG
    out: dict[str, AuditDepth] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = row.get("tenant_id")
            d = row.get("default_depth")
            if isinstance(tid, str) and isinstance(d, int) and d in (1, 2, 3):
                out[tid] = _validate_depth(d)  # last write wins
    return out
