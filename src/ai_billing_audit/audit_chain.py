"""Canonical SHA-256 hash-chain for every audit trail in Zorva.

This module is the single owner of the chain rule. Four logs are linked
by it — the Postgres ``audit_trail`` table, the FastAPI JSONL
``audit_trail.jsonl``, the biller ``feedback`` log, and the tenant
configuration logs — and before this module existed each of them carried
its own copy of the field list and the stringifier. Three of those copies
disagreed, which is how ``verify_chain`` came to reject rows written by
its own append path (kanban / issue #113).

Two rules live here and nowhere else:

1. :data:`CHAIN_FIELDS` — the field names, in the order they are hashed.
2. :func:`coerce_field` — how each field is rendered as text before hashing.

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

``previous_signature`` is hashed first, then each field in
:data:`CHAIN_FIELDS` order, with no separator between them. The genesis
row of each chain partition carries :data:`GENESIS_PREVIOUS_SIGNATURE`.

Field coercion
--------------

``data_elements`` is written to storage as a canonical JSON string
(sorted keys, no whitespace) and read back either as that same string
(JSONL, ``psql -A``) or as a parsed ``dict`` (Postgres ``JSONB`` via
psycopg). :func:`coerce_field` renders both to the identical canonical
JSON text, so a row verifies the same way regardless of which transport
read it. That equivalence is the whole point of centralizing this
function — a verifier that hashed ``str(dict)`` was guaranteed to
disagree with a writer that hashed canonical JSON.

``None`` renders as the empty string. That is the pre-existing rule in
``src/audit_log.py``, and it must stay: changing it would invalidate
every signature already on disk.

Public surface
--------------

* :func:`compute_signature` — digest for one row, given the previous
  row's stored signature. Pure, no I/O.
* :func:`verify_chain` — walk rows in chain order, return the 0-based
  index of the first broken row, or ``None`` when the chain is intact.
* :func:`walk_chain` — the canonical ``(timestamp, event_id)`` ordering.

Both functions are storage-agnostic: they accept any iterable of
row-shaped mappings, which keeps the hash logic unit-testable without a
database and lets the live chain, the offline auditor verifier, and the
test suite share one implementation.

Migration note
--------------

``src/audit_log.py`` is retained as a thin re-export of this module so
existing imports (``tests/test_audit_log.py``, the QA harnesses in
``scripts/``) keep working and so the chain rule has exactly one
implementation to review. New code should import from here.
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


# Ordered tuple of fields whose concatenation forms the hash payload,
# after the leading ``previous_signature``. Read by the chain writers,
# the verifiers, the tests, and the SQL backfill. Any reorder changes
# every signature and breaks the chain, so this is a compatibility
# constant, not a styling choice.
CHAIN_FIELDS: tuple[str, ...] = (
    "event_id",
    "timestamp",
    "user_identifier",
    "action",
    "patient_hash",
    "data_elements",
    "model_run_id",
)

# Genesis row's previous_signature: 64 ASCII zeros.
GENESIS_PREVIOUS_SIGNATURE: str = "0" * 64

# The row stores its own signature, and the signature of the row before it.
_PREVIOUS_SIGNATURE_FIELD = "previous_signature"
_STORED_SIGNATURE_FIELD = "cryptographic_signature"

# Fields that may arrive either as a string or as a parsed structure.
# Both render to canonical JSON text so the digest does not depend on
# which reader produced the row.
_STRUCTURED_FIELDS = ("data_elements",)


def coerce_field(row: Mapping[str, Any], field: str) -> str:
    """Render ``row[field]`` as the exact text that gets hashed.

    ``None`` and missing values render as ``""``. Values that storage may
    return either as text or as a parsed structure (``data_elements``)
    render to canonical JSON — sorted keys, no whitespace — so a JSONL
    read and a Postgres ``JSONB`` read produce the same digest. Every
    other value renders through ``str()``.
    """
    value = row.get(field)
    if value is None:
        return ""
    if field in _STRUCTURED_FIELDS:
        return _canonical_json(value)
    return str(value)


def _canonical_json(value: Any) -> str:
    """Canonical JSON text for a chain field.

    A string is passed through *iff* it is already canonical; otherwise
    it is parsed and re-serialized. Passing a stored canonical string
    through unchanged matters because a few rows in the wild carry
    key ordering that ``json.dumps`` cannot reproduce, and re-serializing
    those would report a false chain break.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            # Not JSON at all — treat the raw text as the payload rather
            # than inventing a representation for it.
            return value
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        return canonical if canonical == value else canonical
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def compute_signature(
    previous_signature: str,
    row: Mapping[str, Any],
    *,
    fields: Iterable[str] = CHAIN_FIELDS,
) -> str:
    """Return the SHA-256 hex digest of ``row`` chained to ``previous_signature``.

    ``previous_signature`` must be a 64-character hex string; use
    :data:`GENESIS_PREVIOUS_SIGNATURE` for the oldest row in a chain
    partition. The row's own stored signature (if present) is ignored —
    the digest is always recomputed from the payload.

    ``fields`` defaults to :data:`CHAIN_FIELDS`, the audit-trail field set.
    A caller with a genuinely different field set (the biller feedback log
    records a decision, not a reviewer action) passes its own tuple so that
    it shares this digest *rule* without sharing the field list. The rule —
    no separator, canonical JSON, ``None`` as ``""`` — is what must not
    diverge; the field list may.
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
    for field in fields:
        hasher.update(coerce_field(row, field).encode("utf-8"))
    return hasher.hexdigest()


def verify_chain(rows: Iterable[Mapping[str, Any]]) -> int | None:
    """Return the 0-based index of the first broken row, or ``None`` if intact.

    ``rows`` must already be in chain order; use :func:`walk_chain` for
    the canonical ordering. Each row must carry both signature fields
    plus every field in :data:`CHAIN_FIELDS`.

    A row breaks the chain when either its stored ``previous_signature``
    does not match the signature it follows, or its stored
    ``cryptographic_signature`` does not match the recomputed digest.
    Checking both is deliberate: the link check alone misses an in-row
    mutation, and the digest check alone misses a fabricated
    ``previous_signature``.
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
        # Advance on the stored value so a non-canonical encoding choice
        # on the row just verified does not cascade into false reports
        # for every row after it.
        previous_signature = stored
    return None


def walk_chain(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return ``rows`` sorted by ``(timestamp, event_id)`` ascending."""
    materialized = list(rows)
    materialized.sort(
        key=lambda r: (coerce_field(r, "timestamp"), coerce_field(r, "event_id"))
    )
    return materialized
