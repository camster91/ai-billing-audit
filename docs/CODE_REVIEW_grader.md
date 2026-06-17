# Code review: scoring layer (grader.py, grading.py, judge.py)

**Scope.** `src/ai_billing_audit/grader.py` (418 LOC), `grading.py` (277 LOC), `judge.py` (502 LOC).
**Reviewer.** Kanban task `t_52d211ee`, fresh subagent context.
**Continuity note.** This file overwrites the report from the prior task `t_27cb3b1b` (2026-06-16 22:46). That prior review covered the same three files. I re-derived conclusions from the source line by line; findings marked "CONFIRMED" replicate the prior review's verdict because the code at the cited lines is unchanged. Findings marked "NEW" are observations the prior review did not surface, or sharper readings of the same code with different line numbers / examples.
**Out of scope.** Refactoring, adding tests, performance benchmarks, files outside the three above. JSONL write safety is not in scope (the three files do no file I/O — see §5).

## Executive summary

The scoring layer is small, well-documented, and largely correct. Across the 5 focus areas:

- (1) **TP/FP/FN rules.** PASS. Greedy by overlap, then by indices, with category+code+Jaccard-≥-0.80 as the eligibility filter. Comprehensive test coverage. Three Minor gaps in untested corner cases.
- (2) **LLM judge fallback / provider-difference enforcement.** CONCERN (Minor). String-level check, enforced at construction. Robust against unintentional same-provider; leaky against adversarial provider-aliasing. NEW: the same-class exception `SameProviderError` is correctly *only* raised at construction — there is no per-call re-check, but there is no path that bypasses the construction check either.
- (3) **Abstain handling.** PASS. Traced to `judge.py:482-487` — abstain returns `score=overlap, method="abstain_fallback", judge_used=False`, exactly per the spec. NEW: the spec's "fall back to string-match" wording is honored — the returned score is the token-Jaccard overlap, not 0, not 1, not a sentinel. Caveat: `overlap` is in `[0.7, 0.9]` (the trigger band), so the abstained score is indistinguishable from a confident yes to consumers that only look at `score`.
- (4) **Determinism (temp=0, seed=42).** PARTIAL — PASS for the deterministic `Grader` (config gate + per-call pin + RNG seed), PASS-by-design for `FallbackGrader` (stochastic yes/no classifier, contract not stated in the docstring — NEW: this is worth documenting), PASS for `match_findings` (pure Python).
- (5) **JSONL history writes.** NOT APPLICABLE. The three review files do no file I/O at all. The JSONL writes in the project live in `optimize.py` and `job_queue.py` (outside scope).

**One Critical/Blocker: zero.** Everything is Minor or Info.

## Per-focus-area findings

### 1. TP/FP/FN matching rules — PASS

The rules are restated below, line-cited, and the test coverage is comprehensive for the documented behavior. Three Minor gaps in untested corner cases.

**Exact rule (verbatim from `grading.py:136-198`).** A predicted finding `p` matches a ground-truth finding `g` iff all three hold:

1. `_field(g, "category") == p_cat` (line 167) — exact string equality.
2. `_field(g, "suggested_code") == p_code` (line 169) — exact string equality.
3. `_jaccard(pred_tokens[pi], gt_tokens[gi]) >= threshold` (line 172), `threshold` defaulting to `EVIDENCE_OVERLAP_THRESHOLD = 0.80` (line 61).

The matcher then sorts all eligible `(overlap, pi, gi)` candidates by `(-t[0], t[1], t[2])` — highest overlap first, then lowest `pred_index`, then lowest `gt_index` (line 176) — and greedily picks pairs, marking each `pi` and `gi` as used. Anything left in `predicted` is `fp`; anything left in `ground_truth` is `fn`. `MatchResult.tp / fp / fn` are the counts of `matches` / `unmatched_predicted` / `unmatched_ground_truth` (lines 191-197).

**Test coverage matrix** (all in `tests/test_grading.py`):

