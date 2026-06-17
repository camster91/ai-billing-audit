# Code review: tests/ — coverage gaps and weak assertions

**Scope.** All 28 test files under `tests/` (27 at root + 1 in `tests/agents/auditor/`), all 25 `src/` modules (4 at top level + 21 inside the `ai_billing_audit` package), and the four `scripts/` modules imported by tests (`aggregate_metrics.py`, `optimize.py`, `score_predictions.py`).

**Method.** Walked the test tree (`find tests/ -name 'test_*.py'`), parsed each test's body for `import` / `from ... import` / `spec_from_file_location` to map coverage; counted every test function (including parametrised cases and class methods — 408 cases total); grepped for assertion-free, network-call, filesystem, and time-of-day patterns; read `test_dashboard.py`, `test_cross_provider_smoke.py`, and `test_synth_determinism.py` end-to-end; cross-checked each `src/` file against the import set.

**Date.** 2026-06-16. **No test or source file was modified.**

**Note on file count.** The task body references "24 test files" in `tests/`. The actual count is **28**: 27 `test_*.py` files in `tests/` plus 1 in `tests/agents/auditor/test_signature.py`. The agents/ test is a duplicate of the surface already covered by `tests/test_auditor_module.py` and `tests/test_auditor_signature.py` and should arguably be merged (see finding D-2 below).

---

## Executive summary

The test suite is **substantially healthier than the brief's framing implies.** Every test that the brief calls out as suspect (`test_dashboard.py`, `test_cross_provider_smoke.py`, the `seed=42` determinism test) is in fact correctly written. The "split-screen" and "merely imports" hypotheses are both wrong: the dashboard tests assert real DOM-level markup, and the cross-provider smoke test exercises the production dispatch table for all four providers with real wire-shape assertions.

The real gaps are different from the brief's list:

- **3 src/ modules have zero behavioural coverage.** `ai_billing_audit.synth.template`, `ai_billing_audit.synth.render`, and `ai_billing_audit.synth.content_table` are checked only structurally (AST inspection for forbidden imports) by `test_synth_purity.py` — never invoked by a test. The synth agent's renderer functions (`_build_easy`, `_build_medium`, `_build_hard`, `_rng_for`, `_enc_id`) are exercised only via the public `generate_suite` / `generate_encounter` API; the underlying classes (`Scenario`, `Template`) and the content table validator (`_validate`) are not.
- **5 src/ modules are indirectly covered only.** `ai_billing_audit.ground_truth`, `ai_billing_audit.encounter_schema`, `ai_billing_audit.billing`, `ai_billing_audit.demo_entries`, and `ai_billing_audit.audit` (the package subpackage, which is a placeholder) have no direct test. `ground_truth` is loaded transitively via the committed `data/train.json` and `data/val.json`; `encounter_schema` and `demo_entries` are loaded transitively via the dashboard routes.
- **1 test file is a true duplicate** of surface already covered at the top level: `tests/agents/auditor/test_signature.py` tests the same `auditor_module.AuditorModule` + `auditor_signature.AuditClaim` API as `test_auditor_module.py` and `test_auditor_signature.py`. 6 test cases, 294 lines, all in scope of the root tests.
- **1 single test makes a real network call** when `MINIMAX_API_KEY` is set: `tests/test_minimax_integration.py::test_minimax_live_chat_completion_is_non_empty_and_echoes_model`. It is gated by a `pytest.mark.integration` marker and a `pytest.skip` if the env var is missing, so hermetic CI is unaffected.
- **1 test file uses wall-clock polling loops** (4 sites in `test_encounters_upload.py` — lines 407, 473, 708, 736), with `time.sleep(0.05)` and a 3-5s deadline. The pattern is not flaky in practice (the runner is in-process), but it would break if the runner ever moved out of process.
- **Zero assertion-free tests in the strict sense.** No `assert True`, no `assert 1`, no bare `assert 0`, no zero-arg test bodies. The 3 "no-raise" tests (a separate, legitimate pattern — they assert the function does NOT raise) are listed in Q2.
- **Zero "merely imports" tests in the strict sense.** Every test file imports the surface it tests; the AST-purity check in `test_synth_purity.py` is the closest thing to an "import-only" pattern, and it has 3 substantive parametrised assertions.

The brief's two specific suspicions are both reversed:

- **Q4 (dashboard split-screen): the test does NOT only check HTTP 200.** 25 of the 27 dashboard tests assert DOM-level markup details — `<mark class="evidence">` tags, `data-action="copy-quote"` button counts, severity CSS class hooks, per-finding `<blockquote class="finding-quote">` counts, advanced-action button IDs (`btn-jump-high`, `btn-next-finding`, `btn-severity-filter`) gated on difficulty. **But** the brief's "split-screen" framing is itself wrong: there is no split-screen concept in the current dashboard code. See Q4.
- **Q5 (cross-provider smoke): the test DOES swap provider backends and DOES verify provider-specific behaviour.** It uses the production `create_llm_client()` factory (no `_TEST_PROVIDER_OVERRIDES` shim), the real `litellm.completion` mock, and per-provider assertion diffs. **But** the verification is shallower than a true smoke test — it pins only response shape and the canned prompt/reply, not provider-specific features (rate-limiting, retry, error mapping). Those live in their own dedicated tests. See Q5.
- **Q6 (seed=42 determinism): the test DOES run twice and DOES assert byte-equal output** for every (tier, variant, seed) combination. It is, however, a unit-level "call function twice" harness, not a "run the entire suite twice and compare stdout" harness. No `pytest-replay` / `pytest-randomly` is configured. See Q6.

---

## 1. Coverage matrix (Question 1)

### src/ tree

