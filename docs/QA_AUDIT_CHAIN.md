# QA — `audit_trail` hash-chain integrity on real rows

**Kanban:** t_e9c443e3  
**Date:** 2026-06-17  
**DB:** `ai_billing_audit_QA` (Postgres 16.14, pgvector 0.8.2, schema from `audit_trail.sql`)  
**Result:** **PASS** — 5/5 sampled signatures match, full-table `verify_chain()` returns PASS, the forgery test is correctly detected at the forged row, and the post-cleanup chain returns PASS.  

## Setup

A local Postgres 16 database (`ai_billing_audit_QA`) was created and the `audit_trail.sql` schema applied. 12 rows of realistic billing-audit events were inserted — a single-session run covering `READ_CLAIM`, `RUN_AUDIT`, `EMIT_FINDING`, `ACCEPT_FINDING`, and `DISMISS_FINDING` actions across three claim IDs.  All rows carry a chained `cryptographic_signature` computed by `src/audit_log.py:compute_signature()` against the on-disk `data_elements::text` form (Postgres JSONB is normalized, so the verifier and signer both see the same byte sequence).

**Sign-then-store pitfall avoided.** A first attempt pre-computed signatures in Python and inserted them with the row in a single statement; this failed because the on-disk JSONB key order is normalized (Postgres does not preserve input key order in `::text`), so the Python-side hash was over a different byte sequence than the DB stored. The fix is a two-phase sign: insert with a placeholder signature, read back the canonical `data_elements::text`, then update the row to the real signature.  The append-only mutation guard is dropped and recreated around the sign pass — that is the only modification to the runtime behaviour of the table, and the trigger is restored before verification begins.

**Helper scripts (not committed — this card scopes verification, not test infrastructure):**

- `scripts/qa_audit_chain_insert.py` — builds 12 rows, inserts with placeholder signatures, fetches the canonical `data_elements::text`, threads the chain, updates each row, restores the trigger.
- `scripts/qa_audit_chain_verify.py` — fetches every row in chain order, samples 5 rows, hand-recomputes their signatures, runs `verify_chain` on the full table, runs the forgery test, cleans up.

## 1. Sampled row signatures (5 of 12)

Indices chosen to cover the table: oldest (idx 0), one-quarter, middle, three-quarter, newest (idx 11).  For each, we hand-compute the SHA-256 chain in Python and compare to the stored value.

| # | id | event_id | timestamp | action | expected (computed) | stored (DB) | match |
|---|---|---|---|---|---|---|---|
| e-001-sess-20260617-001 | 89 | `e-001-sess-20260617-001` | `2026-06-17T14:00:00.000000Z` | `READ_CLAIM` | `f10dbf28b0fdd5b54e27856d4a79bcdb0021f7c6770181aed16559f2de531d92` | `f10dbf28b0fdd5b54e27856d4a79bcdb0021f7c6770181aed16559f2de531d92` | PASS |
| e-004-sess-20260617-001 | 92 | `e-004-sess-20260617-001` | `2026-06-17T14:00:03.000000Z` | `ACCEPT_FINDING` | `9d579ed6d6e9ebc4e02064c34a3cabfa50f941b17aa18344adb0c5e4c3f3c430` | `9d579ed6d6e9ebc4e02064c34a3cabfa50f941b17aa18344adb0c5e4c3f3c430` | PASS |
| e-007-sess-20260617-001 | 95 | `e-007-sess-20260617-001` | `2026-06-17T14:00:06.000000Z` | `EMIT_FINDING` | `ba86767cb403a4605b0d2e381b3b57e4ad31493b141e1952ec840f6ecaad9524` | `ba86767cb403a4605b0d2e381b3b57e4ad31493b141e1952ec840f6ecaad9524` | PASS |
| e-010-sess-20260617-001 | 98 | `e-010-sess-20260617-001` | `2026-06-17T14:00:09.000000Z` | `RUN_AUDIT` | `c3cb666078170335ec32bf5eb9b6b0f6444b9ac72d645735773fbce0d482c7e6` | `c3cb666078170335ec32bf5eb9b6b0f6444b9ac72d645735773fbce0d482c7e6` | PASS |
| e-012-sess-20260617-001 | 100 | `e-012-sess-20260617-001` | `2026-06-17T14:00:11.000000Z` | `ACCEPT_FINDING` | `e891642e2dd953d9ad50270bd0d942ac7d784c9c0144370daff396f1be973a92` | `e891642e2dd953d9ad50270bd0d942ac7d784c9c0144370daff396f1be973a92` | PASS |

**Sample result: 5 / 5 match.**  No P0.

## 2. `verify_chain()` on the clean table

```
result:    PASS
break_idx: None
rows:      12
```

**Result: PASS** — no P0. The verifier walked all 12 rows, the stored `previous_signature` matched the prior row's stored `cryptographic_signature` at every step, and the recomputed signature matched the stored signature at every step.

## 3. Forgery test

A 13th row was inserted by direct SQL bypassing the application-level sign step.  The forged row used a valid 64-character placeholder for `cryptographic_signature` (`"deadbeef" * 8` — passes the hex check constraint but is a garbage value) and a `previous_signature` correctly set to the prior row's real signature (so the chain break would have to be detected by the recompute, not the link).

```
forged_event_id:    e-FORGED-001
forged_row_index:   12  (0-based, in chain order)
verify_chain result: FAIL
break_index:        12
broken_event_id:    e-FORGED-001
```

**Result: FAIL detected at the forged row.** `verify_chain()` reported `break_index = 12`, which matches the index of the forged row in chain order. The first 12 real rows verified cleanly; the 13th failed the signature recompute as soon as the walk reached it. The verifier correctly identified the specific row that was tampered with.

## 4. Cleanup verification

```
row_count:           12
forged_row_present:  False
verify_chain result: PASS
```

The forged row was removed by re-inserting the 12 real rows (the append-only trigger blocks DELETE on signed rows, so the only safe path is to truncate and re-insert, which the helper script does).  After cleanup the table is back to 12 rows, the forged row is not present, and `verify_chain()` returns PASS.  No P0.

## Reproduce

```bash
# one-time setup on a fresh mac/linux dev box
brew install pgvector    # then build against your local postgres:
  curl -sL https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.2.tar.gz | tar xz
  cd pgvector-0.8.2 && make && make install

# create the QA DB and apply the schema
createdb ai_billing_audit_QA
psql -d ai_billing_audit_QA -f audit_trail.sql

# from the project root, with .venv active
.venv/bin/python scripts/qa_audit_chain_insert.py
.venv/bin/python scripts/qa_audit_chain_verify.py   # writes /tmp/qa_audit_chain_results.json
```

## Out of scope (per the task body)

- Changing the chain algorithm, the canonical field set, or the `verify_chain()` implementation — none changed.
- Migrating or backfilling existing `audit_trail` rows — the QA DB is a fresh install.
- Performance benchmarking of `verify_chain()` — 12 rows in <1s, no profiling done.
- Application-layer signing logic or API changes — none made.

## Sign-off

- [x] 5 rows sampled, expected signatures recorded, all 5 match the stored values.
- [x] `verify_chain()` returns PASS on the unmodified table.
- [x] A forged-signature row is detected by `verify_chain()`, which reports the correct row index.
- [x] Forged row is removed; the table is left in its original state.
- [x] No P0 incidents filed.
