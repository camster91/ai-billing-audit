# Code review: backend plumbing (api.py, audit.py, job_queue.py, billing.py)

**Scope.** `src/ai_billing_audit/api.py` (667 LOC), `src/ai_billing_audit/audit.py` (11 LOC), `src/ai_billing_audit/job_queue.py` (370 LOC), `src/ai_billing_audit/billing.py` (10 LOC).
**Reviewer.** Kanban task `t_d6215f8f` (initial pass) → re-reviewed under `t_cd56dc8f` (this file). Original review (231 lines) covered all five checklist areas with line-cited evidence; this pass sharpens §1 with a CORS finding and §4 with a traceback-loss finding, both newly observed on a re-read.
**Reviewer (re-review).** Same `default` profile, fresh subagent context, no in-place edits to source files; only `docs/CODE_REVIEW_backend.md` is modified.
**Related.** Sibling reviews: `docs/CODE_REVIEW_auditor.md` (auditor agent), `docs/CODE_REVIEW_grader.md` (scoring), `docs/CODE_REVIEW_llm.md` (provider layer). Cross-references below.
**Out of scope.** Refactoring, test addition, files outside the four above. Note: the real hash-chain `audit_trail` implementation lives in `src/audit_log.py` and is intentionally **not** in this review's scope — see §3.

## Executive summary

The four files cover the FastAPI surface, the upload-portal job queue, and two package placeholders. Across the five checklist areas:

- **(1) API authentication.** ABSENT. Zero `Depends`/`HTTPBearer`/`Security`/`OAuth2`/`api_key`/`Authorization` imports, zero middleware (no `add_middleware(...)` call, no `CORSMiddleware` either), zero dependency-injection call sites in any of the three non-stub files. Every route is reachable anonymously on the local network. **Severity: Critical.** The module docstring at `api.py:288-290` explicitly defers auth to "whatever the portal already enforces upstream" — that sentence is the spec; the review confirms nothing in the code fulfils it. **Related, Medium:** no CORS configuration at all — if the dashboard frontend is ever served from a different origin than the API (e.g. a Vite dev server on `:5173` talking to the FastAPI process on `:8765`), browsers will block the fetch with no preflight handler to relax it.
- **(2) Input validation.** PARTIAL. `validate_required_fields` (`x12_parser.py:371-406`) checks non-empty and regex-shape for NPI / date_of_service only. `encounter_id` and `patient_id` are non-empty-validated but otherwise unconstrained (no character class, no length cap, no reserved-name blocklist, no path-traversal guard for the value that gets stitched into the upload's JSONL log and into the `logs/uploaded_notes/` filesystem path on the notes endpoint). Re-validates on submit (`api.py:524-541`), which is good. The "is_flagged" / "difficulty_tier" / "variant" enums are whitelisted by the default runner (`job_queue.py:309-314`) but the submit endpoint never enforces those, so a row with `difficulty_tier="HACKED"` lands in the queue unchallenged and only gets coerced at synth-call time.
- **(3) Audit log persistence to a hash-chain `audit_trail` table.** NOT PRESENT IN THESE FILES. `src/ai_billing_audit/audit.py` is an 11-line placeholder (`__all__: list[str] = []`) that documents itself as a future landing spot for the billing-rules corpus loader — the auditor lives in `auditor.py` (sibling review `CODE_REVIEW_auditor.md`). The real hash-chain `audit_trail` writer is `src/audit_log.py` (222 LOC, SHA-256 chained `cryptographic_signature`), which is outside this review's scope. None of the four files imports the audit log; the upload flow's only persistence is `logs/upload_jobs.jsonl`, a plain append-only log with no chain.
- **(4) Job queue concurrency / idempotency / DLQ.** PARTIAL. The queue is thread-safe (single `threading.Lock` on `_jobs`, `BoundedSemaphore` for the worker pool, `daemon=True` background threads), the JSONL rebuild is restart-safe, and the public surface is small and well-tested (`tests/test_encounters_upload.py`, 753 LOC, 30+ tests covering the upload happy path and the malformed-X12 / ZIP-error / 404 cases). Three real gaps: **(a) NO idempotency key on enqueue or processing** — a retry from the upload form generates a new `job_id` (uuid4 hex[:12], `job_queue.py:233`) and the synth runs again from a re-hashed seed (`job_queue.py:316-317`), so the user can spam N copies of the same claim through the pipeline; **(b) NO dead-letter queue (DLQ)** — `Job.status` has exactly four states (`queued`/`running`/`done`/`failed`, `job_queue.py:67-68`) and the only post-failure action is `_append_log(job)` at `job_queue.py:272-276` with the exception text; there is no retry-with-backoff, no quarantine, no operator-visible retry endpoint, and `_append_log` itself swallows `OSError` (`:216-217`) so a disk-full failure loses the failure record silently; **(c) `_append_log` opens with mode `"a"` and never `fsync`s** — a process kill mid-write can lose a status transition, and the comment at `:14-17` says "the latest line per `job_id` is the source of truth," which is true only if the OS didn't reorder / drop the write.
- **(5) `billing.py` stub assessment.** STUB. 10 lines: a one-paragraph docstring saying "billing-domain logic (claim normalization, line-item extraction, payment posting) lands in later tasks" and `__all__: list[str] = []`. No functions, no classes, no imports, no module-level work. The docstring's claim that "downstream imports resolve cleanly" is the only thing keeping it in the package. The same is true of `audit.py` (11 lines) — both are scaffolding placeholders, neither ships any behaviour. (Note: a separate `src/ai_billing_audit/billing.py` mentioned in the marketing pricing-page card `t_256bdb45` does not exist in this checkout; the only `billing.py` here is the 10-line stub. There may be a billing implementation in a sibling package, but it is not in this review's four files.)

