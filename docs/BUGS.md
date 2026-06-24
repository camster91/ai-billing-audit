# BUGS.md — AI Billing Audit

Findings from the cross-tenant isolation bug hunt (kanban `t_bb58405d`),
plus the related bugs surfaced while testing the dedup contract,
plus deploy/infra findings from the VPS smoke test (kanban `t_b199142a`).

---

## BUG-2026-06-16-04 — VPS deploy never completed: no Traefik route, no container, no project dir

**Severity: High (deploy blocker)**

**Status: Open (no fix shipped — out of scope per the smoke test task body)**

**Found by:** kanban `t_b199142a` (VPS build smoke test, 2026-06-16 23:30 EDT)

**Related docs:** `docs/VPS_SMOKE_TEST.md` (full smoke run + captured outputs)

### One-line summary

The `ai-billing-audit` application was never successfully deployed to
the Ashbi VPS at `187.77.26.99`. The repo and the `deploy-to-vps.sh`
script exist locally (commit `5305197` "Mirror VPS build to v0.1.0-rc1",
2026-06-16 23:24), but on the host: no Docker container is running
under any `ai-billing*`/`*billing*audit*` name, no Traefik router or
service for the hostname exists in `/opt/traefik/dynamic/`, the
project source dir `/opt/projects/ai-billing-audit/` does not exist,
and no Let's Encrypt cert has been provisioned under
`/opt/traefik/certs/`. The public hostname
`https://ai-billing-audit.ashbi.ca/healthz` returns Traefik's static
`404 page not found` on every path tried.

### Affected surface

* DNS: A record exists and points at the correct VPS (verified
  `dig +short ai-billing-audit.ashbi.ca A` → `187.77.26.99`), so the
  hostname is reachable; the failure is purely on the host.
* Traefik dynamic config:
  `/opt/traefik/dynamic/routers.yml` — no entry for
  `ai-billing-audit.ashbi.ca`. The 17 existing routers (arcan, photogen,
  hub, markup, splash, contractions, relay, simaqadeer, lull,
  lull-relay, jwhabits, tkd, artisan, animals, etc.) do not include
  this hostname.
* Traefik dynamic config:
  `/opt/traefik/dynamic/tls.yml` — no TLS entry for the host.
* Container inventory: `docker ps -a | grep -iE "billing|audit"`
  returns no matches. The closest neighbors are `arcan-app` (port
  3000) and `markup-clone` (port 3030) — unrelated.
* Project source: `/opt/projects/ai-billing-audit/` does not exist.
  The directory `/opt/projects/` only holds `contraction-tracker`,
  `contraction-tracker-relay`, `lull`, `lull-relay`, `splashtown-app`.
* TLS cert: no file under `/opt/traefik/certs/` for the host. The
  cert that Traefik serves on a 404 fallback is its self-signed
  default (`/CN=TRAEFIK DEFAULT CERT`, valid 2026-06-16 → 2027-06-16),
  which is the smoking gun: Traefik only emits that cert when no
  router claimed the request, so the `letsencrypt` resolver never
  ran for this hostname.
* Deploy script: `deploy-to-vps.sh` at the repo root is
  well-formed and idempotent (it preserves existing routers and
  only rewrites the `ai-billing-audit` block), but it has not been
  run successfully against this host.

### Repro (from a fresh macOS terminal)

```bash
# 1. Public hostname — should return 2xx + JSON; actually 404
curl -k -sS -w '\nhttp=%{http_code}\n' \
  https://ai-billing-audit.ashbi.ca/healthz
# Expected: {"status":"ok",...}
# Actual:   404 page not found (19 bytes, text/plain)

# 2. Traefik route should exist; it doesn't
ssh hostinger 'grep -i "ai-billing" \
  /opt/traefik/dynamic/routers.yml /opt/traefik/dynamic/tls.yml'
# Actual: no matches (exit 1)

# 3. Container should be running; it isn't
ssh hostinger 'docker ps -a --format "{{.Names}}\t{{.Status}}" \
  | grep -iE "billing|audit"'
# Actual: no rows (exit 1)

# 4. Source dir should exist on the host; it doesn't
ssh hostinger 'ls /opt/projects/ai-billing-audit'
# Actual: ls: cannot access '/opt/projects/ai-billing-audit': No such file or directory

# 5. Cert should be in /opt/traefik/certs/; it isn't
ssh hostinger 'ls /opt/traefik/certs/ | grep -i billing'
# Actual: no matches
```

