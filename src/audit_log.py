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

# ---------------------------------------------------------------------------
# Implementation note (issue #113)
# ---------------------------------------------------------------------------
# The hash shape now lives in exactly one place: ``ai_billing_audit.chain``.
# This module is kept as the historical import surface — ``audit_trail.sql``,
# ``docs/RUNBOOK.md``, ``scripts/qa_audit_chain_*.py``, and
# ``tests/test_audit_log.py`` all import from ``audit_log``, and the runbook
# tells auditors to run the verifier from here.
#
# Previously this module held its own copy of the hash rule that rendered
# ``data_elements`` with ``str()`` while the live writer
# (``ai_billing_audit/audit_actions.py``) canonicalised it to JSON. The two
# disagreed on every row the writer produced, so verification reported
# tampering from row 0. Both now import from ``ai_billing_audit.chain``.

from ai_billing_audit.chain import (  # noqa: F401
    CHAIN_FIELDS,
    GENESIS_PREVIOUS_SIGNATURE,
    coerce_field as _coerce_field,
    compute_signature,
    verify_chain,
    walk_chain,
)

__all__ = [
    "CHAIN_FIELDS",
    "GENESIS_PREVIOUS_SIGNATURE",
    "compute_signature",
    "verify_chain",
    "walk_chain",
]
