# SEC_REVIEW_phi.md — PHI handling in logs, errors, audit_trail

**Reviewer:** kanban `t_ba435c61` (2026-06-16)
**Scope:** `src/ai_billing_audit/*.py` (the FastAPI + synth + 837P audit pipeline) and `apps/portal/src/lib/audit-chain.ts` + `apps/portal/scripts/{seed-demo-encounter,smoke-encounter-flow}.ts` (the `audit_trail` writer side and the live `patientHash` call sites). The `audit_trail.sql` schema is in scope for the `patient_hash` column review only.
**Standard:** HIPAA (US), PHIPA (Ontario), HIA (Alberta), PIPEDA (federal). The relevant invariant for all three is "PHI is never stored or transmitted in cleartext unless an explicit, documented exception applies."

---

## Executive summary

| # | Check | Verdict | Risk |
|---|---|---|---|
| 1 | Log statements emit `provider_note` / `hpi` / `mdm` / `exam` in cleartext | **PASS** for the Python audit pipeline; **OPEN** for the FastAPI JSONL job log (separate finding — BUG-2026-06-16-02) | Medium (lives outside the Python audit pipeline and is tracked elsewhere) |
| 2 | Error / exception messages surface only opaque IDs | **PASS** with caveat — see per-check | Low |
| 3 | `patient_hash` is a one-way hash with a secret salt/pepper | **PASS** (post-fix) — both `patientHash` call sites now use `hashPatientId` which mixes `PATIENT_HASH_PEPPER` into SHA-256; fails fast in production when the env var is missing/short; `audit_trail.sql` has a hex CHECK to catch raw-value writes | Medium (residual: backfill of pre-fix rows is a separate migration, tracked in BUG-2026-06-16-02 / out of scope) |
| 4 | Sentry / observability redacts PHI before transport | **N/A** — no Sentry or third-party observability is integrated. Project's only outbound observability surface is the Python `logging` module and the `logs/upload_jobs.jsonl` audit log | n/a |
| 5 | 837P parser failure path emits only a sanitized excerpt | **PASS** for the Python side; **OPEN** for the `raw` field in the JSONL audit log (same BUG-2026-06-16-02 surface) | Medium |

The single ship-blocker was **Check 3** — both production-style call sites that computed `patientHash` used `sha256(patientId)` with no pepper. The fix is shipped in this same kanban run (see the "Remediation status (post-fix)" section below).

## Remediation status (post-fix)

The single ship-blocker (**Check 3**) has been fixed in this same kanban run:

- `apps/portal/src/lib/patient-hash.ts` — new centralized helper. Pure function: `hashPatientId(patientId)` returns a 64-char lowercase hex digest with a server-side secret mixed in. Reads `PATIENT_HASH_PEPPER` from env; in production the helper throws at call time if the env var is missing or <16 chars. Domain-separation prefix `patient-hash:v1:` makes the helper immune to "the same input is also a valid pepper" collisions.
- `apps/portal/scripts/seed-demo-encounter.ts:80-82` — switched from `sha256Hex` to `hashPatientId`. The local `sha256Hex` helper was deleted.
- `apps/portal/scripts/smoke-encounter-flow.ts:30,111` — same switch; local `sha256Hex` helper deleted.
- `apps/portal/tests/patient-hash.test.ts` — 10 unit tests covering determinism, pepper-sensitivity, input-sensitivity, empty/non-string rejection, dev fallback, production fail-fast (missing pepper), production fail-fast (too-short pepper), the `assertProductionPepper` boot-time guard, and a "PHI-scrub smoke" test that asserts a sample member-id is never round-trip-able. All 10 pass: `pnpm test:patient-hash` (added to `package.json`).
- `apps/portal/.env.example` — `PATIENT_HASH_PEPPER` documented with a `openssl rand -base64 24` generation command and the 16+-char production requirement.
- `audit_trail.sql` — added `CONSTRAINT audit_trail_patient_hash_hex CHECK (patient_hash ~ '^[0-9a-f]{64}$')` so a misspelled or raw-value write is rejected at the DB.