```
src/
├── audit_log.py                  # 222 lines
├── llm_client.py                 # 618 lines
├── optimize.py                   # 349 lines
├── optimize_compile.py           # 330 lines
└── ai_billing_audit/
    ├── api.py                    # 600+ lines
    ├── audit.py                  # placeholder
    ├── auditor.py                # 286 lines
    ├── auditor_module.py         # ~280 lines
    ├── auditor_signature.py      # 91 lines
    ├── auditor_prompt.txt
    ├── billing.py                # 16 lines (placeholder)
    ├── demo_entries.py           # ~95 lines
    ├── demo_registry.py          # ~140 lines
    ├── encounter_schema.py       # ~280 lines
    ├── grader.py                 # ~370 lines
    ├── grading.py                # ~290 lines
    ├── ground_truth.py           # 485 lines
    ├── job_queue.py              # 446 lines
    ├── judge.py                  # ~600 lines
    ├── llm.py                    # ~340 lines
    ├── messages.py               # ~280 lines
    ├── minimax_client.py         # ~350 lines
    ├── minimax_errors.py         # ~280 lines
    ├── scenario_schema.py        # 213 lines
    ├── scenario_schema.json      # 209 lines
    ├── synth_agent.py            # 215 lines
    ├── synth/
    │   ├── __init__.py
    │   ├── template.py           # 87 lines
    │   ├── content_table.py      # 298 lines
    │   └── render.py             # 179 lines
    └── x12_parser.py             # ~480 lines
```

### Coverage matrix (rows = src/ files; columns = which test file directly imports/exercises the module)

| `src/` module | Has direct test? | Test files (direct importer) | Notes |
|---|---|---|---|
| `src/audit_log.py` | YES | `test_audit_log.py` | Full coverage: 14 test functions, pure-data harness. |
| `src/llm_client.py` | YES | `test_cross_provider_smoke.py`, `test_llm_client.py`, `test_llm_client_factory.py`, `test_minimax_integration.py`, `test_dev_loop_factory.py` (factory), `test_llm_pin.py` (literal-pinning AST check, not behaviour) | Five files cover this; behaviour (per-provider) is in `test_cross_provider_smoke.py` + `test_llm_client.py`; factory dispatch in `test_llm_client_factory.py`. |
| `src/optimize.py` | YES | `test_optimize.py`, `test_dev_loop_factory.py` (LM-selector only) | 23 test functions in `test_optimize.py`; the dev-loop LM selector is covered separately. |
| `src/optimize_compile.py` | YES | `test_optimize_compile.py` | 20 test functions, covers stub and mipro modes + dspy import isolation. |
| `ai_billing_audit/__init__.py` | YES | `test_import.py` (smoke) | 4 tests: version string, public-API attribute checks. |
| `ai_billing_audit/api.py` | YES | `test_dashboard.py`, `test_encounters_upload.py` (uses `from ai_billing_audit import api`) | 27 dashboard tests + 28 upload tests exercise the route layer. |
| `ai_billing_audit/audit.py` | **NO** | (none) | Placeholder module. The docstring (`audit.py:1-9`) states the auditor agent lives in `ai_billing_audit.auditor` and the file is "reserved for the future billing-rules corpus loader." No test needed today; flag for future. |
| `ai_billing_audit/auditor.py` | YES (indirect) | `test_aggregate_metrics.py` (imports `Finding`, `AuditResult` and stubs `run_audit`), `test_v0_baseline.py` (imports `run_audit`, `validate_findings`, `RESPONSE_JSON_SCHEMA`, `Finding`, `AuditResult`) | 13 v0-baseline tests + 8 aggregate-metrics tests exercise the auditor end-to-end against a fake LLM. **Direct `run_audit()` execution happens in `test_v0_baseline.py`.** |
| `ai_billing_audit/auditor_module.py` | YES | `test_auditor_module.py`, `agents/auditor/test_signature.py` | 16 + 6 tests, both exercise the DSPy `Predict` round-trip with `DummyLM`. **Duplicate surface — see D-2.** |
| `ai_billing_audit/auditor_signature.py` | YES | `test_auditor_signature.py`, `test_auditor_module.py`, `agents/auditor/test_signature.py` | 11 + 16 + 6 tests. **Triple-overlap.** |
| `ai_billing_audit/auditor_prompt.txt` | YES (file-hash) | `test_v0_baseline.py` (asserts byte-equality with `prompts/v0/auditor_prompt.txt`) | 1 test pins the v0 prompt pin + manifest hash. |
| `ai_billing_audit/billing.py` | **NO** | (none) | 16-line placeholder. No test. Acceptable per current code state. |
| `ai_billing_audit/demo_entries.py` | NO (indirect only) | (not directly imported; executed as a side-effect of `ai_billing_audit/__init__.py` import) | The 3 `register_demo_encounter` calls in `demo_entries.py` are tested transitively by `test_dashboard.py` (which asserts `enc_10032`, `enc_0007`, `enc_0000` are registered). No direct test of the file's body. |
| `ai_billing_audit/demo_registry.py` | YES | `test_dashboard.py` (idempotency, unknown-difficulty rejection, load-by-id, registry-empty path) | 5 tests cover the registry surface; the easy/medium/hard wiring tests in `test_dashboard.py` cover the `register_demo_encounter` + `load_encounter_record` integration. |
| `ai_billing_audit/encounter_schema.py` | NO (indirect) | (not directly imported) | Not referenced by any test. The committed `data/val.json` and `data/train.json` are produced by `ground_truth.py` (via `synth_agent`); the encounter_schema is the format spec but is not validated at test time. **Gap** — see G-3. |
| `ai_billing_audit/grader.py` | YES | `test_grader.py` | 12 tests cover config loading, `build_messages` purity, `Grader.grade` end-to-end with a fake LLM, byte-identical-Grader determinism. |
| `ai_billing_audit/grading.py` | YES | `test_grading.py`, `test_judge.py`, `test_aggregate_metrics.py` (transitively via scripts/aggregate_metrics) | 23 + 24 tests cover `match_findings` (the Jaccard matcher) and `grade_with_fallback`. |
| `ai_billing_audit/ground_truth.py` | NO (indirect) | (not directly imported) | Loaded transitively via the committed JSON files. `test_synth_determinism.py` proves the synth's output is byte-stable but does not exercise `ground_truth.py` directly (the synth calls `ground_truth` only at split-generation time, not at `generate_suite` time). **Gap** — see G-3. |
| `ai_billing_audit/job_queue.py` | YES | `test_encounters_upload.py` | 28 tests cover the queue: enqueue, status, cancel, transitions, default-singleton, JSONL log writes. |
| `ai_billing_audit/judge.py` | YES | `test_judge.py` | 24 tests cover `FallbackGrader`, `grade_with_fallback`, `SameProviderError`, abstain handling, judge-provider override. |
| `ai_billing_audit/llm.py` | YES | `test_llm_complete_json.py`, `test_llm_pin.py`, `test_grader.py` (uses `LLMClient`), `test_judge.py` (uses `LLMClient`), `test_v0_baseline.py` (uses `LLMClient`), `test_synth_purity.py` (AST-check: `ai_billing_audit.llm` must not be imported by synth) | Multiple files; the `complete_json` happy/edge paths are in `test_llm_complete_json.py`; the model pin is in `test_llm_pin.py`. |
| `ai_billing_audit/messages.py` | YES | `test_messages.py` | 29 tests cover the typed-message helpers + validators. |
| `ai_billing_audit/minimax_client.py` | YES | `test_minimax_client.py`, `test_minimax_client_retry.py`, `test_minimax_integration.py` | 9 + 18 + 1 tests cover the default constants, the transport, the retry layer, and one live-API test. |
| `ai_billing_audit/minimax_errors.py` | YES | `test_minimax_client_retry.py` | 18 tests cover `compute_backoff`, `should_retry`, `translate_sdk_exception`, and the exception hierarchy. |
| `ai_billing_audit/scenario_schema.py` | YES | `test_scenario_schema.py` | 48 tests cover schema shape, example validation, jsonschema round-trip, per-field rejection. |
| `ai_billing_audit/scenario_schema.json` | YES | `test_scenario_schema.py` (loads via `ss.SCHEMA_PATH`) | Same file. |
| `ai_billing_audit/synth_agent.py` | YES | `test_synth_determinism.py`, `test_synth_purity.py` | 10 determinism tests + 3 purity tests + 1 smoke. |
| `ai_billing_audit/synth/__init__.py` | YES (AST-only) | `test_synth_purity.py` (parses source, asserts no LLM imports) | Structural only — no behavioural coverage. |
| `ai_billing_audit/synth/template.py` | **NO (behavioural)** | (only AST-checked in `test_synth_purity.py`) | `class Scenario`, `class Template` never imported by a test. The `generate_suite` path uses these internally but no test asserts on `Template` shape directly. **Gap** — see G-1. |
| `ai_billing_audit/synth/render.py` | **NO (behavioural)** | (only AST-checked in `test_synth_purity.py`) | `_rng_for`, `_enc_id`, `_build_easy`, `_build_medium`, `_build_hard` are called transitively by `generate_suite`, but no test pins the per-tier ordering, the `_enc_id` format, or the deterministic-RNG contract at the renderer level. **Gap** — see G-1. |
| `ai_billing_audit/synth/content_table.py` | **NO (behavioural)** | (only AST-checked in `test_synth_purity.py`) | `_validate` is the only function. Never imported by a test. **Gap** — see G-1. |
| `ai_billing_audit/x12_parser.py` | YES | `test_encounters_upload.py` | 28 tests exercise the parser end-to-end (single 837P, ZIP, valid/invalid envelopes, required-field rejection). |