| Behaviour | Test | Line |
| --- | --- | --- |
| Exact match (single, multi) | `test_exact_match_single_pair`, `test_exact_match_multiple_pairs` | 76-97 |
| Paraphrase ≥ 0.80 matches | `test_paraphrased_quote_at_threshold_matches` | 108-122 |
| Pure-substring predicted within longer GT (matches) | `test_pure_substring_predicted_matches_longer_ground_truth` | 125-137 |
| Pure-substring predicted 4-of-24 tokens (no match) | `test_short_substring_in_long_ground_truth_does_not_match` | 140-150 |
| Pure-substring GT within longer predicted (matches) | `test_pure_substring_ground_truth_matches_longer_predicted` | 153-168 |
| Paraphrase < 0.80 (no match, with caveat) | `test_paraphrase_below_threshold_is_no_match` | 176-197 |
| Unrelated quote (no match) | `test_completely_unrelated_quote_is_no_match` | 200-208 |
| Extra prediction → FP | `test_extra_prediction_is_fp` | 216-226 |
| Missing prediction → FN | `test_missing_prediction_is_fn` | 229-239 |
| Category mismatch (no match) | `test_category_mismatch_is_no_match` | 247-253 |
| Suggested-code mismatch (no match) | `test_suggested_code_mismatch_is_no_match` | 256-262 |
| Empty inputs (both, pred-only, gt-only) | `test_both_empty`, `test_predicted_empty_ground_truth_has_findings`, `test_ground_truth_empty_predictions_are_all_fp` | 270-292 |
| Greedy one-to-one by overlap | `test_greedy_prefers_highest_overlap_on_ties` | 300-319 |
| Each prediction matched ≤ 1 | `test_each_prediction_matched_at_most_once` | 322-333 |
| Each ground truth matched ≤ 1 | `test_each_ground_truth_matched_at_most_once` | 336-347 |
| Dataclass-shaped inputs (incl. mixed) | `test_dataclass_inputs_match_dict_inputs`, `test_mixed_dict_and_dataclass_inputs` | 355-379 |
| `MatchResult.precision/recall/f1` math | `test_match_result_precision_recall_f1`, `test_match_result_zero_predictions_precision_is_one` | 387-413 |
| Custom threshold knob | `test_custom_threshold_relaxes_match` | 421-447 |

**Untested branches (Minor / Info):**

- **Empty-quote pair.** `_jaccard(frozenset(), frozenset())` returns `1.0` (`grading.py:75-76`). Two findings with matching `category` and `suggested_code` and *empty* `clinical_evidence_quote` will match. The `_jaccard` docstring documents this (line 73) but `match_findings` does not, and no test covers it. **Severity: Minor.** Suggested fix: add a test or a `len(union) > 0` guard in `match_findings` so empty-quote pairs are excluded.
- **Quote with only non-alphanumerics** (e.g. `"!!!"` or `"   "`) tokenizes to an empty frozenset, same path. **Severity: Minor.** Same fix.
- **`threshold` is not validated to be in `[0, 1]`.** `match_findings` accepts `threshold=2.0` (silently no-match-all) or `threshold=-0.1` (silently match-all). **Severity: Minor.** Suggested fix: add `if not 0.0 <= threshold <= 1.0: raise ValueError(...)` in `match_findings`.
- **Tie-break when two candidates have identical `(overlap, pred_index)` but different `gt_index`.** Greedy picks the lowest `gt_index` by the sort key `(-t[0], t[1], t[2])`. No explicit test. **Severity: Info.** Behaviour is consistent and deterministic; documenting it in a test would protect against future sort-key changes.

**NEW: spec/implementation wording mismatch on the substring decision.** The spec docstring in `grading.py:9-48` (and the grader prompt at `prompts/grader_prompt.txt:12-16`) says "A Jaccard token overlap of 0.80 or higher counts as a match. Substring relationships alone are not sufficient; both quotes must be roughly the same length and share most of their tokens." This is the Jaccard position. The earlier docstring paragraph at `grading.py:20-28` references the spec's "substring direction" language ("`p.quote in g.quote` or `g.quote in p.quote`") and explicitly disambiguates: "We use the Jaccard overlap as the primary contract (>= 80%)." Tests codify the Jaccard decision (`test_short_substring_in_long_ground_truth_does_not_match` is the canonical example). **Severity: Info.** No code change needed; the docstring is internally consistent and the tests are the contract. If a reviewer wanted to clean it up, the "Substring direction" paragraph at lines 20-28 could be condensed to one sentence pointing at the Jaccard decision.

**Summary.** The matching rules are correctly implemented, the test matrix is comprehensive, and the few untested branches are minor corner cases. **Verdict: PASS.**

### 2. LLM judge fallback / provider-difference enforcement — CONCERN (Minor)

The provider-difference check is at the provider-**string** level, enforced at construction. It is robust against the realistic case where the operator accidentally picks the same string for both; it is leaky against the adversarial case where two different provider strings alias to the same underlying model.

**Construction-time enforcement** (`judge.py:270-292`):

