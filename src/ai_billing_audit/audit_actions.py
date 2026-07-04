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
is now byte-for-byte interchangeable with ``src/audit_log.py``:
this module's ``compute_signature`` concatenates fields directly
(no separator), so rows written here verify cleanly against
``audit_log.verify_chain`` and vice versa. The QA JSONL log and the
prod Postgres ``audit_trail`` rows are interchangeable; either
``verify_chain`` works on both.
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

from .patient_hash import hash_patient_id

# Module-level path. Read on every access so the test suite can
# set ``AUDIT_TRAIL_LOG`` BEFORE audit_actions is imported (or
# monkey-patch ``aa_mod._LOG_PATH = log`` directly) and have the
# new path take effect immediately. Without this lazy resolution
# the module would pin its path at first import and tests that
# set the env var later would write to the production default
# (``/app/logs/...``) — which doesn't exist on developer laptops
# and causes Read-only file system errors when the test attempts
# ``Path.parent.mkdir(...)``.
def audit_trail_path() -> Path:
    """Return the audit-trail JSONL path (read on every call).

    Resolution order:
    1. If the module attribute ``_LOG_PATH`` was set explicitly
       (e.g. ``monkeypatch.setattr(aa_mod, '_LOG_PATH', log)``
       in ``tests/test_audit_actions_tenant.py::tmp_log``) return
       that value. This is the standard test-isolation pattern.
    2. Otherwise return ``Path($AUDIT_TRAIL_LOG)`` if the env var
       is set, falling back to ``/app/logs/audit_trail.jsonl``.

    Resolves on every call so a per-test monkeypatch takes effect
    immediately AND a late-set ``AUDIT_TRAIL_LOG`` env var (e.g.
    from a parallel test that imports audit_actions first) is
    also honored — neither path can silently pin the production
    default.
    """
    # Resolution order:
    # 1. Module-level override ``_LOG_PATH`` (set by ``monkeypatch.setattr``
    #    in ``tests/test_audit_actions_tenant.py::tmp_log`` and other
    #    per-tenant tests). When the override is a Path (the typical
    #    test pattern) we trust it as the authoritative path for
    #    the current test scope; the function we are inside, the
    #    function we are, and the module-global ``_LOG_PATH`` form
    #    a single contract that pre-dates the env-var path.
    # 2. ``AUDIT_TRAIL_LOG`` env var (set by ``tests/test_rbac.py``,
    #    ``tests/test_contact.py``, ``tests/test_finding_assignments.py``,
    #    etc. via ``monkeypatch.setenv`` + ``importlib.reload``).
    # 3. Production default ``/app/logs/audit_trail.jsonl``.
    #
    # Priority: env var wins over monkeypatched _LOG_PATH.
    # Reason: pytest's monkeypatch.setattr(aa_mod, '_LOG_PATH', log)
    # calls getattr(target, name, NOTSET) internally to read the
    # current value. If we serve _LOG_PATH via __getattr__ it
    # returns a sentinel-y Path, monkeypatch interprets that as the
    # "previous value" and writes it back into __dict__ on undo —
    # causing the rbac test's env var path to leak across tests.
    # Returning from env var FIRST means monkeypatch sees a real
    # missing attribute and cleanly adds + removes on undo.
    env_value = os.environ.get("AUDIT_TRAIL_LOG", "")
    if env_value:
        return Path(env_value)
    # Fall through to _LOG_PATH only when the env var is unset,
    # which is the original audit_actions_tenant test pattern.
    override = globals().get("_LOG_PATH")
    if override is not None and not isinstance(override, type(audit_trail_path)):
        return override
    return Path("/app/logs/audit_trail.jsonl")


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
    """Compute the SHA-256 hex digest for a single row.

    Uses the same concatenation-as-:func:`audit_log.compute_signature`
    shape (no separator byte) so rows written by this module are
    byte-for-byte interoperable with rows written by the canonical
    ``src/audit_log.py`` chain. The older ``"|"`` separator broke
    cross-module ``verify_chain`` (rows written here failed
    ``audit_log.verify_chain`` and vice versa) — this is the
    consolidation that the module docstring deferred.
    """
    h = hashlib.sha256()
    h.update(previous_signature.encode("utf-8"))
    for field in _CHAIN_FIELDS:
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

    swarm-audit H-Perf-1: this used to walk the entire log file
    on every audit append (every accept / dismiss / modify / flag
    click). With ~50k events in a real pilot that's a 50k-row
    read + JSON-parse per click — 200ms+ at scale. Now caches
    the result in process memory and only re-reads when:

      * the cache is empty (first call after import / file change)
      * the file's mtime has changed since the last read (someone
        else wrote to the log, e.g. the worker process)
      * a manual ``_reset_last_signature_cache()`` is invoked
        (used by tests that rewrite the log out-of-band)

    The cache is process-local and best-effort — a multi-worker
    deployment would have one cache per worker. The chain
    verification on read (``verify_chain``) still walks the full
    log, which is correct: chain integrity must be exact, not
    cached.
    """
    global _LAST_SIG_CACHE, _LAST_SIG_MTIME, _LAST_SIG_PATH
    path = audit_trail_path()
    try:
        mtime = path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        return _GENESIS_SIG
    if (
        _LAST_SIG_CACHE is not None
        and _LAST_SIG_MTIME == mtime
        and _LAST_SIG_PATH == path
    ):
        return _LAST_SIG_CACHE
    # Cache miss — read the file. (Cheap when the file is empty
    # or the process just started; expensive only on the cold
    # path that the cache is designed to skip.)
    if not path.is_file():
        last_sig = _GENESIS_SIG
    else:
        last_sig = _GENESIS_SIG
        try:
            with path.open() as fh:
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
            last_sig = _GENESIS_SIG
    _LAST_SIG_CACHE = last_sig
    _LAST_SIG_MTIME = mtime
    _LAST_SIG_PATH = path
    return last_sig


def _reset_last_signature_cache() -> None:
    """Drop the in-process cache. Used by tests that rewrite
    the audit-trail log out-of-band (e.g. via direct file writes)
    and need the next ``_read_last_signature()`` to re-read.
    """
    global _LAST_SIG_CACHE, _LAST_SIG_MTIME, _LAST_SIG_PATH
    _LAST_SIG_CACHE = None
    _LAST_SIG_MTIME = None
    _LAST_SIG_PATH = None


# Process-local cache for ``_read_last_signature``. Set by the
# function on a cache miss; cleared by ``_reset_last_signature_cache``.
_LAST_SIG_CACHE: str | None = None
_LAST_SIG_MTIME: float | None = None
_LAST_SIG_PATH: Path | None = None


# RBAC roles supported by the audit app. Multi-user team feature
# (kanban t_846407c4): admin = office manager / clinic owner,
# biller = full write access, viewer = read-only. The Next.js
# portal's team management UI (kanban t_23bfd49c) is the source
# of truth for the user/role table; the FastAPI audit app
# enforces these roles via the per-request ``X-User-Id`` /
# ``X-User-Role`` headers until a real auth integration lands.
ROLE_ADMIN = "admin"
ROLE_BILLER = "biller"
ROLE_VIEWER = "viewer"
VALID_ROLES = (ROLE_ADMIN, ROLE_BILLER, ROLE_VIEWER)


def append(
    action: str,
    encounter_id: str,
    *,
    user_identifier: str = "demo",
    findings: list[dict[str, Any]] | None = None,
    note: str | None = None,
    extra: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    user_role: str | None = None,
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
        user_id: Multi-user team identifier (UUID from the Next.js
            team management UI; kanban t_23bfd49c). Stored on the
            row for cross-system audit joins; never null when the
            request carries ``X-User-Id`` (the FastAPI middleware
            enforces that for write actions). Additive — old rows
            without ``user_id`` continue to verify cleanly because
            the field is NOT in :data:`_CHAIN_FIELDS`.
        user_role: One of "admin" / "biller" / "viewer". Stored
            alongside ``user_id`` for forensics; also NOT in the
            chain hash. Same backward-compat guarantee.

    Returns the appended row including cryptographic_signature.
    """
    p = audit_trail_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    findings = findings or []
    # patient_hash is a salted SHA-256 of the encounter identifier,
    # using PATIENT_HASH_PEPPER for the secret. This is the FastAPI
    # equivalent of apps/portal/src/lib/patient-hash.ts so the audit
    # chain written by the FastAPI service and the audit chain
    # written by the portal produce comparable patient_hashes.
    # See src/ai_billing_audit/patient_hash.py for the threat model
    # and the migration note (old unsalted rows in the chain still
    # verify because the signature is computed from each row's own
    # patient_hash field).
    patient_hash = hash_patient_id(encounter_id)

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
    # Multi-user team RBAC: ``user_id`` + ``user_role`` are ADDITIVE
    # row fields. We deliberately keep them OUT of :data:`_CHAIN_FIELDS`
    # so that old audit rows (written before the kanban t_846407c4
    # feature) continue to verify cleanly — the chain hash shape is
    # unchanged. The fields are JSON-serialized alongside the row so
    # privacy-officer / forensic queries can join ``user_id`` back to
    # the Next.js team management table.
    if user_id:
        row["user_id"] = str(user_id)
    if user_role:
        row["user_role"] = str(user_role)
    row = _normalize_row(row)

    # Append (line-by-line, JSONL)
    with audit_trail_path().open("a") as fh:
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
    if not audit_trail_path().is_file():
        return []
    rows: list[dict[str, Any]] = []
    with audit_trail_path().open() as fh:
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

    NOTE: This is now a thin pass-through to the canonical
    :func:`audit_log.verify_chain`. As of the P11 bug-sweep fix,
    :func:`compute_signature` in this module matches
    :func:`audit_log.compute_signature` byte-for-byte (no separator),
    so rows written by this module's :func:`append` verify cleanly
    against the canonical chain and vice versa.

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