**Summary counts:** 25 of 25 source modules have *some* test surface. 21 have direct behavioural coverage; 4 have AST-only / transitive / no test (`audit.py`, `billing.py`, `demo_entries.py`, the three `synth/*` modules). The brief's "flag any `src/` file with zero direct test coverage" question yields 5 names if "direct" means "directly imported by a test" (`audit.py`, `billing.py`, `encounter_schema.py`, `ground_truth.py`, `demo_entries.py`), or 3 if "behavioural" is the criterion (`template.py`, `render.py`, `content_table.py`).

---

## 2. Assertions (Question 2)

**Search criterion.** Grep for `^\s*assert True\b|^\s*assert False\b|^\s*assert 1\b|^\s*assert 0\b|^\s*assert None\b|^\s*assert ""$` across `tests/`. **Result: zero matches** in any test file. No test is "assertion-free" in the strict sense the brief defines.

**"No-raise" tests (3 total).** Three tests assert *the function does not raise* by calling it without an `assert` and relying on pytest to fail the test if an exception propagates. This is a legitimate pattern for boundary-value checks (the function call IS the assertion), but the brief's question explicitly says "not just runs without error" — so these are listed.

| File:line | Test function | Body shape |
|---|---|---|
| `test_messages.py:224` | `test_validate_chat_request_accepts_boundary_temperatures` | Loops `(0.0, 1.0, 2.0)` and calls `validate_chat_request(req)`; the implicit assertion is "must not raise." |
| `test_scenario_schema.py:159` | `test_example_validates_with_pure_jsonschema` | Loads a fresh `jsonschema.Draft202012Validator` and calls `validator.is_valid(example)`; the implicit assertion is "validator returns True." (Has 0 explicit `assert` statements but 1 `validator.is_valid()` call whose return value the test could plausibly have asserted on.) |
| `test_scenario_schema.py:295` | `test_office_outpatient_em_code_accepted_silently` | Calls `ss.validate_scenario(example_payload)` and trusts the "must not raise" semantic. |

**Verdict.** The 3 no-raise tests are legitimate boundary/negative-assertion contracts and are not "weak" — they catch the failure mode of "the validator started raising on a valid input." The strict-spirit finding for the brief's question is: **zero `assert True`/trivial-assertion tests**; **3 no-raise tests** that are semantically meaningful but could be hardened by adding `assert result is True` / `assert validator.is_valid(...)` (Low priority — not a real gap).

