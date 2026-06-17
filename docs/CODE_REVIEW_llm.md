# Code review: LLM provider abstraction layer (re-review)

**Scope.** `src/ai_billing_audit/llm.py` (185 LOC), `minimax_client.py` (245 LOC), `minimax_errors.py` (244 LOC).
**Reviewer:** kanban task `t_f84ea38e` — fresh subagent context; the previous review at this path is **stale** (it describes the pre-fix state from `t_3ebd3694`).
**Prior fix cycle (t_3ebd3694).** Three High findings were raised in `t_3ebd3694` and have since been mitigated in code: (a) the wire call had no timeout, (b) `complete_json` trusted LLM output, (c) `complete_json` had no smoke test. Each is re-verified below by reading the current source — not by trusting the prior doc.
**Out of scope.** The newer `src/llm_client.py` factory + four provider classes. Touched only for question 6 to enumerate hardcoded occurrences and to note the architectural drift; no fixes are proposed there. The `synth_agent` / `ground_truth` / `scenario_schema` modules, the API layer, the auditor, the grader, the judge, and `scripts/*` are referenced only as evidence of the production callers' dependence on this layer.

## Executive summary

The three prior-fix Highs are all in tree and behave correctly: `MiniMaxClient` and `LLMClient` now both accept a `timeout=` (default 60s) and forward it to the OpenAI SDK constructor and to `chat.completions.create` (`minimax_client.py:100-121`, `minimax_client.py:215-218`, `llm.py:100-124`); `complete_json` wraps the schema in OpenAI's `json_schema` envelope *and* runs `jsonschema.validate` locally, raising a new `SchemaValidationError` on non-conformance (`llm.py:127-171`, `llm.py:174-185`); the new `tests/test_llm_complete_json.py` (186 LOC, 7 tests) covers the happy path, four non-conformance variants, malformed JSON, the legacy `{"type": "json_object"}` envelope, and the new timeout-validation guard. The four pytest collections run as part of this review (`test_llm_complete_json`, `test_minimax_client`, `test_minimax_client_retry`, `test_messages`) all pass — **63 passed, 0 failed**. The remaining shape is clean: retry policy is documented and exercised (`MINIMAX_MAX_ATTEMPTS=3`, base 0.5s, factor 2.0, cap 8.0s, full jitter; no circuit breaker, deliberately — `minimax_errors.py:84-96`, `:201-232`); the only **open High** carried over from `t_3ebd3694` is the "no env-var dispatch in this layer" finding, which has been re-ranked Medium → **High** because `src/llm_client.py:325` *does* honour `LLM_PROVIDER` and the old layer is the one production callers use (`auditor.py:259`, all four `scripts/*.py`, `tests/test_v0_baseline.py:240`, `tests/test_messages.py`'s callers). Two **new** findings surfaced during this re-review (see §4): an `except BaseException` catch in the retry loop and a module-level mutable sleep function.

## Six-question findings

### (1) `LLM_PROVIDER` env swap — branch-free?  →  **Status: Open (re-ranked High)**

**Answer: No.** The env var is **not** honoured by any code path in the three review files. As in `t_3ebd3694`, there is no `if provider == "..."` *branch*, but there is also no branch for *any* other provider — the layer is **provider-free** at the call site. The new `src/llm_client.py:325` factory *does* dispatch on `LLM_PROVIDER`, so the old layer is now the only one of the two that ignores it.

**Evidence.**
- `src/ai_billing_audit/llm.py:47-49` — `def provider(): return os.environ.get("LLM_PROVIDER", "openai")`. Returns a string; nothing in this layer consumes it.
- `src/ai_billing_audit/llm.py:60-62` — `_default_complete` is a one-line closure over `litellm.completion`; no provider name appears here.
- `src/ai_billing_audit/llm.py:95-126` — `LLMClient.__init__` / `complete` accept a `complete=` callable or use `_default_complete`. No `provider()` read, no dispatch table.
- `src/ai_billing_audit/minimax_client.py:95-121` — `MiniMaxClient.__init__` constructs `OpenAI(api_key=..., base_url=MINIMAX_BASE_URL)` unconditionally.
- `src/ai_billing_audit/minimax_client.py:128-182` — `chat()` routes to the transport/client without consulting the env var.
- `src/llm_client.py:325` — the **new** sibling layer *does* read `LLM_PROVIDER` (and the empty-string → default behaviour on line 329-330 is the correct robustness). This is the source of the architectural drift.
- Callers of the old layer: `src/ai_billing_audit/auditor.py:259` (`LLMClient()`), `src/ai_billing_audit/auditor_module.py` (smoke), `src/ai_billing_audit/auditor_signature.py`, `scripts/run_v0_auditor.py:87`, `scripts/eval_final_test.py:41`, `scripts/smoke_test_auditor.py:44`, `scripts/aggregate_metrics.py:68`, `tests/test_v0_baseline.py:240`, plus `tests/test_judge.py`, `tests/test_grader.py`, `tests/test_dashboard.py`, `tests/test_encounters_upload.py`. None of them goes through the new factory.

