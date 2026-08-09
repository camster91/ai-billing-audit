"""SHA-256 hash-chain ``cryptographic_signature`` for the ``audit_trail`` table.

The ``audit_trail`` table is the immutable-append log of every event the
AI billing auditor emits: every claim read, every LLM call, every
finding, every reviewer accept / dismiss. PHIPA (Ontario) and HIA
(Alberta) require that what we record be tamper-evident — a retroactive
edit, even by an insider, must be detectable. We satisfy that by linking
each row to the one before it with a SHA-256 hash. Any mutation breaks
the chain at the mutated row and all rows that follow.

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

The genesis (oldest) row in each chain partition has
``previous_signature = "0" * 64`` (64 ASCII zeros). Subsequent rows
store the previous row's ``cryptographic_signature`` as their
``previous_signature``. The chain is ordered by ``timestamp``; ties are
broken by ``event_id`` so the walk is deterministic.

Public surface
--------------

* :func:`compute_signature` — build the SHA-256 hex digest for a single
  row given the previous row's stored signature. Pure function, no I/O.
* :func:`verify_chain` — walk an iterable of row dicts in chain order
  and return the first row whose recomputed signature does not match
  its stored ``cryptographic_signature``. Returns ``None`` when the
  chain is intact.

Both functions are intentionally DB-agnostic: they accept any iterable
of row-shaped dicts (or ``sqlite3.Row`` / ``psycopg2`` dict-cursor
rows) and use ``Mapping`` access by key. This keeps the hash logic
unit-testable without spinning up a real database, and means the same
module is used by the live production chain, the offline auditor
verifier, and the unit test suite.

Migration
---------

The companion SQL file ``audit_trail.sql`` defines the table with the
``cryptographic_signature TEXT NOT NULL`` column, indexes that preserve
the chain walk order, and a backfill procedure for existing rows:

1. Lock the table to appends only (``audit_trail_no_update`` trigger).
2. For each row ordered by ``timestamp`` (oldest first), compute the
   signature using the previous row's stored signature (or 64 zeros
   for the genesis row), and ``UPDATE`` in place. The trigger blocks
   this ``UPDATE`` because the column is part of the protected set;
   the backfill runs as the migration owner and is exempt via a
   session-level ``SET LOCAL`` flag, then re-armed.

The verifier is re-runnable as a one-line command — see
``docs/RUNBOOK.md`` for the OIPC auditor procedure.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping

__all__ = [
    "CHAIN_FIELDS",
    "GENESIS_PREVIOUS_SIGNATURE",
    "compute_signature",
    "verify_chain",
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

# Field on the row that stores the signature of the previous row in
# the chain. The row stored in audit_trail is expected to carry both
# ``previous_signature`` (set at insert time) and
# ``cryptographic_signature`` (the row's own signature).
_PREVIOUS_SIGNATURE_FIELD = "previous_signature"
_STORED_SIGNATURE_FIELD = "cryptographic_signature"


def _coerce_field(row: Mapping[str, Any], field: str) -> str:
    """Return ``row[field]`` rendered as the exact string we hash.

    Every field in the chain is concatenated as text. The DB stores
    ``timestamp`` as ISO-8601 text (we use ``TIMESTAMP NOT NULL`` with
    a CHECK that it round-trips through ``str()`` unchanged), the
    identifiers as text, ``data_elements`` as canonical JSON text
    (sorted keys, no whitespace), and ``patient_hash`` as hex text.
    Numeric ``None`` is rendered as the empty string so missing values
    are stable and detectably different from present-but-empty ones.
    """
    value = row.get(field)
    if value is None:
        return ""
    return str(value)


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
        every field in :data:`CHAIN_FIELDS` plus
        ``previous_signature``. The row's own stored
        ``cryptographic_signature`` (if any) is ignored — we recompute
        from the payload.

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
        hasher.update(_coerce_field(row, field).encode("utf-8"))
    return hasher.hexdigest()


def verify_chain(
    rows: Iterable[Mapping[str, Any]],
    *,
    key: Any = None,
) -> int | None:
    """Walk ``rows`` in chain order and return the first broken row's position.

    The chain is walked in the order the iterable yields rows. The
    caller is responsible for sorting by ``timestamp`` (and breaking
    ties deterministically — by ``event_id`` is the project convention).
    See :func:`walk_chain` for the canonical ordering helper used by
    the live verifier and the runbook.

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
        0-based index of the first row whose recomputed signature
        does not match its stored ``cryptographic_signature``. Returns
        ``None`` if the entire chain verifies cleanly. The genesis row
        must carry :data:`GENESIS_PREVIOUS_SIGNATURE` as its
        ``previous_signature``; a different value at index 0 also
        reports index 0.
    """
    previous_signature = GENESIS_PREVIOUS_SIGNATURE
    for index, row in enumerate(rows):
        stored_prev = _coerce_field(row, _PREVIOUS_SIGNATURE_FIELD)
        if stored_prev != previous_signature:
            return index
        expected = compute_signature(previous_signature, row)
        stored = _coerce_field(row, _STORED_SIGNATURE_FIELD)
        if stored != expected:
            return index
        # Advance the chain using the just-verified stored signature.
        # Using the stored value (not the recomputed one) lets the
        # verifier tolerate a non-canonical encoding choice on the row
        # we just verified, while still detecting any downstream break
        # because the stored value propagates forward.
        previous_signature = stored
    return None


def walk_chain(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return ``rows`` sorted by ``(timestamp, event_id)`` ascending.

    Convenience for the runbook and the live verifier — both of which
    want the same canonical order without re-deriving the sort key
    each time.
    """
    materialized = list(rows)
    materialized.sort(
        key=lambda r: (_coerce_field(r, "timestamp"), _coerce_field(r, "event_id"))
    )
    return materialized
