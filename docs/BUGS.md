# BUGS.md — AI Billing Audit

Findings from the cross-tenant isolation bug hunt (kanban `t_bb58405d`),
plus the related bugs surfaced while testing the dedup contract.

---

## BUG-2026-06-16-01 — Encounter upload API has no tenant model and zero dedup

**Severity: Critical**

**Status: Open (no fix shipped — out of scope per the task body)**

### One-line summary

The `ai_billing_audit.api` FastAPI backend accepts anonymous uploads of any
`encounter_id` from any caller, enqueues one job per submit with a fresh
`job_id`, and writes every accepted job to `logs/upload_jobs.jsonl` with
no tenant context, no idempotency key, and no per-tenant scope.

### Affected surface

* `src/ai_billing_audit/api.py` (entire module, all upload routes)
* `src/ai_billing_audit/job_queue.py` (the queue, the runner, the JSONL log)
* `src/ai_billing_audit/synth_agent.py` (re-seeds the synth pipeline from
  `encounter_id`, so duplicate submissions deterministically produce
  duplicate `synth_encounter_id` values)

### Repro

```python
import json
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from ai_billing_audit import api
from ai_billing_audit.job_queue import (
    get_default_queue, reset_default_queue_for_tests,
)

reset_default_queue_for_tests()
client = TestClient(api.app)

def submit(payload):
    return client.post(
        "/encounters/upload/submit",
        data={"payload": json.dumps(payload)},
    )

TENANT_A = {"rows": [{
    "encounter_id": "enc_collide_001",
    "patient_id": "pat_alpha",
    "NPI": "1111111111",
    "date_of_service": "2024-05-15",
    "CPT_codes": ["99214"],
    "source_filename": "(paste form)",
    "source": "paste",
    "errors": [],
}]}

# 1000 alternating submits, two distinct payload contexts
with ThreadPoolExecutor(max_workers=64) as ex:
    responses = list(ex.map(submit, [TENANT_A] * 1000))

print("HTTP 200:", sum(r.status_code == 200 for r in responses))
# 1000

q = get_default_queue()
jobs = q.list_jobs()
print("Total jobs:", len(jobs))
print("Unique encounter_ids:", len({j.encounter_id for j in jobs}))
print("Jobs with encounter_id=enc_collide_001:",
      sum(1 for j in jobs if j.encounter_id == "enc_collide_001"))
```

**Result (verified 2026-06-16, FastAPI in-process):**

* 1000 HTTP 200 responses in 0.86s
* 1000 distinct `job_id`s in the queue
* 1000 jobs with the same `encounter_id`
* The synth runner (which seeds RNG from `encounter_id`) deterministically
  produces the same `synth_encounter_id` for every one of them

### Root cause

`job_queue.py:221-250` (`enqueue`) keys on a fresh `uuid4().hex[:12]` per
call and does not look at `encounter_id` at all. There is no
`(tenant_id, encounter_id)` unique key, no idempotency token, and no
`tenant_id` field in the `Job` or the `encounter` dict passed to
`enqueue`.

The author note at `api.py:288-290` (verbatim):

```python
# Auth / tenant scoping is intentionally out of scope per the
# task body — the route lives behind whatever the portal already
# enforces upstream.
```

The portal does not, in fact, enforce anything upstream. The portal's
Prisma schema has `Encounter.tenantId` and every portal query
(`src/lib/encounter-data.ts:62`) is tenant-scoped via
`where: { id: encounterId, tenantId }`, but the FastAPI backend is a
separate process that doesn't talk to the portal at all.

### Tenant-pair visibility matrix (on the current FastAPI backend)

| What tenant A submits | What tenant B submits | A can see | B can see | Cross-tenant leak? |
| --- | --- | --- | --- | --- |
| `enc_collide_001` with `pat_alpha`, NPI `1111…` | same `enc_collide_001` with `pat_beta`, NPI `2222…` | All 500 of A's jobs + all 500 of B's jobs in the JSONL log | All 500 of B's jobs + all 500 of A's jobs in the JSONL log | YES — but only because there is no notion of tenant at all |
| `enc_collide_001` only | (B does not submit) | All 1000 jobs | All 1000 jobs (via the same `encounter_id`) | YES — there is no isolation |
| `enc_AAA` (A's space) | `enc_BBB` (B's space) | All 1000 jobs (mix of both ids) | All 1000 jobs (mix of both ids) | YES — the JSONL log and the in-memory queue are global |

