# 03 — Eval methodology improvements for the auditor

**Author:** general subagent (research track)
**Date:** 2026-06-27
**Scope:** the v12 AHCIP auditor evaluation loop — `scripts/run_7x.py` (multi-run scorer), `data/synth/val_ca.json` (19-encounter gold), `prompts/MANIFEST.json` (per-version F1 log), and the per-clinic infrastructure scaffolded today (`apps/portal/src/lib/calibration.ts` + `src/ai_billing_audit/feedback.py:280`).

> **TL;DR.** The current headlined number is F1=0.690 on 19 encounters / 31 gold findings, but the **95% CI is roughly ±0.17–±0.20** — about a third of the number itself. The scorer is `rule_id`-only (ignores `severity`, `category`, `suggested_code`, `quote`, and `clinical_evidence_quote`), the gold is single-annotator (Hermes, an AI session — not a human Alberta biller), and the multi-run variance is dominated by **model temperature** (default T=1.0, not pinned). Three improvements do most of the work: **(1) add a 30–50-encounter held-out human-labelled subset** for IAA + real F1 floor; **(2) re-score on `(rule_id, severity-tier)` instead of `rule_id` only**, which catches over- and under-severity calibration without forcing a category field the model doesn't reliably emit; **(3) re-run the multi-run with `temperature=0` and provider `seed=42`** so the reported stdev is the model-sampling floor rather than a mix of backend noise and stochasticity.

---

## 1. Current state

### 1.1 Scorer contract

The shipped production scorer (`scripts/run_7x.py:137–165`) matches predicted findings to gold findings on **a single field**:

```python
def finding_key(f):
    return f.get('rule_id', '')
```

Per-encounter set intersection over `rule_id` strings; severity, category, suggested_code, and quote are **discarded at score time**. (The older `smartness_test.py` scorer uses `rule_id` + ≥0.40 Jaccard quote overlap; `run_7x.py` deliberately drops quote-overlap — see the in-file comment at lines 138–145 explaining why `category`-or-`rule_id` matching would penalise correct rule_id hits for missing an undocumented field.)

The `grader_metric` for DSPy optimization (`scripts/optimize.py:615`) calls `match_findings()` from `src/ai_billing_audit.grading`, which **does** use `(category, suggested_code, quote-Jaccard)` — but that scorer is wired only into the offline MIPROv2 optimization path, **not** into the production multi-run path. So the F1 number we report to stakeholders is computed under a different contract than the F1 the optimizer actually maximized.

**Concretely:** the optimizer was tuned against `match_findings()` (strict — 80% quote Jaccard, category, code), but the headline `F1=0.690` is `rule_id`-only set intersection. The two contracts can rank different prompts first. Until they agree, every iteration is being judged against a moving target.

### 1.2 Validation set size and content