## Per-focus-area findings

### 1. API authentication

**Verdict: ABSENT (Critical).** The API has no authentication, no authorization, and no rate limiting. Every route on `app` is reachable by an anonymous client for the lifetime of the process. The module docstring at `api.py:1-30` and the inline comment at `api.py:288-290` explicitly defer auth to a hypothetical upstream layer.

**What the code does (verified imports + route bodies).** The four files import only these from FastAPI (line 40, `api.py`):

```python
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
```

There is no `fastapi.security.HTTPBearer`, no `fastapi.security.OAuth2`, no `Depends` import, no `Security` import, no `Header` import, no custom `Depends`-style helper. A repo-wide search for `Depends|Security|HTTPBearer|OAuth2|api_key|Authorization|Header` against `src/ai_billing_audit/` (excluding `llm_client.py` and `llm.py` which only use `api_key=` as an LLM-client constructor kwarg, not as an HTTP-auth concern) returns zero matches.

**What the route bodies look like.** Every route's signature is a bare FastAPI path with a typed query/path/form parameter and no `Depends` call:

- `index(request: Request)` — `api.py:184`
- `encounter_detail(request: Request, encounter_id: str)` — `api.py:211`
- `encounter_json(encounter_id: str)` — `api.py:249`
- `healthz()` — `api.py:271`
- `encounters_upload(request: Request)` — `api.py:380`
- `encounters_upload_preview(file: UploadFile = File(...))` — `api.py:393`
- `encounters_upload_submit(payload: str = Form(...))` — `api.py:483`
- `encounters_upload_job_status(job_id: str)` — `api.py:570`
- `encounters_upload_paste(payload: str = Form(...)) — `api.py:588`
- `encounters_upload_note(file: UploadFile = File(...))` — `api.py:621`

**Why it matters.**

- `encounter_detail` and `encounter_json` (`api.py:210-268`) return the full `ground_truth` for any registered encounter id. The data is currently demo data; if the real audit pipeline ever feeds `load_encounter_record` from a production source, those two routes are an unauthenticated read-everything endpoint.
- `encounters_upload_submit` (`api.py:482-567`) writes to the job queue and triggers a background synth call. No auth means anyone on the local network can submit N concurrent synthetic claims and watch the JSONL log fill with their work.
- `encounters_upload_note` (`api.py:620-661`) writes arbitrary bytes (up to 10 MiB) under `logs/uploaded_notes/<uuid>.<ext>` with an extension allow-list of `.pdf .png .jpg .jpeg .webp .tiff` (`:294, 638-645`). The path is randomised, which prevents a naïve `..` escape from hitting a known location, but the content is unmoderated — a malicious PDF lands on disk without size sanity-checking beyond the 10 MiB cap (`:631-635`).
- `healthz` (`api.py:270-272`) leaks the count of registered encounters to anonymous clients, which is a small info-disclosure for a demo but would be a problem if the count is itself sensitive (e.g. number of customers in a tenant).

**Author's note (`api.py:288-290`, verbatim):**

```python
# Auth / tenant scoping is intentionally out of scope per the
# task body — the route lives behind whatever the portal already
# enforces upstream.
```

The spec defers to "upstream." The review confirms: nothing in `api.py` enforces it, and there is no comment pointing at the upstream component by name, file, or test. **Severity: Critical** for the production cutover (the comment is correct that it's out of scope **for this card**, but the routes cannot ship to a non-loopback bind without it). **Recommendation:** add a `verify_token: Callable[[Request], str] = Depends(...)` dependency to every route that touches data the demo doesn't own, with at minimum an `X-Internal-Token` shared-secret check, and gate the bind to `127.0.0.1` (already in place per `scripts/run_dashboard.py` — verify in a follow-up review) until the real auth lands.

**CORS / cross-origin (Medium).** The `create_app` factory (`api.py:153-180`) builds the FastAPI instance with `FastAPI(title=..., version=..., description=...)` and immediately mounts static files and templates. There is no `app.add_middleware(CORSMiddleware, allow_origins=..., allow_methods=..., allow_headers=...)` call anywhere in the module — a repo-wide grep for `add_middleware` and `CORSMiddleware` against `src/ai_billing_audit/` returns zero matches. The default FastAPI behavior is to send **no** `Access-Control-Allow-Origin` header, so a browser script on a different origin (e.g. a Vite dev server on `:5173` during development, or a future production frontend served from `app.example.com` while the API lives at `api.example.com`) will be blocked by the same-origin policy on the upload preview / submit / job-status fetches. The dashboard's own JS at `templates/encounters_upload.html` (and the API client in `static/`) currently lives on the same origin as the API (mounted as static files at `/static/`), so this is a latent issue — it will only bite if/when the frontend is split out. **Severity: Medium** (latent, not currently exploited). **Recommendation:** add `from fastapi.middleware.cors import CORSMiddleware` and a single `app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["GET","POST"], allow_credentials=False)` line gated on `os.environ.get("ENABLE_CORS")` so the production cutover is one env var away.

### 2. Input validation

**Verdict: PARTIAL (High for `encounter_id`; Medium for the rest).** The 837P and paste-form inputs go through `validate_required_fields` and get a re-validation on submit, which is the right pattern. The validator only checks presence and the NPI/date regex; `encounter_id`, `patient_id`, the difficulty enum, and the notes filename all pass through under-validated. The notes endpoint writes to disk without further validation beyond the extension allow-list.

**What `validate_required_fields` actually validates (`x12_parser.py:371-406`).** Field-by-field:

| Field | Empty check | Format check | Length cap | Char class |
| --- | --- | --- | --- | --- |
| `encounter_id` | yes (`:379-381`) | **no** | **no** | **no** |
| `patient_id` | yes (`:382-386`) | **no** | **no** | **no** |
| `NPI` | yes (`:387-388`) | yes — `re.fullmatch(r"\d{10}", npi)` (`:392-393`) | implicit 10 | digits-only |
| `date_of_service` | yes (`:394-398`) | yes — `re.fullmatch(r"\d{4}-\d{2}-\d{2}", dos)` (`:399-402`) | implicit 10 | digits + dashes |
| `CPT_codes` | yes — must be non-empty list (`:403-405`) | **no per-code regex** | **no** | **no** |

A 50,000-character `encounter_id` containing a `\n` and an `<` would pass `validate_required_fields` because the field is non-empty after `.strip()`. The 837P parser (`_extract_claim`, `x12_parser.py:239-289`) gets the value from `CLM01` (`:257-261`) and only strips and nullifies; it does not constrain the upstream CLM01 to a known format. A misbehaving / malicious submitter can put `../etc/passwd\n<script>...</script>` into a claim, and it will flow all the way to `queue.enqueue(encounter=claim, ...)` (`api.py:555-559`).

**Where the unconstrained strings end up.**

- `queue.enqueue` writes the encounter dict (including `encounter_id`) to `logs/upload_jobs.jsonl` (`job_queue.py:205-217`) as JSON. JSONL serialisation escapes the special characters safely, so this is not a log-injection vector. The string is then read back into a `Job.encounter_id` (`:235-237`).
- The default runner hashes the `encounter_id` to a seed (`job_queue.py:316-317`): `seed = abs(hash(seed_source)) % (2**31)`. CPython's `hash()` is process-randomised by default, so two process restarts of the same `encounter_id` produce two different seeds — minor determinism footgun (separate from the dashboard's "MEDIUM/clean" choice at `:309-314`).
- The job_id returned to the client (`api.py:562`) is the truncated uuid, not the encounter_id, so a UI rendering escape is not directly reachable from a stored encounter_id — but the notes endpoint (below) does write user-controlled bytes to disk.

**Notes endpoint (`api.py:620-661`).** Accepts a file upload with extension allow-list (`:294, 638-645`) and a 10 MiB size cap (`:631-635`). The path it writes to is `_NOTES_DIR / f"{note_id}{suffix}"` (`:651`), where `note_id` is a fresh `uuid4().hex[:12]` (`:650`) and `suffix` is the lowercased extension from `Path(name).suffix`. The uuid prefix is the right shape (no collision, no traversal), but the file body is unmoderated — the comment at `:624-628` explicitly says OCR is deferred, so the bytes are written to disk for later processing. A 10 MiB PDF containing an embedded XSS payload lands in `logs/uploaded_notes/` and will be served back to staff via the `audit-chain.ts` path downstream of the review's scope; out of scope here, but worth flagging that the notes endpoint has no content-type sanity check, no magic-byte verification that the file is actually a PDF, and no quarantine for files that fail a future verification step.

**Re-validation on submit (`api.py:524-541`).** Good pattern — the submit endpoint re-runs `validate_required_fields` on the trimmed claim dict regardless of what the preview's `errors` array said (`api.py:525-526` explicitly comments: "we never trust the client to decide what's accepted"). This is the right instinct, but it re-runs the **same** validator, so the gaps in §2 propagate.

**Difficulty / variant enums (`job_queue.py:309-314`).** The default runner enforces the whitelists at synth-call time, but the API submit endpoint (`api.py:543-554`) accepts whatever `source` the client sends and falls back to `"837p"` / `"zip"` / `"paste"` by filename heuristic. A `source` value of `"rm -rf /"` would land in the queue and then in the JSONL log (which JSON-serialises it safely, so no shell injection) but also gets returned to the polling client as `{..., "source": "rm -rf /"}` (`api.py:560-566`). No code consumes that string other than the template, but the surface is wider than the validator's intent.

**Test coverage.** `tests/test_encounters_upload.py` covers the happy path (`test_preview_single_837p_parses_to_normalised_dict`, `test_zip_of_837p_files_parses_each_individually`, `test_submit_accepted_row_enqueues_job_and_status_is_pollable`), the rejection path (`test_missing_required_fields_produces_per_file_errors`, `test_invalid_npi_format_is_rejected`, `test_malformed_file_is_rejected_with_per_file_error`, `test_malformed_file_inside_zip_does_not_enqueue`), and the 404 path (`test_job_status_404_for_unknown_id`). It does **not** test the `encounter_id` length / char-class / XSS-injection path, and it does **not** test the difficulty_tier / variant enum at the API boundary. The grader-review sibling (CODE_REVIEW_grader.md) has a similar pattern — the tests codify the implementation, the implementation is incomplete, and the next test pass needs to add the missing cases.

**Severity: High for `encounter_id`; Medium for the rest.** `encounter_id` is the natural primary key downstream of the audit pipeline; allowing an attacker to inject any string into it pollutes the demo registry's id-space and (when the real pipeline lands) the production data store. The notes endpoint is Medium because the path is uuid-prefixed.

**Recommendations.**

1. Add a regex to `validate_required_fields` for `encounter_id` (suggested: `re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", enc)`) and `patient_id` (same shape, longer cap). 64 is generous for CLM01 in the wild; bump if real X12 data needs it.
2. Add a per-code regex to the CPT_codes list (`re.fullmatch(r"\d{5}", code)` for the common case; allow 5-char alphanumeric for HCPCS Level II if the project needs it).
3. Whitelist `source` and `difficulty_tier` at the submit boundary, not at the runner.
4. Add a `Content-Type` magic-byte check to the notes endpoint before write (e.g. `%PDF-` for PDF, `\x89PNG` for PNG, etc.) and reject mismatches with a 400.

