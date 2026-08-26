# Operations Runbook

> **Historical, audit-trail-only runbook.** This file is the
> read-only runbook for verifying the `audit_trail` hash chain,
> extracting evidence, and supporting breach notification under
> PHIPA / HIA. It is **not** the canonical operator runbook.
>
> For preflight, deploy, rollback, backup, secret, and retention
> commands, see [`docs/OPERATIONS_RUNBOOK.md`](OPERATIONS_RUNBOOK.md).
> The two files together cover the full surface; do not infer
> live retention or compliance posture from either file alone.
> Tracked in issue #15.

> **Audience:** on-call engineer, OIPC / OAG auditor, support responder.
> **Scope:** every command here runs against the production database
> with the auditor's read-only role. None of them mutate state.

## 1. Audit trail verification (PHIPA / HIA evidence-of-record)

The `audit_trail` table is the immutable, append-only log of every
event the AI billing auditor emits. Each row carries a SHA-256
`cryptographic_signature` chained to the prior row's signature. Any
retroactive edit — by an insider, by a misbehaving model, by anyone —
breaks the chain at the edited row and at every row that follows. The
chain is the difference between "logs nobody reads" and "logs
admissible as evidence."

### 1.1 Chain construction (one-time reference)

For row `i`:

```
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
```

The genesis (oldest) row in each chain partition has
`previous_signature = "0" * 64` (64 ASCII zeros). Rows are walked in
`(timestamp ASC, event_id ASC)` order. The implementation lives in
`src/audit_log.py` and is exercised by `tests/test_audit_log.py`.

### 1.2 On-site verification command

Connect to the production database with the auditor's read-only
credential, then run:

```bash
psql -v ON_ERROR_STOP=1 -d ai_billing_audit <<'SQL'
SELECT id, event_id, "timestamp",
       previous_signature, cryptographic_signature
FROM   audit_trail
ORDER  BY "timestamp" ASC, event_id ASC
\gset chain_

python3 - <<'PY'
import sys
from pathlib import Path
# Allow running from any cwd; the project ships src/ on sys.path via
# the installed package, but for an on-site auditor we resolve it
# explicitly against the project root.
sys.path.insert(0, "/opt/ai-billing-audit/src")
from audit_log import verify_chain  # noqa: E402

import psycopg2
import psycopg2.extras

conn = psycopg2.connect("dbname=ai_billing_audit user=auditor_ro")
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("""
    SELECT event_id, "timestamp", user_identifier, action,
           patient_hash, data_elements::text AS data_elements,
           model_run_id, previous_signature, cryptographic_signature
    FROM   audit_trail
    ORDER  BY "timestamp" ASC, event_id ASC
""")
rows = cur.fetchall()
break_index = verify_chain(rows)
if break_index is None:
    print("OK — chain intact over", len(rows), "rows")
    sys.exit(0)
else:
    bad = rows[break_index]
    print("BREAK at index", break_index, "event_id=", bad["event_id"],
          "timestamp=", bad["timestamp"])
    sys.exit(2)
PY
```

Exit code 0 = intact. Exit code 2 = break detected. Anything else =
run failed; contact on-call.

### 1.3 Interpreting the result

| Exit | Output | Meaning |
|------|--------|---------|
| 0 | `OK — chain intact over N rows` | The chain verifies end-to-end. No retroactive edit detected. Record the row count and the SHA of the verifier script you ran in the auditor's notebook. |
| 2 | `BREAK at index I event_id=E timestamp=T` | The chain is broken. The row at index `I` (0-based) is the first row whose recomputed signature does not match the stored `cryptographic_signature`, or whose `previous_signature` does not match the prior row's stored signature. Treat the row as evidence of tampering: do not delete it, do not repair it, do not "fix" the signature. Export the row and every row after it (rows `I` through `N-1`) to a sealed CSV and notify the Privacy Officer. |
| 1 | any Python traceback | The verifier crashed (likely a connection error or a missing dependency on the auditor's laptop). Re-run after restoring connectivity; if the failure persists, escalate to on-call — do not interpret a crash as "chain intact." |

### 1.4 What "first break" means in practice

The verifier returns the **lowest** index whose recompute fails. In a
chain of `N` rows, a single edit at row `k` produces a break at index
`k` (because rows `k+1` through `N-1` carry `previous_signature`s that
do not match the broken row's stored signature, so they also fail to
verify). The first break is always the original edit point; the
remaining breaks are downstream artifacts of that edit.

A break that is **not** the original edit point is impossible unless
two independent edits happened. If `verify_chain` reports a break
at index `k` but the row at index `k` looks untouched, look for
an earlier edit that was somehow masked (e.g. a row whose
`previous_signature` was rewritten to point at a fabricated
genesis). The `verify_chain` implementation checks **both** the
link (`previous_signature` matches the prior row's stored
`cryptographic_signature`) **and** the digest (the row's own stored
`cryptographic_signature` matches the recompute). Either failure
surfaces as the first break.

### 1.5 What a break is NOT

- A break is not a bug in the verifier. The verifier is deterministic
  and unit-tested (`tests/test_audit_log.py`); 11 tests pin the
  behavior of `compute_signature` and `verify_chain` including the
  canonical 3-row insert / mutate / verify scenario.
- A break is not a clock-skew artifact. The chain walks on
  `(timestamp, event_id)`, not on insertion order, and the DB column
  is `TIMESTAMPTZ`.
- A break is not a duplicate-`event_id` artifact. The schema enforces
  `UNIQUE (event_id)` and the verifier does not re-insert.

### 1.6 Repair procedure (Privacy Officer only)

There is no automatic repair. The chain is append-only by design
(trigger `audit_trail_no_mutation` on the table). If a break is
confirmed and a legitimate business reason exists (e.g. an analyst
corrected a typo in `data_elements` before the row was signed), the
Privacy Officer must:

1. Export the broken row(s) to sealed storage with the verifier
   output attached.
2. Open an incident ticket with the chain break and the business
   reason.
3. The chain cannot be retroactively un-broken. New events from the
   repair time forward are appended as usual, and the chain resumes
   from the last verified row's `cryptographic_signature`.

## 2. Schema migration

The chain column was added by `audit_trail.sql` in the project root.
The migration is idempotent: re-running it on a populated table is a
no-op (the column-add is `IF NOT EXISTS`, the backfill is guarded by
`WHERE cryptographic_signature IS NULL`, and the trigger is created
with `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER`).

To re-verify a fresh install:

```bash
psql -v ON_ERROR_STOP=1 -d ai_billing_audit -f audit_trail.sql
psql -c "SELECT COUNT(*) AS unsigned_rows FROM audit_trail WHERE cryptographic_signature IS NULL;"
# Expected: 0  (backfill completed and column is NOT NULL)
```

## 3. References

- Zorva Unified Self-Hosted Master Specification, §9.D (chain
  construction, OIPC evidence-of-record).
- PHIPA (Ontario) s. 13 — accuracy, safeguarding, retention.
- HIA (Alberta) s. 35 — safeguards on individually identifying
  health information.
- `src/audit_log.py` — `compute_signature`, `verify_chain`,
  `walk_chain`.
- `tests/test_audit_log.py` — verifier unit tests.
- `audit_trail.sql` — schema, backfill, append-only trigger.
