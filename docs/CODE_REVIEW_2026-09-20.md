# Code Review — 2026-09-20

Full-repo review of `camster91/ai-billing-audit` at commit `24f969e`, covering four surfaces:
the Python/FastAPI API stack, the Next.js portal (`apps/portal`), the deploy/ops surface, and the
database schema.

**Method and limits.** This was a static, read-only review. No test suite was run, no script was
executed, and no request was sent to a live instance. Findings marked *confirmed* are verified in
the source with file:line evidence; findings marked *suspicion* are mechanisms that the code
permits but were not demonstrated. Several findings (notably the deploy and schema items) describe
what the checked-in code *allows*, not proof that production is currently in that state — the repo's
own `docs/OPERATIONS_RUNBOOK.md` warns that the repo is not evidence a live host matches.

**Overall.** The codebase is more carefully built than a ~36k-line single-module scan suggests.
PHI encryption is real AEAD, LLM output is schema-validated, retry semantics are correct, the
secret-handling discipline in the deploy scripts is above average, and the test suite contains no
fake-passing tests. The real defects cluster in four places: the audit trail's integrity
guarantees, tenant scoping on the Python side, the deploy/migration path, and a handful of
missing authorization gates.

---

## Priority fixes

| # | Severity | Area | Finding |
|---|----------|------|---------|
| 1 | High | Portal authz | `/api/audit/export` has no permission check and is unlogged |
| 2 | High | Python audit trail | Audit writes swallowed by `except Exception: pass` (8 sites) |
| 3 | High | Deploy | No pre-migration DB backup; no app/schema version coupling |
| 4 | High | Database | `audit_trail` append-only trigger is bypassable via null signature |
| 5 | High | Python correctness | Completed audits become unretrievable after a restart |
| 6 | Medium | Audit chain (both stacks) | Python chain has no lock and can fork; portal chain is unkeyed |
| 7 | Medium | Repo hygiene | Eight `.edi` uploads committed to git; `uploads/` not ignored |

---

## 1. Portal: `/api/audit/export` has no role or capability gate — HIGH (confirmed)

`apps/portal/src/app/api/audit/export/route.ts:44-59`

The route authenticates the session and resolves the active tenant, then queries
`prisma.auditTrailEntry.findMany({ where: { tenantId: tenant.id } })` with **no** call to
`assertMembershipCapability` / `requireTenantRole` / `hasCapability`. Every sibling read route
(encounters/export, findings/export, usage) gates on the `read` capability.

The audit chain is the most sensitive artifact in the product: every accept/dismiss action, the
reason text, patient hashes, and prior signatures. Any active member of the tenant — including a
read-only `viewer` the tenant deliberately restricted — can export up to `EXPORT_ROW_CAP`
(10,000) rows of it. The route also disables its own self-logging (explicit `TODO` at lines 31-37),
so the export leaves no trace of who pulled what.

**Fix.** Add `assertMembershipCapability(session.user.id, tenant.id, "read")` — or gate stricter
(`owner`/`admin`) if privacy-officer exports are treated as a write-class action — and implement
the deferred `appendAuditEvent` so exports are themselves chained.

---

## 2. Python: audit-trail writes are swallowed — HIGH (confirmed)

`src/ai_billing_audit/api.py:2437-2438, 2776-2777, 3032-3033, 3195-3196, 3525-3527, 6779-6780, 6827-6828, 7570-7571`

Thirteen sites in `src/` (eight in `api.py`) wrap the audit write in a bare swallow while the route
still returns success:

```python
try:
    audit_append(...)
except Exception:
    pass
return JSONResponse({...})
```

At `api.py:7570` this covers the **tenant data-purge** audit row: `DELETE /api/tenants/{id}` returns
200 even if the compliance record of the purge was never written. For a compliance product the audit
trail is a first-class output, not a side effect — a 200 that silently skipped the record is an
integrity claim the caller cannot detect.