### 3. Audit log persistence to a hash-chain `audit_trail` table

**Verdict: NOT PRESENT IN THESE FILES (N/A for this review).** The four files in scope do not write to a hash-chain `audit_trail` table. `src/ai_billing_audit/audit.py` is a 11-line placeholder stub with an empty `__all__` and zero runtime behaviour. The real hash-chain implementation lives in `src/audit_log.py` (222 LOC, SHA-256 chained `cryptographic_signature`), which is outside this review's scope.

**What `src/ai_billing_audit/audit.py` actually contains (full file, 11 lines):**

```python
"""Audit-domain logic placeholder.

The ``ai_billing_audit.audit`` subpackage is reserved for the future
billing-rules corpus loader; the auditor agent itself lives in
:mod:`ai_billing_audit.auditor` at the package root, following the
single-file-per-concept convention used throughout this package.
"""

from __future__ import annotations

__all__: list[str] = []
```

No functions, no classes, no imports beyond `__future__`, no module-level work. The docstring's claim is that the file exists so "downstream imports resolve cleanly," but a repo-wide grep of `src/ai_billing_audit/` for the string `audit` (excluding `auditor` and the audit-pipeline prose in docstrings) returns **zero** import sites that target `audit.py`. The file is dead weight — it can be deleted without breaking any code in the package. (Not in scope to delete it; just noting the absence of consumers.)