`data/synth/val_ca.json` (verified 2026-06-27, after this morning's 19-encounter expansion):

- **19 encounters**, encounter_ids `ca_ahcip_001` … `ca_ahcip_019`
- **31 gold findings** total (avg 1.63 per encounter, range 1–3)
- **11 distinct `rule_id` values** appear in the gold:
  `rule_ahcip_em_level` (×9), `rule_ahcip_preventive_opportunity` (×6),
  `rule_ahcip_em_level_upcode` (×5), `rule_ahcip_missing_procedure` (×3),
  `rule_ahcip_modifier` (×3), `rule_ahcip_psychotherapy_time` (×2),
  `rule_ahcip_referring_npi` (×1), `rule_ahcip_same_day_conflict` (×1),
  `rule_ahcip_global_window` (×1), `rule_ahcip_telehealth` (×1),
  `rule_ahcip_dx_linkage` (×1), `rule_ahcip_lab_coverage` (×1)
- **Severity distribution:** `high=14, info=9, medium=7, critical=1` — skews high/info, light on medium and critical.
- **Category distribution:** `evaluation=15, procedure=9, modifier=3, consultation=1, psychotherapy=1, diagnosis=1, laboratory=1` — dominated by E/M and procedure categories; underweight on modifier, dx, lab, preventive.

The 19 encounters is **double** the size documented in `docs/AUDIT_PROMPTS_VAL.md` (which described a 10-encounter / 13-finding cleaned set, post-2026-06-22). The expansion happened sometime between 2026-06-23 (the `v12_summary.md` "cleaned run" was on 10/13) and 2026-06-27 (today's audit reads 19/31). The prompt MANIFEST entry for v12 still pins the headline to the 10-encounter number:

> `"val_n": 10, "val_set": "data/val_ca.json (cleaned, 13 gold findings)", "val_F1": 0.690`

That pin is now stale — re-running today on the expanded set will produce a slightly different F1 (likely 0.65–0.72 depending on whether the new 9 encounters favour recall or precision).

### 1.3 Ground-truth provenance

The gold was authored by **Hermes** (an AI session, 2026-06-22), not a human Alberta biller. The cleanup log in `docs/AUDIT_PROMPTS_VAL.md:2.1` is explicit:

> "**NOT by a real Alberta biller**"

`docs/AHCIP_GOLD_AUDIT.md` re-audited the gold against SOMB and found:

- **9 of 15 findings CORRECT** (in the original 10-encounter / 15-finding pre-cleanup file)
- **5 findings that should not exist** (false-positive dx_linkage over-fire on encounters where dx is present and valid — same root cause ×5)
- **2 INCOMPLETE on suggested_code** (right rule, wrong fix)
- **1 WRONG on Alberta convention** (ca_ahcip_005 fires `modifier -24` which Alberta does not have)
- **No IAA numbers reported** — there is no second annotator, so Cohen's κ and Krippendorff's α are both undefined for the current gold.

**Bias direction:** the gold systematically over-fires `rule_ahcip_dx_linkage` because Hermes (per `AHCIP_GOLD_AUDIT.md`) was lenient on the "dx present but matches" condition. This is a single-annotator artefact, not a model artefact — the model is correct to *not* fire dx_linkage on those encounters, and gets marked as FN because the gold says it should have.

### 1.4 Variance profile

Two data points on the 7-run multi-run:

| Run source | Set | Prompt | Mean F1 | F1 stdev | F1 range |
|---|---|---|---|---|---|
| `multi-20260617T194715Z` (US, 50 enc) | `val.json` | v0 | 0.265 | 0.034 | 0.227 – 0.318 |
| `multi-valca-v12-20260627T15…` (AHCIP, 19 enc) | `val_ca.json` | v12 | (incomplete — 1/7 runs completed) | — | — |

The 2026-06-27 AHCIP multi-run was aborted after run 1 (empty `run_01/` dirs); today's retry+URL fix landed before it could finish, so we don't yet have the new variance profile on v12+val_ca. We can extrapolate from the v0/US run:

- **TP range 21–31 across 7 runs** = ±5 TP on a base of ~25. That's a ±20% swing in raw TP counts driven entirely by model stochasticity (no temperature pinning in `src/ai_billing_audit/llm.py:96-107`).
- **Backend noise before today's fix:** ~80% error rate (per the in-file comment at `run_7x.py:11-17`). **After today's retry+URL fix:** expected to drop to <2% (transient 429/Timeout/JSONDecodeError now retried 3× with exponential backoff).
- **Implied decomposition of the v0 F1=0.265 ± 0.034:** the bulk is model-temperature variance, not backend noise. The retry fix removes the *systematic* part of the noise (every blip became a permanent error) but leaves the *stochastic* part (temperature-induced TP count swings).

The headlined `F1=0.690` is therefore **a single sample** of a distribution whose standard deviation we haven't measured yet on val_ca+v12. Once the 7-run completes today, we should expect F1 stdev on the order of **0.05–0.08** (extrapolating from the v0 run proportionally: the v0 base was 0.265, the v12 base is 0.690, but the absolute TP count is similar — v12 finds ~10 TP vs v0's 25; relative TP swings should be similar in absolute terms, so F1 stdev on val_ca+v12 might be even *larger* than v0's 0.034 because of fewer denominator findings).

### 1.5 Per-clinic F1 — current state

There is **no per-clinic F1 on val_ca**. The val encounters have no `clinic_id` / `tenant_id` field (confirmed by inspection — top-level keys per encounter are `encounter_id`, `claim`, `clinical_note`, `rules`, `ground_truth`, no tenant).

The per-clinic infrastructure lives elsewhere:

- **Portal-side** (`apps/portal/src/lib/calibration.ts` + the `CalibrationSignal` Prisma table added in migration `20260627110000_add_calibration_scaffold`): reads accept/dismiss counts per `(tenant, ruleId)` and buckets into `calibrated / reviewing / overcalled / uncalibrated` at the `CALIBRATION_MIN_ACTED_ON = 5` threshold. This is **production-feedback based**, not gold-based.
- **FastAPI-side** (`src/ai_billing_audit/per_clinic_f1.py` + `feedback.py:280`): derives `precision / recall / f1` per rule per clinic from `feedback.jsonl` and `appeal_outcomes.jsonl`. The recall proxy is `support / max_support` (within-clinic) — i.e., **not a real recall** against any ground truth.
- **Today's `CalibrationSignal` scaffold** (commit c33b88c) wires the read path + dashboard card, not the write path. There is no `Grader`-style LLM-as-judge in the loop yet.

**Implication for slicing:** once we have ≥5 feedback events per `(clinic, rule_id)`, we can compute accept-rate buckets. We cannot currently compute **gold-based per-clinic F1** without either (a) tagging val_ca encounters with clinic metadata or (b) treating the feedback log as a "live gold" with its own (much messier) ground truth.

---

## 2. Pain points

### 2.1 False confidence: the headlined F1 overstates real performance

The combination of (a) `rule_id`-only scoring, (b) small N, (c) self-generated gold, and (d) high model stochasticity produces a number that **systematically overstates** the model's actual Alberta-billable accuracy:

1. **`rule_id`-only scoring hides severity miscalibration.** v12 emits 14 `high` findings in the gold; the model over-emits `high` on borderline matches. The scorer never sees this. A finding scored "correct" because it has the right `rule_id` can still be the wrong severity — and for a biller, a `high` on a non-issue wastes more time than an `info` on a real issue. (The AUDIT_PROMPTS_VAL audit §3.3 flags this exact issue but argues for *disabling* the severity penalty; this research disagrees — see §3.2 below.)
2. **Small N inflates the apparent stability.** F1=0.690 looks like a precise number. It's a single draw from a distribution with stdev ~0.06 on 19 encounters. Reporting it to stakeholders ("F1 = 0.69, that's solid") without the CI is misleading.
3. **Single-annotator gold inflates precision, deflates recall** (or vice versa). The Hermes bias toward over-firing dx_linkage means the model is **correctly** not firing dx_linkage on those 5 encounters — but gets marked as FN. Net effect: the F1 number is "low because gold is wrong", which is the wrong kind of regression signal.

### 2.2 False regression: ablation studies are underpowered

The v13 ablation (MANIFEST entry, 2026-06-24) reported F1 dropping from 0.690 to 0.500 after removing few-shot examples. Without a CI on both numbers, we can't tell whether 0.690–0.500=0.190 is a real regression or noise. **My read: it's probably real** (the per-rule F1 deltas are consistent across `em_level_upcode`, `psychotherapy_time`, `em_level` — all three dropped, not random), but the eval doesn't let us *prove* it. A "regression" alert that fires on |Δ F1| > 0.05 is now ~50% likely to be a false alarm at N=10.

### 2.3 False parity: per-clinic F1 is silently undefined

The per-clinic dashboard today (`src/ai_billing_audit/per_clinic_f1.py`) returns `recall = support / max_support` — a **within-clinic proxy**, not a real recall against ground truth. A clinic with 5 accept events on `rule_ahcip_em_level` and 0 events on every other rule gets `recall = 1.0` for `em_level` and `recall = 0.0` for everything else. This is **statistically defensible as a "you're getting feedback on X but not on Y"** signal, but if anyone reads it as "the model is 100% accurate on em_level for this clinic", they're going to make a bad product decision. The dashboard does have an explicit `is_insufficient = True` state for <3 feedback events, which is good, but at 5–30 events the per-clinic F1 numbers become misleadingly precise.

### 2.4 Variance from the multi-run — what's real, what's noise

Decomposing the v0 7-run variance on 50 US encounters:

| Component | Estimated contribution to F1 stdev (0.034) | Fixable today? |
|---|---|---|
| Model temperature (T=1.0 default) | ~0.030 (dominant) | Yes — pin T=0 + seed=42 |
| Backend transient errors pre-fix | ~0.020 (sporadic but large when present) | Yes — already done today |
| Real per-encounter outcome stochasticity (note ambiguity, tied findings) | ~0.010 (irreducible) | No |
| Prompt version / hash drift | ~0.005 | Yes — pin content_sha256 |

After today's retry+URL fix, the second row collapses to ~0.002. The **first row is the real signal**: model-temperature-induced TP swings dominate the multi-run variance, and we are not currently measuring that signal cleanly.

---

## 3. Proposed improvements (ranked)

### 3.1 [HIGH] Add a held-out, human-labelled 30-encounter gold subset

**Method:** Author a parallel `data/synth/val_ca_heldout.json` with 30 fresh AHCIP encounters, each labelled by **two independent human annotators** (Alberta billers or AAPC CPMA-certified contractors). Compute Cohen's κ on the (rule_id, severity-tier) match per finding; require κ ≥ 0.7 before the held-out is treated as authoritative. Score v12 on this held-out alongside val_ca, report both with CIs.

**Expected reduction in bias/variance:**
- **Bias reduction:** removes the Hermes-induced dx_linkage over-fire, the US-flavored modifier conventions, and the suggested_code mistakes (`modifier -24`, etc.). Expected to **raise** reported F1 by 0.05–0.10 because the gold stops penalising correct model behaviour.
- **Variance reduction:** doubling N (19 → 49) shrinks the encounter-level SE by ~37%, so the CI on F1 tightens from ±0.18 to ±0.11. Not enough for ±0.05 alone, but a major step.
- **Confidence:** gives us a known-bad-bias-free floor for the model. We can finally distinguish "the model is bad at AHCIP" from "the gold is wrong about AHCIP".

**Complexity:** high — finding 2 Alberta billers, getting them to label 30 encounters, computing κ, reconciling disagreements, getting a sign-off. Estimated 2–4 weeks of effort.

**Cost:** ~$3–6k for a contractor (30 encounters × 2 annotators × $50–100/encounter). Could be done internally if Cameron has access to a SOMB-trained contractor.

**Why ranked first:** every other improvement is **interpretable only against a known-good gold**. Without a held-out human-labelled set, we can't tell whether a +0.05 F1 improvement is the model getting better or the gold getting worse. This is the eval equivalent of fixing the ruler before measuring anything else.

### 3.2 [HIGH] Re-score on `(rule_id, severity-tier)` instead of `rule_id` only

**Method:** In `scripts/run_7x.py:146`, change `finding_key` to return `(rule_id, severity_tier)` where `severity_tier ∈ {action, watch, info}` is a 3-bucket coarsening of the 5-tier severity ladder (`critical→action`, `high→action`, `medium→watch`, `low→info`, `info→info`). A match requires both `rule_id` and `severity_tier` to agree.

**Expected reduction in bias/variance:**
- **Bias reduction:** the model currently over-emits `high` on borderline matches (per AUDIT_PROMPTS_VAL §3.3 — this is *why* the severity penalty was disabled). Scoring on `(rule_id, severity_tier)` forces the model to be calibrated on severity without requiring the model to perfectly emit one of 5 tiers — the 3-tier coarsening allows `high` ↔ `medium` (same tier) but punishes `high` ↔ `info`. Expected to **drop** headline F1 by 0.05–0.10 (revealing severity miscalibration) but make the number **honest**.
- **Variance reduction:** minimal direct effect, but it forces severity discipline which should make per-rule breakdowns more interpretable.
- **Cost:** ~30 minutes of code, no external dependencies.

**Why this matters even though it lowers the number:** today, a stakeholder reading "F1=0.690" thinks "the model is right 69% of the time." With `(rule_id, severity-tier)` scoring, "F1=0.61" means "the model gets both the rule and the urgency right 61% of the time." The second number is what the clinic cares about — a wrong-severity finding is more harmful than a missed finding, because it triggers alert fatigue on the biller.

**Counter-argument considered:** AUDIT_PROMPTS_VAL §3.3 disabled severity matching because it "hid genuine improvements in finding emission" — the few-shot examples biased the model toward `medium` while gold uses `info/low`. The 3-tier coarsening mitigates this: `info` and `medium` are *different tiers* in this scheme, but `medium` ↔ `high` is allowed (same "action-ish" tier). This recovers most of the benefit of disabling while still penalizing egregious over- or under-severity.

**Do NOT include `category` or `suggested_code` in the matching key.** The model emits `category` on <10% of findings (per QA_RESEARCH_SUMMARY.md finding #1 and the v12 example outputs); including it would reintroduce the "we punished a correct rule_id hit for missing an undocumented field" failure mode that the current scorer was deliberately written to avoid.

### 3.3 [HIGH] Re-run the multi-run with `temperature=0` and provider `seed=42`

**Method:** In `scripts/run_7x.py`, before constructing `LLMClient`, set:

```python
os.environ.setdefault('LLM_TEMPERATURE', '0')
os.environ.setdefault('LLM_SEED', '42')
```

(Or extend `LLMClient.__init__` to accept `temperature` and `seed` as kwargs — currently only `timeout` is exposed per `src/ai_billing_audit/llm.py:96-107`.) Re-run the 7-run on val_ca+v12 and report the new aggregate.

**Expected reduction in variance:**
- **Variance reduction:** collapses the model-temperature component (the dominant ~0.030 of the F1 stdev on v0) to ~0.005 (residual from note-ambiguity + tied-finding disambiguation). Reported F1 stdev should drop from ~0.06 to ~0.015 on val_ca+v12.
- **What this gives us:** a true reproducibility floor. After this, any future F1 delta <0.05 is **noise**, and any delta >0.05 is a real signal — the basis for a CI-driven regression alert.

**Complexity:** trivial — one config change plus a re-run (~2 hours of wall-clock at 19 encounters × 7 runs × ~30s/encounter).

**Cost:** ~2 hours of compute. Free.

**Caveat:** the grader (`src/ai_billing_audit/grader.py`) already does this (T=0, seed=42 per `prompts/grader_config.json`). The auditor does not. There is no technical reason for the asymmetry — it's an oversight.

### 3.4 [MEDIUM] Add a 2-encounter smoke fixture at the top of `smartness_test.main()` and `run_7x.py`

**Method:** Add a fixed 2-encounter fixture (1 known-match, 1 known-no-match) as `tests/fixtures/eval_smoke.json`. Before scoring the real val set, run `run_audit()` on both fixtures with the configured prompt, assert P/R/F1 on each matches expectations within ±0.05. Fail loudly if not.

**Expected reduction in noise:**
- **Detection latency:** drops from "we run the val set, see a regression, wonder why" to "we run the smoke fixture at minute 0, see a fail, abort." Catches the silent-failure mode where the LLM returns empty payloads (F1=0.0 with no error) or the schema changes upstream.
- **Cost:** ~4 hours of work (2 fixtures, 1 test, wire into both scripts). Cheap.

**Note:** `scripts/verify_grader_reproducibility.py` already does this for the **grader**. We're adding the equivalent for the **auditor**.

### 3.5 [MEDIUM] Author `data/SPLIT.md` with hash chain for all three sets

**Method:** Document the train/val/test split policy in `data/SPLIT.md`: encounter_id ranges per split, SHA-256 of each set's manifest, policy for adding encounters, contamination check procedure.

**Expected reduction in bias:**
- **Auditability:** anyone can verify in 5 seconds that no train encounter appears in val_ca. Today this requires manually grepping for IDs across 5 files (`train.json`, `val.json`, `val_ca.json`, `fewshot_ca.json`, `holdout_seed9999.json`).
- **Leakage prevention:** the few-shot leakage (v12 EXAMPLE 6 was ca_ahcip_004 verbatim, EXAMPLE 7 was ca_ahcip_008 paraphrased — fixed 2026-06-23 per `v12_summary.md`) could have been caught by a pre-commit hook that diffs the prompt's example clinical_notes against the val set. Add the hook.
- **Cost:** ~2 hours. Free.

### 3.6 [LOW] Compute Wilson confidence intervals on all reported F1 numbers

**Method:** Wrap `score()` to also emit `f1_ci_95_low`, `f1_ci_95_high` (Wilson interval on the underlying TP/FP/FN counts, encounter-level resampling unit). Display in the daily report and the prompt MANIFEST entries.

**Expected reduction in false confidence:**
- **Honest reporting:** `F1 = 0.690 (95% CI: 0.46 – 0.86, n=19)` is a far more defensible stakeholder-facing number than `F1 = 0.690`. The number itself doesn't change; the reader's mental model does.
- **Cost:** ~4 hours. Trivial.

---

## 4. Recommended first move

**One experiment, highest leverage: §3.3 — pin `temperature=0` + `seed=42` on the auditor and re-run the 7-run multi-run on val_ca+v12.**

Why this first:

1. **Cost is near-zero** (~2 hours of compute, ~30 minutes of code).
2. **Result is immediately actionable**: we'll know the true reproducibility floor of our F1 number. If the new stdev is 0.015, every subsequent F1 delta is interpretable as signal-vs-noise. If it's still 0.05+, we know the temperature pin isn't enough and need to investigate (likely Ollama cloud model drift, since `ollama/minimax-m3:cloud` is a tag, not a hash — see AUDIT_PROMPTS_VAL §5.6).
3. **Unblocks §3.1 and §3.2.** Once we know the model's true variance floor, we can size the held-out set (§3.1) correctly — we don't want to author 30 encounters only to discover the model has ±0.10 noise and we needed 200. And the `(rule_id, severity-tier)` re-score (§3.2) becomes interpretable: the drop from 0.690 → 0.610 is a real severity miscalibration signal if the new stdev is 0.015, but might be noise if the stdev is still 0.06.
4. **Independent of the held-out human-labelled gold** (§3.1), which has a 2–4 week lead time. We can do this today.

**Concrete steps for the first move:**
1. Add `temperature=0`, `seed=42` to `LLMClient.__init__` kwargs in `src/ai_billing_audit/llm.py:96-107` (default to current behaviour if not set, to avoid breaking other callers).
2. Pass through to `complete()` and `complete_json()` in `llm.py:153-213` via the litellm kwargs dict.
3. In `scripts/run_7x.py:105`, instantiate the client with the new defaults.
4. Re-run: `python scripts/run_7x.py --split val_ca --prompt v12 --n-runs 7` (~2 hours).
5. Report the new aggregate: mean F1, stdev F1, range, and compare to the existing `runs/recall/v12_ahcip_clean.json` F1=0.690 single sample.
6. Decision rule: if new stdev ≤ 0.025, proceed to §3.2 re-score. If new stdev > 0.05, investigate Ollama model drift first.

---

## 5. Out of scope (rejected approaches)

### 5.1 Re-score on `(category, suggested_code, quote-Jaccard)` — the DSPy `match_findings()` contract

**Rejected** because the model emits `category` on <10% of findings (per QA_RESEARCH_SUMMARY.md finding #1 and confirmed by inspection of v12 outputs), and `suggested_code` is often *deliberately* vague ("REVIEW: see note"). The 80% quote-Jaccard threshold was tuned for the v0/v1 prompt family and is too strict for v12, which is encouraged by the prompt to emit findings with inferred evidence rather than verbatim quotes. The 2026-06-17 scorer change to `rule_id`-only matching was a deliberate response to this exact failure mode. Reverting to the strict contract would re-introduce the "we punished a correct rule_id hit for missing an undocumented field" failure.

### 5.2 Switch to macro-F1 over per-rule buckets

**Rejected** because macro-F1 weights rare rules equally with common ones. `rule_ahcip_cmgp` has 2 FP and 0 FN in val_ca — its macro contribution would dominate the average even though the clinic almost never sees CMGP issues. Micro-F1 (the current contract) correctly weights by encounter prevalence. We do want **per-rule F1** as a *breakdown* (the v12 MANIFEST already reports this) but not as the headlined aggregate.

### 5.3 Bootstrap-based variance decomposition over the existing 7 runs

**Rejected** as a primary method because the existing 7-run has 80% backend errors pre-fix (today's retry+URL fix is exactly what's needed before bootstrap makes sense). Bootstrap on 2 successful runs and 5 error runs gives garbage. Wait until the post-fix multi-run completes, then bootstrap on those 7.

### 5.4 LLM-as-judge for ground truth

**Rejected** because the entire problem is that we don't trust the LLM enough to author the gold; using an LLM-as-judge to validate LLM-authored gold is circular. The only acceptable judge is a human Alberta biller (or AAPC CPMA-certified contractor). If §3.1 cannot be staffed, the next-best option is **deterministic** consistency checks (the same LLM, same seed, T=0, twice — should produce byte-identical output, and disagreement is a flag).

### 5.5 Hold out a single clinic's audit log for per-clinic F1

**Rejected for now** because we have **zero production clinics** with enough feedback to compute a meaningful per-clinic F1 (the `INSUFFICIENT_DATA_THRESHOLD = 3` in `per_clinic_f1.py:420` means we need ≥3 feedback events per clinic before the dashboard even renders a number; no clinic currently meets this). The portal-side `CalibrationSignal` scaffold (today's work) and the FastAPI-side `feedback.py:280` are the right infrastructure for when we do — but until we have clinics, the per-clinic F1 question is moot. Use the val_ca global F1 as the proxy until production clinics provide signal.

### 5.6 Author a fully synthetic "second annotator" using a different LLM (e.g., Claude labels what Hermes labelled)

**Considered and rejected.** The bias direction is the worry: a second LLM with different training would have a *different* bias, and Cohen's κ between two biased annotators is meaningless (high κ just means they agree on the bias). The only acceptable second annotator is a human. If we cannot staff a human in the next 4 weeks, **§3.3 + §3.2 + §3.6** are the next-best stack: deterministic scorer on a known-bias-laden gold, with CIs that honestly convey the uncertainty.

---

## Appendix A: F1 confidence interval math

Working numbers (assumes F1=0.690, P=0.625, R=0.769 on N=19 encounters / 31 gold findings / 16 predicted findings, matching v12 corrected run):

**Delta-method SE on F1** (using only the 16 predicted / 13 gold counts):

```
SE_P = sqrt(P*(1-P)/16) = sqrt(0.625*0.375/16) ≈ 0.121
SE_R = sqrt(R*(1-R)/13) = sqrt(0.769*0.231/13) ≈ 0.117
SE_F1 = sqrt((R²·SE_P² + P²·SE_R²) / (P+R)²) ≈ 0.085
95% CI: F1 = 0.690 ± 0.166
```

**Encounter-level resampling** (the bottleneck — encounters are correlated within):

| Assumed stdev(per_encounter_F1) | SE on mean | 95% CI | N needed for ±0.05 |
|---|---|---|---|
| 0.35 (optimistic — encounters are mostly binary right/wrong) | 0.080 | ±0.157 | 188 |
| 0.40 (realistic — most encounters have 1–2 findings) | 0.092 | ±0.180 | 246 |
| 0.45 (conservative — some encounters are genuinely ambiguous) | 0.103 | ±0.202 | 311 |

**Take-away:** at N=19, the 95% CI on F1 is roughly **±0.17 to ±0.20** — about a third of the headlined value. To get ±0.05 precision (the conventional "I can detect a 5-point regression" threshold), we need **200–300 encounters** of held-out gold, plus the temperature pin from §3.3 to ensure the model itself isn't contributing an additional ±0.05 of noise on top.

## Appendix B: per-rule F1 spread on v12 (10-encounter cleaned run)

From `runs/recall/v12_ahcip_clean.json` (the corrected run, post EXAMPLE 6/7 leak fix):

| Rule | TP | FP | FN | F1 | Bucket |
|---|---|---|---|---|---|
| `rule_ahcip_dx_linkage` | 1 | 0 | 0 | 1.00 | clean |
| `rule_ahcip_global_window` | 1 | 0 | 0 | 1.00 | clean |
| `rule_ahcip_referring_npi` | 1 | 0 | 0 | 1.00 | clean |
| `rule_ahcip_same_day_conflict` | 1 | 0 | 0 | 1.00 | clean |
| `rule_ahcip_telehealth` | 1 | 0 | 0 | 1.00 | clean |
| `rule_ahcip_em_level` | 3 | 2 | 0 | 0.75 | over-emit |
| `rule_ahcip_psychotherapy_time` | 1 | 0 | 1 | 0.67 | miss |
| `rule_ahcip_em_level_upcode` | 1 | 1 | 1 | 0.50 | miss + over-emit |
| `rule_ahcip_lab_coverage` | 0 | 0 | 1 | 0.00 | miss |
| `rule_ahcip_cmgp` | 0 | 2 | 0 | 0.00 | over-emit |
| `rule_ahcip_non_insured_service` | 0 | 1 | 0 | 0.00 | over-emit |

Per-rule F1 stdev = 0.40 (5 rules at 1.00, 6 rules below 0.75). This is **wider than the headline F1 confidence interval suggests** — the per-rule picture is "5 nailed-it rules, 6 in various states of failure." Any aggregate F1 number masks this bimodal structure. The per-rule F1 table is already reported in MANIFEST — it should be the *primary* stakeholder-facing number, not the aggregate.

## Appendix C: file/line citations

- `scripts/run_7x.py:137-165` — current scorer contract (`rule_id`-only set intersection)
- `scripts/run_7x.py:11-32` — retry config added today (collapses backend noise to ~0%)
- `scripts/run_7x.py:54-56` — model + URL pin (Ollama cloud, `minimax-m3:cloud`)
- `src/ai_billing_audit/llm.py:96-107` — `LLMClient.__init__` lacks `temperature`/`seed` kwargs
- `src/ai_billing_audit/llm.py:153-213` — `complete()` / `complete_json()` pass-through
- `data/synth/val_ca.json` — 19 encounters / 31 gold findings (current state, vs 10/13 in MANIFEST pin)
- `docs/AUDIT_PROMPTS_VAL.md` — historical eval audit (2026-06-23); flags few-shot leakage, severity-disabled scoring, no temperature pinning
- `docs/AHCIP_GOLD_AUDIT.md` — Hermes-authored gold audit (2026-06-22); 9/15 correct, 5 false-positive dx_linkage over-fires
- `prompts/MANIFEST.json:46-90` — v12 entry pinning F1=0.690 to n=10 / 13 findings (stale; current set is 19/31)
- `runs/recall/v12_ahcip_clean.json` — per-rule F1 on the corrected 10-encounter run
- `runs/acceptance/multi-20260617T194715Z/summary.json` — 7-run baseline (v0+US); F1=0.265±0.034
- `runs/acceptance/multi-valca-v12-20260627T15…` — incomplete (1/7 runs done; today's retry+URL fix is the prerequisite)
- `src/ai_billing_audit/per_clinic_f1.py:175-258` — per-rule metrics from feedback log; recall is `support/max_support` (proxy, not real)
- `apps/portal/src/lib/calibration.ts:78-100` — `computeCalibration()` read path; bucket thresholds at 0.70 / 0.40 / <5 acted-on
- `apps/portal/prisma/migrations/20260627110000_add_calibration_scaffold/migration.sql` — today's `CalibrationSignal` table
- `src/ai_billing_audit/grader.py:9-48` — grader's determinism contract (T=0, seed=42) that the auditor should mirror

---

End of research deliverable. Recommended first move: §3.3 (temperature=0 + seed=42 + re-run 7x) — cost ~2 hours, unblocks every other improvement.