**Fix.** Log at `error` with action + encounter_id and surface `"audit_recorded": false` in the
response, or fail the request. A bare `pass` is only defensible when the lost write is
reconstructible elsewhere; for the purge path it is not.

---

## 3. Deploy: no pre-migration backup and no schema coupling — HIGH (confirmed)

`deploy-to-vps.sh:283-292` vs `docker-compose.yml:110-118`; init mount `docker-compose.yml` →
`./audit_trail.sql:/docker-entrypoint-initdb.d/01-audit_trail.sql:ro`

The API deploy builds and brings up the stack with no `pg_dump` beforehand. The only backup is the
separate weekly cron (`deploy/scripts/ai-billing-audit-backup.cron`). Critically,
`audit_trail.sql` only auto-applies on the **first boot of an empty pgdata volume** — a redeploy
over an existing volume silently does nothing. If the new image expects newer columns (e.g.
`bulk_action_id`, `previous_signature`), the app boots, `/healthz` returns green (it never touches
the database), and the first real audit write fails.

`docs/OPERATIONS_RUNBOOK.md:110-116` already requires "record a database backup artifact" before
deploying, but the script does not produce one.

**Fix.** Before `up -d`, run `pg_dump` to a dated host artifact (or invoke
`deploy/scripts/audit-backup.sh --tier daily --force`) and gate the deploy on it succeeding.
Add an explicit migration step that runs `psql -v ON_ERROR_STOP=1 -f audit_trail.sql` against the
existing volume and fails the deploy on error, mirroring the portal's `portal-migrate` one-shot
service.

*Before acting on this item:* two DB-URL lines (`deploy-to-vps.sh:262-263`,
`deploy-portal.sh:156`) rendered ambiguously during review. Confirm by eye that they interpolate
`${POSTGRES_PASSWORD}` rather than a literal.

---

## 4. Database: append-only trigger on `audit_trail` is bypassable — HIGH (confirmed)

`audit_trail.sql:196-213` (trigger `audit_trail_block_mutation`)

```sql
IF OLD.cryptographic_signature IS NULL
   AND NEW.cryptographic_signature IS NOT NULL THEN
    RETURN NEW;
END IF;
```

The trigger permits any `UPDATE` on a row whose *current* signature is `NULL`. The column is set
`NOT NULL` by the script, but the trigger's null branch stays live — so any row written by a code
path that omits the signature, restored from an older dump, or produced by a future bug lands
unprotected. Such a row can have `patient_hash`, `data_elements`, `action`, or `user_identifier`
rewritten without the trigger firing, defeating the tamper-evidence guarantee the chain exists to
provide. `verify_chain()` will still report a break, but the mutation is not blocked at write time.

**Fix.** Reject null signatures at insert time (a `BEFORE INSERT` trigger), and scope the bypass to
the backfill block via a transaction-local flag (e.g. `current_setting('audit_trail.backfill', true)`)
rather than keying the guard off a nullable column.

---

## 5. Python: completed audits become unretrievable after a restart — HIGH (confirmed)

`src/ai_billing_audit/public_api.py:334, 654, 711-742`; `job_queue.py:510-528, 531-546`

`POST /v1/audits` returns `202 {audit_id, status_url}`. After any process restart, the durable index
row is found, but `queue_resolver().get(job_id)` returns `None` because the job body lives only in
the in-memory registry. The route then returns `404 {"code": "not_found", ...}` at
`public_api.py:735-741`. A routine `docker compose up -d` therefore makes every in-flight and
recently-completed audit permanently unretrievable to an API consumer.

**Fix.** Add `JobQueue.rehydrate(job_id)` that rebuilds a `Job` from the last JSONL row and call it
when `get()` misses; or store the terminal `result` in the `v1_audits.jsonl` index row itself.

---

## 6. Audit chain integrity — MEDIUM (Python: confirmed mechanism; Portal: confirmed)