The cert check is the most diagnostic — the LE cert for this host
should be at `/opt/traefik/certs/ai-billing-audit.ashbi.ca.{crt,key}`
if the deploy had ever run, because `deploy-to-vps.sh` waits up to
90s for the LE cert to issue. Its absence proves the deploy script
never reached the cert-provisioning step.

### Likely root cause

Two possibilities, in order of probability:

1. `deploy-to-vps.sh` was never invoked against this host. The script
   is the only documented path to put a route in Traefik + a
   container in Docker + a cert in `/opt/traefik/certs/`. All three
   are absent, which is the script's exact pre-condition vs.
   post-condition. The repo was committed (`5305197`) but the script
   was not run before the smoke test was scheduled.
2. The script was invoked but aborted before the cert-wait step.
   This is the less likely branch — even an aborted deploy would
   typically leave the source dir, the container, and at least a
   half-written route. The host is fully clean, so the script
   almost certainly never ran.

### Recommended fix direction

Run `deploy-to-vps.sh` from the repo root on the local machine with
the SSH alias (`hostinger` or `coolify`) configured. Pre-flight:

* Confirm `ssh hostinger 'docker ps'` works.
* Confirm `/opt/traefik/dynamic/routers.yml` is writable.
* Confirm the MiniMax API key file
  `/root/ai-billing-audit-secrets/minimax.env` exists on the host
  (referenced by the script; missing file would cause it to fail
  with a clear error).
* Confirm the postgres password file at
  `/root/ai-billing-audit-secrets/postgres.env` exists on the host.

If the script aborts, capture the line it failed on and update
this bug with the new exit point. Once the script finishes
successfully, re-run the smoke test in `docs/VPS_SMOKE_TEST.md`
from step 1.

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


---

# BUG-2026-06-18-01 — Live demo data files missing from container

**Severity: Critical (sales-call launch-blocker)**

**Status: Open**

**Found by:** kanban `t_ea5b7b03` (pilot demo dry run, 2026-06-18 20:51 UTC)

**Related docs:** `docs/PILOT_DEMO_RECORDING.md`

### One-line summary

The three demo encounters that `SALES_DEMO.md` is built around
(`enc_10032` easy / `enc_0007` medium / `enc_0000` hard) are registered in
the dashboard's index, but the underlying `data/val.json` and
`data/train.json` files are missing from the running container. Every
encounter-detail page returns 404 with `{"detail":"encounter '...' is
registered but the underlying record could not be located in data/val.json
or data/train.json."}`

### Affected surface

* `GET /encounter/{encounter_id}` for the 3 registered demo encounters
  returns the error JSON above (not a 404 — a 200 with a `detail` body
  that the template can't render, so the user sees a "no encounter"
  page).
* `GET /encounter/{encounter_id}/json` returns
  `{"detail":"'enc_10032' record not found"}`.
* `GET /` (home page) renders the encounter cards but each one shows
  the "record missing" badge.
* `n_registered: 3` in `/healthz` confirms the registry is loaded; the
  data files just aren't there.

### Repro

```bash
curl -sS -H "Authorization: Bearer *** \
  https://ai-billing-audit.ashbi.ca/encounter/enc_10032
# Actual: {"detail":"encounter 'enc_10032' is registered but the
#          underlying record could not be located in data/val.json
#          or data/train.json."}
```

### Probable cause