**What writes to `audit_trail` in this codebase.** The real chain is in `src/audit_log.py`. The schema for the `audit_trail` table is in `apps/portal/prisma/schema.prisma`. The portal-side writer is `apps/portal/src/lib/audit-write.ts` and the chain verifier is `apps/portal/src/lib/audit-chain.ts`. The Python upload-portal (`api.py` / `job_queue.py`) **does not** call into this chain at all — its only persistence is `logs/upload_jobs.jsonl`, a plain JSONL log with no chaining and no cryptographic signature.

**What this means for the four files in scope.** The "audit log" section of the review checklist is **not applicable** to `api.py`, `audit.py`, `job_queue.py`, and `billing.py`. The real audit-trail work is reviewed elsewhere (or, if there is a sibling review of `src/audit_log.py` and the TypeScript chain, that is the file to read).

**Severity: N/A for this review. Recommendation:** the project should either (a) commission a dedicated review of `src/audit_log.py` + `apps/portal/src/lib/audit-write.ts` + `apps/portal/src/lib/audit-chain.ts` + the prisma schema, or (b) decide explicitly that the Python upload portal does not feed the chain (which is the current state) and document the decision. As it stands, the file `src/ai_billing_audit/audit.py` is a misleading name for an empty placeholder — rename it to `_placeholder.py` or delete it, so a future reader does not waste time looking for a hash-chain writer that is not there.