**Python — chain can fork.** `src/ai_billing_audit/audit_actions.py:183-232, 265-352`.
`_read_last_signature()` caches `(signature, mtime, path)` in module globals and serves the cache
whenever the file mtime is unchanged. `append()` performs read → compute → write with **no lock
anywhere in the module**. `job_queue.py:604-610` runs audits on daemon threads with a default
worker count of 2. Two threads finishing within the same mtime granularity can chain to the same
predecessor and both append, forking the chain. Fix: guard read/compute/append with one module-level
`threading.Lock`, and drop the mtime cache from the write path entirely.

**Portal — chain is unkeyed.** `apps/portal/src/lib/audit-chain.ts:37, 43-51, 80-91`. The chain is
plain `SHA-256(prev || eventId || ...)`. There is no HMAC and no key (`createHmac` appears nowhere
in `audit-chain.ts` or `audit-write.ts`). Anyone with database write can recompute every signature
forward and produce a chain `verifyChain()` accepts, since the verifier advances on the *stored*
signature. Tamper-evidence against accidental edits holds; tamper-*resistance* does not. Fix: HMAC
the digest with a key held outside the database, or sign the head hash out-of-band.

---

## 7. Eight uploaded `.edi` files are committed to git — MEDIUM (confirmed)

`apps/portal/uploads/*.edi` — 8 tracked files. `apps/portal/.gitignore` has no `/uploads/` entry.

The files are plaintext 837P (`ISA*00*...`), not the `zorva-aesgcm-v1` format the upload path
writes, so they predate or bypass it. Content is clearly synthetic (`JANE DOE`, `PATIENT001`,
NPI `123456789`), so there is no live PHI leak — but this proves the upload directory is a tracked
path. One real upload from a dev checkout commits PHI to the repository permanently.

**Fix.** Add `uploads/` to `.gitignore`, `git rm --cached` the eight files, and add a CI check that
rejects tracked `uploads/**`.

---

## Medium and lower findings

### Python / API stack

- **Tenant scoping is global, not per-caller — MEDIUM.** `api.py:947-948` defines a single
  `_TENANT_ID` from env; `UserContext.tenant_id` is parsed and validated (even enforced against the
  env at `api.py:253`) but `grep -rn "user.tenant_id" src/` returns nothing — no query is filtered
  by the caller's tenant. All scoping reads the process-wide constant. Correct for one clinic today;
  it will not hold two. Thread `user.tenant_id` into every read and make the constant a default used
  only when no principal is present.
- **Idempotency keys are not owner-scoped — MEDIUM.** `idempotency.py:155, 196-215` stores
  `{key, fingerprint, status_code, response_json}` with no owner field; lookup matches on key +
  fingerprint alone, and `api.py:5941` takes the raw client header. Two callers choosing the same
  key with an identical body receive each other's cached response verbatim. Namespace the key with
  tenant + user before lookup and store.
- **SSRF guard is DNS-rebindable — MEDIUM.** `webhooks.py:213-253` resolves the URL at registration
  and rejects private/loopback/link-local IPs, but the dispatcher performs its own DNS lookup before
  the POST. A host can resolve public at registration and internal at delivery. Resolve once and pin
  the IP through the connection; re-validate the peer IP after connect.
- **Per-clinic attribution collapses silently — MEDIUM.** `per_clinic_f1.py:216, 298, 403, 953` and
  `finding_assignments.py:267` all share a `_resolve_clinic` that swallows any exception from
  `clinic_for_biller` and returns `biller_id or "default_biller"`. A failing resolver silently
  attributes every affected biller to one pseudo-clinic, and the dashboard renders a plausible wrong
  number with no log line. Log a warning and return a sentinel the dashboard renders as
  "attribution unavailable".
- **Empty-findings retry doubles LLM spend and is a leading prompt — MEDIUM.** `auditor.py:690-699`
  re-invokes the model at the same `temperature=0.2` when the first pass returns no findings and a
  clinical note exists, accepting the retry whenever it returns *any* findings — with no scoring and
  no record that the primary response was overridden. The retry message hardcodes five SOMB rules to
  look for, biasing a genuinely clean claim toward false positives, and the zero-findings case is
  the common path, so it is a 2× cost on the majority of audits. Retry at `temperature=0`, require
  the retry to survive validation, and record `retried: true` with the discarded first pass.
