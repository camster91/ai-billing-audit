# QA — load-test live /encounters with 50 concurrent uploads

**Kanban:** t_59ff2fbb
**Date:** 2026-06-17
**Target:** `https://ai-billing-audit.ashbi.ca`
**Endpoint exercised:** `POST /encounters/upload/submit` (the live `/encounters` family; `/encounters/upload/preview` is not relevant here — the task body asks for the upload path)
**Result (load-only):** **PASS** — 50/50 accepted, 50/50 processed, zero 5xx, p95 = 444.5ms
**Result (audit_trail/chain):** **NOT APPLICABLE** — see P0 finding below

## TL;DR

The live `/encounters` upload endpoint handled 50 concurrent synthetic uploads without errors, latency regressions, or queue drops. The 50 jobs were accepted (HTTP 200, all returned a `job_id`), the in-process queue drained to 50/50 `done` within 3.1s of the fire window, and no 5xx was observed. p95 latency was 444.5ms against the 5s acceptance bar.

**However, two of the task body's acceptance criteria cannot be met by the current architecture and are flagged as a P0 spec-vs-reality finding below.** Specifically: the upload flow does not write to the `audit_trail` Postgres table, and there is no remote queue-depth endpoint. The upload portal's durable log is `logs/upload_jobs.jsonl` inside the api container, not `audit_trail`. That is a deliberate architecture decision (the auditor pipeline — the only writer to `audit_trail` — has not been wired into the upload job's runner yet), not a bug in this load test. The task body is wrong on those two points and the report says so.

## 1. Setup

- 50 distinct synthetic claims. Each row carried a unique `encounter_id` (`ENC-QA-LOAD50-NNN-<hex>`), unique `patient_id`, unique 10-digit `NPI`, fixed `date_of_service=2024-06-01`, two CPT codes (`99213`, `99214`), and `source="paste"` to bypass the 837P parser path (the form path is the same code branch).
- Concurrency model: `ThreadPoolExecutor(max_workers=50)`. All 50 POSTs were issued within a 456ms wall-clock fire window.
- Submission: each request was a `multipart/form-data` POST to `/encounters/upload/submit` with a single-row `payload` field.
- After firing, every returned `job_id` was polled via `GET /encounters/upload/jobs/{id}` until terminal status, with a 60s per-job deadline.
- Workspace: `/Users/biancabienaime/.hermes/kanban/boards/ai-billing-audit/workspaces/t_59ff2fbb/`
- Test script: `load_test.py` in the workspace. Raw results: `load_test_results.json` (per-request records, full job-state timeline).

The first attempt with `date_of_service="20240601"` (YYYYMMDD) was rejected by the live validator with `date_of_service '20240601' is not in YYYY-MM-DD format`. That is a server-side validation correctness — the validator is enforcing the documented YYYY-MM-DD contract. Adjusted to `2024-06-01` and the second pass was 50/50 accepted.

## 2. Results

### 2.1 Submit (POST /encounters/upload/submit)

| metric | value |
|---|---|
| N | 50 |
| HTTP 200 | 50 |
| HTTP 4xx | 0 |
| HTTP 5xx | 0 |
| Accepted (job_id returned) | 50 / 50 |
| Rejected by server | 0 |
| Fire window (50 parallel POSTs) | 455.9 ms |
| p50 latency | 364.7 ms |
| p95 latency | 444.5 ms |
| p99 latency | 454.6 ms |
| mean latency | 365.2 ms |
| max latency | 454.6 ms |
| min latency | 273.3 ms |

p95 (444.5ms) is well under the 5s bar.

### 2.2 Queue drain (polling /encounters/upload/jobs/{id})

| metric | value |
|---|---|
| Jobs polled | 50 / 50 |
| Final status = `done` | 50 |
| Final status = `failed` | 0 |
| Final status = `timeout` (60s deadline) | 0 |
| Poll window (all 50 parallel polls) | 3126 ms |

The in-process queue drained to baseline (zero in-flight) within ~3.1s of the fire window completing. Per the v1 architecture, the queue is a 2-worker thread pool inside the api process (`src/ai_billing_audit/job_queue.py:JobQueue._sem = BoundedSemaphore(worker_count=2)`), so concurrency above 2 jobs serializes at the worker layer. With 50 jobs at ~60ms of synth work each, the expected drain time is `ceil(50/2) * ~60ms ≈ 1.5s`; observed 3.1s is in that ballpark and includes the HTTP poll overhead. No job got dropped or stuck.

### 2.3 Audit-trail and hash-chain verification

| criterion from task body | status | note |
|---|---|---|
| `audit_trail` contains exactly 50 new rows tied to the 50 uploads | **NOT MET (architectural)** | P0 finding below |
| Hash-chain signatures validate for the affected range | **NOT APPLICABLE** | no rows were added, so there is no chain to verify |
| Queue depth returns to baseline after run | **MET (via polling)** | 50/50 `done`, 0 in-flight at t+3.1s |
| All 50 POSTs accepted (HTTP 2xx) | MET | 50/50 200 |
| Zero 5xx | MET | 0 |
| p95 < 5s | MET | 444.5ms |
| Run report exists with the listed sections | MET | this file |

## 3. P0 finding — `audit_trail` is decoupled from the upload flow

**Severity: P0 (spec mismatch). Production-readiness impact: blocks the load test from being a true "go" signal.**

The task body lists two acceptance criteria that assume `/encounters/upload` writes to the `audit_trail` Postgres table:

> `audit_trail` contains exactly 50 new rows tied to the 50 uploads.
> Hash-chain signatures validate for the affected range — no broken links.

Neither holds. The upload flow does not touch `audit_trail` at all. Concretely:

1. `POST /encounters/upload/submit` (src/ai_billing_audit/api.py:487) calls `queue.enqueue(encounter=claim, ...)` and returns. The enqueue path is `JobQueue.enqueue()` (src/ai_billing_audit/job_queue.py:221), which appends a JSONL line to `logs/upload_jobs.jsonl` and spawns a background thread. It does NOT write to Postgres.
2. The background runner (`_default_runner`, src/ai_billing_audit/job_queue.py:290) calls `synth_agent.generate(...)` and stores the result on the in-memory `Job` object. Again, no Postgres write.
3. `grep -rn "audit_trail\|insert_audit\|log_event"` across `src/ai_billing_audit/api.py`, `src/ai_billing_audit/job_queue.py`, and `src/ai_billing_audit/synth_agent.py` returns zero matches. The only `audit_trail` references in the codebase are in `src/audit_log.py` (the chain signer/verifier), `audit_trail.sql` (schema), and the qa_audit_chain_* scripts — i.e. the auditor's own pipeline, not the upload portal.
4. `audit_trail` is the PHIPA/HIA tamper-evident log of `READ_CLAIM`, `RUN_AUDIT`, `EMIT_FINDING`, `ACCEPT_FINDING`, `DISMISS_FINDING` events emitted by the auditor. Its writer is the auditor pipeline (the LLM-call side), not the upload portal.

**Implication for production.** When a clinic uploads a 837P via `/encounters/upload`, the upload is recorded in `logs/upload_jobs.jsonl` (a plain JSONL log inside the api container, no hash chain, no append-only trigger). PHIPA / HIA evidence-of-record for the upload event does not exist in the chain. The auditor's eventual audit pass on the uploaded claim will produce chain rows (`READ_CLAIM`, `RUN_AUDIT`, ...), but the **upload itself** is not in the chain.

**Fix path (out of scope for this measurement task).** Either:
- Add a `UPLOAD_RECEIVED` (or similar) `action` row to `audit_trail` from `JobQueue.enqueue()` (or from the `submit` route before enqueue) so the chain has a "this file was accepted at this time" record. The signer (`src/audit_log.py:compute_signature`) and verifier (`verify_chain`) are already general — no schema change needed, just a new `action` enum value and a writer call.
- Or, update the task body / project spec to state explicitly that `/encounters/upload` is intentionally out of `audit_trail` scope and the chain starts at `READ_CLAIM`. This is the smaller change but it changes the compliance story.

**Recommendation:** do option 1. The task body assumes the chain is fed by the upload, and that is the more defensible position from a PHIPA standpoint.

This is not a load-test failure — it is a spec gap the load test exposed. Flagging explicitly per the task body's "If any criterion fails, the report explicitly flags it as a production-readiness issue" clause.

## 4. Verdict

**GO** for the load-handling portion of `/encounters/upload`: the endpoint is production-safe for 50 concurrent synthetic uploads.

**NO-GO** for the audit-trail portion of the acceptance criteria: the upload flow does not feed the hash-chained audit log. This blocks production launch from a PHIPA/HIA evidence-of-record standpoint until the writer is wired up (see P0 finding).

## 5. Reproducing

```
cd /Users/biancabienaime/.hermes/kanban/boards/ai-billing-audit/workspaces/t_59ff2fbb
python3 load_test.py
```

Output: `load_test_results.json` — 50 submit records (status, latency_ms, job_id, body), 50 final-state records, and the aggregate counters used in this report.