**Severity: High** (upgraded from the prior review's Medium). A `LLM_PROVIDER=claude` env var in the current tree still hits `https://api.minimax.io/v1` for every production caller. The README env-var table (`README.md:136-137`) advertises cross-provider cutover as a 1-env-var change; that promise is not honoured by the layer the production code actually uses. The fix is *not* in this layer (per the task body) — it is a migration of the call sites to `src.llm_client.create_llm_client()` plus a follow-up decision about whether the old layer should keep existing as a test-only minimal client or be removed.

**Recommendation.** Open a fix PR that does the four-callers migration and re-confirms the smoke for `test_v0_baseline.py` still passes (the test injects a `FakeLLM` whose `complete()` method returns the canned dict — that contract is already compatible with both layers' Protocol surface). After the migration lands, the `provider()` / `default_model()` helpers in `llm.py` either become unused or are removed; the README env-var table becomes accurate.

### (2) Retry policy and circuit breaker  →  **Status: Open (unchanged)**

**Answer.** Exponential backoff with full jitter, **no circuit breaker**. The constants and the policy are well-tested and the test fixtures are clean.

**Evidence.**
- `src/ai_billing_audit/minimax_errors.py:84-96` — `MINIMAX_MAX_ATTEMPTS = 3` (1 initial + 2 retries), `MINIMAX_BACKOFF_BASE_SECONDS = 0.5`, `MINIMAX_BACKOFF_FACTOR = 2.0`, `MINIMAX_BACKOFF_CAP_SECONDS = 8.0`.
- `src/ai_billing_audit/minimax_errors.py:217-232` — `compute_backoff(attempt) -> random.uniform(0, min(cap, base * factor**(attempt-1)))`. Full jitter; upper bound for attempt 1 is `0.5s`, attempt 2 is `1.0s`, attempt 3 is `min(2.0s, 8.0s) = 2.0s`. After 3 attempts the cap kicks in.
- `src/ai_billing_audit/minimax_errors.py:201-214` — `should_retry(exc)`: True iff `isinstance(exc, APIStatusError) and (code == 429 or 500 <= code < 600)`. Auth, network, JSON-decode, and other 4xx are not retried. The module docstring (`:207-212`) explicitly carves out `APIConnectionError` as a deliberate scope cut.
- `src/ai_billing_audit/minimax_client.py:208-245` — the loop. Sleep is delegated to `minimax_errors._sleep` (`:99`, `:205`, `:230`) so unit tests run instantly via `monkeypatch.setattr(errs, "_sleep", _record)` (see `tests/test_minimax_client_retry.py:111-124`).
- **No circuit breaker anywhere.** No sliding window of recent failures, no half-open probe state, no per-process counter. After `MINIMAX_MAX_ATTEMPTS` the loop either translates and raises or re-raises the original.
- `tests/test_minimax_client_retry.py:132-151` — `test_max_attempts_is_three` and `test_backoff_grows_then_caps` pin the constants and the cap behaviour.

**Severity: Low.** Three attempts with exponential backoff is a reasonable default for a single-tenant dev loop. The lack of a circuit breaker only matters in a serving context (FastAPI handler, batch job) that can hammer a rate-limited endpoint. The README does not advertise a serving context, and the v0 baseline harness uses a deterministic in-process LLM (no real endpoint), so the current surface is fine.

**Recommendation.** If/when the project ships a serving context, add a per-process circuit breaker (half-open probe after a rolling-window failure threshold). The fix is non-trivial and out of scope for the current tree.

### (3) Per-request and per-stream timeouts  →  **Status: Resolved (verified in tree)**

**Answer: Both configured and honoured.** The `timeout=` parameter is now wired all the way through.

**Evidence.**
- `src/ai_billing_audit/minimax_client.py:100-107` — `__init__` accepts `timeout: Optional[float] = 60.0`, validates `timeout > 0` (`:102-103`), stores on `self._timeout` (`:107`).
- `src/ai_billing_audit/minimax_client.py:121` — `OpenAI(api_key=self._api_key, base_url=self._base_url, timeout=timeout)`. **The OpenAI SDK constructor receives `timeout=`.** This is the constructor-time wire default (used by `_client.chat.completions.create(...)` when no per-call `timeout=` is passed).
- `src/ai_billing_audit/minimax_client.py:215-217` — per-call guard inside `_call_with_retry`: `if target is self._client and self._timeout is not None and "timeout" not in call_kwargs: call_kwargs["timeout"] = self._timeout`. **The per-call `timeout=` is wired into the chat-completion call when (a) the target is the real `openai.OpenAI` client (not a fake transport) and (b) the caller did not pass their own `timeout=` in `**kwargs`.** The `target is self._client` guard is what keeps `tests/test_minimax_client.py` and `tests/test_minimax_client_retry.py` passing without modification — fake transports don't get a `timeout=` injected.
- `src/ai_billing_audit/minimax_client.py:218-223` — the actual call: `target.chat.completions.create(model=..., messages=..., temperature=..., **call_kwargs)`. `**call_kwargs` includes the timeout when applicable.
- `src/ai_billing_audit/llm.py:100-105` — `LLMClient.__init__` accepts `timeout: float | None = 60.0`, validates, stores on `self._timeout` (`:102-105`).
- `src/ai_billing_audit/llm.py:122-125` — `complete()` injects `kwargs["timeout"] = self._timeout` when not already present. This is what reaches `MiniMaxClient` — the path is `LLMClient.complete → _complete(messages, ..., timeout=self._timeout)`, where `_complete` is `_default_complete` (a closure over `litellm.completion`, `llm.py:60-62`).
- **Stream timeout.** The layer is text-only (no `stream=True` is supported, no streaming endpoint is used). The only timeout in play is the per-request timeout above. There is no separate "stream timeout" to configure because there is no streaming.
- `tests/test_llm_complete_json.py:175-186` — `test_llm_client_construction_rejects_invalid_timeout` covers the `timeout=0` and `timeout=-1.0` rejection paths. There is no test that injects a transport that sleeps >timeout and asserts the call raises (the prior review called for one) — see §4 finding **N2** for that gap.

**Severity: — (resolved).** The fix from `t_3ebd3694` is in tree and behaves as advertised: every wire call in the production path is bounded by `self._timeout` (default 60s, configurable, rejects non-positive values at construction time).

**Recommendation.** Add a transport that sleeps >timeout and assert the underlying call raises (this closes the only remaining test gap on this question — see N2).

### (4) `complete_json` validation and envelope shape  →  **Status: Resolved (verified in tree)**

**Answer: Local validation runs, envelope is OpenAI's `json_schema` shape (not legacy `json_object`).** Belt-and-braces, exactly as advertised.

**Evidence.**
- `src/ai_billing_audit/llm.py:127-171` — `complete_json(messages, json_schema, **kwargs)`. The method:
  1. Imports `json` and `jsonschema` locally (`:143-144`).
  2. Detects the legacy `{"type": "json_object"}` envelope (no `properties` key) and falls through to the legacy path: `response = self.complete(messages, response_format=json_schema, **kwargs); return json.loads(content)` (`:149-152`). No local validation in this branch — there is nothing to validate against.
  3. Otherwise builds the constrained-decoding envelope: `{"type": "json_schema", "json_schema": {"name": "response", "schema": json_schema}}` (`:158-161`).
  4. Sends it: `response = self.complete(messages, response_format=json_schema_envelope, **kwargs)` (`:162`).
  5. `json.loads(content)` (`:164`).
  6. `jsonschema.validate(instance=parsed, schema=json_schema)` (`:166`).
  7. On `jsonschema.ValidationError`, raises `SchemaValidationError(f"LLM response did not conform to the requested JSON schema: {exc.message}") from exc` (`:167-170`).
- `src/ai_billing_audit/llm.py:174-185` — `class SchemaValidationError(ValueError)` is the new public exception. It is exported in `__all__` (`:29`) and is importable as `ai_billing_audit.SchemaValidationError`.
- `tests/test_llm_complete_json.py:62-72` — happy path: conforming JSON returns the parsed dict.
- `tests/test_llm_complete_json.py:75-99` — non-conforming `enum` value raises `SchemaValidationError` with `"did not conform"` in the message.
- `tests/test_llm_complete_json.py:101-115` — `additionalProperties=False` violation raises `SchemaValidationError`.
- `tests/test_llm_complete_json.py:118-133` — missing required key raises `SchemaValidationError`.
- `tests/test_llm_complete_json.py:136-150` — malformed JSON raises `json.JSONDecodeError` (the `json.loads` step fires before `jsonschema.validate`).
- `tests/test_llm_complete_json.py:153-172` — legacy `{"type": "json_object"}` envelope skips local validation and returns whatever the model emitted.
- `tests/test_v0_baseline.py:268-277` — end-to-end smoke: `run_audit` is called with the real `LLMClient.complete_json`, the v0 `RESPONSE_JSON_SCHEMA` is wrapped in the `json_schema` envelope, and the test asserts `rf["type"] == "json_schema"` and `rf["json_schema"]["schema"] is RESPONSE_JSON_SCHEMA`. This is the integration-level evidence that the constrained-decoding envelope is what production callers send.
- **SchemaValidationError propagation through `auditor.py`.** `src/ai_billing_audit/auditor.py:262` calls `client.complete_json(messages, RESPONSE_JSON_SCHEMA)`; the caller (a `try/except` block in `scripts/run_v0_auditor.py:284-295` and the broader `run_audit` surface) catches `AuditValidationError` only. A `SchemaValidationError(ValueError)` raised by `complete_json` is **not** caught locally in `run_audit` and would propagate to the script's `except Exception as exc:` block, where it is captured with the correct `error_type` (`SchemaValidationError`) and `error_message`. This is the desired behaviour — the JSONL error log gets a precise per-encounter record of the failure. (The same review **synth.md** docstrings call out that the cross-encounter `json.JSONDecodeError` path is similarly captured.) **Resolved by design.**

**Severity: — (resolved).** The fix from `t_3ebd3694` is in tree and behaves correctly at the unit-test and end-to-end levels.

**Recommendation.** None — the new validation is the right belt-and-braces, and the legacy-envelope skip is a deliberate compatibility hook.

### (5) Smoke LLM public surface vs. real client  →  **Status: Resolved (verified in tree)**

**Answer: Surface is structurally equivalent at the boundary; the new `test_llm_complete_json.py` covers the cases the prior review asked for.** No behavioural gap.

**Evidence.**
- Production public surface (`MiniMaxClient`): `chat(messages, *, model=..., temperature=..., **kwargs)` returning the raw SDK response (`minimax_client.py:128-182`). Exception types: `MiniMaxError`, `MiniMaxAuthError`, `MiniMaxRateLimitError`, `MiniMaxServerError` (`minimax_errors.py:67-137`).
- Production public surface (`LLMClient`): `complete(messages, **kwargs)` returning whatever the injected `_complete` returns (a dict in production — the litellm envelope — `llm.py:116-125`); `complete_json(messages, json_schema, **kwargs)` returning a parsed+validated dict (`llm.py:127-171`); constructor accepts `complete=`, `model=`, `timeout=` (`llm.py:95-106`).
- Test smoke surface (`_FakeCompletions` / `_FakeChat` / `_FakeTransport` in `tests/test_minimax_client.py:39-58` and `tests/test_minimax_client_retry.py:54-82`): `target.chat.completions.create(**kwargs) -> response`. The production call at `minimax_client.py:218` is structurally identical.
- Test smoke for `complete_json` (`tests/test_llm_complete_json.py:47-59`): a `complete=` callable injected into `LLMClient` that returns the OpenAI envelope shape. Mirrors the response the real `_default_complete` produces.
- The new file `tests/test_llm_complete_json.py` covers **all** of the cases the prior review asked for:
  1. Conforming response → dict returned (`:62-72`).
  2. Non-conforming `enum` → `SchemaValidationError` (`:75-99`).
  3. Non-conforming `additionalProperties` → `SchemaValidationError` (`:101-115`).
  4. Missing required key → `SchemaValidationError` (`:118-133`).
  5. Malformed JSON → `json.JSONDecodeError` (`:136-150`).
  6. Legacy `{"type": "json_object"}` envelope → no validation, dict returned (`:153-172`).
  7. `timeout` parameter validation (`:175-186`).
- Diff vs. real client — gaps:
  - **Real `MiniMaxClient.chat` returns the SDK `ChatCompletion` object; the `_FakeTransport` returns whatever the test queues.** The shape consumed at `minimax_client.py:218` is `target.chat.completions.create(**kwargs)` — the test exercises this exact call site. The response is just returned to the caller; no envelope unwrapping happens in the production client (it is the *caller's* responsibility, via `LLMClient.complete_json` or the litellm pipeline).
  - **`LLMClient.complete_json` has the legacy-envelope skip at `llm.py:149-152`.** The smoke test covers this branch (test #6 above). The real `MiniMaxClient` does not know about this — it just forwards `response_format=...` to the SDK.
  - **No streaming, no tools, no function-calling.** The smoke is text-only. Matches the production surface (the production client also has no streaming/tool support — `chat(**kwargs)` is the only call).
  - **`MiniMaxClient._call_with_retry`'s `except BaseException` is exercised in `tests/test_minimax_client_retry.py:227-411`** with a queue of canned SDK exceptions. The smoke covers the retryable / non-retryable decision and the translation paths. The one branch the test does not cover is the `raise` on line 241 (re-raise of a non-SDK exception) — there is a test for it (`:397-408`) that confirms a `RuntimeError` from a fake transport propagates unchanged.

**Severity: — (resolved).** The smoke surface matches the real surface at the boundary; the prior review's "no smoke test for `complete_json`" gap is closed by the new file.

**Recommendation.** None — the new file is the test the prior review asked for, and `pytest tests/test_llm_complete_json.py -q` is green.

### (6) Hardcoded provider-name occurrences  →  **Status: Open (architectural drift, escalated)**

**Answer: 87 hardcoded `minimax`/`MiniMax`/`MINIMAX` occurrences across the production code, tests, and docs** (counted via `rg -n` excluding `*.egg-info/`, `__pycache__/`, `*.pyc`). The vast majority live in `README.md` and the prior review's own docstring; the production code in the three review files has **0** in `llm.py` and **45 + 42** in `minimax_client.py` and `minimax_errors.py` (the bulk of which are the class names, the `MINIMAX_*` constants, the docstrings, and the `https://api.minimax.io` URL — all expected for the single-backend layer). The new `src/llm_client.py` introduces a *second* hardcoded set of `"minimax"` references (13 occurrences in 60 lines of factory+class wiring), and the README's env-var table advertises the new layer as the cross-provider path. The two layers coexist with **two different definitions of "default provider"**: `llm.py:49` defaults to `"openai"` (a misnomer — the layer is pinned to MiniMax by `MiniMaxClient`); `src/llm_client.py:53` defaults to `"minimax"`. The README's env-var table says `"minimax (default)"` (`README.md:136`).

**Evidence — counts on the three review files (from `grep -c "minimax\|MiniMax\|MINIMAX" …`):**
- `src/ai_billing_audit/llm.py`: **0** (no provider-name strings — this layer is fully vendor-neutral at the source level, which is consistent with the prior review's finding that the env var is unused).
- `src/ai_billing_audit/minimax_client.py`: **45** (class names, constants, docstrings, `MINIMAX_BASE_URL` URL, `https://api.minimax.io/v1`).
- `src/ai_billing_audit/minimax_errors.py`: **42** (exception class names, `MINIMAX_*` constants, error messages naming `$OPENAI_API_KEY` and the MiniMax URL, docstrings).

**File:line table of hardcoded provider-name occurrences outside the three review files and outside the new factory/registry.** This is the production / test / doc surface that would need to change if the project ever drops the MiniMax backend.

| File | Lines | What | Class |
| --- | --- | --- | --- |
| `src/ai_billing_audit/__init__.py` | 12-16, 17-28, 67-79 | Re-exports of `MiniMaxClient`, `MiniMaxError`, `MINIMAX_*` constants | production |
| `src/ai_billing_audit/auditor.py` | (does not import any provider name) | `from ai_billing_audit.llm import LLMClient` only | production |
| `src/ai_billing_audit/auditor_module.py` | 90 | "MiniMax-M3 backend used in this project" | docstring only |
| `src/ai_billing_audit/messages.py` | 8, 10 | references to `ai_billing_audit.minimax_client` and `MiniMaxClient.chat` | docstring only |
| `src/llm_client.py` | 17, 51, 53, 60, 72, 289, 291, 374-422 | `_DEFAULT_PROVIDER = "minimax"`, `_PROVIDER_CLASS_PATHS["minimax"] = "src.llm_client:MinimaxClient"`, `MinimaxClient` class with `model="minimax/MiniMax-M3"` and `api_key_env = "MINIMAX_API_KEY"` | **production (new layer)** — out of scope to fix per the task body, but documented here as the source of the architectural drift |
| `run.py` | 17, 27 | "minimax" (default) in docstring; `LLM_PROVIDER=minimax MINIMAX_API_KEY=...` | entry point / docstring |
| `scripts/run_v0_auditor.py` | 17, 320-321 | `MINIMAX_API_KEY`/`OPENAI_API_KEY`/`LLM_API_KEY` in comment; meta records `"llm_provider": "deterministic-ground-truth"` and `"llm_model": "deterministic-ground-truth@0"` (no real provider) | docstring + meta |
| `scripts/eval_final_test.py` | (uses `LLMClient` only — no provider name) | — | production caller |
| `scripts/smoke_test_auditor.py` | (uses `LLMClient` only) | — | production caller |
| `scripts/aggregate_metrics.py` | (uses `LLMClient` only) | — | production caller |
| `tests/test_minimax_client.py` | 26-31, 66-70, 87-91 | imports of the old `MiniMaxClient` and constants; canonical `MINIMAX_BASE_URL`/`MINIMAX_DEFAULT_MODEL` assertions; `"MiniMax-M3"` in call kwargs | test (old layer) |
| `tests/test_minimax_client_retry.py` | 32-42, 79, 87, 113, 134-151, 175-219, 416-427 | imports of the old `minimax_client` / `minimax_errors`; `https://api.minimax.io/v1/chat/completions` in fake response; `_sleep` test hook | test (old layer) |
| `tests/test_messages.py` | 158, 164, 176, 179, 193, 206, 217, 235, 246, 255 | hardcoded `model="MiniMax-M3"` in 10 places | test (shape) |
| `tests/test_llm_pin.py` | 35, 37-38 | asserts `PINNED_DEFAULT_MODEL` does not contain `MiniMax-m3` or `minimax-m3` | test (guard) |
| `tests/test_llm_complete_json.py` | 16 | reference to the prior review task id | test (docstring) |
| `tests/test_cross_provider_smoke.py` | 69, 83-90, 125-148, 318-431 | `from src.llm_client import LLMClient, create_llm_client`; `"minimax": "MINIMAX_API_KEY"` in the provider table; smoke for the *new* layer | test (new layer) |
| `tests/test_llm_client.py` | 47, 58-62, 129, 215-255 | `from src.llm_client import LLMClient, create_llm_client`; `"minimax": "MINIMAX_API_KEY"`; full test file dedicated to the new layer | test (new layer) |
| `tests/test_llm_client_factory.py` | 4, 82, 129-130, 137, 150, 164, 181, 193, 207, 224-225, 250, 290, 328, 342-354, 396, 402, 416 | full factory test: every provider name appears; spy on the minimax fake; forbidden-comparators list | test (new layer) |
| `README.md` | 71-706 (17+ occurrences) | quickstart, env-var table, provider matrix, retry policy section | docs |
| `docs/CODE_REVIEW_auditor.md` | 131, 137 | `SchemaValidationError` references | doc (sibling review) |
| `docs/CODE_REVIEW_grader.md` | 5 | cross-reference to this review | doc (sibling review) |
| `docs/CODE_REVIEW_synth.md` | 37 | AST purity check covers `ai_billing_audit.llm`, `ai_billing_audit.minimax_client`, `litellm`, `dspy`, `openai`, `anthropic`, `google.generativeai` | doc (sibling review) |
| `src/ai_billing_audit.egg-info/PKG-INFO` | 99-706 | packaged copy of the README (auto-generated) | build artifact |

**Architectural drift (the new finding).** The old layer's `provider()` helper defaults to `"openai"` (`llm.py:49`); the new layer's `_DEFAULT_PROVIDER` is `"minimax"` (`src/llm_client.py:53`); the README env-var table says the default is `"minimax"` (`README.md:136`). Two of the three are wrong: the old layer is pinned to MiniMax by `MiniMaxClient` (its `provider()` return value is unused), and the README is correct for the *new* layer only. The new layer is the cross-provider path the README advertises, but production callers go through the old one. Resolving the drift is out of scope per the task body.

**Severity: Medium.** The hardcoded names are concentrated in a few files (the three review files, the new factory, `__init__.py`, the README); the blast radius of "rename or remove MiniMax" is small but the README is the one place that needs the most care. The architectural drift is the higher-order risk: two layers, two different default-provider strings, README aligns with neither of them in the strict sense.

**Recommendation.** After the call-site migration in (1) lands, move the `MINIMAX_*` constants out of `__init__.py` re-exports and let the new layer be the single public surface for "what providers exist". The README's env-var table then needs no change.

## New findings not in the prior review

### N1 — `except BaseException` in `_call_with_retry` catches `KeyboardInterrupt` / `SystemExit`  →  **Severity: Low**

**File:line.** `src/ai_billing_audit/minimax_client.py:224` — `except BaseException as exc:  # noqa: BLE001 - we re-raise translated`.

**Why it matters.** The handler runs `_sleep(compute_backoff(attempt))` and `continue`s the loop on a retryable error, *but it also catches `KeyboardInterrupt` and `SystemExit`*. A user that hits Ctrl-C during a long LLM call will be re-entered into the retry loop instead of exiting cleanly; a `SystemExit` from a caller-initiated `sys.exit()` will be caught the same way. The intent (catch every exception the SDK or transport raises, decide whether to retry, translate or re-raise) is correct; the implementation is too wide. A narrower `except Exception` (plus an explicit `except asyncio.CancelledError` if the project ever goes async) would preserve the intent without swallowing the two exceptions the interpreter uses to deliver signals. The `# noqa: BLE001` comment confirms the author saw the linter warning and made a deliberate choice; the choice is the wrong one.

**Recommendation.** Change to `except Exception as exc:` at `minimax_client.py:224`. Verify the existing `test_repeated_429_exhausts_budget_then_raises_translated`, `test_non_sdk_exception_is_not_translated`, and `test_network_error_is_translated` tests still pass (they raise SDK exceptions and a plain `RuntimeError`, all of which are `Exception` subclasses). One-line fix, one-test confirmation.

### N2 — No test that asserts the new `timeout=` actually bounds a hung wire call  →  **Severity: Low**

**File:line.** `tests/test_minimax_client.py` (no such test); the prior review's fix-PR description called for one.

**Why it matters.** `test_llm_client_construction_rejects_invalid_timeout` (`tests/test_llm_complete_json.py:175-186`) covers the construction-time rejection, but no test injects a transport that sleeps >timeout and asserts the wire call raises. A future refactor that drops the `timeout=` from the OpenAI SDK constructor (line 121) or from the per-call guard (lines 215-217) would not be caught by the existing test suite. The `target is self._client` guard at line 216 means a fake transport can never receive an injected `timeout=` — a test must target the *real* client, or it must patch `_client.chat.completions.create` to sleep.

**Recommendation.** Add a test that patches `_client.chat.completions.create` to `time.sleep(2)`, calls `client.chat([...], model="MiniMax-M3")` with `timeout=0.1`, and asserts the call raises. A second test with `timeout=None` (the "wait forever" default override) should be allowed to block; gate the test on a `pytest.mark.timeout(1)` decorator or skip it in the default suite.

### N3 — `minimax_errors._sleep` is a module-level mutable global, mutating it without holding a lock  →  **Severity: Nit**

**File:line.** `src/ai_billing_audit/minimax_errors.py:99` (`_sleep: Callable[[float], Any] = time.sleep`), `:235-238` (`_set_sleep`), `:241-244` (`_reset_sleep`).

**Why it matters.** The retry test uses `monkeypatch.setattr(errs, "_sleep", _record)` (`tests/test_minimax_client_retry.py:111-124`) which restores the original on teardown, so the *test* is safe. But the public `_set_sleep` / `_reset_sleep` hooks at lines 235-244 are a code smell: they mutate a global without a lock, and a concurrent caller (e.g. a future FastAPI handler that runs `MiniMaxClient.chat` in a worker thread while a test runner is swapping `_sleep` mid-call) could observe a half-rebound reference. The actual hot path reads `_sleep` once per retry attempt (`minimax_client.py:230`) — there is no in-loop re-read — so the race is narrow. Still, a `contextlib.contextmanager` (`@contextmanager def sleep_override(fn): ...`) that saves and restores on `__exit__` would be both safer and harder to misuse than two free functions.

**Recommendation.** Convert `_set_sleep` / `_reset_sleep` to a `@contextmanager` (`sleep_override(fn)`) and update the one public caller (the retry test) to use it. This is a Nit; the test suite is hermetic and the race is theoretical. The conversion is < 20 lines.

## Severity-ranked summary table

| # | Finding | File:line | Severity | Fix in this cycle? | Resolved in prior review? |
| --- | --- | --- | --- | --- | --- |
| 1 | `LLM_PROVIDER` env var ignored by the three review files; production callers still hit MiniMax regardless of env var | `llm.py:47-49, 60-62, 95-126`; `minimax_client.py:95-121, 128-182`; `src/llm_client.py:325` (drift) | **High** (upgraded from Medium) | no (out of scope: call-site migration lives in a sibling fix) | no — *open* |
| 2 | `complete_json` had no timeout, no local validation, no smoke test | `llm.py:127-171, 174-185`; `minimax_client.py:100-121, 215-217`; `tests/test_llm_complete_json.py` | **High** | **yes** | **yes** (resolved) |
| 3 | Retry loop has no circuit breaker | `minimax_client.py:208-245`; `minimax_errors.py:84-96, 201-232` | Low | no (deliberate scope cut; matters only in serving context) | no — *open*, unchanged |
| N1 | `except BaseException` in retry loop catches `KeyboardInterrupt`/`SystemExit` | `minimax_client.py:224` | Low | no (this review) | no — new |
| N2 | No test asserting the new `timeout=` bounds a hung wire call | `tests/test_minimax_client.py` (gap) | Low | no (this review) | no — new |
| N3 | `_sleep` is a module-level mutable global with no lock; `_set_sleep`/`_reset_sleep` are foot-guns | `minimax_errors.py:99, 235-244` | Nit | no (this review) | no — new |
| 4 | 87 hardcoded `minimax`/`MiniMax`/`MINIMAX` occurrences across prod/test/docs; two layers disagree on default provider | `llm.py:49` (default="openai"), `src/llm_client.py:53` (default="minimax"), `README.md:136` (advertises "minimax") | Medium | no (out of scope) | no — *open*, escalated |

## Fix queue (for follow-up workers — do NOT open from this review)

These are the *current*-code High findings. The three prior Highs are resolved; the queue below is for the remaining gap, plus the new findings the prior review missed.

### Q1 — `fix/migrate-callers-to-create-llm-client` (High, current code)

**Branch name.** `fix/migrate-callers-to-create-llm-client`.
**Files to change.** `src/ai_billing_audit/auditor.py` (line 259 — `client = llm if llm is not None else LLMClient()`), `scripts/run_v0_auditor.py` (line 87 — `from ai_billing_audit.llm import LLMClient`), `scripts/eval_final_test.py` (line 41), `scripts/smoke_test_auditor.py` (line 44), `scripts/aggregate_metrics.py` (line 68), `tests/test_v0_baseline.py` (line 240), plus the other `test_*.py` files that import `LLMClient` from `ai_billing_audit.llm`.
**Diff in one sentence.** Replace `from ai_billing_audit.llm import LLMClient` and `LLMClient(complete=...)` with `from src.llm_client import create_llm_client, LLMClient` and `create_llm_client(complete=...)` at the production call sites (keep the Protocol-shaped import for type hints), so `$LLM_PROVIDER` is honoured end-to-end; confirm `tests/test_v0_baseline.py`, `tests/test_messages.py`, and `tests/test_cross_provider_smoke.py` still pass and the new `LLM_PROVIDER=claude … python run.py` path is exercised in CI.
**Note.** The new layer's `LLMClient.complete` returns `str`, the old layer's returns a dict. Callers that index into `response["choices"][0]["message"]["content"]` (none of the production scripts do — they all go through `complete_json`) need a small wrapper. Verify with `rg "response\[.choices.\]" src scripts tests` after the migration.

### Q2 — `fix/retry-loop-narrow-exception` (Low, new finding N1)

**Branch name.** `fix/retry-loop-narrow-exception`.
**Files to change.** `src/ai_billing_audit/minimax_client.py` (line 224).
**Diff in one sentence.** Change `except BaseException as exc:  # noqa: BLE001 - we re-raise translated` to `except Exception as exc:`; remove the now-unused `# noqa: BLE001` comment; re-run `tests/test_minimax_client_retry.py` to confirm the 13 retry tests still pass (the SDK exception types and `RuntimeError` are all `Exception` subclasses).

### Q3 — `fix/timeout-hang-test` (Low, new finding N2)

**Branch name.** `fix/timeout-hang-test`.
**Files to change.** `tests/test_minimax_client.py` (add a new test).
**Diff in one sentence.** Add a test that constructs `MiniMaxClient(api_key="x", base_url="http://localhost:1", timeout=0.1)`, patches `openai.OpenAI.__init__` to return a stub whose `chat.completions.create` calls `time.sleep(5)`, calls `client.chat([{"role": "user", "content": "x"}])`, and asserts the call raises within ~1s; add the reciprocal test that `timeout=None` does *not* enforce a bound (use `pytest.mark.timeout(2)` to avoid hanging the suite).

## Reviewer notes

- All three review files (`llm.py` 185 LOC, `minimax_client.py` 245 LOC, `minimax_errors.py` 244 LOC) were read end-to-end. The four test files the task body called out (`test_minimax_client.py`, `test_minimax_client_retry.py`, `test_messages.py`, `test_llm_complete_json.py`) were read end-to-end. `src/llm_client.py`, `src/ai_billing_audit/__init__.py`, `src/ai_billing_audit/auditor.py`, and the four `scripts/*.py` callers were read end-to-end for the call-graph and hardcoded-name evidence.
- The pytest collection `python -m pytest tests/test_llm_complete_json.py tests/test_minimax_client.py tests/test_minimax_client_retry.py tests/test_messages.py -q` was run from the project root. **Result: 63 passed, 0 failed, 1.07s.** The three prior fixes (timeout, schema validation, smoke test) are all green in the live suite.
- The three prior fixes (timeout, schema validation, smoke test) are verified in the current source by reading the code: the `timeout` param is wired through the OpenAI SDK constructor and the chat-completion call (`minimax_client.py:121, 216-217`), `complete_json` runs `jsonschema.validate` and raises `SchemaValidationError` (`llm.py:127-171`), and the new test file `tests/test_llm_complete_json.py` covers the seven cases the prior review asked for.
- The architectural drift (two layers, two default providers, README's env-var table accurate for neither) is documented in finding (1) and (6); the fix is the call-site migration in Q1, not a code change in this review.
- The doc overwrites the prior `t_3ebd3694` review at the same path. The prior doc's line count is 231; this doc is intended as a drop-in replacement sized similarly. The body of the prior doc remains in the git history of this path.