- **`api.py` is a god-file — MEDIUM.** 8,033 lines, 99 routes. Contains RBAC/signed-principal auth,
  middleware, financial computation, ~1,800 lines of marketing HTML routes, the LLM audit endpoint,
  and inline Slack integration. The largest handler (`encounters_audit`) is 371 lines; `_bulk_apply`
  is 306. Extract `routes/marketing.py`, `routes/audit.py`, `routes/reports.py`; move the pure
  financial functions into the existing `analytics.py`.
- **Duplicate modules split the claimed single source of truth — MEDIUM.** `src/llm_client.py` (628
  lines, per-provider factory) vs `src/ai_billing_audit/llm.py` (241 lines, single litellm-backed
  class) — both declare `LLMClient`, and `llm.py`'s docstring claims all calls must go through it,
  which is only true inside the package. `compute_signature` and its chain-field tuple are
  implemented **three times** (`src/audit_log.py:125`, `audit_actions.py:136`, `feedback.py:427`)
  with a hand-maintained byte-compatibility invariant and a prior separator bug on record. Extract a
  single `audit_chain` module and a regression test that asserts one implementation verifies the
  other's rows.
- **CI gate is largely cosmetic — MEDIUM.** `.github/workflows/test-on-pr.yml:59-62` runs
  `mypy src/ai_billing_audit` with no configuration at all; the inline comment claims it matches a
  `[tool.mypy]` section in `pyproject.toml` that does not exist. `ruff check .` runs with no
  `[tool.ruff]` config, i.e. the default rule tier. Neither would flag the swallowed exceptions in
  finding 2. Add real `[tool.mypy]` and `[tool.ruff.lint]` config, and type-check all of `src/`.
- **Rate limiter trusts a client-controllable header — LOW.** `api.py:1512-1522` takes the rightmost
  `X-Forwarded-For` hop. That is only the proxy-added hop if a trusted proxy actually appends; if the
  app is reachable directly, the client controls it and can rotate to bypass the cap on `/contact`
  and `/api/encounters/upload`. Prefer `request.client.host` and parse XFF only from an allowlisted
  proxy CIDR.
- **Slack integration registration has no admin check — LOW.** `api.py:7957-7986` accepts a
  client-supplied `clinic_id` and is reachable by any `biller` role. Add `Depends(require_admin)`.
- **`AUDIT_ALLOW_HEADER_RBAC` is an env-flippable privilege escalation — LOW.** `api.py:204-217`.
  Header RBAC is correctly untrusted by default; the opt-in flag is safe in code but would be a full
  escalation primitive if ever set in production. Confirmed absent from the deploy script; keep it
  that way, or remove the flag.
- **Test suite misses the risky seams — MEDIUM.** `tests/conftest.py:26` sets `AUDIT_ALLOW_NO_AUTH=1`
  globally, so no test exercises the auth middleware as a negative case. `test_audit_endpoint.py:232`
  replaces the queue with a fake, so the real handler/queue/JSONL path is untested — an integration
  test driving POST → GET through a simulated restart would have caught finding 5. CI also uses
  `--maxfail=1`, aborting after the first failure.
- **Python version targets disagree — LOW.** `.python-version:1` and CI target 3.11;
  `Dockerfile:11` builds on 3.12; `pyproject.toml` declares no `requires-python`. Add
  `requires-python = ">=3.11,<3.13"` and test 3.12 alongside 3.11.
- **No lockfile — LOW.** Eight direct pins with documented rationale, but `dspy` and `litellm` pull
  large unpinned transitive trees. Commit a `uv.lock` and install from it in CI and the image.