`Dockerfile` lost the `COPY data/ /app/data/` line in a recent image
rebuild, or the `data/` volume was cleared on deploy. Per
`docs/ITERATION_LOG.md` ("live URL frontend 2026-06-17 23:50 — DONE:
Added `data/` to the Docker image (was missing — demo encounters
404'd)"), this exact regression has happened once before.

### Fix

1. `cd /opt/projects/ai-billing-audit` on the VPS (or pull the repo
   to a local dir).
2. Verify `Dockerfile` contains a `COPY data/ /app/data/` (or
   `COPY data ./data`) line.
3. Verify the `data/` directory is present in the build context with
   `ls data/val.json data/train.json`.
4. Rebuild and redeploy: `docker build -t ai-billing-audit:latest .`
   then restart the container.
5. Smoke test: `curl /encounter/enc_10032` should return a full HTML
   page with clinical note + claim + findings.

---

# BUG-2026-06-18-02 — Uploaded encounter detail page returns 500

**Severity: High (sales-call launch-blocker)**

**Status: Open**

**Found by:** kanban `t_ea5b7b03`

**Related docs:** `docs/PILOT_DEMO_RECORDING.md`

### One-line summary

`GET /encounters/{encounter_id}` returns `Internal Server Error` for any
uploaded encounter (i.e. an encounter that was created via
`/encounters/upload/submit` and exists in the in-memory job queue). The
JSON endpoint `GET /encounters/{encounter_id}/json` works and returns
the audit data; only the HTML template route is broken.

### Repro

1. Submit a claim via `POST /encounters/upload/submit` and capture the
   returned `job_id` (e.g. `de33f7a358db`).
2. Wait for the job to complete.
3. `curl -H "Authorization: Bearer ***" \
   https://ai-billing-audit.ashbi.ca/encounters/pilot_easy_001` — returns
   `Internal Server Error` plain-text body.
4. The JSON variant works: `curl .../encounters/pilot_easy_001/json`
   returns `{"encounter_id":"pilot_easy_001","status":"done",
   "audit_status":"pending", ...}`.

### Probable cause

The HTML template likely tries to render the full encounter object
(claim, ground-truth findings, etc.) from the synth library, but an
uploaded encounter is a different shape than a synth encounter and the
template has no fallback.

### Fix

Either (a) make the HTML template robust to missing fields, or (b)
build a minimal EncounterView object for uploaded encounters with the
fields the template needs (encounter_id, status, summary, findings).

---

# BUG-2026-06-18-03 — Home page hardcodes `ENC001` placeholder link

**Severity: Medium**

**Status: Open**

**Found by:** kanban `t_ea5b7b03`

**Related docs:** `docs/PILOT_DEMO_RECORDING.md`

### One-line summary

The home page template renders a 4th encounter card with a hardcoded
`/encounter/ENC001` link and an encounter summary about a `cough, R05`
case. The link 404s (`ENC001` is not registered). The card sits
alongside the 3 registered demo encounter cards and was probably a
placeholder left in the template.

### Repro

```bash
curl -sS -H "Authorization: Bearer *** \
  https://ai-billing-audit.ashbi.ca/ | grep ENC001
# 5 occurrences of ENC001 in the rendered HTML
```

### Fix

Remove the hardcoded card from the template (likely
`templates/index.html.j2` or similar) and rely on the encounter loop
that renders the 3 registered cards. If the placeholder is intentional
content, register `enc_ENC001` in the demo registry and add a matching
entry to `data/val.json` so the card resolves.

---

# BUG-2026-06-18-04 — `/encounters/upload` route collides with catchall

**Severity: Medium**

**Status: Open**

**Found by:** kanban `t_ea5b7b03`

**Related docs:** `docs/PILOT_DEMO_RECORDING.md`

### One-line summary

`GET /encounters/upload` returns 404 (or, with trailing slash, 307 → 404)
because FastAPI's route matcher treats `upload` as an `encounter_id` for
the `/encounters/{encounter_id}` catchall route, and the encounter-detail
handler doesn't find a matching record. The "upload" nav link in the
topbar therefore 404s.

### Repro

```bash
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer ***" \
  https://ai-billing-audit.ashbi.ca/encounters/upload
# 404
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer ***" \
  https://ai-billing-audit.ashbi.ca/encounters/upload/
# 307
```

### Fix

In `src/ai_billing_audit/api.py`, reorder the `@app.get(...)` decorators
so that the more specific `/encounters/upload` route is declared
BEFORE the `/encounters/{encounter_id}` catchall. FastAPI matches in
registration order; the catchall is shadowing the upload page route.

---

# BUG-2026-06-18-05 — Job status endpoint returns stale `audit_status`

**Severity: Low**

**Status: Open**

**Found by:** kanban `t_ea5b7b03`

**Related docs:** `docs/PILOT_DEMO_RECORDING.md`

### One-line summary

`GET /encounters/upload/jobs/{job_id}` returns `audit_status: "pending"`
and `audit_summary: ""` even after the LLM has completed and the
summary is in the on-disk `upload_jobs.jsonl` log. The home page
correctly displays the LLM summary (it reads the log file directly),
but the JSON status endpoint returns the stale in-memory field.

### Repro

1. Upload a claim. Capture the `job_id` (e.g. `4af9d49700ca`).
2. Wait for the job's `status` field to become `"done"` (~5s).
3. `curl -H "Authorization: Bearer ***" \
   https://ai-billing-audit.ashbi.ca/encounters/upload/jobs/4af9d49700ca`
4. Response includes `"audit_status": "pending"` and empty
   `audit_summary` and `findings: []`, even though the LLM DID return
   a summary (the home page's "Most Recent Real-Audit Run" panel
   shows the real text for the same job).

### Fix

In the job-runner code, update `Job.audit_status` and
`Job.audit_summary` (and the `findings` list) when the LLM callback
returns. Currently it looks like the LLM result is appended to the log
file but the in-memory `Job` object is never updated to reflect it.