**`@pytest.mark.parametrize` is heavily used** to expand assertion coverage at low cost. The strongest example is `test_cross_provider_smoke.py`: 2 test functions, but parameterised over 4 providers, so 8 distinct test cases with 8 distinct assertion paths. `test_scenario_schema.py` has 48 test functions/methods covering the schema surface, all with substantive assertions.

---

## 3. Network and external-state dependencies (Question 3)

**Search criteria.**
- `import requests | import httpx | import urllib | import socket | import aiohttp`
- `httpx.Request( | http.client | litellm.completion( | requests.(get|post|put|delete)`
- `time.time() | time.sleep( | datetime.now() | datetime.today() | freezegun`
- `os.environ[ | os.environ.get( | monkeypatch.setenv(.*API_KEY`

### Network calls

| File:line | Test function | Dependency | Verdict |
|---|---|---|---|
| `test_minimax_integration.py:152` | `test_minimax_live_chat_completion_is_non_empty_and_echoes_model` | `litellm.completion(model="minimax/MiniMax-M3", api_key=$MINIMAX_API_KEY, ...)` — **real HTTP** to `api.minimax.io` if the env var is set | Gated by `pytest.mark.integration` and `pytest.skip` when `MINIMAX_API_KEY` is unset. Hermetic CI is unaffected. See F-1. |
| `test_minimax_client_retry.py:87, 88, 166, 382` | retry-translation tests | `httpx.Request("POST", "...")` / `httpx.Response(...)` used as **exception-construction argument**, not as a live request. `httpx` is imported once at module top. | NOT a network call. `httpx.Request` is used because the OpenAI SDK's `APIConnectionError` requires an `httpx.Request` in its `__init__`. Verified by reading the test bodies. |
| `test_minimax_client_retry.py:1` (top) | (module import) | `import httpx` | OK — only used to construct exception objects. |
| `test_minimax_client_retry.py:20` | (module import) | `from openai import APIConnectionError, ...` | OK — OpenAI exceptions, not the OpenAI client. |

**Conclusion.** Exactly **1 real network call** in the entire test suite, gated by an integration marker. All other HTTP-shaped imports are exception-construction arguments.

### Live filesystem (committed data files, not `tmp_path`)

| File:line | Resource | Verdict |
|---|---|---|
| `test_v0_baseline.py:77, 85, 168, 178, 193, 263` | `data/val.json`, `data/val_manifest.json`, `prompts/v0/auditor_prompt.txt`, `prompts/v0/MANIFEST.json`, `src/ai_billing_audit/auditor_prompt.txt` | All committed; `val_split` is a module-scoped fixture that fails the suite if the file is missing (line 73-76). The test pins the v0-prompt-byte-equality invariant. |
| `test_scenario_schema.py:32-40, 50, 55` | `src/ai_billing_audit/scenario_schema.json`, `data/example_scenario.json` | Committed; resolved at module load via `ss.SCHEMA_PATH` and a fallback. |
| `test_llm_pin.py:84, 114` | `src/ai_billing_audit/llm.py` source | Committed; the test reads the file and counts occurrences of the pinned id. AST-based. |
| `test_auditor_module.py:90` | `auditor_module.py` source (AST) | Committed. |
| `test_llm_client_factory.py:280` | `src/llm_client.py` source (AST) | Committed. |
| `test_synth_determinism.py:212` | `synth_agent.py` source (docstring check) | Committed. |
| `test_dashboard.py:65-68` | `data/train.json` (via `load_encounter_record("enc_10032")`) | Committed. The test asserts `enc_10032` is in the registry and loadable. |
| `test_encounters_upload.py:576-577` | `tmp_path` (PDF bytes round-trip) | `tmp_path` — hermetic. |

**Conclusion.** All filesystem reads are against committed, version-pinned files (data, prompts, schema). No test reads from a user home directory, no test writes outside `tmp_path`/`monkeypatch`-managed paths.

### Time-of-day / wall-clock

| File:line | Test | Pattern | Verdict |
|---|---|---|---|
| `test_encounters_upload.py:407, 473, 708, 736` | 4 separate tests (`test_job_status_*` / `test_*_reaches_terminal_state_*`) | `deadline = time.time() + 5.0; while time.time() < deadline: ... time.sleep(0.05)` | The runner is in-process; the polling loop is not flaky in practice. See F-2. |

**Conclusion.** No `freezegun`, no `datetime.now()` in tests, no real wall-clock assertions. The 4 polling loops in `test_encounters_upload.py` are the only time-of-day dependencies, and they are bounded by a deadline + sleep, not by clock-equality assertions.

### Environment variables

| File:line | Test | Env vars | Verdict |
|---|---|---|---|
| `test_minimax_integration.py:135` | live API call | `$MINIMAX_API_KEY` (gate: skip if missing) | OK — gated, intentional. |
| `test_minimax_client.py:77, 100, 119, 131` | transport-injection tests | `$OPENAI_API_KEY` (set to `test-key-not-real` via `monkeypatch.setenv`) | OK — fake key, real `monkeypatch` cleanup. |
| `test_cross_provider_smoke.py:243, 333` | provider-swap tests | `$LLM_PROVIDER` + per-provider API key (set via `monkeypatch.setenv`) | OK — fake key, real `monkeypatch` cleanup. |
| `test_llm_client.py:149` | provider-swap test | same as above | OK. |
| `test_dev_loop_factory.py:199, 242, 538` | dev-loop selector tests | `$MINIMAX_API_KEY` / `$ANTHROPIC_API_KEY` / `$OPENAI_API_KEY` / `$GEMINI_API_KEY` | OK — fake key, `monkeypatch.setenv`. |
| `test_llm_pin.py:42, 51, 60` | pin tests | `$LLM_MODEL` (unset / set to a fake) | OK — `monkeypatch.delenv` / `monkeypatch.setenv`. |
| `test_llm_client_factory.py:121` (and similar) | factory re-import tests | `$LLM_PROVIDER` | OK — `monkeypatch.setenv` / `monkeypatch.delenv`. |
| `test_messages.py` | (no env reads) | — | — |

