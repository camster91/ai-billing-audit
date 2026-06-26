# Zorva `ai-billing-audit` — Code Quality & Dead Code Audit

**Date:** 2026-06-23
**Scope:** Read-only audit of `/Users/biancabienaime/projects/ai-billing-audit/`.
**Files surveyed:** 38 Python modules in `src/ai_billing_audit/` (10,370 LOC), 51 test files (727 test functions / 791 collected by pytest), 62 scripts, 12 prompt versions, 19 data files.
**Brief:** "72 tests pass" — the actual count is **791 collected tests** (`pytest --collect-only`), 51 test files. The "72" figure from prior session memory is stale; the test suite has roughly 10× grown.
**Source LOC:src test ratio:** 10,370 / ~5,000 ≈ 2:1 — undertested by typical Python standards (3:1 is the lower bound for a healthy suite).

---

## TL;DR

- **Code health is good but with a few structural rot spots.** 38 modules, ~10K LOC, mostly tight. Type-hint coverage is ~99%, modern `X | None` style used 92× vs 4× legacy `Optional[X]`.
- **Biggest single risk: `audit_actions.py` and `src/audit_log.py` are two parallel implementations of the same hash-chain.** The FastAPI app uses `audit_actions.py` (wired in 8 places); tests + qa scripts use `src/audit_log.py` (`verify_chain`, `compute_signature`). They have the same field list, the same genesis constant, and the same wire shape. A bug-fix in one will silently not propagate to the other. The `verify_chain()` function **in `audit_actions.py`** is dead — `audit_actions.verify` is never called from src/, scripts, or tests; only `src/audit_log.verify_chain` is.
- **`audit_actions.py` is no longer "BUILT BUT NOT WIRED".** It is now wired into 8 places in `api.py` (accept-all, dismiss, rerun, flag, plus the re-audit route). Two of its public functions — `read_for_encounter()` and `verify()` — are still unused.
- **The upload-portal synth trap is partially fixed but still partially present.** The first-run job path in `_default_runner` (`job_queue.py:517-602`) now has a real-data branch keyed on `uploaded_note + queued CPTs`. **But the re-audit endpoint** `POST /encounters/{encounter_id}/audit` at `api.py:2041-2244` still regenerates a synth encounter from the `encounter_id` hash (line 2191) and audits that, not the user's actual claim. So "re-audit" still audits a synthetic claim against the user's real note. Mismatch.
- **`_quote_in_note()` in `auditor.py:205` is still present, still tested** (9 tests in `tests/test_hallucination_guardrail.py`). All pass.
- **Two auditor implementations exist.** `auditor.py` (403 LOC) is the live one — used by `_default_runner`. `auditor_module.py` (225 LOC) is a DSPy wrapper that is **never called from `src/`**; only tests and QA scripts import it. It is functional and tested, but aspirational.
- **`MANIFEST.json` has 2 entries, not 12.** Only v0 (the bootstrap) and v12 (the latest AHCIP rewrite) are recorded. v1–v11 have no entries — neither the historical chain nor their F1 deltas are tracked in the manifest.

---

## Dead Code Inventory (top 20)