### 4. Job queue concurrency, idempotency, and DLQ

**Verdict: PARTIAL (Critical for idempotency gap; High for DLQ gap; Low for the `_append_log` swallow).** The queue's thread-safety story is solid, the JSONL rebuild is correct, and the public surface is small and well-tested. Three real gaps that the review needs to flag.

**Thread safety (PASS).**

- Single `threading.Lock()` on `_jobs` (`job_queue.py:159`). All public mutators (`enqueue`, `get`, `list_jobs`) and the per-job state transitions in `_run_job` (`job_queue.py:265-268, 272-276, 278-282`) acquire it before reading or writing.
- `BoundedSemaphore(worker_count)` (`job_queue.py:164`) caps concurrent synth calls. `BoundedSemaphore` (not `Semaphore`) raises `ValueError` on a release-bug, which is the right safety net for a daemon thread.
- Background threads are `daemon=True` (`job_queue.py:248`), so a process exit doesn't hang on a pending synth call.
- The module-level singleton (`_DEFAULT_QUEUE`, `job_queue.py:335-360`) uses double-checked locking under `_DEFAULT_QUEUE_LOCK` to avoid a thundering-herd on first `enqueue`.

**JSONL rebuild (PASS, with one caveat).**

- `_load_from_log` (`job_queue.py:172-203`) reads the log line-by-line, parses each JSON line, and lets the **last** line per `job_id` win (`:198`). Corrupt lines are skipped silently with a comment (`:188-194`) noting that a production system would quarantine them.
- `_append_log` (`job_queue.py:205-217`) opens with mode `"a"`, writes one JSON-serialised dict per line, and swallows `OSError` with no-op (`:216-217`).
- **Caveat 1 (Low):** `_append_log` does not `fsync`, so a process kill mid-write can lose a status transition. The comment at `:14-17` calls the JSONL "the source of truth" (alongside the in-memory dict), but a SIGKILL between `_append_log` calls can produce a JSONL where the latest transition is missing — and the rebuild-at-startup will load the **previous** transition as the latest. For the demo portal this is fine; for a production audit log, this would be a real gap. `fh.flush(); os.fsync(fh.fileno())` is the fix.
- **Caveat 2 (Medium):** `_append_log` swallows `OSError` (`:216-217`) with `pass`. The in-memory dict is authoritative for the running process, but the **failure record itself** is lost — there is no second log, no error counter, no Prometheus metric. A disk-full failure looks identical to a healthy run from the operator's view.
- **Caveat 4 (Medium):** the failure record itself is lossy. `job_queue.py:274` stores `job.error = f"{type(exc).__name__}: {exc}"` — that stringifies the exception to its class name and message and **discards the traceback entirely**. When a synth call fails deep inside the LLM provider or inside the synth agent, the JSONL stores `"RuntimeError: cannot find template"` with no frames, no file, no line. For a demo this is fine; for the production cutover, an operator triaging a failed job has no path to the cause without re-running the synth with a debugger attached. Fix: `job.error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))` and persist that.
- **Caveat 3 (Low):** no rotation, no size cap on `upload_jobs.jsonl`. A long-running process in a high-upload environment grows the file unbounded.