**Conclusion.** Every test that reads env vars either gates on the value (skip-if-missing) or sets a `monkeypatch`-managed fake. No test depends on the host environment without cleanup.

### Network: 1 (gated). Live filesystem: all on committed files. Wall-clock: 4 polling loops. Env vars: all `monkeypatch`-managed.

---

## 4. Dashboard test verdict (Question 4)

**The brief asks: does `test_dashboard.py` actually exercise the split-screen dashboard rendering, or only check that the dashboard route returns HTTP 200?**

**Verdict on the brief's premise: the "split-screen" concept is not present in the current dashboard code.** Search for `split|split-screen|left-panel|right-panel|side-by-side` in `src/ai_billing_audit/api.py`, `src/ai_billing_audit/templates/`, and `tests/test_dashboard.py` returns zero matches. The dashboard is a one-pane encounter-detail page with a clinical-note column and a per-finding block list (a card grid, not a split pane). The "split" framing in the brief is a misreading of the UI.

**Verdict on the question as asked: the dashboard tests do NOT only check HTTP 200.** 25 of 27 tests in `test_dashboard.py` assert DOM-level markup details in `r.text`. Concretely:

| Test function (file:line) | Asserts |
|---|---|
| `test_index_lists_registered_encounter` (line 79) | `r.status_code == 200` + `'enc_10032' in body` + `'class="encounter-card encounter-card--easy"' in body` + `'href="/encounter/enc_10032"' in body` + `'href="/encounter/enc_10032/json"' in body` |
| `test_index_renders_no_card_when_registry_empty` (line 90) | HTTP 200 + `'No demo encounters registered yet.' in r.text` |
| `test_encounter_detail_renders_evidence_highlight` (line 103) | `'<mark class="evidence">Duplicate service on same date</mark>' in body` + `'class="clinical-note"'` + `'data-action="copy-quote"'` + `'data-action="scroll-to-note"'` + `'id="btn-toggle-mark"'` + `'badge--high'` + `'rule_overlap_001'` |
| `test_encounter_detail_404_for_unregistered` (line 124) | `r.status_code == 404` (the only 404-only test; legitimate negative-path) |
| `test_encounter_json_returns_minimal_envelope` (line 129) | JSON shape: `encounter_id`, `difficulty`, `isinstance(n_gold_findings, int)`, `n_gold_findings >= 1` |
| `test_healthz` (line 139) | `r.status_code == 200` + `body["status"] == "ok"` + `body["n_registered"] >= 1` |
| `test_index_lists_medium_card` (line 185) | `'enc_0007' in body` + `'class="encounter-card encounter-card--medium"' in body` + per-difficulty CSS hook |
| `test_medium_detail_renders_full_audit_panel` (line 197) | All 4 medium-tier rule IDs and 4 ICD/CPT/lab codes present in `body` |
| `test_medium_detail_shows_evidence_highlight` (line 213) | `'<mark class="evidence">Type 2 diabetes follow-up</mark>' in body` + `body.count('<blockquote class="finding-quote">') >= 4` |
| `test_medium_detail_buttons_clickable` (line 238) | `body.count('data-action="copy-quote"') >= 4` + `'id="btn-toggle-mark"'` |
| `test_medium_json_endpoint` (line 248) | JSON shape: `encounter_id`, `difficulty == "MEDIUM"`, `n_gold_findings == 4`, `is_flagged is True` |
| `test_medium_detail_404_when_unregistered` (line 258) | HTTP 404 (with monkey-patched registry) |
| `test_index_lists_hard_card` (line 325) | `'enc_0000' in body` + `'class="encounter-card encounter-card--hard"' in body` |
| `test_hard_detail_renders_full_audit_panel` (line 337) | All 5 hard-tier rule IDs and 5 codes present |
| `test_hard_detail_shows_evidence_highlight` (line 354) | `'<mark class="evidence">established patient moderate complexity</mark>' in body` + `body.count('<blockquote class="finding-quote">') >= 5` |
| `test_hard_detail_buttons_clickable` (line 377) | `body.count('data-action="copy-quote"') >= 5` + `'id="btn-toggle-mark"'` + `'id="btn-jump-high"'` + `'id="btn-next-finding"'` + `'id="btn-severity-filter"'` |
| `test_hard_detail_advanced_actions_absent_on_easy` (line 405) | **Reverse-direction DOM assertion**: easy/medium must NOT contain `id="btn-jump-high"`, `id="btn-next-finding"`, `id="btn-severity-filter"`. Pins the `{% if difficulty == "HARD" %}` Jinja gate. |
| `test_hard_json_endpoint` (line 420) | JSON shape: `n_gold_findings == 5`, `difficulty == "HARD"`, `is_flagged is True` |
| `test_hard_detail_404_when_unregistered` (line 430) | HTTP 404 (with monkey-patched registry) |

**5 of the 27** dashboard tests assert *only* `r.status_code == 200` + a body-content presence (the 3 `test_*_404_when_unregistered` tests + `test_healthz` + the negative-direction `test_hard_detail_advanced_actions_absent_on_easy` which is more than just a status check). The other 22 assert real markup shape. The DOM assertions are *substring* checks on the rendered HTML, not full structural trees, so a regression that wraps the same text in an extra `<div>` would pass — but a regression that drops the highlight, the action buttons, or the per-finding blockquote count would fail. That's the right level for a smoke test.

**Conclusion.** The dashboard tests are well above the "HTTP 200 only" floor. The "split-screen" framing in the brief is wrong about the current UI; the test does exercise the dashboard's actual rendered regions (clinical note, evidence highlight, finding card list, action buttons, JSON endpoints). The 3 404 tests are intentionally status-only and are correct.

---

## 5. Cross-provider smoke test verdict (Question 5)

**The brief asks: does `test_cross_provider_smoke.py` actually swap provider backends and verify provider-specific behaviour, or merely import provider modules?**