The current backend has exactly one tenant: the world. There is no
"tenant A" or "tenant B" — every submitter shares the same in-process
queue and the same JSONL log.

### What the "per-tenant review queue" and "audit findings store" are

Neither exists in the current backend. The audit findings are produced
by the synth agent (synthetic demo data) and discarded — they are
written to the JSONL log's `result` field as
`{"synth_encounter_id": "...", "difficulty_tier": "...", "variant": "..."}`
and never persisted to a queryable store. There is no per-encounter
review queue, no per-tenant index, and no findings table in the
backend.

The portal has a per-tenant `Finding` model keyed by `encounterId`, but
it is populated only by seed/test scripts (`scripts/seed-demo-encounter.ts`).
No production ingest path converts an 837P upload into a `Finding` row
on the portal.

### Recommended fix direction

1. Add `tenant_id: str` to the request model (header `X-Tenant-Id` or
   derived from the auth session — the API has no auth yet, see
   `docs/CODE_REVIEW_backend.md` finding #1).
2. Add an idempotency key: `(tenant_id, encounter_id)` is the natural
   composite. On duplicate submit, return the existing `job_id` (or
   409 if the existing job is in a terminal state the caller doesn't
   expect).
3. Add the same composite as a unique index on the future
   `audit_trail`-style table when it lands. The hash chain
   `audit_trail.sql` schema (currently `src/audit_log.py` /
   `apps/portal/src/lib/audit-chain.ts`) does not yet have an encounter
   table, so the unique constraint has to be added at the same time
   as the table.
4. Until auth lands, the upload API must bind to `127.0.0.1` only
   (already the case per `scripts/run_dashboard.py`).

### Cross-references

* `docs/CODE_REVIEW_backend.md` — finding #1: API auth absent (Critical).
  This bug is the same shape as #1 applied to the upload path.
* `docs/CODE_REVIEW_auditor.md` — finding #7: `dspy.configure(...)`
  mutates a process global, which would make a per-tenant adapter
  pin impossible in the same process. Independent of this bug but in
  the same "multi-tenant in a single Python process" lane.

---

## BUG-2026-06-16-02 — patient_id stored as raw string in FastAPI backend

**Severity: High**

**Status: Open**

### One-line summary

`api.py` accepts `patient_id` from anonymous submitters and persists it
in three places (the `encounter` dict, the `logs/upload_jobs.jsonl` log,
the `notes` endpoint's stored files) without hashing, encryption, or
tenant scoping.

### Affected surface

* `src/ai_billing_audit/api.py:315, 469, 529, 608` — captures
  `patient_id` from the paste form, 837P parser, and submit payload
* `src/ai_billing_audit/job_queue.py:205-217` — appends the full
  encounter dict (including `patient_id`) to `logs/upload_jobs.jsonl`
  on every status transition
* `src/ai_billing_audit/x12_parser.py:241-289` — parses `NM1*QC` /
  `NM1*MI` / `NM1*II` and surfaces the raw subscriber id as
  `patient_id`

### Repro

```python
import json
from fastapi.testclient import TestClient
from ai_billing_audit import api
from ai_billing_audit.job_queue import reset_default_queue_for_tests

reset_default_queue_for_tests()
client = TestClient(api.app)

payload = {"rows": [{
    "encounter_id": "enc_phi_test",
    "patient_id": "John Doe DOB 1970-01-01 MBR-123456",
    "NPI": "1234567890",
    "date_of_service": "2024-05-15",
    "CPT_codes": ["99214"],
    "source_filename": "(paste form)",
    "source": "paste",
    "errors": [],
}]}
r = client.post(
    "/encounters/upload/submit",
    data={"payload": json.dumps(payload)},
)
# r.json() returns a job_id; the patient_id is in the JSONL log.
```

After the call, `logs/upload_jobs.jsonl` contains a line with the raw
`patient_id` string. Anyone with read access to the project root can
recover it.

### Why this matters

* The portal stores `patient_id` only as a SHA-256 `patientHash`
  (`apps/portal/src/lib/onboarding.ts:80-81` /
  `scripts/seed-demo-encounter.ts:80-81`). The FastAPI backend
  contradicts the same project's hash-only policy.
* The plaintext patient_id in the JSONL log is a PHIPA / HIPAA
  evidence-of-record violation. The runbook verifier
  (`docs/RUNBOOK.md`) chains the JSONL log forward, so the chain
  silently preserves the raw PHI indefinitely.
* The notes endpoint at `api.py:620-661` writes the user-supplied PDF
  / image bytes to `logs/uploaded_notes/<uuid>.<ext>` — these notes
  may also contain patient identifiers in the body, and they are
  served back from disk on subsequent requests without any redaction.

### Recommended fix direction

1. Hash `patient_id` at the API boundary with SHA-256 (matches the
   portal's existing pattern; matches `src/audit_log.py`'s
   `patient_hash` field shape).
2. Reject `patient_id` values that fail a length/charset check
   (currently the field is non-empty-validated only — see
   `x12_parser.py:382-386`).
3. Add the same hash at the `x12_parser` layer so 837P uploads
   inherit the sanitization.
4. For the existing JSONL log, ship a one-off redaction script that
   replaces any plaintext `patient_id` with the SHA-256 hash and
   breaks the hash chain — the chain break is the correct signal
   (it is a redaction, and the runbook needs to know).
5. Until the redaction ships, treat `logs/upload_jobs.jsonl` and
   `logs/uploaded_notes/` as containing PHI and apply the same
   access controls the production Postgres will get.

### Cross-references

* `docs/CODE_REVIEW_backend.md` — finding #2 (input validation) flags
  the missing `patient_id` charset check; this bug is the privacy
  consequence of that gap.
* `apps/portal/prisma/schema.prisma` `Encounter.patientHash` — the
  reference design.

---

## BUG-2026-06-16-03 — Demo seed uses a single global encounter_id namespace

**Severity: Low**

**Status: Open (documented, not blocking)**

### One-line summary

`synth/render.py:_enc_id` mints encounter_ids as `enc_<8 hex>` with
**no** tenant prefix and **no** uniqueness guard beyond the seeded RNG.
Two tenants that happened to use the same seed (e.g. both running
`EASY/clean` for the first time after a process restart) would
collide.

### Affected surface

* `src/ai_billing_audit/synth/render.py:60, 90, 146` — `_enc_id(rng, …)`
* `src/ai_billing_audit/synth_agent.py:316-317` — `seed = abs(hash(encounter_id)) % 2**31`

### Detail

The synth agent deterministically maps `encounter_id → seed` via
Python's `hash()`. CPython's `hash()` is process-randomised by
default, so the same `encounter_id` produces two different seeds in
two different processes (separately noted in
`docs/CODE_REVIEW_backend.md` finding #2.c, as a determinism
footgun). Combined with the global `enc_<> → 8 hex` namespace, a
fresh dev process that lands on `seed=0` for an `EASY/clean`
generate call will mint the same `enc_xxxxxxxx` as the previous
process.

This is a demo-only concern. The portal uses Prisma cuids for
`Encounter.id` and is not affected. The fix is to either prefix the
synth id with the (future) tenant id, or to add a `tenant_salt` to
the seed hash, when the multi-tenant ingest ships.

### Recommended fix direction

* Add a `tenant_salt` parameter to `_enc_id(rng, tier, variant, salt)`
  and have the upload path pass `f"tenant:{tenant_id}"` (or a stable
  hash) as the salt.
* When the upload path is wired to the portal, the Prisma `Encounter.id`
  is the authoritative id and the synth id becomes a debug/audit
  field — collision between tenants' debug ids is then harmless.

---

## Methodology

The 1000-concurrent-upload test was run with Python 3.11 in-process
via `starlette.testclient.TestClient` (the project's existing test
harness — `tests/test_encounters_upload.py`). The thread pool size
matched the queue's `worker_count=2` default plus a safety margin
(`max_workers=64`); the queue's `BoundedSemaphore(2)` serialized
actual work, so the 1000 submits exercised the `enqueue` hot path
under contention, not the runner.

The "two tenants" framing is a thought experiment, not a real
multi-tenant setup — the current backend has no tenant concept. The
visibility matrix is what would happen if a tenant concept were
added naively (e.g. a header `X-Tenant-Id` with no enforcement).
With the current code, the matrix degenerates to "everyone sees
everything" because there is exactly one tenant.
