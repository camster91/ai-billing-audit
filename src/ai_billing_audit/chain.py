"""Canonical SHA-256 hash chain for the ``audit_trail`` table.

This module is the **single source of truth** for the audit chain's hash
shape. It exists because the chain previously had three implementations
that disagreed with each other:

* ``src/ai_billing_audit/audit_actions.py`` — the live writer
* ``src/audit_log.py`` — the canonical verifier
* the ``DO $$`` backfill block in ``audit_trail.sql`` — the migration writer

The writer and the verifier disagreed on how ``data_elements`` is rendered
(``audit_actions`` canonicalised dicts to JSON; ``audit_log`` called
``str()`` on them). Because ``audit_actions.append()`` always stores
``data_elements`` as a dict, its own ``verify_chain()`` — which delegated
to ``audit_log.verify_chain()`` — reported every row it had just written
as tampered. See issue #113.

Chain shape
-----------

For row ``i``::

    cryptographic_signature_i = SHA-256(
        previous_signature_i
        || event_id_i
        || timestamp_i
        || user_identifier_i
        || action_i
        || patient_hash_i
        || data_elements_i
        || model_run_id_i
    )

Field rendering (the part that used to drift):

* ``None`` -> ``""``. Missing values render as empty. ``audit_log``
  documented this rule; ``audit_actions`` used to render ``None`` as
  ``"None"``. No writer produced ``None`` in a chain field, so no stored
  row depends on the old behaviour.
* ``dict`` / ``list`` -> canonical JSON: ``sort_keys=True``,
  ``separators=(",", ":")``. No whitespace, deterministic key order. This
  is the rule the live writer has always used, so existing rows written
  by ``audit_actions.append`` continue to verify unchanged.
* anything else -> ``str(value)``

The genesis (oldest) row in each chain partition carries
``previous_signature = "0" * 64``. The chain is ordered by ``timestamp``;
ties break on ``event_id`` so the walk is deterministic.

There is deliberately **no separator byte** between fields. An earlier
writer inserted ``b"|"`` between fields; removing it is what makes rows
written by the live writer and rows verified by the canonical verifier
agree. Do not reintroduce a separator without a chain-wide migration.

Relationship to the ``feedback`` chain
--------------------------------------

``src/ai_billing_audit/feedback.py`` keeps its **own** field set
(``event_id``, ``timestamp``, ``encounter_id``, ``finding_id``, ``action``,
``biller_id``, ``rule_id``, ``category``, ``severity``) and its own
``b"|"`` separator. That is a different chain over a different dataset —
not a duplicate of this one — and its historical rows depend on its
existing shape, so it is intentionally not migrated here. It imports
:func:`coerce_field` from this module so the per-field rendering rules
cannot drift, and its docstring no longer claims to share this chain's
shape.

Remaining known divergence: the SQL backfill
--------------------------------------------

``audit_trail.sql``'s backfill block computes ``data_elements::text``,
which renders JSONB with Postgres's own spacing (``{"a": 1}``) rather
than the canonical form (``{"a":1}``). That path only runs for rows whose
``cryptographic_signature`` is NULL (legacy rows predating the column), so
live rows are unaffected — but any row it signs will not verify under this
module. Tracked separately; the correct fix is to run the legacy backfill
through this module rather than hashing in SQL.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

__all__ = [
    "CHAIN_FIELDS",
    "GENESIS_PREVIOUS_SIGNATURE",
    "coerce_field",
    "compute_signature",
    "verify_chain",
    "walk_chain",
]


# Ordered tuple of fields whose concatenation forms the hash payload
# (after the leading ``previous_signature``). Kept as a module constant
# so the unit test, the runbook, and the SQL trigger all agree on the
# exact ordering — any reorder changes every signature and breaks the
# chain.
CHAIN_FIELDS: tuple[str, ...] = (
    "event_id",
    "timestamp",
    "user_identifier",
    "action",
    "patient_hash",
    "data_elements",
    "model_run_id",
)

# Genesis row's previous_signature. 64 ASCII zeros, per the spec.
GENESIS_PREVIOUS_SIGNATURE: str = "0" * 64

_PREVIOUS_SIGNATURE_FIELD = "previous_signature"
_STORED_SIGNATURE_FIELD = "cryptographic_signature"


def coerce_field(row: Mapping[str, Any], field: str) -> str:
    """Return ``row[field]`` rendered as the exact string we hash.

    The rendering rule is the contract between writers and verifiers, so
    it lives in exactly one place:

    * ``None`` -> ``""``
    * ``dict`` / ``list`` -> canonical JSON, sorted keys, no whitespace.
      This is what the live writer has always produced, so every existing
      ``audit_actions`` row verifies against it unchanged.
    * otherwise -> ``str(value)``
    """
    value = row.get(field)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


# Back-compat alias: the previous implementations exposed this privately.
_coerce_field = coerce_field


def compute_signature(previous_signature: str, row: Mapping[str, Any]) -> str:
    """Return the SHA-256 hex digest of the row chained to ``previous_signature``.

    Parameters
    ----------
    previous_signature:
        The 64-character hex digest of the prior row's
        ``cryptographic_signature``. Use
        :data:`GENESIS_PREVIOUS_SIGNATURE` for the oldest row in the
        chain partition.
    row:
        Mapping (dict / ``sqlite3.Row`` / ``psycopg2`` dict-row) carrying
        every field in :data:`CHAIN_FIELDS` plus ``previous_signature``.
        The row's own stored ``cryptographic_signature`` (if any) is
        ignored — we recompute from the payload.

    Returns
    -------
    str
        64-character lowercase hex SHA-256 digest.
    """
    if not isinstance(previous_signature, str):
        raise TypeError(
            f"previous_signature must be str, got {type(previous_signature).__name__}"
        )
    if len(previous_signature) != 64:
        raise ValueError(
            f"previous_signature must be 64 hex chars, got len={len(previous_signature)}"
        )

    hasher = hashlib.sha256()
    hasher.update(previous_signature.encode("utf-8"))
    for field in CHAIN_FIELDS:
        hasher.update(coerce_field(row, field).encode("utf-8"))
    return hasher.hexdigest()


def verify_chain(
    rows: Iterable[Mapping[str, Any]],
    *,
    key: Any = None,
) -> int | None:
    """Walk ``rows`` in chain order and return the first broken row's index.

    The chain is walked in the order the iterable yields rows. The caller
    is responsible for sorting by ``timestamp`` (and breaking ties
    deterministically — by ``event_id`` is the project convention). See
    :func:`walk_chain` for the canonical ordering helper.

    Parameters
    ----------
    rows:
        Iterable of row mappings. Each row must carry
        ``previous_signature`` and ``cryptographic_signature`` plus
        every field in :data:`CHAIN_FIELDS`.
    key:
        Optional callable for re-sorting the iterable in place; the
        default is to trust the caller's order.

    Returns
    -------
    int | None
        0-based index of the first row whose recomputed signature does
        not match its stored ``cryptographic_signature``. Returns ``None``
        if the entire chain verifies cleanly. The genesis row must carry
        :data:`GENESIS_PREVIOUS_SIGNATURE` as its ``previous_signature``;
        a different value at index 0 also reports index 0.
    """
    previous_signature = GENESIS_PREVIOUS_SIGNATURE
    for index, row in enumerate(rows):
        stored_prev = coerce_field(row, _PREVIOUS_SIGNATURE_FIELD)
        if stored_prev != previous_signature:
            return index
        expected = compute_signature(previous_signature, row)
        stored = coerce_field(row, _STORED_SIGNATURE_FIELD)
        if stored != expected:
            return index
        # Advance using the just-verified stored signature rather than the
        # recomputed one, so a non-canonical encoding on the row we just
        # verified does not silently rewrite the chain forward. Any
        # downstream break still surfaces because the stored value
        # propagates.
        previous_signature = stored
    return None


def walk_chain(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return ``rows`` sorted by ``(timestamp, event_id)`` ascending.

    Convenience for the runbook and the live verifier — both of which want
    the same canonical order without re-deriving the sort key.
    """
    materialized = list(rows)
    materialized.sort(
        key=lambda r: (coerce_field(r, "timestamp"), coerce_field(r, "event_id"))
    )
    return materialized