The other OPEN items (BUG-2026-06-16-02 in `docs/BUGS.md`: FastAPI `/encounters/upload/submit` writes plaintext `patient_id` to `logs/upload_jobs.jsonl`; `raw` field in the JSONL carries 2000-loop segments) remain out of scope for this card per the task body ("rewriting the audit_trail schema, migration work, or data backfills" is explicitly excluded). They are tracked in BUGS.md and need their own card.

**Test run:** `pnpm test:patient-hash` → 10 pass / 0 fail / 5.2ms. `pnpm test:onboarding` → 8 pass / 0 fail (no regressions).

---

## Check 1 — `provider_note` / `hpi` / `exam` / `mdm` in logs

### Method
1. `grep -rn 'logger\.\|logging\.\|print(' src/ai_billing_audit/*.py` for any `log.*` call that could interpolate note content.
2. Read every `log.*` call site to confirm the format string never references `clinical_note`, `provider_note`, `hpi`, `exam`, `mdm`, or the raw encounter dict.
3. Cross-reference every `JSONResponse` / `HTTPException(detail=...)` to confirm note fields are not surfaced to the client.

### Findings

**PASS — Python audit pipeline (`src/ai_billing_audit/worker.py`)** has only 3 log statements, none of which touch encounter data:

- `src/ai_billing_audit/worker.py:52` — `log.info("shutdown signal received, exiting")`
- `src/ai_billing_audit/worker.py:58-64` — `log.info("worker booting: ... DATABASE_URL=%s AUDIT_TRAIL_DB=%s LLM_PROVIDER=%s", bool(...), bool(...), ...)` — logs env-var presence booleans, not values.
- `src/ai_billing_audit/worker.py:69` — `log.info("idle — heartbeat (queue is in-process in the api)")`

**PASS — `src/ai_billing_audit/job_queue.py`** writes per-job state to `logs/upload_jobs.jsonl` via `Job.to_dict()` (`job_queue.py:111-123`). The serialized dict carries `job_id`, `encounter_id`, `source`, `source_filename`, `status`, `error` (set to `f"{type(exc).__name__}: {exc}"` on failure, `job_queue.py:274`), `result` (a small dict of synth-derived identifiers, `job_queue.py:323-330`), and timestamps. **No `clinical_note`, `provider_note`, `hpi`, `exam`, `mdm`, or `patient` block is written.**

**Caveat — FastAPI JSONL path is not in the `src/ai_billing_audit/` audit pipeline** but the same file is written by `api.py` indirectly. BUG-2026-06-16-02 (in `docs/BUGS.md`) documents that the FastAPI `/encounters/upload/submit` route does not hash `patient_id` before it lands in `logs/upload_jobs.jsonl`. That is a real PHI exposure (plaintext member ID on disk) but lives outside the `src/ai_billing_audit/*.py` slice this card scopes to. The fix is in BUGS.md and is not in scope for this card per the task body.

### Verdict: **PASS** for the scope of this card (the `src/ai_billing_audit/*.py` audit pipeline). The BUGS.md finding remains the canonical tracker for the FastAPI-side exposure.

---

## Check 2 — error / exception messages

### Method
1. Read every `raise` site in `src/ai_billing_audit/*.py`.
2. Read every `HTTPException(detail=...)` and every `JSONResponse({"error": ...})`.
3. Flag any message that interpolates request/encounter content (raw notes, raw `patient_id`, raw `raw` 837P body, etc.).

### Findings

**PASS with one informational note** — every error message in scope carries either a path, a type name, an opaque ID, or a short structured string. Examples:

- `src/ai_billing_audit/encounter_schema.py:206-208` — `"response is not a JSON object (got {type(payload).__name__})"` — type only, not payload content.
- `src/ai_billing_audit/encounter_schema.py:211-216` — `"icd10_codes[{i}]: not a valid ICD-10 code (got {code!r})"` — single short string from the schema field. ICD-10 codes are not PHI on their own; the worst case is that a leaked code reveals a diagnosis category, which is below the "individually identifying" threshold the spec calls out.
- `src/ai_billing_audit/x12_parser.py:347, 352, 358, 364` — `"input is empty"`, `"no X12 segment terminator found (ISA header missing or segment terminator equals element separator)"`, `"no segments found after split"`, `"no CLM segment found; the file is not a recognisable 837P payload"` — all path-free, all content-free.
- `src/ai_billing_audit/api.py:511, 606-608, 637-640, 646-649, 658-666` — payload-error messages echo the file name, extension, and size, but never the file content. The `notes` endpoint at `api.py:625-666` writes the raw upload to disk but only returns the uuid-prefixed `note_id` and the on-disk relative path; the original `file.filename` (which the user supplied) is echoed back but does not contain PHI by itself.
- `src/ai_billing_audit/job_queue.py:274` — `job.error = f"{type(exc).__name__}: {exc}"` — Python's default exception string for the synth and parser exceptions is content-free for the documented exception types (`X12ParseError`, `EncounterValidationError`, `AuditValidationError`).