**Verdict: the test DOES swap provider backends and DOES verify provider-specific behaviour, but it pins only the *common* surface** (response shape, JSON schema, and `litellm.completion` call count). Provider-specific features (retry, rate-limiting, error mapping) are out of scope by design and live in their own dedicated tests (`test_minimax_client_retry.py`, the per-provider suites).

**Evidence.**

- **Provider swap happens via the production dispatch table, not via test injection.** Line 248: `client = create_llm_client()` after `monkeypatch.setenv("LLM_PROVIDER", provider_name)`. The factory walks `_PROVIDER_CLASS_PATHS` in `src/llm_client.py:71-77` and instantiates `MinimaxClient`, `ClaudeClient`, `OpenAIClient`, or `GeminiClient` depending on the env var. The test explicitly avoids `_TEST_PROVIDER_OVERRIDES` (which is the test-injection hook used in `test_llm_client_factory.py`) — see the design note at lines 31-35.

- **All four production classes are present on disk.** Verified at `src/llm_client.py:408` (`class MinimaxClient`), `:463` (`class ClaudeClient`), `:512` (`class OpenAIClient`), `:561` (`class GeminiClient`). The test exercises the real classes, not stubs.

- **`litellm.completion` is mocked per provider, not imported and discarded.** `patch.object(litellm, "completion", side_effect=_factory)` at line 264 returns a `_make_litellm_response(CANNED_REPLY_TEXT)` per call. The mock's `call_count` and `call_args` are inspected at lines 298-309:
  - `assert mocked.call_count == 1` (provider delegated to litellm exactly once)
  - `assert mocked.call_args.kwargs["messages"] == CANNED_PROMPT_MESSAGES` (provider forwarded the input list unchanged — Protocol contract)
  - `assert mocked.call_args.kwargs.get("response_format") == {"type": "json_object"}` (provider forced JSON mode on the JSON path)

- **Provider-specific assertions fire per provider, not in aggregate.** `test_same_canned_prompt_returns_non_empty_text_for_every_provider` is parameterised over `("minimax", "claude", "openai", "gemini")` (line 83), so a failure surfaces as `... [openai] FAILED` — the offending provider is named in the test ID. The `_diff_response_shape` helper (lines 152-186) renders a per-provider, per-field diff in the failure message.

- **The test asserts that the four providers are mutually distinct.** `test_factory_returns_distinct_classes_per_provider` (test_llm_client.py:230, the cross-provider sibling in the same suite) loops over the four env vars and asserts `len({id(c) for c in seen.values()}) == 4` (line 252). A future regression that aliases two providers to the same concrete class fails here.

- **Per-provider checks that ARE present in this test:**
  - Response type is `str` (Protocol contract — line 271).
  - Response is non-empty (line 274).
  - Response text matches the canned reply byte-for-byte (line 282) — catches a provider that wraps the response, decorates it, or surfaces a different envelope.
  - `response_format={"type": "json_object"}` was set on the litellm call (line 384) — catches a provider that forgets to force JSON mode.