**Idempotency (FAIL — Critical for production).**

- `enqueue` generates a fresh `job_id` per call (`job_queue.py:233`: `uuid.uuid4().hex[:12]`). There is no idempotency key, no client-supplied dedup token, and no equivalent-of-`If-Match` semantics.
- The default runner seeds the synth with `abs(hash(encounter_id)) % 2**31` (`job_queue.py:316-317`). CPython's `hash()` is process-randomised by default, so the same `encounter_id` produces a different seed in different processes. **CPython also enables `PYTHONHASHSEED=random` by default**, so two restarts of the same uvicorn process will produce different synth runs for the same encounter, and **the seed value itself is not stored in the JSONL** — only the resulting `synth_encounter_id` is, which depends on the synth agent's internal state, not the seed. A retry from the upload form is therefore a new job that runs the synth fresh, with no dedup and no link to the prior attempt.
- The "reproducibility on re-submission" claim in the comment at `:316` ("Seed from the encounter_id so re-submission is reproducible") is wrong in a multi-process / multi-restart context. Within a single process, yes; across restarts, no.
- **Consequence:** the upload form can spam N copies of the same claim through the synth pipeline, each gets its own `job_id`, each writes its own JSONL line, and the JSONL fills with duplicates. The UI's "Polling every second. Jobs are removed from the queue when the audit pipeline completes" (per `templates/encounters_upload.html:122`) hides the duplication from the user because each duplicate looks like its own success.