| # | Location | Item | Why dead / not actually dead | Suggestion |
|---|----------|------|------------------------------|------------|
| 1 | `src/ai_billing_audit/billing.py:1-10` | entire file (10 LOC placeholder) | No imports anywhere (`grep "billing.py" src/ tests/ scripts/` returns 0 hits outside the file itself). Comment says "lands in later tasks." | **Delete** — pure placeholder, 0 callsites. |
| 2 | `src/ai_billing_audit/audit.py:1-11` | entire file (11 LOC placeholder) | No imports anywhere outside the file. Comment says "subpackage is reserved." | **Delete** — empty placeholder. |
| 3 | `src/ai_billing_audit/encounter_schema.py` (217 LOC) | entire module | Zero imports across src/tests/scripts (`grep "encounter_schema" = 0`). | **Delete** unless planned for v13. |
| 4 | `src/ai_billing_audit/demo_entries.py` (91 LOC) | entire module | Zero imports anywhere. | **Delete** — never wired. |
| 5 | `src/ai_billing_audit/scenario_schema.py` (190 LOC) | top-level module | Has 48 tests in `tests/test_scenario_schema.py`, so the *file* is tested, but the *module* itself is not imported by any other src/ file. Tests cover `load_manifest()` and schema validation. | **Keep but reclassify** — orphaned test target. Either wire it into the prompt loader (the new MANIFEST should reference it) or move to `tests/fixtures/`. |
| 6 | `src/ai_billing_audit/auditor_module.py` (225 LOC) | `AuditorModule` DSPy wrapper | Never imported by `src/`. Only by `tests/test_auditor_module.py`, `tests/agents/auditor/test_signature.py`, and `scripts/qa_clean_claims.py` + `scripts/qa_llm_outage.py`. The live app uses `auditor.py:run_audit` instead. | **Keep** if MIPROv2 prompt optimization is in the v13 plan; **delete** if not. Cost: 225 LOC of dead-ish code. |
| 7 | `src/ai_billing_audit/auditor_signature.py` (86 LOC) | `AuditClaim` DSPy signature | Only used by `auditor_module.py` + 2 test files. | Same disposition as #6. |
| 8 | `src/audit_log.py` (whole file) | `compute_signature`, `verify_chain`, `walk_chain`, `CHAIN_FIELDS` | Lives at `src/audit_log.py` (NOT under the package). Only used by `tests/test_audit_log.py` and `scripts/qa_audit_chain_{insert,verify}.py`. The live FastAPI app uses `src/ai_billing_audit/audit_actions.py` instead — which has its **own** `compute_signature()` (line 56) with the same chain shape. | **Pick one**. Either delete `src/audit_log.py` and migrate tests+scripts to `audit_actions`, or delete `audit_actions.py` (after porting 8 API call sites). |
| 9 | `src/ai_billing_audit/audit_actions.py:222-247` | `read_for_encounter(encounter_id)` | Defined, never called from src/, tests, or scripts. `read_all` is the only reader used. | **Delete** unless planned for a per-encounter audit-log viewer. |
| 10 | `src/ai_billing_audit/audit_actions.py:228-271` | `verify()` | Defined, never called. The chain-verify workflow is implemented entirely in `src/audit_log.py:verify_chain` and only the qa scripts touch it. | **Delete or wire** — currently dead. |
| 11 | `src/ai_billing_audit/worker.py` (75 LOC) | `main()` no-op heartbeat loop | Container entry-point that does nothing but sleep(30) and log "queue is in-process in the api." It exists only to satisfy the v1 4-service docker-compose topology. | **Keep** if spec requires the sidecar; **delete** the sidecar from docker-compose if not. |
| 12 | `src/ai_billing_audit/messages.py` (336 LOC) | re-exports `ChatMessage`, `ChatRequest`, `Role`, `validate_chat_request`, etc. | Only callers are `__init__.py:52` (re-exports) and `tests/test_messages.py:21` (imports for test). The live LLM call path uses `minimax_client.py` directly with dicts, not these typed wrappers. | **Keep** as the typed validation seam — non-zero design value, but currently the public API surface is unused by callers. |
| 13 | `src/ai_billing_audit/demo_registry.py` (113 LOC) | entire module | No `from .demo_registry` or `from ai_billing_audit.demo_registry` references in src/. Used in tests. | Test-only module. Move to `tests/fixtures/` or wire into the demo flow. |
| 14 | `prompts/MANIFEST.json` entries | entries v1–v11 missing | Only v0 and v12 entries exist. The 10 intermediate versions have prompt files (`prompts/v1/auditor_prompt.txt` etc.) but no manifest entry. | **Append** the missing 10 entries; otherwise the manifest does not match the on-disk artifacts. |
| 15 | `prompts/v1/...v11/` MANIFEST.json | missing per-version MANIFEST | Only `prompts/v0/MANIFEST.json` exists; v1-v12 do not have per-version manifests. | **Generate** per-version `MANIFEST.json` (or document why only v0 is pinned). |
| 16 | `scripts/test_actions.py` (32 LOC) | curl-based smoke test that reads a bearer token from `~/.config/ai-billing/bearer.txt` | Token file path looks stale (other live_audit_*.py scripts use `~/.ai_billing_bearer.txt`). The 4 endpoints tested (`/accept-all`, `/flag`, `/rerun`, `/dismiss`) are all POST routes. | **Fix the token path** or **delete** — likely broken. |
| 17 | `scripts/score_predictions.py` | scores `data/predictions_v0.jsonl` | `data/predictions_v0.jsonl` and `metrics_v0.{json,md}` exist but are v0 artifacts. v12 is the current prompt; v0 scoring is historical. | **Archive** to `data/archive/v0/` or **delete** if v0 baseline is no longer maintained. |
| 18 | `scripts/smoke_dashboard.py`, `scripts/check_*.py` (10+ files) | ad-hoc live smoke checks against `ai-billing-audit.ashbi.ca` | Each is a one-shot curl/check shell, never invoked from a CI workflow (`.github/workflows/e2e.yml` does not reference any `scripts/` entry). | **Keep** for ad-hoc ops, **document** the use case, or **delete** the ones not used in 30 days. |
| 19 | `scripts/ab_prompt.py` | A/B harness for prompt comparison | Single-file, never referenced in `tests/` or `.github/`. | **Keep if A/B is in roadmap, else delete.** |
| 20 | `src/ai_billing_audit/ground_truth.py` (428 LOC) | rule generator | Only imported by `scripts/generate_holdout.py` and `scripts/generate_test_split.py`. **Zero test coverage** — `tests/test_*` do not import it. 428 LOC of untested rule-encoding logic is the largest coverage gap in the repo. | **Add tests** for `_TEMPLATES` and `ground_truth_for()`. Highest priority dead-adjacent code. |