```python
auditor_p = auditor_provider if auditor_provider is not None else provider()
judge_p   = judge_provider   if judge_provider   is not None else _resolve_judge_provider(auditor_p)
judge_m   = judge_model      if judge_model      is not None else _resolve_judge_model(auditor_p, judge_p)
if judge_p == auditor_p:
    raise SameProviderError(...)
```

The `_PAIR_TABLE` at `judge.py:126-134` maps seven auditor providers to a different default judge provider. The final fallback at `judge.py:159` (`return "openai" if auditor_provider == "anthropic" else "anthropic"`) ensures the table and the fallback are symmetric. So under default configuration the check passes with `(auditor_p, judge_p) !=` always.

**The check works against unintentional same-provider** (e.g. operator sets `JUDGE_LLM_PROVIDER=openai` when the auditor is `openai` → `SameProviderError` at line 283-287). It is exercised by `test_same_provider_raises_same_provider_error` (`tests/test_judge.py:158-165`) and `test_default_provider_pairs_differ` (`tests/test_judge.py:168-172`).

**Concrete adversarial bypass.** The spec invariant is "the judge must be a different LLM than the auditor" (the rationale: same model inherits the same blind spots and biases — see `judge.py:13-17`). The implementation enforces "different provider string." A motivated operator can satisfy the string check while violating the model check:

```python
# Both provider strings differ — construction passes.
# Both underlying models are gpt-4o-mini — invariant violated.
grader = FallbackGrader(
    llm=LLMClient(model="gpt-4o-mini"),   # judge routes to openai/gpt-4o-mini
    auditor_provider="openai",            # LLM_PROVIDER=openai (auditor)
    judge_provider="azure",               # JUDGE_LLM_PROVIDER=azure (judge)
    judge_model="azure/gpt-4o-mini",      # judge routes to Azure-hosted gpt-4o-mini
)
# SameProviderError? No — "openai" != "azure".
# Both calls land on gpt-4o-mini. The judge is the auditor.
```

This works because `azure` and `openai` are distinct litellm provider names that both serve OpenAI's model family. It is not the case the spec is guarding against for *honest* operators (the spec is about not using the same model for the same problem), but it is a real bypass for an *adversarial* operator. The check is at the wrong layer: it should compare the *resolved model identifier* (e.g. `gpt-4o-mini` in both cases), not the *provider string*.

**NEW: there is no per-call re-check, but there is no path that bypasses the construction check either.** I traced the call sites:
- `FallbackGrader.__init__` raises `SameProviderError` (line 282-287).
- `FallbackGrader.grade` (line 450-487) does not re-check; it just calls `self._invoke_judge`.
- `FallbackGrader._invoke_judge` (line 389-420) just dispatches to `self._llm.complete`.
- `grade_with_fallback` (in `grading.py:206-277`) constructs no grader itself; it accepts a pre-built `FallbackGrader` as the `grader` argument.

If a grader successfully constructs, every grade call uses the same judge provider. There is no per-call override path. **PASS for the integrity of the construction check; the bypass is at the construction step itself (provider aliasing), not at call time.**

**Suggested fix (Minor).** Add a model-level check after the provider-level check. E.g.:

```python
# After: if judge_p == auditor_p: raise SameProviderError(...)
# New (advisory; needs an explicit allowlist of acceptable cross-provider models):
if judge_m == self._resolve_auditor_default_model(auditor_p):
    raise SameProviderError(
        f"Judge model ({judge_m!r}) on provider ({judge_p!r}) resolves to the "
        f"same model as the auditor on {auditor_p!r}. Use a genuinely different model."
    )
```

This is defense against an operator actively trying to game the metric — the realistic case is a typo or a stale `JUDGE_LLM_PROVIDER` in `.env`, which the string check already catches. **Severity: Minor.** Document and move on unless the metric is shown to be gamed in practice.

**Prompt/parsing robustness for the yes/no answer.** The prompt (`judge.py:191-199`) asks for "exactly one word: yes or no. No prose, no punctuation, no explanation." The parser (`judge.py:422-444`) is conservative:

- Empty / whitespace-only / `?` / `maybe` / `unsure` / explicit abstain phrases → abstain (lines 425-437).
- Regex sweep on `_YES_RE` / `_NO_RE` (lines 439-442) — both match (e.g. `"yes no"`) → abstain; neither match → abstain; one match → yes/no.
- "Anything outside this set is treated as a 'no'" (line 88 docstring).

Adversarial prompts to the model (traced by hand from the parser):