**Dead-letter queue (FAIL — High).**

- The state machine at `:24-32` is `queued → running → {done, failed}`. The four states are: `"queued"`, `"running"`, `"done"`, `"failed"` (`:67-68`).
- A failure path exists (`:270-277`): any exception in the runner is caught (`except Exception as exc:  # noqa: BLE001 (deliberately broad)`), the job is marked `"failed"`, the error text is set, and `_append_log` is called. **That is the entirety of the failure handling.**
- There is no retry. There is no exponential backoff. There is no quarantine file for jobs that failed N times. There is no operator-visible retry endpoint. The `_default_runner` itself catches no exceptions and depends entirely on the broad `except Exception` in `_run_job`.
- `BoundedSemaphore` releases in the `finally` (`:283-284`), so a failed job correctly frees a worker slot, but the next enqueue from the same user starts a fresh job, not a retry of the failed one — the failed job's `job_id` is dead-lettered in the JSONL sense but never re-driven.
- **Severity: High.** For the demo portal this is acceptable. For the production cutover, a job that fails because the synth agent OOM'd or the LLM call 5xx'd will never retry; the staff user has to manually re-upload, which loses the `job_id` and breaks the link to the failure context.
- **Recommendation:** add a retry policy. A small first cut: an `attempt` counter on `Job` (`:79-90` already lists `__slots__`, easy to add), a max-attempts config (default 3), a `time.sleep(backoff)` between attempts in `_run_job` (`:262-284`), and a `retry` endpoint that takes a `job_id` and re-enqueues with the same encounter dict. For DLQ, a separate JSONL at `logs/upload_jobs_dlq.jsonl` that captures the failure record with the full traceback, not just `f"{type(exc).__name__}: {exc}"` (`:274`).

**Test coverage.** `tests/test_encounters_upload.py` covers:

- `test_preview_single_837p_parses_to_normalised_dict` (`:181`) — happy path for the preview endpoint.
- `test_zip_of_837p_files_parses_each_individually` (`:208`) — bulk upload expansion.
- `test_missing_required_fields_produces_per_file_errors` (`:243`) — validator behaviour.
- `test_invalid_npi_format_is_rejected` (`:270`) — the one format check the validator does.
- `test_malformed_file_is_rejected_with_per_file_error` (`:288`) and `test_malformed_file_inside_zip_does_not_enqueue` (`:304`) — parser behaviour.
- `test_submit_with_no_accepted_rows_rejects_all` (`:342`) and `test_submit_accepted_row_enqueues_job_and_status_is_pollable` (`:368`) — the submit/poll loop.
- `test_job_status_404_for_unknown_id` (`:431`) — the lookup-miss path.