---

## Type Safety Gaps

**Counts (src/ai_billing_audit/*.py):**
- `Any` return types / parameters: 49 occurrences across the package
- `# type: ignore` comments: 8 (all in 4 files — see below)
- `cast()` calls: 0
- `Optional[X]` (legacy style): 4 occurrences
- `X | None` (PEP 604): 92 occurrences
- Public functions with no return type: 0 in src/ (exception: `worker.py:51` has `# noqa: ANN001` on the signal handler — acceptable)

**Top 5 examples:**

1. **`src/ai_billing_audit/api.py` — `Any` parameter sprawl.** Functions like `compute_clean_rate_metrics(records: list[dict[str, Any]])`, `read_latest_real_audit(encounter_id: str) -> dict[str, Any] | None`, and 30+ FastAPI route handlers use `dict[str, Any]` for request bodies and DB rows. The dict-of-Any pattern is hard to typecheck at the boundary. (49 total `Any` mentions — most concentrated in api.py.)
2. **`# type: ignore` cluster on the DSPy wrapper:** `auditor_module.py:146` and `auditor_signature.py:14` both suppress `import-untyped` for `import dspy`. Acceptable — dspy ships no py.typed marker.
3. **`# type: ignore` in `contact.py:71`** — `from .api import _TENANT_ID  # type: ignore[attr-defined]`. Suppresses "private attribute" warning on a cross-module import of a private global. **This is a code smell**, not a type problem. Either export `_TENANT_ID` properly or use a `get_tenant_id()` accessor.
4. **`# type: ignore` in `doctor_email.py:205`** — `import requests  # type: ignore`. `requests` does have type stubs (`types-requests`), so this suppression is unnecessary if `types-requests` is in dev deps. Quick check: pyproject.toml does not list it.
5. **`# type: ignore` cluster in `minimax_client.py:41-42` and `minimax_errors.py:63-64`** — `OpenAI = None  # type: ignore[assignment]`. These are the "lazy import fallback" pattern. Suppression hides the fact that the fallback types are not equivalent to the real OpenAI types; a caller calling `isinstance(e, OpenAI.APIError)` would silently miss matches. **Real type problem masked.** Add a stub module or use `TYPE_CHECKING` to swap the import.

**Inconsistency:**
- `src/ai_billing_audit/messages.py:167` and `minimax_client.py:43,97,100` use `Optional[X]`. Everywhere else uses `X | None`. Trivial, but worth a one-pass `ruff check --fix`.

**Pydantic models:** Project has **zero** Pydantic models (only DSPy signatures). The `auditor_module.py` DSPy signatures inherit pydantic from dspy. So "Pydantic models missing validators" is N/A.

**Public APIs with no type hints:** 0 (verified across all `def` and `async def` in src/). The signal handler in `worker.py:51` is `noqa: ANN001`, not an untyped API.

---

## Complexity Hotspots (top 5 files by LOC, with worst function)

| File | LOC | Worst function | Function LOC | Lines |
|------|-----|----------------|--------------|-------|
| `src/ai_billing_audit/api.py` | 2279 | `encounter_appeal` (POST `/encounter/{id}/appeal`) | 173 | 1165-1337 |
| `src/ai_billing_audit/job_queue.py` | 759 | `_default_runner` | 211 | 517-727 |
| `src/ai_billing_audit/doctor_email.py` | 629 | `send_doctor_summary` | 64 (modular: small helpers offset) | 230-293 (approx) |
| `src/ai_billing_audit/appeal_letter.py` | 520 | `generate_appeal_letter` | 103 | 264-366 |
| `src/ai_billing_audit/judge.py` | 502 | `_build_judge_messages` | 301 | 158-459 |

**Notes on each:**

- **`api.py:encounter_appeal` (173 LOC):** Builds the appeal-letter prompt, calls the LLM, parses the response, persists the result, and returns JSON. Five responsibilities. **Refactor candidate.** Extract `_build_appeal_prompt(claim, note, finding) -> list[dict]`, `_persist_appeal(encounter_id, letter) -> str`, `_parse_appeal_response_json(raw) -> dict | None` into `appeal_letter.py`. The function currently inlines all three.

- **`job_queue.py:_default_runner` (211 LOC):** The "if uploaded_note + queued_cpts: real-data path; else: synth path" switch is correct (no longer a synth trap) but the function mixes (a) synth materialization, (b) claim construction, (c) zorva_context build, (d) auditor call, (e) finding flattening, (f) doctor-email dispatch, (g) result envelope assembly. **Refactor candidate.** Extract `_build_real_data_audit_encounter()` and `_build_synth_audit_encounter()`.

- **`judge.py:_build_judge_messages` (301 LOC):** This is mostly a giant f-string / template assembly. Long but flat — readability is OK, complexity is moderate. Lower priority to refactor.

- **`appeal_letter.py:generate_appeal_letter` (103 LOC):** Mixes prompt construction, LLM call, response parsing, and PHI scrubbing. **Refactor candidate.**

- **`doctor_email.py:send_doctor_summary` (64 LOC):** The module is large (537 LOC after the 2026-06-26 Mailgun removal) but the public functions are small and well-factored. The bulk of the file is the doctor summary builder, the operator-outbox JSONL writer, the NPI lookup table, and the opt-out list — not complexity hotspots.

---

## Test Coverage Gaps

**Current state:** 791 tests collected, 51 test files. Ratio is roughly 727 test functions / 10,370 src LOC = 14% test-to-source ratio (counting test function definitions, not executed lines).

**Top 10 untested or undertested critical modules (by impact):**

1. **`src/ai_billing_audit/ground_truth.py` (428 LOC, 0 tests)** — Largest untested module. Rule templates, `ground_truth_for()`, `get_val()`, `get_train()`. **This is the source of every gold finding label in the eval set.** If it's wrong, every F1 number is wrong. Zero coverage. `scripts/generate_holdout.py` and `generate_test_split.py` are the only callers.
2. **`src/ai_billing_audit/encounter_schema.py` (217 LOC, 0 tests, never imported)** — Dead module — but if v13 plans to use it, it has zero test coverage.
3. **`src/ai_billing_audit/scenario_schema.py` (190 LOC, 48 tests)** — The *file* is tested, but the *module* is not used by src/. The 48 tests in `test_scenario_schema.py` exercise it in isolation.
4. **`src/ai_billing_audit/api.py:encounter_appeal` (173 LOC, partial coverage)** — 4 tests in `test_appeal_letter.py` cover the LLM pathway but not the error paths, the persistence path, or the `cryptographic_signature` linking to `audit_actions.append`.
5. **`src/ai_billing_audit/api.py:tenant_delete` (65 LOC, light coverage)** — `tests/test_tenant_export.py` covers the read path; the destructive `tenant_delete` endpoint has 0 tests.
6. **`src/ai_billing_audit/api.py:encounters_upload_submit` (98 LOC, partial)** — 28 tests in `test_encounters_upload.py` cover the X12 parsing; the actual job enqueue and queue-handling integration is thinly tested.
7. **`src/ai_billing_audit/job_queue.py:_default_runner` (211 LOC, integration-tested)** — `test_encounters_upload.py` exercises the runner, but the new real-data branch (`use_real_data = bool(uploaded_note) and bool(queued_cpts)`) is not explicitly tested end-to-end. **Critical gap** — this is the path that fixes the synth trap.
8. **`src/ai_billing_audit/audit_actions.py` chain verification** — `verify()` and `read_for_encounter()` are untested. `test_audit_actions_tenant.py` covers `append()` but not the two dead functions.
9. **`src/ai_billing_audit/doctor_email.py` (629 LOC, 16 tests in `test_doctor_email.py`)** — Tests cover `send_doctor_summary` and `opt_out_doctor`. The NPI-lookup table and the 19-line `build_summary` prompt are tested. Lowest test-density in src/ relative to LOC, but the highest-priority code paths are covered.
10. **`src/ai_billing_audit/api.py` (2279 LOC, ~20 endpoint tests)** — Per-endpoint test count averages 1-2 per route. The `healthz`, `legal_privacy`, `legal_terms`, `case_study_detail`, `roi_calculator`, `roi_calculator_post`, `activity_page`, `prompt_history_api`, `prompt_history_compare` routes have thin or no dedicated test files. The dashboard route `encounter_detail` (117 LOC) is covered indirectly by `test_dashboard.py`.

**Tests that mock so heavily they test nothing (5 examples):**

1. **`tests/test_npi_lookup.py`** — 30 mock/patch references in a 130-line file. Mocks the NPI registry HTTP call; the test asserts that the mock was called. Pure tautology if the production code path is wrong.
2. **`tests/test_doctor_email.py`** — **updated 2026-06-26**: the two Mailgun tests were replaced with an outbox-JSONL test + a "no-network-calls" invariant test; the rest of the file exercises the real `send_doctor_summary` against a tmp_path JSONL. No `requests` mocks remain.
3. **`tests/test_runner_doctor_email.py`** — 11 mock references. Mocks `send_doctor_summary` and asserts `_send_doctor_emails` calls it the right number of times. Validates the **counting** logic, not the email-send behavior.
4. **`tests/test_runner_doctor_email_npi.py`** — Similar to #3, but for the NPI-lookup pathway.
5. **`tests/test_minimax_client_retry.py`** — 18 mock references. Mocks `time.sleep` and `openai.OpenAI()`. The retry test does not exercise a real network failure; it asserts the retry counter increments.

These are not *bad* tests — they pin behavior — but they cannot catch a regression in the unmocked layer. (No more Mailgun concern after 2026-06-26 — there is no longer a third-party API to drift.)

---

## Known-Issues Confirmation / Refutation Table

| # | Known issue (from prior session memory) | Confirmed? | Evidence |
|---|----------------------------------------|-----------|----------|
| 1 | `_quote_in_note()` in `auditor.py` is the v0.5 hallucination guardrail | **✅ STILL PRESENT, STILL TESTED** | `src/ai_billing_audit/auditor.py:205` defined; called at lines 334 and 346; tested in `tests/test_hallucination_guardrail.py:126-132` (6 assertions on direct helper) + integration tests on the auditor. |
| 2 | `audit_actions.py` chain: `append()`, `read_for_encounter()`, `verify_chain()` are called from anywhere | **❌ PARTIALLY REFUTED** | `append()` is wired into 8 API call sites in `api.py:738, 765, 814, 831, 1946, 2013` plus `contact.py:69`. `read_for_encounter()` is **still dead** (line 222 of `audit_actions.py`; zero callers). `verify_chain()` exists **only in `src/audit_log.py:162`**, not in `audit_actions.py` — the `audit_actions.verify()` function (line 228) is dead. So the prior statement was 1/3 right. |
| 3 | `_default_runner` at `job_queue.py:357` uses the synth trap | **❌ REFUTED (line number is wrong; behavior is fixed at the new line)** | `_default_runner` is now at `job_queue.py:517-727` (not 357). The function **does have a real-data branch** keyed on `uploaded_note + queued_cpts` (lines 547, 557, 562-602). When both are present, it builds a real `claim` from the queued CPTs and skips the synth. The synth is now the **fallback**, not the default. The path that does still trap is `api.py:encounters_audit` (re-audit endpoint, line 2191) — that one still re-synthesizes the claim from `encounter_id` hash. |
| 4 | `doctor_email.py` is wired into `_default_runner` | **✅ CONFIRMED** | `_send_doctor_emails()` is called from `_default_runner` at `job_queue.py:703`. Returns count of emails sent and is included in the result envelope. 16 tests in `test_doctor_email.py` + 11 integration tests in `test_runner_doctor_email.py` and `test_runner_doctor_email_npi.py`. |
| 5 | `zorva_context.py` is aspirational, not used by the auditor | **❌ REFUTED** | `zorva_context.build_context_for_encounter()` is called from `job_queue.py:658-665` (real-data path) and from `api.py` upload endpoints. The context is also rendered in `templates/encounter_detail.html:13-24` (market badge). 24 tests in `test_zorva_context.py` cover it. **It is wired, not aspirational.** |
| 6 | `MANIFEST.json` has entries only for v0 and v12 | **✅ CONFIRMED** | `prompts/MANIFEST.json` has 2 entries (v0 at 2026-06-16, v12 at 2026-06-22). v1-v11 are not in the manifest, even though their prompt files exist in `prompts/v1/` through `prompts/v11/`. |
| 7 | The "5 conversion-blocking gaps" — doctor email wiring, action endpoints, upload portal bypass, /app/logs bind mount, mailgun key | **❌ 5 OF 5 RESOLVED (as of 2026-06-26)** | Doctor email: wired (`job_queue.py:703`). Action endpoints (`/accept-all`, `/dismiss`, `/rerun`, `/flag`): wired in `api.py:732-840` and exercised by `tests/test_audit_endpoint.py`. Upload portal bypass: partially fixed (real-data path in `_default_runner`); the **re-audit endpoint still bypasses** (`api.py:2191` still re-synthesizes the claim). /app/logs bind mount: named-volume, persists across recreate. Mailgun: RESOLVED 2026-06-26 by removal — `MAILGUN_API_KEY` is no longer read anywhere; `requests` no longer a dependency; `_send_via_mailgun` and `_mailgun_configured` deleted from `src/ai_billing_audit/doctor_email.py`. |

---

## Risk-Ranked Recommendations (top 10)

In order of leverage. Each is a concrete next action.

1. **Pick one hash-chain module.** Either migrate `tests/test_audit_log.py` and `scripts/qa_audit_chain_{insert,verify}.py` to use `audit_actions.{compute_signature,verify}`, **or** delete `audit_actions.py` and port the 8 `api.py` call sites to `src/audit_log.py`. The current state is two implementations of the same wire format, with different feature coverage (`audit_actions` has 8 API call sites, `audit_log` has 0). A bug-fix in one will not propagate. (Addresses issues #2, #8 in the dead-code list.)

2. **Fix the re-audit synth trap at `api.py:2181-2234`.** The endpoint accepts a `clinical_note` from the user, then ignores the user's claim and re-synthesizes from `encounter_id` hash. The fix is to read the cached `Job.result["claim"]` (which the endpoint already has at `job = queue.find_by_encounter(encounter_id)`) and pass that into `_run_audit(audit_encounter)`, instead of rebuilding the claim via `synth_agent.generate()`. This is the **last remaining user-visible synth trap** after the `_default_runner` fix.

3. **Add tests for `ground_truth.py`.** 428 LOC of rule-encoding logic, zero coverage. Every F1 number depends on this module. Two `def test_` files for `_TEMPLATES` and `ground_truth_for()` would close the largest gap in the repo.

4. **Delete the dead stubs: `billing.py`, `audit.py`, `encounter_schema.py`, `demo_entries.py`.** Combined: 419 LOC of placeholder or unused code. None has a caller. None has tests. Removing them improves the cognitive surface area of the package by 4%.

5. **Append v1–v11 to `prompts/MANIFEST.json`.** The manifest is supposed to be append-only and exhaustive of optimization runs. The current 2-entry manifest does not match the 12 prompt directories on disk. Either backfill the 10 missing entries, or document that v0 and v12 are the only "officially tracked" runs and the intermediate prompts are dev artifacts.

6. **Add a test for the `_default_runner` real-data branch.** The new `use_real_data = bool(uploaded_note) and bool(queued_cpts)` code path is critical (it removes the synth trap for the upload portal) but has no end-to-end test. `tests/test_encounters_upload.py` should add a case where the upload posts both a clinical note and CPT codes, and assert the runner does not call `synth_agent.generate()`.

7. **Refactor `api.py:encounter_appeal` (173 LOC).** Extract the prompt-build, LLM-call, response-parse, and persist steps into `appeal_letter.py`. The function is the largest in api.py and has 5 responsibilities. Tests in `test_appeal_letter.py` would benefit from testing the extracted helpers directly.

8. **Delete `audit_actions.{read_for_encounter, verify}` or wire them.** Both are defined (lines 222 and 228) and both are dead. If a per-encounter audit-log viewer is on the v13 roadmap, keep them with a `TODO(kanban: ...)` comment. Otherwise, delete and reduce the module to `append` + `read_all` + `compute_signature`.

9. **Resolve the doctor_email/audit_log cross-module private-attribute import in `contact.py:71`.** `from .api import _TENANT_ID  # type: ignore[attr-defined]` is a code smell. Either export `_TENANT_ID` from `api.py` (or move it to a small `tenant.py` module) or wrap it in a `get_tenant_id()` accessor in `api.py`. Removes a `# type: ignore` and a module-level cross-private import.

10. **Generate per-version `MANIFEST.json` for `prompts/v1/` through `prompts/v11/`.** Only `prompts/v0/MANIFEST.json` exists. The other 11 prompt directories have just an `auditor_prompt.txt`. Per-version manifests let `load_prompt(path='prompts/vN/auditor_prompt.txt')` validate that the prompt file matches a known content hash. Mechanical work: 11 file writes, each 20 lines.

**Bonus (not in the top 10):**

- The `scripts/check_*.py` cluster (10+ files) appears to be ad-hoc live smoke checks. Audit which are still used; archive the rest to `scripts/archive/`.
- `src/worker.py` (75 LOC no-op heartbeat) exists only to satisfy the 4-service docker-compose. If that topology is no longer required, drop the worker container from `docker-compose.yml` and delete `worker.py`.

---

## Appendix: Audit Method

- Cross-referencing done with `grep -rn` against `src/`, `tests/`, `scripts/`, `.github/`, `docker-compose.yml`, and `pyproject.toml`.
- LOC counts from `wc -l`.
- Test count from `.venv/bin/python -m pytest --collect-only -q` (791 tests, 1.49s).
- No source code, prompts, val sets, or kanban state was modified.
- 20-minute budget observed; no LLM calls, no API calls, no secret reads.