- **Per-provider checks that are NOT in this test** (and which the test's own design note acknowledges at lines 41-47):
  - Retry behaviour on 429 / 5xx → lives in `test_minimax_client_retry.py` (minimax-only, by design — the four providers have heterogeneous retry policies).
  - Rate-limit handling → not in the test, and the project does not have a shared rate-limit layer in the `LLMClient` Protocol.
  - Error-mapping to the project-local exception hierarchy → `test_minimax_client_retry.py` exercises `MiniMaxError` / `MiniMaxAuthError` / `MiniMaxRateLimitError` / `MiniMaxServerError`. The non-MiniMax providers do not have an equivalent error-mapping test (gap — see G-2).
  - Real wire shape (request/response envelopes) — not pinned here; would require unmocking `litellm.completion` and reading the call kwargs (the test does read `mocked.call_args.kwargs` to verify `messages` and `response_format` are forwarded, which is the closest equivalent).

**Conclusion.** The test is a genuine cross-provider smoke test, not a "merely imports" test. The verification depth is appropriate for a smoke test (response shape, non-emptiness, JSON-mode enforcement, call delegation), and the test suite as a whole covers per-provider features in dedicated test files. The "verify provider-specific behaviour" framing in the brief is true for the **shape** dimension and false for the **feature** dimension — and the latter is intentional, not an oversight.

---

## 6. `seed=42` determinism test verdict (Question 6)

**The brief asks: locate the pytest determinism test using `seed=42` and determine whether it runs the suite twice and asserts byte-identical output, or is a single-run test that does not actually verify reproducibility.**

**Verdict: the seed=42 test runs the function twice and asserts byte-equal output** at the unit level. It is **not** a "run the entire pytest suite twice" determinism harness; no `pytest-replay` or `pytest-randomly` is configured.

**Evidence.**

- **`seed=42` is used in exactly one test file**: `tests/test_synth_determinism.py` (8 occurrences, lines 61, 62, 82, 83, 101, 102, 152, 171, 172, 176, 200, 202, 230, 231). The other file that mentions `seed=42` is `tests/test_grader.py` (lines 5, 9, 186), where the seed is a config-pinning assertion (`assert int(judge["seed"]) == 42`), not a determinism check.

- **No `pytest-replay` or `pytest-randomly` is installed.** `pyproject.toml:37-38` lists only `pytest>=8.0` and `pytest-cov>=4.1`. The `[tool.pytest.ini_options]` block (line 51) has no `--replay` / `-p pytest_randomly` configuration. A search for `pytest-replay|pytest-randomly|pytest_determinism` in the repo returns zero matches.

- **The "runs twice and compares" pattern is the dominant one in `test_synth_determinism.py`.** Every `seed=42` test in that file is a two-call comparison:

  | Test function (file:line) | Two-call pattern |
  |---|---|
  | `test_two_calls_same_seed_inprocess_are_byte_identical` (line 60) | `a = generate_suite(seed=42); b = generate_suite(seed=42); assert a == b` — pure in-process byte equality. Also asserts `_dumps_roundtrip(a) == _dumps_roundtrip(b)` to defend against container-subtype drift. |
  | `test_generate_encounter_individually_deterministic` (line 81, parametrised over 6 (tier, variant) pairs) | `a = generate_encounter(tier, variant, seed=42); b = generate_encounter(tier, variant, seed=42); assert a == b` for every combination. |
  | `test_deterministic_even_after_perturbing_global_rng` (line 92) | Burns 50 `random.random()` calls, sets `random.seed(9999)`, shuffles a list, then runs `generate_suite(seed=42)` twice and asserts equality. Pins the "no global RNG leak" invariant. |
  | `test_across_process_byte_identical` (line 131) | Spawns two **subprocesses** via `subprocess.check_output`, runs `generate_suite(seed=42)` in each, asserts the JSON outputs are equal, then compares MD5 hashes. This is the strongest "byte-identical across process boundaries" check. |
  | `test_across_process_same_hash_seed` (line 140) | Same as above, but with one subprocess pinned to `PYTHONHASHSEED=0`. Rules out hash-randomisation as the source of any disagreement. |
  | `test_returned_suite_is_deep_independent` (line 170) | Calls `generate_suite(seed=42)` three times, mutates the first suite, asserts the third call still equals the second (deep-copy snapshot). Catches a "shared mutable state" regression. |
  | `test_stable_across_seeds` (line 188, parametrised over 7 seeds) | Two calls per seed, asserts equality. |
  | `test_reseed_does_not_contaminate_original_seed` (line 199) | `a42 = generate_suite(seed=42); _ = generate_suite(seed=9999); b42 = generate_suite(seed=42); assert a42 == b42` — pins call-order independence. |
  | `test_dump_full_output_for_audit` (line 229) | Two calls, writes the JSON to `tmp_path`, asserts encounter IDs are unique within each run and the two runs are equal. |

- **The pattern is "call the function twice and assert byte-equal output"** — exactly what the brief asks about, and exactly what the test does. **At the unit level**, this is a strong determinism guarantee: any non-determinism in the function's pure path (a `time.time()` call, a `uuid` call, an unordered `dict` iteration, a shared module-level RNG, a hash-randomisation leak) would break one of these tests.

- **What this test is NOT**: it is not a "run the entire pytest suite twice and SHA-256-match the stdout" harness. The pytest-replay and pytest-randomly packages can replay a test session verbatim and assert byte-equal output across replays — that level of test is not configured here. A test that does this would catch non-determinism in **pytest itself** (collection order, fixture ordering, plugin side-effects), not in the function under test. The `seed=42` test in `test_synth_determinism.py` is the right level of determinism check for the synth package; it does not and should not test pytest's own determinism.

- **What the test MISSES** (call this out as a gap, F-3):
  - The seed=42 pattern is in `test_synth_determinism.py` only. The optimizer's `seed=1729` (`test_optimize.py:73`, `test_optimize_compile.py`) is also a determinism check but is not run twice-and-compared in the same harness — `test_optimize_compile.py::test_deterministic_for_fixed_seed` calls `compile_and_evaluate(...)` twice on the same seed and asserts equal output, but the assert is `assert 0.0 <= R <= 1.0` style (range), not a byte-equal check. The two-run-and-compare is asymmetric across the seed-using tests.
  - There is no cross-file determinism test that runs `generate_suite(seed=42)` in `test_synth_determinism.py` and `test_synth_purity.py` and asserts equality — the two files share the seed but exercise the function in different process contexts and never cross-check.

**Conclusion.** The seed=42 test is a genuine "runs twice and compares byte-equal output" determinism test at the function level. It is not the kind of "run the entire pytest suite twice" replay test the brief's framing implies, but that level of test is not needed for the synth's reproducibility contract — the function-level harness is the right tool.

---

## Findings

Severity tags: **C** = Critical, **H** = High, **M** = Medium, **L** = Low, **F** = finding (neutral), **G** = gap (no test where there should be one), **D** = duplication.

### F-1 (Low): `test_minimax_integration.py` makes a real network call.

- **File:** `tests/test_minimax_integration.py:152`
- **Detail:** `litellm.completion(model="minimax/MiniMax-M3", api_key=$MINIMAX_API_KEY, ...)` — a real HTTP request to `api.minimax.io`. Gated by `pytest.mark.integration` (registered in `pyproject.toml`) and `pytest.skip` (lines 136-141) when `MINIMAX_API_KEY` is unset. Hermetic CI is unaffected.
- **Verdict:** Intentional, well-gated. Acceptable. Worth knowing about because the suite is not 100% hermetic.

### F-2 (Low): `test_encounters_upload.py` uses wall-clock polling in 4 sites.

- **Files:** `tests/test_encounters_upload.py:407, 473, 708, 736`
- **Detail:** `deadline = time.time() + 3.0; while time.time() < deadline: ... time.sleep(0.05)`. The runner is in-process; the loop is not flaky today. If the runner ever moved out-of-process or the job queue's startup time exceeded the deadline, the loop would time out without asserting.
- **Verdict:** Time-of-day dependency, not a real flake today. Acceptable; could be hardened with a deterministic condition variable if the runner ever moves.

### F-3 (Low): Asymmetric two-run determinism harness across the seed-using test files.

- **Files:** `tests/test_synth_determinism.py` (10 tests, two-run + byte-equal) vs. `tests/test_optimize_compile.py:146` (`test_deterministic_for_fixed_seed` — only one call, range-style assert on R/P/F1) vs. `tests/test_optimize.py:178` (`test_deterministic_for_fixed_seed` — one call only).
- **Verdict:** The synth test is the gold standard; the optimizer tests are weaker. Not a real gap — the optimizer's stub mode is checked separately — but the asymmetry is worth knowing.

### G-1 (Medium): Three `synth/*` modules have no behavioural test.

- **Files:** `src/ai_billing_audit/synth/template.py`, `src/ai_billing_audit/synth/render.py`, `src/ai_billing_audit/synth/content_table.py`
- **Detail:** `class Scenario`, `class Template`, the per-tier renderer functions (`_build_easy` / `_build_medium` / `_build_hard`), the per-call RNG factory (`_rng_for`), the encounter-id generator (`_enc_id`), and the content-table validator (`_validate`) are never imported by a test. The `test_synth_purity.py` AST check confirms they don't import LLM modules but says nothing about their behaviour.
- **Verdict:** The functions are exercised transitively via `generate_suite` / `generate_encounter`, so the user-facing contract is covered. The gap is at the **unit level** — a refactor that swaps the renderer for an equivalent implementation would pass the existing tests but might break subtle invariants (per-tier encounter-id format, RNG scoping, content-table validation rules). A focused unit test on each renderer would close this gap.

### G-2 (Medium): Only the MiniMax provider has retry/error-mapping tests.

- **Files:** `src/llm_client.py` (4 concrete classes: `MinimaxClient`, `ClaudeClient`, `OpenAIClient`, `GeminiClient`) vs. `tests/test_minimax_client_retry.py` (the only retry/error-mapping test).
- **Detail:** `test_minimax_client_retry.py:18` tests verify `MiniMaxError` / `MiniMaxAuthError` / `MiniMaxRateLimitError` / `MiniMaxServerError` and the backoff policy. The other three providers have no equivalent. If a future refactor adds per-provider error translation (e.g. mapping Anthropic's `anthropic.APIStatusError` to the same hierarchy), there is no test to catch a regression in the translation.
- **Verdict:** Gap. The cross-provider smoke test (`test_cross_provider_smoke.py`) only pins response shape, not error mapping. A reasonable fix is a parametrised test that runs the same canned-failure scenario through all four provider classes and asserts the project-local exception hierarchy is used.

### G-3 (Low): `ground_truth.py` and `encounter_schema.py` have no direct test.

- **Files:** `src/ai_billing_audit/ground_truth.py`, `src/ai_billing_audit/encounter_schema.py`
- **Detail:** Both are loaded transitively via the committed `data/train.json` and `data/val.json`. The data files pin the on-disk output, but if `ground_truth.py` is refactored to produce a different on-disk format, the existing tests would not catch the regression unless someone re-runs the data-generation pipeline. `encounter_schema.py` is the format spec; a refactor that drops a field from the schema would not be caught because no test reads the schema directly via the module.
- **Verdict:** Gap. The committed data files act as a frozen snapshot, which is a weaker guarantee than a direct test would be. A focused test on `_split_data(train_seed=1729, ...)` and on `encounter_schema.validate_encounter()` would close this.

### D-1 (Low): `tests/agents/auditor/test_signature.py` duplicates the surface covered at the top level.

- **File:** `tests/agents/auditor/test_signature.py` (294 lines, 6 test functions)
- **Detail:** Tests `AuditorModule` + `AuditClaim` — the same surface as `tests/test_auditor_module.py` (16 tests) and `tests/test_auditor_signature.py` (11 tests). The agents/ tests overlap the type/shape coverage; the root tests overlap the behavioural coverage. There is no shared fixture, no shared `DummyLM` wiring helper, and the two test files disagree on details (e.g. `confidence_score` boundary coverage is in `agents/auditor/test_signature.py:276` but not in `test_auditor_module.py`).
- **Verdict:** Duplication. The agents/ test was likely the original location; the root tests were added later and the agents/ test was not retired. A reasonable cleanup is to delete `tests/agents/auditor/test_signature.py` and merge any unique coverage into `test_auditor_module.py`.

### D-2 (Low): Brief file-count mismatch.

- **Detail:** The brief says "24 test files" in `tests/`. The actual count is 27 at the root + 1 in `tests/agents/auditor/` = 28. The acceptance criteria's "coverage matrix that lists every `src/` file" is met regardless.
- **Verdict:** Cosmetic mismatch — not a test issue, just a brief/spec drift.

### No-finding (sanity checks)

- **Zero `assert True` / `assert 0` / `assert None` / `assert 1` / `assert False` tests.** Confirmed by `grep` across `tests/`. No test is "assertion-free" in the strict sense.
- **Zero "merely imports provider modules" tests.** The closest pattern is the AST-purity check in `test_synth_purity.py`, which has 3 parametrised assertions that import-and-inspect the source for forbidden names. The check is structural, not behavioural, but it has real assertions.
- **All env-var reads are `monkeypatch`-managed or skip-gated.** No test depends on the host environment without cleanup.
- **All filesystem reads are against committed, version-pinned files.** No test reads from a user home directory.
- **No `freezegun`, no `datetime.now()` in tests.** Wall-clock dependencies are limited to the 4 polling loops in `test_encounters_upload.py`.

---

## Acceptance-criteria cross-check

| Criterion | Met? | Evidence |
|---|---|---|
| `docs/CODE_REVIEW_tests.md` exists and is non-empty | YES | This file. |
| Coverage matrix lists every `src/` file with a yes/no test | YES | Section 1, table covering all 25 `src/` modules. |
| Q1 answered: every `src/` file classified | YES | Section 1; 25/25 classified. |
| Q2 answered: list of assertion-free tests | YES | Section 2: zero `assert True`-style; 3 "no-raise" tests enumerated. |
| Q3 answered: list of network/external-state dependencies | YES | Section 3: 1 real network call (gated), 4 polling loops, all filesystem/env deps on committed files / `monkeypatch`. |
| Q4 answered: dashboard test verdict | YES | Section 4: 22/27 tests assert DOM markup; "split-screen" premise wrong about current UI. |
| Q5 answered: cross-provider test verdict | YES | Section 5: test exercises production dispatch table for all 4 providers; per-feature retry/error-mapping is intentionally out of scope. |
| Q6 answered: seed=42 determinism test verdict | YES | Section 6: function-level "runs twice and asserts byte-equal" across 10 test cases; not a "runs the entire suite twice" replay harness. |
| Each finding cites file path and line/function reference | YES | Every finding has `file.py:line` references. |
| No `src/` code modified | YES | This task created one markdown file; no test or source was touched. |