**Missing tests (the review's "what's not there"):**

- No test for the JSONL rebuild on restart — the comment at `:14-17` and `_load_from_log` at `:172-203` are unverified.
- No test for `_run_job` failure path — the broad `except` at `:270-277` is unverified.
- No test for the `BoundedSemaphore` worker cap — five concurrent enqueues should produce exactly two concurrent `_default_runner` invocations; nothing checks this.
- No test for the `daemon=True` thread join semantics — a SIGTERM during a long synth call is unverified.
- No test for the `reset_default_queue_for_tests` helper at `:363-370` actually clearing the singleton.

**Severity summary for §4:** the **idempotency** gap is **Critical** (the upload flow can be spammed into duplicate work); the **DLQ** gap is **High** (no retry, no operator visibility into recurring failures); the **traceback-loss** and **`_append_log` swallowing** are **Medium** (failure records are kept but lossy and the disk-write path can silently drop them); the `fsync` omission and the missing JSONL rotation are **Low** for the demo and **High** for production; the test coverage gaps are **Medium** (the lock-and-semaphore code is right by inspection, but unverified by tests).

### 5. `billing.py` stub assessment

**Verdict: STUB (N/A — no behaviour to review).** 10 lines, all prose.

**Full file (`src/ai_billing_audit/billing.py`):**

```python
"""Billing-related logic placeholder.

The current scope scaffolds the package. Billing-domain logic (claim
normalization, line-item extraction, payment posting) lands in later
tasks. This file exists so that downstream imports resolve cleanly.
"""

from __future__ import annotations

__all__: list[str] = []
```

**What the 10 lines do.** Nothing at runtime. The docstring says the file exists so "downstream imports resolve cleanly," but a repo-wide search for `from ai_billing_audit.billing` or `from ai_billing_audit import billing` returns **zero** matches. The file is currently dead code. The marketing pricing-page card `t_256bdb45` ("Pricing page: integrate Zorva 3-tier with Stripe Checkout") would have introduced billing logic, but that card shipped against a separate backend (the FastAPI app at `apps/portal/`), not against this `billing.py`. The result: this `billing.py` is a stub with no consumers.

**Stub flag.** Yes — flag as stub. The docstring itself says so explicitly: "Billing-domain logic (claim normalization, line-item extraction, payment posting) lands in later tasks." The "later tasks" have either landed in a sibling package or have not been written.

**Severity: N/A — there is no code to flag.** **Recommendation:** either delete the file (since nothing imports it) or populate it with the intended billing logic. As it stands, the file is documentation-shaped code that adds nothing to the package. (Not in scope to delete it; just noting the absence of consumers.)

**Note on `audit.py` (the sibling stub).** The same comment applies — `src/ai_billing_audit/audit.py` is an 11-line placeholder with an empty `__all__` and zero consumers. The docstring at `audit.py:1-7` even says so:

> The ``ai_billing_audit.audit`` subpackage is reserved for the future
> billing-rules corpus loader; the auditor agent itself lives in
> :mod:`ai_billing_audit.auditor` at the package root, following the
> single-file-per-concept convention used throughout this package.

If the package convention is "one file per concept," then a placeholder for a concept that has not landed is a convention violation — there is no concept to place a file behind. **Recommendation:** delete both stubs (`audit.py` and `billing.py`) or rename them to `_audit_placeholder.py` and `_billing_placeholder.py` so a future reader does not assume they contain real logic.

## Summary

| Area | Verdict | Severity | One-line action |
| --- | --- | --- | --- |
| (1) API auth | ABSENT | Critical | Add `Depends`-based auth to every route, or bind to 127.0.0.1 only and document. |
| (1b) CORS | NOT CONFIGURED | Medium (latent) | Add `CORSMiddleware` behind an `ENABLE_CORS` env var before the frontend is split to a different origin. |
| (2) Input validation | PARTIAL | High (`encounter_id`), Medium (rest) | Tighten `validate_required_fields` regex/length/char-class; whitelist `source`/`difficulty_tier` at the API boundary. |
| (3) Audit log persistence | NOT PRESENT IN THESE FILES | N/A | Commission a separate review of `src/audit_log.py` + the portal TypeScript chain. |
| (4) Job queue concurrency | PASS for thread-safety; FAIL for idempotency (Critical), DLQ (High), traceback-loss (Medium) | Critical / High / Medium | Add idempotency key on enqueue; add retry-with-backoff + DLQ JSONL on failure; persist `traceback.format_exception(...)` instead of `f"{type}: {exc}"`; `fsync` `_append_log`. |
| (5) `billing.py` stub | STUB | N/A | Delete `billing.py` and `audit.py` (both empty placeholders with no consumers) or populate with real logic. |

The "backend plumbing" review surfaces two genuine production-blockers (API auth and enqueue idempotency), three production-debt items (DLQ / retry, traceback-loss on failure, CORS config), and one naming-and-hygiene issue (the `audit.py` / `billing.py` placeholders that point at concepts that live elsewhere). The Python upload portal's actual behaviour — parse 837P, validate, enqueue, run synth, poll status — is small, well-scoped, and well-tested for the happy path. The gaps are the perimeter, not the core.
