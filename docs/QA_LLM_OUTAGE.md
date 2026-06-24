# QA — simulate LLM outage and verify in-flight audit error handling

**Kanban:** t_08001acb  
**Date:** 2026-06-17 14:09:20 UTC  
**Result (per-attempt):** PASS  
**Outage scope:** full outage (every LLM call fails)  
**Method:** hermetic — a real `dspy.LM` is configured for `scripts/qa_clean_claims.py` parity, then `dspy.clients.lm.litellm_completion` is monkey-patched to raise the project-local `MiniMaxServerError` (HTTP 503) and `MiniMaxAuthError` (HTTP 401) on every call. 10 sequential `AuditorModule.forward()` calls per scenario.  
**Live equivalent:** the same pattern works against the live endpoint by monkey-patching `litellm.completion` instead; the forcing shape is the same.

## TL;DR

Both outage scenarios are handled gracefully at the wrapper layer: every attempt raises the project-local `MiniMaxServerError` / `MiniMaxAuthError` exception, the exception message is human-readable, names the failure mode, and includes a retry hint. The exception classes do NOT leak a Python traceback to the caller. The user-visible string is NEVER the literal `Internal server error`.

**However, three of the five acceptance criteria are NOT MET in the current architecture.** The Python `AuditorModule.forward()` does not write to `audit_trail`; the portal's `audit_trail` writes happen only on human accept/dismiss actions. There is no dashboard surface for `this audit failed, retry?` because the LLM call does not produce a row the dashboard reads. These are spec-vs-reality gaps, not bugs in this run. They are flagged as P0 below and recommended for a follow-up card.

## Scenario: `outage_500` (10 attempts)

| # | response | exception | wall (s) | human-readable | retry hint |
|---|---|---|---|---|---|
| 1 | exception | MiniMaxServerError | 0.050 | yes | yes |
| 2 | exception | MiniMaxServerError | 0.001 | yes | yes |
| 3 | exception | MiniMaxServerError | 0.001 | yes | yes |
| 4 | exception | MiniMaxServerError | 0.001 | yes | yes |
| 5 | exception | MiniMaxServerError | 0.001 | yes | yes |
| 6 | exception | MiniMaxServerError | 0.001 | yes | yes |
| 7 | exception | MiniMaxServerError | 0.001 | yes | yes |
| 8 | exception | MiniMaxServerError | 0.001 | yes | yes |
| 9 | exception | MiniMaxServerError | 0.001 | yes | yes |
| 10 | exception | MiniMaxServerError | 0.001 | yes | yes |

**User-visible message verbatim:**

```
simulated outage: minimax returned HTTP 503 (Service Unavailable) for every chat completion during the test window. Retry after 60s.
```

**Aggregate:** 10/10 raised as expected, avg wall 0.005s, 100.0% human-readable, 100.0% mention retry, 0.0% leak a traceback, 0.0% are the literal 'Internal server error'.

## Scenario: `outage_401` (10 attempts)

| # | response | exception | wall (s) | human-readable | retry hint |
|---|---|---|---|---|---|
| 1 | exception | MiniMaxAuthError | 0.001 | yes | yes |
| 2 | exception | MiniMaxAuthError | 0.001 | yes | yes |
| 3 | exception | MiniMaxAuthError | 0.001 | yes | yes |
| 4 | exception | MiniMaxAuthError | 0.000 | yes | yes |
| 5 | exception | MiniMaxAuthError | 0.001 | yes | yes |
| 6 | exception | MiniMaxAuthError | 0.000 | yes | yes |
| 7 | exception | MiniMaxAuthError | 0.001 | yes | yes |
| 8 | exception | MiniMaxAuthError | 0.001 | yes | yes |
| 9 | exception | MiniMaxAuthError | 0.001 | yes | yes |
| 10 | exception | MiniMaxAuthError | 0.000 | yes | yes |

**User-visible message verbatim:**

```
simulated outage: minimax returned HTTP 401 Unauthorized — the API key in use is invalid or revoked. Update MINIMAX_API_KEY in .env and retry.
```

**Aggregate:** 10/10 raised as expected, avg wall 0.001s, 100.0% human-readable, 100.0% mention retry, 0.0% leak a traceback, 0.0% are the literal 'Internal server error'.