- `"y e s"` (spaces) → `re.sub(r"\s+", "", text)` produces `"yes"` at line 430, then the compact check on line 431 finds it NOT in `_ABSTAIN_TOKENS`, then the yes-sweep on line 439 matches → **yes**. (Not a leak; the model said yes.)
- `"y\nes"` → compact to `"yes"` → `\byes\b` matches → **yes**. (Not a leak.)
- `"y\nyes"` → compact to `"yyes"` → no word boundary for `\byes\b` or `\by\b` → falls through to no-match → abstain. Conservative. **Not a leak.**
- `"I think not, but I'm not sure"` → compact to `"ithinknot,butimnotsure"` → contains `"notsure"` → **abstain**. Conservative. **Not a leak.**
- `"supported"` → matches `_YES_RE` (`supported` is in the alternation at line 102) → **yes**. By design.
- `"unsupported"` → matches `_NO_RE` (`unsupported` is in the alternation at line 103) → **no**. By design.
- NEW: `"yes no"` → both regexes match → falls through to `"abstain"` (line 444). **Not a leak** — the model is hedging, abstain is the right call. Untested by the suite (covered as finding #8 in the severity table).

**Verdict.** The prompt+parser is robust for the realistic failure modes (model hedges, model rambles, model returns formatting). The only bypass is at the configuration layer (provider string aliasing), not at the prompt/parser layer. **PASS for prompt/parsing. CONCERN (Minor) for provider-difference enforcement.**

### 3. Abstain handling — PASS

The abstain path is fully traced. On abstain, the score returned is the deterministic overlap (not 0), the method is `"abstain_fallback"`, and `judge_used` is `False`. Exactly per the spec.

**Exact path** (`judge.py:450-487`):

1. `grade()` calls `self._should_invoke_judge(prediction, ground_truth)` (line 468). Returns `(should_invoke, overlap)`.
2. If `should_invoke` is False → `GradeResult(score=float(overlap), method="deterministic", judge_used=False)` (lines 469-474).
3. If `should_invoke` is True → calls `self._invoke_judge(...)` (line 476), which is the LLM call.
4. Parses the raw answer via `self._parse_judge_answer(raw)` (line 477) → `"yes"` / `"no"` / `"abstain"`.
5. `verdict == "yes"` → `GradeResult(score=1.0, method="judge", judge_used=True)` (lines 478-479).
6. `verdict == "no"` → `GradeResult(score=0.0, method="judge", judge_used=True)` (lines 480-481).
7. **`verdict == "abstain"` → `GradeResult(score=float(overlap), method="abstain_fallback", judge_used=False)` (lines 482-487).**

The `overlap` returned in step 7 is the *deterministic* token-Jaccard overlap computed in `_should_invoke_judge` (line 366: `_jaccard(_tokenize(pred_quote), _tokenize(gt_quote))`). Because the trigger band is `[0.7, 0.9]`, an abstained score is in `[0.7, 0.9]`.

**NEW: the spec's "fall back to string-match" wording is honored.** The spec says (per the file docstring `judge.py:39-50`): on abstain, "the deterministic token-Jaccard overlap is returned." The implementation does exactly that — the `overlap` from `_should_invoke_judge` is the same `_jaccard(_tokenize(...), _tokenize(...))` value used in `match_findings` (`grading.py:171`). Same function call, same threshold rule, same input. The abstain score is the string-match score, not 0, not 1, not a sentinel. **PASS.**

**`_invoke_judge` paths that produce abstain:**

- **Transport error** — `judge.py:403-414`: `try: self._llm.complete(...) except Exception: return "abstain"`. Covers any LLM-side failure (network, auth, rate limit, schema rejection). **Tested: `test_llm_transport_error_treated_as_abstain` (`tests/test_judge.py:384-407`).**
- **Malformed response shape** — `judge.py:416-419`: `try: content = response["choices"][0]["message"]["content"] except (KeyError, IndexError, TypeError): return "abstain"`. Covers a non-OpenAI-shape response. **Not explicitly tested.** Add a test that injects a fake LLM returning `{}` or `{"choices": []}` and asserts the result is `method="abstain_fallback"`. **Severity: Minor.**
- **Empty / abstain token / hedge phrase** — `judge.py:425-437`. **Tested by parameterization `test_abstain_responses_fall_back_to_deterministic` (`tests/test_judge.py:360-381`) with `""`, `" "`, `"?"`, `"maybe"`, `"unsure"`, `"I'm not sure"`, `"I cannot determine"`.**
- **Both yes and no regex match (or neither matches)** — `judge.py:443-444`: `return "abstain"`. **Not explicitly tested.** Edge case: `"yes no"` → both regexes match → abstain. Add a test. **Severity: Minor.**

**NEW: Caveat for downstream consumers.** An abstained call's `score` is the deterministic overlap, which for the trigger band is in `[0.7, 0.9]`. A naive consumer that looks only at `score >= 0.5` would treat an abstained call (0.7-0.9) and a confident "yes" (1.0) the same way. The `method` field distinguishes them; consumers should branch on `method` first. **Severity: Info.** Document this on `GradeResult` (`judge.py:106-112`) or in a `README` section for downstream callers.

**Verdict.** The abstain path is correct, the spec is satisfied, and the common cases are tested. The two untested branches (malformed response shape, both-regex-match hedge) are minor. **PASS.**

### 4. Determinism (temp=0, seed=42) — PARTIAL → PASS (asymmetric)

The temp=0/seed=42 contract is fully honored by the deterministic `Grader.grade` and is intentionally not applied to the `FallbackGrader.grade`. `match_findings` is pure Python and fully deterministic. The `verify_grader_reproducibility.py` script tests the deterministic grader only, which is the right thing given the asymmetric contracts.

**`Grader.grade` (deterministic LLM grader, `grader.py:270-418`).** Three layers of enforcement:

1. **Config-level gate** (`grader.py:200-212` in `load_grader_config`): `float(judge["temperature"]) != 0.0` and `int(judge["seed"]) != 42` both raise `GraderConfigError` at construction. A misconfigured grader cannot be built.
2. **Per-call pin** (`grader.py:359-366` in `_call_llm`): every `LLMClient.complete()` call passes `model=..., temperature=0.0, seed=42, max_tokens=..., response_format=...`. There is no retry/fallback path inside `Grader.grade` itself — a single call, single response, single parse.
3. **Pure helpers** (`grader.py:243-267` for `build_messages`, `grader.py:221-240` for `_render_prompt`): no timestamps, no thread identifiers, no environment reads. `_render_prompt` uses `sort_keys=True` (lines 229-230) — NEW: this is a small but real determinism guarantee. Two callers passing the same dict with different key insertion order get the same JSON.

The `random.seed(42)` at `grader.py:300` (with `PYTHON_RNG_SEED = 42` at line 86) is essentially decorative in the current code — `Grader.grade` does not consume any RNG. The test `test_grader_constructor_seeds_python_rng` (`tests/test_grader.py:177-202`) verifies the post-construction RNG state, not that any randomness is actually used.

NEW: **the `LLMClient` in `grader.py:331` pins `model=self._judge_model`** so the resolved LLMClient does not re-read `LLM_MODEL` from the environment. This is a small but real determinism guarantee — without the explicit `model=` in the constructor, the LLMClient would resolve the model from the environment on every call, making the grader's behavior dependent on `os.environ["LLM_MODEL"]` at request time.

**`FallbackGrader.grade` (LLM-as-judge, `judge.py:389-420`).** No `temperature=` and no `seed=` are passed on the LLM call (`judge.py:403-412`). This is by design: the FallbackGrader is a yes/no classifier, and the spec does not require its output to be byte-identical. A `FallbackGrader.grade` call is allowed to be stochastic; the reproducibility contract applies only to the deterministic `Grader.grade` and to `match_findings`.

NEW: **`FallbackGrader` is also missing `response_format` on its LLM call.** The deterministic `Grader` uses `response_format=_VERDICT_SCHEMA` (`grader.py:365`) for constrained JSON output. The judge does not — its prompt asks for free-text "yes" or "no" (`judge.py:191-199`), and the parser (`judge.py:422-444`) is built to handle a model that doesn't comply. This is correct for the use case (yes/no is shorter than JSON), but it does mean a verbose model could return multi-paragraph output that the parser still has to regex-sweep. The parser is robust. **PASS-by-design.**

NEW: **The class docstring at `judge.py:231-268` does not explicitly state the stochastic contract.** It says "LLM-as-judge fallback grader" and explains the trigger logic, but it does not say "This grader is stochastic; the temp=0/seed=42 contract applies to `ai_billing_audit.grader.Grader` only." A new reader who assumes both graders are deterministic could be surprised. **Severity: Info.** One-line addition to the docstring would close this.

**`match_findings` (`grading.py:136-198`).** Pure Python, no I/O, no globals (other than the threshold constant `EVIDENCE_OVERLAP_THRESHOLD = 0.80` at `grading.py:61` and the regex `_TOKEN_RE` at line 64 — both are module-level immutable constants). Same input → same output, byte for byte.

**Retry/fallback path question.** The task body asks: "verify by reading the call sites that temperature and seed are actually passed on every judge call, including any retry/fallback path." The deterministic `Grader.grade` has no internal retry. The retry lives in the LLM transport layer below:

- `LLMClient.complete` (`llm.py:116-125`) — no retry, just `self._complete(messages=..., **kwargs)`.
- `litellm.completion` (the default backend) — has its own retry behaviour, but it is governed by litellm and is not in the three review files. The seed=42 passed by `Grader.grade` is forwarded as a kwarg, and litellm's retry would re-send with the same seed (assuming the seed survives the retry, which is the documented behaviour of the OpenAI and Anthropic SDKs at temperature=0).
- The sibling review (`docs/CODE_REVIEW_llm.md`) flagged that `LLMClient` does not surface a `timeout=` parameter. That is a separate concern (no timeouts) and does not affect the determinism contract directly.

**For the deterministic `Grader.grade`:** temp=0 and seed=42 are pinned at every call site (`grader.py:361-365`). No retry path inside the grader itself. The seed is preserved through the LLMClient's pass-through to litellm. **PASS.**

**For the `FallbackGrader.grade`:** no temp/seed pin. The docstring (`judge.py:1-53`) is silent on the determinism contract for the judge — by omission, it is non-deterministic. The `verify_grader_reproducibility.py` script (`scripts/verify_grader_reproducibility.py:31`) only imports from `ai_billing_audit.grader`, confirming that the determinism contract is scoped to the deterministic grader. **PASS (by design).**

**`grade_with_fallback` orchestrator (`grading.py:206-277`).** Deterministic in its orchestration: `match_findings` is deterministic, and the FP list is deterministic, so the set of (predicted, ground_truth) pairs sent to the judge is deterministic. The judge answers themselves are stochastic, so two runs of `grade_with_fallback` on the same input may differ in *which* FPs are promoted to TPs (and how many), but the orchestration never re-routes or re-shuffles.

NEW: **tie-break in `grade_with_fallback` is by `live_gt.items()` iteration order, which is the dict-insertion order from `unmatched_ground_truth`** (`grading.py:242-244`). For a single predicted FP and multiple unmatched GTs, the first GT whose `grader.grade()` returns `score >= 1.0` wins. This is deterministic *for a fixed judge answer stream* but not necessarily the *best* match — a lower-indexed GT that the judge says "no" to will block a higher-indexed GT that the judge says "yes" to. The test `test_grade_with_fallback_promotes_fp_to_tp_on_yes` uses 1-vs-1 so this branch is not exercised. **Severity: Info.** Add a test with 1 FP vs 2 GTs where the first GT is "no" and the second is "yes" to pin the order-sensitivity.

**Verdict.** The determinism contract is well-defined (deterministic `Grader` only) and well-enforced. **PASS.**

### 5. JSONL history writes — NOT APPLICABLE

**Verdict: NOT APPLICABLE to the three review files.** The three review files (`grader.py`, `grading.py`, `judge.py`) do not write to any file at all. The closest file I/O in these files is two `read_text()` calls (`grader.py:186` for the config JSON, `grader.py:321` for the prompt template), both read-only and not on a JSONL path. There is no `open(..., 'a')`, no `with open(...).write(...)`, no `Path(...).write_text(...)` with append-mode, no file handle sharing, no lock, no concurrency primitive, and no thread/process spawning in any of the three review files. The "interleaving risk under concurrent runs" question is moot: there is no write to interleave.

**Search results (verified):**

```
$ rg "jsonl|JSONL|\.history|open\(" src/ai_billing_audit/grader.py src/ai_billing_audit/grading.py src/ai_billing_audit/judge.py
(no matches)
```

All `.append()` calls in these three files are list appends on in-memory Python lists, not file appends (`grading.py:162, 173, 186, 256, 258, 268`). There is no file I/O on `.jsonl` paths.

**Where the JSONL writes actually live** (outside this review's scope per the task body):

- `src/ai_billing_audit/job_queue.py:14` and `:358` — appends a JSONL line to `logs/upload_jobs.jsonl` on every status change. This is a separate concern (job-queue durability) and is not invoked by any of the three review files.
- `src/ai_billing_audit/optimize.py:22, :92, :287-288` — appends a JSONL line to `logs/optimization_history.jsonl` after each DSPy compile. This is the optimization loop's audit trail, not the scoring layer's.

**Implication for the report.** The task body listed JSONL history writes as a focus area, presumably because the reviewer's checklist included "all file I/O across the layer." For the three files in scope, there is no JSONL write. A follow-up review of `optimize.py` and `job_queue.py` is warranted if the focus is "JSONL safety across the project." Within the three review files, there is nothing to flag.

**Verdict.** **NOT APPLICABLE** for the three review files. **Severity: Info.** Follow-up: review `optimize.py` and `job_queue.py` for JSONL write safety (interleaving, locks, fsync) in a separate task.

## Severity table

| # | Finding | File:line | Severity | Suggested fix |
| --- | --- | --- | --- | --- |
| 1 | Empty-quote pair matches because `_jaccard(∅, ∅) = 1.0` | `grading.py:75-76` | Minor | Add a `len(union) > 0` guard in `match_findings` or a dedicated test |
| 2 | Quote with only non-alphanumerics tokenizes to empty set, matches | `grading.py:64-69` | Minor | Same fix as #1 |
| 3 | `threshold` not validated to be in `[0, 1]` | `grading.py:136-141` | Minor | Add `if not 0.0 <= threshold <= 1.0: raise ValueError(...)` |
| 4 | Tie-break on identical (overlap, pred_index), different gt_index untested | `grading.py:176` | Info | Add a test that pins the deterministic gt_index tiebreak |
| 5 | Spec/implementation wording mismatch on substring vs Jaccard | `grading.py:20-28` | Info | Condense the "Substring direction" paragraph; tests are already the contract |
| 6 | Provider-difference check at string level, not model level | `judge.py:282-287` | Minor | Add a model-id equality check after the provider check; see §2 |
| 7 | Malformed LLM response shape → abstain, untested | `judge.py:416-419` | Minor | Add a test that injects `{}` and `{"choices": []}` into the fake LLM |
| 8 | Both yes+no regexes match → abstain, untested | `judge.py:443-444` | Minor | Add a test that returns `"yes no"` and asserts `method="abstain_fallback"` |
| 9 | Abstained score in `[0.7, 0.9]` indistinguishable from "yes" to naive consumers | `judge.py:482-487` | Info | Document on `GradeResult` that `method` must be inspected first |
| 10 | `FallbackGrader.grade` does not pass temp/seed (intentional, but contract not stated in docstring) | `judge.py:231-268` | Info | Add a one-line note to the `FallbackGrader` docstring: "Stochastic by design; the temp=0/seed=42 contract applies to `grader.Grader` only." |
| 11 | `random.seed(42)` at `Grader.__init__` is decorative in the current code | `grader.py:300` | Info | Either consume the seeded RNG somewhere (e.g. shuffle candidates) or drop the seed call with a one-line comment |
| 12 | `grade_with_fallback` 1-vs-N tie-break order not exercised by tests | `grading.py:251-255` | Info | Add a test with 1 FP vs 2 GTs where GT[0] is "no" and GT[1] is "yes" |
| 13 | `GraderConfigError` is raised on a malformed LLM response (naming: it's a protocol error, not a config error) | `grader.py:373-395` | Minor | Introduce `GraderProtocolError(ValueError)` and raise it instead; keep `GraderConfigError` for config-file validation only |
| 14 | `_impact_of` swallows `TypeError`/`ValueError` and returns 0.0, hiding malformed input | `judge.py:343-345, 349-351` | Nit | Log a warning, or raise. Currently a `"$100"` string in the impact field silently passes as $0. |
| 15 | JSONL writes in the three review files: none | — | Info | None needed in scope; follow-up review on `optimize.py` and `job_queue.py` |

## Cross-cutting observations

- **Two graders, one name.** The deterministic LLM grader is `ai_billing_audit.grader.Grader`; the LLM-as-judge fallback is also called `Grader` in its source file (`judge.py:231`) but is exported as `FallbackGrader` (`judge.py:502`) to avoid the name collision. The class-level docstring at `judge.py:241-247` documents this. It is a reasonable design but a new reader is likely to be confused. **Severity: Info.** Could add a "Two graders in this package" section to the `__init__.py` re-export at `src/ai_billing_audit/__init__.py:5-61`.

- **Single source of truth for the verdict schema.** `_VERDICT_SCHEMA` in `grader.py:90-102` is a hardcoded Python dict; the same schema is also in the config at `prompts/grader_config.json:16-33`. If a developer updates one, the other can drift. The two are read at different times (Python schema is for local validation; JSON schema is for provider constrained decoding), and they MUST stay in sync. **Severity: Info.** Either generate the JSON schema from the Python dict (single source of truth) or add a test that asserts equality.

- **NEW: Field-name flexibility is asymmetric.** `judge._evidence_of` (`judge.py:314-329`) and `judge._impact_of` (`judge.py:331-352`) accept three aliases for the evidence field (`clinical_evidence_quote` / `evidence_quote` / `quote`) and two for the impact (`financial_impact` / `estimated_financial_impact`). `grading.match_findings` accepts only `clinical_evidence_quote` (`grading.py:84-93`). A finding shaped `{category, suggested_code, quote, financial_impact}` works for the judge but NOT for the deterministic matcher — the matcher would look up `clinical_evidence_quote`, get `None`, default to `""`, tokenize to empty, and either match (per finding #1) or not. **Severity: Minor.** Add the same field-name flexibility to `grading._quote_of` and `grading._field`.

- NEW: **`grade_with_fallback` is exported by `grading.py` but not re-exported in `__init__.py`.** `tests/test_judge.py:36` imports it directly from `ai_billing_audit.grading`, which works, but downstream consumers (e.g. `scripts/eval_final_test.py`) only import `match_findings` and never touch `grade_with_fallback`. If the spec calls for the fallback path to be on by default in the production scorer, that is a missing wire-up. **Severity: Info.** Verify against the spec; if `grade_with_fallback` is the production path, add a re-export in `__init__.py` and wire it into the scorer.

- NEW: **Both review files are well-tested but `grader.Grader` has zero callers in the production scoring path.** A `rg "from ai_billing_audit.grader import" src scripts` (excluding tests) returns only `scripts/verify_grader_reproducibility.py:31`. The deterministic LLM grader exists and is fully wired (config, prompt, schema, tests, verification script) but is not called from the actual scoring loop (`scripts/eval_final_test.py` uses `match_findings` only, `scripts/aggregate_metrics.py:67` uses `match_findings` only, `scripts/optimize.py:66` uses `match_findings` only). This is not a bug — the spec lists both paths and the deterministic LLM grader is the "in addition to" path — but it is a fact worth stating. **Severity: Info.** Confirm with the spec author whether the deterministic LLM grader is meant to be on the production path or only on the dev/CI verification path.

## Fixes recommended for follow-up tasks

The findings above are all Minor or Info; none is Critical or Major. The reviewer's task body asks for "concrete fix suggestions" on Critical/Major — there are none, so the only "fix" suggestions are the Minor items above. The recommended next steps, in priority order:

1. **Provider-difference model-level check** (`judge.py:282-287` after the string check). Defends against the documented adversarial bypass. Land as a one-condition guard.
2. **`threshold` range validation** (`grading.py:136-141`). One-line `ValueError` raise. Cheap insurance.
3. **Field-name flexibility in `grading._quote_of` and `grading._field`**. Match what `judge._evidence_of` and `judge._impact_of` already do.
4. **Rename protocol error exception.** `grader.py:373-395` should raise `GraderProtocolError(ValueError)` (new) on a malformed LLM response, leaving `GraderConfigError` for config-file validation only. Two-line change.
5. **Two untested branches**: malformed LLM response shape and both-yes-no regex match. Two-line tests in `tests/test_judge.py`.
6. **Single source of truth for the grader verdict schema**: generate `prompts/grader_config.json` from `grader._VERDICT_SCHEMA` or add a test that asserts equality.
7. **Document the FallbackGrader's stochastic contract**: one line in the class docstring at `judge.py:231`.
8. **Follow-up review of `optimize.py` and `job_queue.py`** for JSONL write safety (interleaving, locks, fsync). Not in scope for this task.

## Verification

This report is a review only — no source files in `src/ai_billing_audit/` were modified. The deliverable is this Markdown file at `docs/CODE_REVIEW_grader.md`, plus the line-cited evidence in §1-§5 above. Every finding cites the source line(s); every "PASS" is backed by a code path trace, not an inference; every "CONCERN" includes a concrete adversarial example.

The report was re-derived from the source files at the time of writing. Findings labelled "CONFIRMED" replicate the prior review (`t_27cb3b1b`) because the cited code is unchanged. Findings labelled "NEW" are independent observations; if the prior reviewer disagrees with a NEW finding on closer reading, the prior reviewer's interpretation should win unless the NEW finding cites a specific line the prior missed.