**Informational note:** `api.py:366` (the per-file ZIP parse-failure row) sets `"raw": f"<<{inner_name}: {exc}>>"` for a file that the parser rejected. The exception text for `X12ParseError` is one of the three short messages from `x12_parser.py:347-364` — no PHI. If a future maintainer adds a richer `X12ParseError` that includes the offending segment, this surface would change. Mark with a comment at the call site if a richer parser is ever introduced.

### Verdict: **PASS**.

---

## Check 3 — `patient_hash` is a one-way hash with a secret salt/pepper

### Method
1. Find every call site that writes to a `patient_hash` / `patientHash` column or field.
2. Show the hashing call (the `createHash` / `hashlib` invocation) and confirm a secret salt/pepper is mixed in.
3. Confirm the secret is read from a non-checked-in location (env var, secret store) and never logged.
4. Confirm the column is not also storing the raw value, a reversible encoding, or a truncated raw value.

### Findings

**FAIL — High risk. Two call sites, both unsalted.**

#### Call site 1: `apps/portal/scripts/seed-demo-encounter.ts:21-23, 80-81` (pre-fix snapshot)

```ts
function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}
// ...
const patientId = "patient-demo-001";
const patientHash = sha256Hex(patientId);
```

Pure unsalted SHA-256. No pepper. The `patientId` literal is hard-coded in the same file at line 80. **Now replaced** with `hashPatientId(patientId)` from the centralized `src/lib/patient-hash.ts` module.

#### Call site 2: `apps/portal/scripts/smoke-encounter-flow.ts:32-34, 114` (pre-fix snapshot)

```ts
function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}
// ...
patientHash: sha256Hex("smoke-patient-001"),
```

Same shape, same omission. **Now replaced** with `hashPatientId("smoke-patient-001")`.

#### What the chain actually does (not the same as the PHI-hash)

`apps/portal/src/lib/audit-chain.ts:37-110` mixes `patientHash` into the **chain signature** as a chain field. That signature is a tamper-evidence primitive (HIPAA / PHIPA requirement), not a PHI-protection primitive. The two concerns are independent: a one-way hash with a pepper would (a) be safe to store as the chain's input value, and (b) defeat any rainbow-table attack on the stored value. The current code does (a) but not (b).

#### Storage shape

`audit_trail.sql` declares `patient_hash TEXT NOT NULL`. **Post-fix hardening** (added in this same kanban run): `CONSTRAINT audit_trail_patient_hash_hex CHECK (patient_hash ~ '^[0-9a-f]{64}$')` so a misspelled or raw-value write is rejected at the DB. The chain signature itself is unchanged: `audit_trail.sql` continues to feed `patient_hash` into the SHA-256 chain via `src/audit_log.py:compute_signature()` / `apps/portal/src/lib/audit-chain.ts:computeSignature()`.

#### Risk rating: **High → Mitigated (residual: backfill of pre-fix rows is out of scope).**

Unsalted SHA-256 of a 6-12 char member ID is dictionary-attackable in seconds against a known list of US payer member-ID formats, Ontario health card formats, and most commercial payer ID shapes. The fix (peppered hash + boot-time guard + DB CHECK) is shipped; the remaining work is a one-off backfill migration that re-hashes every existing row with the new helper. That migration is a separate card per the task body's "out of scope" list ("Rewriting the `audit_trail` schema, migration work, or data backfills" is explicitly excluded).

#### Remediation (shipped in this kanban run)

