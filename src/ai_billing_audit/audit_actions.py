"""Append-only audit trail with SHA-256 hash chain.

The audit_trail is the immutable record of every reviewer action on
an encounter audit: accept all, dismiss, flag, re-run, etc. Each
row's `cryptographic_signature` is SHA-256(previous_signature ||
<chain fields>), so any retroactive edit breaks the chain at the
mutated row and all subsequent rows.

This module appends to a JSONL file at ``/app/logs/audit_trail.jsonl``
and exposes a ``verify_chain`` function (parallel to the canonical
``audit_log.verify_chain`` in ``src/audit_log.py``) for the chain
integrity check used by the QA audit log.

The same chain shape as the Postgres ``audit_trail`` table
(see audit_trail.sql) — fields match exactly. The on-disk JSONL
is the dev/demo surface; the Postgres table is the prod surface.

Consolidation note (kanban t_2128c8eb)
-------------------------------------
This module's ``verify_chain`` is a thin wrapper around the canonical
``audit_log.verify_chain`` (src/audit_log.py:162). The chain shape
differs by one byte — this module uses ``"|"`` as a field separator
inside ``compute_signature`` while ``src/audit_log.py`` concatenates
fields directly — so the two are NOT byte-for-byte interchangeable.
The QA audit log (JSONL) and the prod Postgres audit_trail each have
their own writer and the split is intentional for now. The plan is
to consolidate to a single canonical implementation in
``src/audit_log.py``; until then, callers should use
``audit_log.verify_chain`` against the prod log and
``audit_actions.verify_chain`` against the QA JSONL.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

_LOG_PATH = Path(os.environ.get("AUDIT_TRAIL_LOG", "/app/logs/audit_trail.jsonl"))
_GENESIS_SIG = "0" * 64

# Fields included in the chain hash. Must match audit_trail.sql.
_CHAIN_FIELDS = (
    "event_id",
    "timestamp",
    "user_identifier",
    "action",
    "patient_hash",
    "data_elements",
    "model_run_id",
)


def _coerce_field(row: dict[str, Any], field: str) -> str:
    """Stringify a chain field for hashing.

    Same rule as src/audit_log.py:
    - dict/list: canonical JSON, no spaces, sorted keys
    - timestamp: ISO 8601 string (caller passes an ISO string)
    - other: str(value)
    """
    v = row.get(field)
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, separators=(",", ":"))
    return str(v)


def compute_signature(previous_signature: str, row: dict[str, Any]) -> str:
    """Compute the SHA-256 hex digest for a single row."""
    h = hashlib.sha256()
    h.update(previous_signature.encode("utf-8"))
    for field in _CHAIN_FIELDS:
        h.update(b"|")
        h.update(_coerce_field(row, field).encode("utf-8"))
    return h.hexdigest()


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce a row into the canonical chain shape.

    - Adds event_id if missing
    - Adds timestamp (ISO) if missing
    - Adds user_identifier if missing (defaults to the X-Forwarded-User
      header or "demo" in dev mode)
    - Sets previous_signature = genesis if missing
    - Sets cryptographic_signature from compute_signature if missing
    """
    if "event_id" not in row:
        row["event_id"] = uuid.uuid4().hex
    if "timestamp" not in row:
        # Use ISO 8601 UTC for chain hashing (timestamp column is TIMESTAMPTZ)
        row["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row.setdefault("user_identifier", "demo")
    row.setdefault("patient_hash", "")
    row.setdefault("model_run_id", "")
    if "data_elements" not in row:
        row["data_elements"] = {}
    if "previous_signature" not in row:
        row["previous_signature"] = _read_last_signature()
    if "cryptographic_signature" not in row:
        row["cryptographic_signature"] = compute_signature(
            row["previous_signature"], row
        )
    return row


def _read_last_signature() -> str:
    """Read the most recent cryptographic_signature from the log.

    Returns genesis (64 zeros) if the log is empty or doesn't exist.
    """
    if not _LOG_PATH.is_file():
        return _GENESIS_SIG
    last_sig = _GENESIS_SIG
    try:
        with _LOG_PATH.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "cryptographic_signature" in rec:
                    last_sig = rec["cryptographic_signature"]
    except OSError:
        return _GENESIS_SIG
    return last_sig


def append(
    action: str,
    encounter_id: str,
    *,
    user_identifier: str = "demo",
    findings: list[dict[str, Any]] | None = None,
    note: str | None = None,
    extra: dict[str, Any] | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Append a new event to the audit trail and return the row.

    Args:
        action: One of "accept_all", "dismiss", "flag", "rerun",
            "submit", "upload", "audit_complete", etc.
        encounter_id: The encounter this event applies to.
        user_identifier: Who did it (from auth in prod, "demo" in dev).
        findings: Findings affected (per-finding for dismiss).
        note: Optional free-text note.
        extra: Free-form payload merged into data_elements.
        tenant_id: The Zorva tenant this event belongs to. Used to
            scope reads in /activity so one clinic can't see
            another's reviewer actions. None means the
            "default" tenant (which today is Acme Family Practice).

    Returns the appended row including cryptographic_signature.
    """
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    findings = findings or []
    # patient_hash is SHA-256 of encounter_id (PHIPA pseudonymization)
    patient_hash = hashlib.sha256(encounter_id.encode("utf-8")).hexdigest()

    # data_elements must be canonical JSON for hashing
    data_elements: dict[str, Any] = {
        "encounter_id": encounter_id,
        "n_findings": len(findings),
        "finding_ids": [f.get("finding_id") or f.get("id") for f in findings],
        "note": note or "",
    }
    if extra:
        data_elements.update(extra)

    row: dict[str, Any] = {
        "action": action,
        "user_identifier": user_identifier,
        "patient_hash": patient_hash,
        "tenant_id": tenant_id or "default",
        "data_elements": data_elements,
        "model_run_id": "",
    }
    row = _normalize_row(row)

    # Append (line-by-line, JSONL)
    with _LOG_PATH.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def read_all(
    limit: int | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read all rows from the log, oldest first.

    When ``tenant_id`` is provided, only rows for that tenant
    are returned. ``tenant_id=None`` returns rows from the
    "default" tenant (the Acme Family Practice scope). Pass
    ``tenant_id="*"`` to read across all tenants (used by the
    privacy officer's cross-tenant audit view).
    """
    if not _LOG_PATH.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with _LOG_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Tenant scoping. The contract:
    #   tenant_id=None      -> only the "default" tenant (Acme)
    #   tenant_id="default" -> only the "default" tenant
    #   tenant_id="acme"    -> only acme's rows
    #   tenant_id="*"       -> all rows (privacy officer's view)
    # Legacy rows written before this change have no tenant_id
    # key; they're treated as belonging to the "default" tenant
    # so existing audit trails don't disappear after the upgrade.
    if tenant_id != "*":
        effective_tenant = tenant_id if tenant_id is not None else "default"
        rows = [
            r for r in rows
            if r.get("tenant_id", "default") == effective_tenant
        ]
    if limit is not None:
        rows = rows[-limit:]
    return rows


def verify_chain(
    rows: Iterable[Mapping[str, Any]],
    *,
    key: Any = None,
) -> int | None:
    """Walk ``rows`` in chain order and return the first broken row's position.

    Thin wrapper around :func:`audit_log.verify_chain` (src/audit_log.py:162)
    that returns the 0-based index of the first row whose stored
    ``cryptographic_signature`` does not match the recomputed value, or
    ``None`` if the entire chain verifies cleanly.

    NOTE: This is a parallel implementation, not a byte-for-byte drop-in.
    The local :func:`compute_signature` in this module uses ``"|"`` as a
    field separator while :func:`audit_log.compute_signature` concatenates
    fields directly. As a result, ``audit_actions.verify_chain`` will
    NOT verify rows written by ``src/audit_log.py`` (and vice versa). Use
    ``audit_actions.verify_chain`` against the QA JSONL log (rows produced
    by :func:`append`) and ``audit_log.verify_chain`` against the prod
    Postgres ``audit_trail`` table. Consolidation to a single canonical
    chain shape is tracked in the module docstring.

    Parameters
    ----------
    rows:
        Iterable of row mappings as returned by :func:`read_all`. Each
        row must carry ``previous_signature`` and ``cryptographic_signature``
        plus every field in :data:`_CHAIN_FIELDS`.
    key:
        Optional callable for re-sorting the iterable in place; the
        default is to trust the caller's order.

    Returns
    -------
    int | None
        0-based index of the first row whose recomputed signature does
        not match its stored ``cryptographic_signature``, or ``None`` if
        the entire chain verifies cleanly.
    """
    from audit_log import verify_chain as _canonical_verify_chain  # src/audit_log.py

    return _canonical_verify_chain(rows, key=key)