- **Repo hygiene — LOW.** `README.design-history.md` (34KB) and a committed `qa-bundle.zip` sit in
  the root; `artifacts/`, `runs/`, `logs/` are large and not uniformly ignored.

### Portal

- **Onboarding routes trust client-supplied `tenantId` and file path — MEDIUM.**
  `src/app/api/onboarding/upload/route.ts:37-38, 70` and `first-encounter/route.ts:38, 52, 63-78`.
  Cross-tenant access is correctly blocked by `requireOnboardingAuth`, and path traversal is
  correctly blocked by the Zod regex plus `path.resolve`/`startsWith` containment. The design is
  still fragile: the public route has the caller name both the tenant and the file. Separately,
  `upload/route.ts` runs the membership check *after* parsing a 20MB multipart body, so an
  unauthenticated caller can force expensive parsing before the 401. Move the auth check before
  `request.formData()` and derive the upload path server-side.
- **Stripe webhook dedup can permanently drop an event — LOW/MEDIUM.**
  `src/app/api/billing/webhook/route.ts:529-551, 575, 589`. Signature verification is correct (raw
  body + `constructEvent`), but `markEventSeen` inserts *before* the handler runs, so a transient DB
  failure in the handler returns 200-ack-and-skip and Stripe's retry never re-applies the event. Pass
  an explicit signature `tolerance`, and delete the dedup row when the handler throws.
- **`trustHost: true` with a conditional host guard — LOW.** `src/auth.ts:236` sets
  `trustHost: true`; `src/middleware.ts:160-171` enforces the canonical host only when
  `NODE_ENV === "production" && AUTH_URL` is set, so an empty `AUTH_URL` in production silently
  disables the guard. Fail closed when `NODE_ENV === "production"` and `AUTH_URL` is unset. (Session
  strategy is the database strategy via `PrismaAdapter` — correct, enables server-side revocation.)
- **`NEXT_PUBLIC_FASTAPI_URL` used as a server-side base — LOW.** `src/lib/fastapi.ts:26-29` falls
  back through `NEXT_PUBLIC_FASTAPI_URL` for a server-side fetch target. `NEXT_PUBLIC_*` ships to
  the browser, so a build-time misconfiguration exposes the internal API origin. Server fetches
  should read only `FASTAPI_BASE_URL`.
- **Shared static bearer for portal→FastAPI — LOW.** `src/lib/fastapi-principal.ts:41-56` mints an
  HMAC-SHA256 principal with a 300s expiry (good) but also carries a static
  `FASTAPI_BEARER_TOKEN` shared across the deployment. Document it as a broad shared credential.

### Deploy / ops

- **Portal env file transits on the remote command line — MEDIUM.** `deploy-portal.sh:178-182`
  base64-encodes `portal.env` (Stripe secret, `AUTH_SECRET`, bearer token, signing secret, PHI key)
  and passes it as an argv to the remote shell, where it is visible in `/proc/*/cmdline` and any
  remote history for the duration of the deploy. Base64 is encoding, not encryption. Pipe it over
  stdin instead.
- **Readiness gate proves less than it claims — MEDIUM.** The compose healthcheck probes `/readyz`,
  which `docs/OPERATIONS_RUNBOOK.md:88-97` correctly describes as config-presence only; the deploy's
  extra `/healthz` probes do not touch the database or the LLM. A deploy can go green with an
  unreachable database or a bad LLM key. Add a real dependency round-trip (a `SELECT 1`, or a cheap
  authenticated LLM call) to the gate.
- **`ollama:latest` unpinned — LOW.** `docker-compose.dev.yml:255`. Dev-only, but the sole unpinned
  image in the tree.
- **Retention-sweep failure counter is dead code — LOW.** `deploy/scripts/audit-backup.sh:470-486`
  declares `failures=0`, never increments it, then alerts only if it is non-zero. A per-tier `rclone
  delete` failure is silently swallowed. Capture each exit status and increment.