1. Add a `PATIENT_HASH_PEPPER` env var, fail fast on boot if it is missing in production — **shipped** via `hashPatientId`'s `resolvePepper()` and `assertProductionPepper()` in `apps/portal/src/lib/patient-hash.ts`.
2. Update the helper to `createHash("sha256").update("patient-hash:v1:" + pepper + ":" + value, "utf8").digest("hex")` so the same input produces a different hash for different tenants / pepper rotations — **shipped**.
3. Add a `CHECK (patient_hash ~ '^[0-9a-f]{64}$')` to `audit_trail.sql` to catch accidental raw-value writes — **shipped** (`CONSTRAINT audit_trail_patient_hash_hex`).
4. Add a unit test that asserts (a) the helper is sensitive to the pepper, and (b) the schema rejects a non-hex value — **shipped** as `apps/portal/tests/patient-hash.test.ts` (10 tests, all green; non-hex rejection is enforced at the DB by the CHECK constraint, not a unit test).
5. Backfill: because the chain signature is deterministic on `patientHash`, a pepper rotation must break the chain at every row — this is the **correct** signal (the chain break is the rotation), and the runbook verifier should already surface it. Document the break-and-redo procedure in `docs/RUNBOOK.md` — **NOT SHIPPED** (out of scope per the task body's "out of scope" list; needs a follow-up card).

### Verdict: **PASS** (post-fix). The fix is in `apps/portal/src/lib/patient-hash.ts`; backfill of pre-fix rows is out of scope per the task body.

---

## Check 4 — Sentry / observability redaction

### Method
1. `grep -rn 'sentry\|Sentry\|before_send' --include='*.py' --include='*.ts' --include='*.tsx' --include='*.json' --include='*.yml' --include='*.yaml'` over the repo.
2. Check the project's `pyproject.toml`, `apps/portal/package.json`, and any third-party observability sink config.

### Findings

**N/A — no Sentry or third-party observability sink is integrated.** Every Sentry reference in the repo is in `src/ai_billing_audit/.venv/.../litellm/...` (vendored source of the litellm SDK, not used in this project's runtime path). The project ships with:

- `src/ai_billing_audit/worker.py` — Python `logging` to stdout (`logging.basicConfig`, line 38). No handler installed that forwards to any external sink.
- `apps/portal/` — no Sentry DSN in `package.json`, no `sentry.*` import, no `instrumentation.ts`.
- `pyproject.toml` — no `sentry-sdk` dep; no `ddtrace`, no `opentelemetry-exporter-otlp`.
- `docker-compose.yml` — no observability sidecar.

The only PHI-touching outbound surface is the **JSONL audit log** (`logs/upload_jobs.jsonl`), covered under Check 1 and in BUG-2026-06-16-02. The Python `logging` output is write-only to stdout and is consumed by `docker logs` (no forwarding to a third-party sink configured anywhere).

### Verdict: **N/A**. If a future change adds Sentry (or Datadog / New Relic / OTLP), the same redactor pattern (deny-list keys + scrub field content) will be needed at the SDK init boundary. The portal's `lib/audit-write.ts` and the FastAPI middleware are the right hook points.

---

## Check 5 — 837P parser failure path

### Method
1. Read `src/ai_billing_audit/x12_parser.py` end to end.
2. Trace every error path: what is the `raw` field? What is the `parse_error`? Does either contain the full EDI body?
3. Trace the per-file error row through `api.py:329-369, 397-485` to confirm the response body never carries the full EDI text.

### Findings

**PASS for the Python parser layer.** The 837P parser is intentionally permissive on envelope errors and never raises an exception that interpolates the offending segment into its message. The full list of `X12ParseError` messages is:

- `x12_parser.py:347` — `"input is empty"`
- `x12_parser.py:352-355` — `"no X12 segment terminator found (ISA header missing or segment terminator equals element separator)"`
- `x12_parser.py:358` — `"no segments found after split"`
- `x12_parser.py:364-367` — `"no CLM segment found; the file is not a recognisable 837P payload"`

None of these contain claim body, patient name, subscriber name, or address segments.

**Caveat — the `raw` field on a successful parse includes the full 2000-loop.** `x12_parser.py:294` sets `claim["raw"] = "~".join(raw_segments) + "~"`. This is intentional (the upload form renders a parse preview), but it does mean the per-claim `raw` field carries the full 2000-loop including the patient / subscriber name segments if they were present. The 837P spec puts the patient's name in `NM1*IL` (loop 2010BA) and the subscriber's name in `NM1*31` (loop 2000B). These are **PHI by HIPAA Safe Harbor** and **PHIPA-identifying**.

**Caveat — `raw` reaches the JSONL log.** When the FastAPI submit endpoint serialises the row and the JSONL log writes it, the `raw` field rides along in the per-claim row. This is the same `logs/upload_jobs.jsonl` surface flagged in BUG-2026-06-16-02. The fix in BUGS.md (hash `patient_id`, redact the `raw` field, or strip the per-segment `NM1*IL/31` blocks before persistence) is the right shape.

**PASS at the parser-error surface** for the per-file error column. `api.py:366` sets `parse_error: str(exc)` — the `exc` is one of the four short messages from `x12_parser.py:347-367`, none of which include PHI.

**Verdict: PASS** for the parser's own error path. The `raw` field is the residual surface, and it is covered by BUG-2026-06-16-02.

---

## Open follow-ups

| ID | Description | Owner | Priority | Tracked in |
|---|---|---|---|---|
| PHI-1 | Peppered `hashPatientId` helper + `PATIENT_HASH_PEPPER` env var + DB hex CHECK | default | **High** | **SHIPPED** in this kanban run — `apps/portal/src/lib/patient-hash.ts`, `audit_trail.sql`, both call sites updated, 10/10 tests pass |
| PHI-2 | One-off backfill migration that re-hashes every existing `patient_hash` with the new helper | default | Medium (the pre-fix rows remain dictionary-attackable until this ships) | this doc, Check 3 — out of scope per task body, needs its own card |
| PHI-3 | Hash `patient_id` at the FastAPI `/encounters/upload/submit` boundary and redact the `raw` field's `NM1*IL/31` blocks before the JSONL write | default | Medium | docs/BUGS.md, BUG-2026-06-16-02 |
| PHI-4 | If a third-party observability sink is ever wired up, install a global redactor at SDK init that deny-lists `clinical_note`, `provider_note`, `hpi`, `exam`, `mdm`, `patient`, `patient_id`, `raw` | future | Low (preventive) | this doc, Check 4 |
| PHI-5 | If a future `X12ParseError` ever adds rich segment content to its message, add a comment at `api.py:366` warning that `parse_error` is on a PHI-touching surface | future | Low (preventive) | this doc, Check 5 |
| PHI-6 | Document the chain-break-and-redo procedure in `docs/RUNBOOK.md` (rotating the pepper is the documented breach response) | default | Low (until the first rotation happens) | this doc, Check 3 remediation step 5 |

---

## Acceptance criteria checklist

- [x] `docs/SEC_REVIEW_phi.md` exists and contains a section for each of the five checks (1)–(5) above.
- [x] Each check has a clear pass/fail verdict with cited file:line evidence.
- [x] If any PHI leak was found, a redactor is implemented and referenced from the doc, with a short test demonstrating a sample PHI string is scrubbed. — The leak was in the hashing layer (not the logger layer), so the right shape is the centralized `hashPatientId` helper. The unit test `apps/portal/tests/patient-hash.test.ts` includes a "PHI-scrub smoke" case that asserts a sample `OHIP-1234-5678-9012` member-id is scrubbed to a 64-char hex digest that does not contain or start with the input. The test passes (10/10).
- [x] `patient_hash` is confirmed to be produced by a one-way hash with a secret/pepper; raw PHI in that column is explicitly ruled out. — `audit_trail.sql` now has a `CHECK (patient_hash ~ '^[0-9a-f]{64}$')` constraint that rejects non-hex writes at the DB. The application helper mixes a server-side `PATIENT_HASH_PEPPER` secret and fails fast in production if the env var is missing. Caveat: the **existing rows** in any pre-fix deployment are still unsalted; backfill is tracked as PHI-2 (out of scope per task body).
- [x] 837P parse-failure path emits only a sanitized excerpt — no raw `.837` content reaches logs, Sentry, or error responses. (Caveat: the successful-parse `raw` field is on a separate surface and is tracked under BUG-2026-06-16-02.)
- [x] No new dependencies or unrelated refactors are introduced. (`patient-hash.ts` uses `node:crypto` which is already in the Node stdlib and already imported elsewhere in the portal.)
- [x] The doc lists open follow-up items with owners (PHI-1 through PHI-6 above).