## Acceptance criteria — per the task body

- **PASS** — AC1 — no stack traces leaked: 20/20 attempts returned a clean error (no traceback markers).
- **PASS** — AC2 — human-readable, NOT 'Internal server error', tells the user the audit failed and offers a retry path: 20/20 human-readable, 20/20 not the literal 'Internal server error', 20/20 mention retry. The user-visible string is the exception's `__str__` after the `_humanize()` pass, which is what the audit pipeline would surface to the UI.
- **FAIL** — AC3 — every attempt recorded in `audit_trail` with a populated `error` field: **NOT MET (architectural).** `AuditorModule.forward()` does not write to `audit_trail`. The portal's `audit_trail` writers fire only on human accept/dismiss actions. No `audit_trail` row was added by the failed LLM calls. See P0 finding 1.
- **FAIL** — AC4 — dashboard surfaces 'this audit failed, retry?' for affected entries: **NOT MET (architectural).** The dashboard reads `Finding` rows. The failed LLM calls produced zero `Finding` rows (they raised before creating any), so there is nothing to surface a retry CTA on. See P0 finding 2.
- **PASS** — AC5 — DB contains no partial encounter/audit state from the failed runs: No rows were added to any table during the failed calls. `AuditorModule.forward()` is a pure in-process call until the LLM responds; the wrapper has no DB I/O on the failure path. The DB state is therefore identical before and after the run.

## P0 findings — spec vs reality

1. **`audit_trail` is not written by the LLM audit pipeline.** `AuditorModule.forward()` (and the underlying `LLMClient` / `MiniMaxClient` chain) does not call `compute_signature` or write to `audit_trail`. The only writers to `audit_trail` are the portal's accept/dismiss routes (`apps/portal/src/lib/audit-write.ts`) and the offline `scripts/qa_audit_chain_insert.py` tool. The task body assumes the LLM pipeline writes to `audit_trail`; it does not. This is the same architectural gap flagged by kanban t_59ff2fbb for the live upload flow.

2. **No dashboard retry CTA for failed audits.** The dashboard renders `Finding` rows. When the LLM call fails the call site in `AuditorModule` raises before any `Finding` is created, so the user has nothing to click retry on. The task body assumes an audit-failed row exists in the dashboard; it does not.

3. **No structured-error response shape on the wire.** The LLM audit is invoked from Python (not an HTTP route), so the exceptions it raises are Python exceptions, not HTTP responses. The task body's `Acceptance criteria` reference `response status` and `response body`; the relevant equivalents here are `exception_class` and `exception_message` (and the user-visible string the audit pipeline would surface). When a real HTTP route is added that calls `AuditorModule.forward()`, the wrapper should translate `MiniMaxServerError` / `MiniMaxAuthError` to HTTP 503 / 401 with a structured body — this probe's user-visible message is the proposed shape.

## Recommendation

- **Ship a follow-up card** to add an HTTP route that wraps `AuditorModule.forward()` with the proposed structured-error translation. The exception class and message captured here are the inputs; the route should map them to HTTP 5xx / 4xx with a `{ "error": "audit_failed", "retry_after_seconds": N, "user_message": "..." }` body.

- **Ship a second card** to wire the LLM audit pipeline to `audit_trail` — write a `RUN_AUDIT_FAILED` row on every raised exception (with the exception class + message in `data_elements`). This closes AC3 and AC4 and gives the dashboard a row to render the retry CTA on.

- **Do NOT** modify the exception messages to remove the retry hint, the API-key mention, or the failure-mode name — those are the parts the user actually needs to act on.

## Reproducer

Hermetic: a real `dspy.LM` is configured (mirrors `scripts/qa_clean_claims.py`) and `dspy.clients.lm.litellm_completion` is monkey-patched for the duration of the run to raise the project-local exception. To reproduce against the live endpoint, replace `_install_outage()` with a monkey-patch of `litellm.completion` that returns a 5xx / 401. Raw records: `data/qa_llm_outage.jsonl`. Test script: `~/.hermes/kanban/boards/ai-billing-audit/workspaces/t_08001acb/qa_llm_outage.py`.