- **`.dockerignore` lacks an env-file backstop — LOW.** The root `.dockerignore` excludes no
  `.env`/`portal.env`. No secret is copied today (the Dockerfile's `COPY` set is explicit), but a
  future `COPY . .` would bake the API env into a layer. Add `.env`, `.env.*`, `portal.env`, `*.pem`,
  `*.key`.
- **Broken `***` placeholders in CI and dev compose — LOW (informational, no leak).**
  `.github/workflows/test-on-pr.yml:110` and `docker-compose.dev.yml:171, 198` contain literal `***`
  in `DATABASE_URL`. These cannot authenticate — they are redaction tokens, not credentials. The CI
  job works only because those tests do not rely on the job-level variable; the dev compose file is
  not runnable as checked in.

---

## Verified good

- **Portal tenant isolation is correct and stronger than the Python side.** `requireTenantById`
  (`lib/active-tenant.ts:55-71`), `requireTenantRole` (`lib/roles.ts:132-149`), and
  `assertMembershipCapability` (`lib/membership-gate.ts:39-52`) all re-query `membership` per request
  and treat `inactive` as a non-member. `x-tenant-id` is a hint, not authority. Prisma queries filter
  in-query (`encounters/export:93`, `findings/export:111`, `findings/bulk/accept:90`), so smuggled
  foreign ids return empty rather than leaking.
- **PHI encryption is genuine AEAD.** `lib/data-encryption.ts:37-41` uses AES-256-GCM with a random
  12-byte IV per record, a 16-byte auth tag, magic-header framing, and fails closed if the key is
  absent, malformed, or not 32 bytes. No ECB, no static IV, no unauthenticated cipher.
- **API auth is well built (Python).** Bearer middleware gates all routes except a tight allowlist,
  `hmac.compare_digest` is used for both bearer and webhook comparison, missing token fails closed
  with 503, and signed principals are HMAC-SHA256 with a ≥32-byte secret, an expiry check, a maximum
  300s lifetime, and tenant binding. CORS is locked to the production origin with credentials off.
- **No SQL injection surface.** No raw SQL in `src/ai_billing_audit/`; storage is JSONL plus
  encrypted records.
- **Path traversal is defended** on every upload path (sanitized encounter ids, UUID-prefixed note
  uploads, regex plus resolve/containment in the portal).
- **Secret handling in the deploy scripts is disciplined.** No `set -x`, no echoed tokens, secrets
  read from host files and `chmod 600`, fail-closed validation of every required secret, and no real
  credential literal anywhere in the tracked tree.
- **Backups are encrypted, verified, and restore-tested.** `age` encryption with no plaintext-on-disk
  window, `audit_trail` presence asserted in the decrypted dump, size-anomaly alerting, tiered
  retention, and a monthly restore-verify into a throwaway database.
- **Container and CI hygiene.** Non-root portal runtime, no secrets baked into image layers,
  loopback-only published ports, no docker-socket mounts, and CI cannot deploy (deploy is a manual
  operator script — appropriate for a PHI system).
- **The Python test suite contains no fake-passing tests.** 1,691 test functions, zero
  assertion-free, one skip, zero xfail.

---

## Not reviewed

- `apps/portal/prisma/schema.prisma` and the Postgres migration set — specifically whether the
  unique constraints on `ProcessedStripeEvent.eventId` / `sourceUploadDigest` and the append-only
  trigger on `AuditTrailEntry` that the application logic assumes actually exist in the database.
  This affects the strength of findings 4 and the Stripe dedup item.
- `apps/portal/scripts/migrate-portal-phi.ts` and the `migrate:portal-phi` path — described in
  `docs/OPERATIONS_RUNBOOK.md:59-72` as an in-place re-encryption with "encrypted backups"; if that
  backup lives on the same volume, it is not a rollback artifact.
- `/api/onboarding/redeem` and `redeemCheckoutSession` — whether a caller can claim another buyer's
  checkout `sessionId` before the buyer does.
- `src/lib/audit-quota.ts` and `src/lib/audit-write.ts` were skimmed only for the chain/key question.
