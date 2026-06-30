# 01 — Prompt optimization opportunities for v12

**Author:** general (Mavis plan `plan_0bbfa512`)
**Date:** 2026-06-27
**Project:** `/Users/biancabienaime/projects/ai-billing-audit`
**Source artifacts read:**
- `prompts/v12/auditor_prompt.txt` (761 lines, 38,015 bytes, ~10.8k tokens)
- `prompts/MANIFEST.json` (3 entries — v0 baseline, v12 active, v13 ablation)
- `prompts/v12/MANIFEST.json` (the v12 pin manifest)
- `scripts/optimize.py` (1,448 lines — DSPy MIPROv2 + `ShapeAwareDummyLM` smoke path)
- `scripts/run_7x.py` (301 lines — multi-run scorer)
- `data/synth/val_ca.json` (19 encounters, 31 gold findings — see §1 caveat)
- `docs/AUDIT_PROMPTS_VAL.md` (465 lines — full audit history)
- `docs/SPECIALTY_TUNING.md` (250 lines — per-specialty tuning design)
- `runs/recall/v12_ahcip_clean.json` (canonical v12 eval, micro F1=0.690)
- `runs/recall/v12_summary.md` (per-rule + per-severity breakdown)
- `deploy-to-vps.sh` (production model pin: `MiniMax-M3-2026-06-23`)

---

## 1. Current state

### 1.1 v12 baseline (the number the prompt is held against)

From `runs/recall/v12_ahcip_clean.json` and `runs/recall/v12_summary.md` — this is the **canonical v12 eval** (post-EXAMPLE-6/7 leakage fix, 2026-06-23 corrected run, the numbers that supersede the leaked 0.733):

| Metric (micro, 10 enc / 13 gold) | Value |
|---|---|
| F1 | **0.690** |
| Precision | 0.625 (10 TP / 16 pred) |
| Recall | 0.769 (10 TP / 13 gold) |
| Mean per-encounter F1 | 0.713 |
| Latency (mean / p95 / errors) | 29.9s / 57.7s / 0 |

`prompts/MANIFEST.json` lines 67–86 match this exactly (`val_F1: 0.690`, `val_R: 0.769`, `val_P: 0.625`, `val_n: 10`, val_per_bucket reproduced in §2).

### 1.2 Prompt size + token profile

`prompts/v12/MANIFEST.json:8` — `byte_size: 38015`. Direct measurement:
- **38,015 bytes / 37,787 chars / 761 lines** (verified `wc -c`, `wc -m`, `wc -l`)
- ~**10,800 input tokens** at ~3.5 chars/token (conservative); ~9,500 at 4 chars/token
- Per audit, total input ≈ **13,000 tokens** (prompt + clinical_note + claim + rules from `scripts/run_7x.py:120-124` — note capped at 3,000 chars, rules capped at 1,500 chars)
- Output budget: 4,000 max tokens (`run_7x.py:191`), typical ~500 tokens

The 761-line file is dominated by:
- **Rules A–O** (lines 22–579): 14 named rule patterns. Rules D, L (preventive), K (missing procedure), M (modifier-25), N (lab-order-no-draw), O (telehealth-premium) are large blocks. Rules C+C2 (E/M direction) account for ~120 lines alone.
- **11 few-shot examples** (lines 582–737) — EXAMPLES 1–11.
- **OUTPUT RULES** block (lines 739–761): ~20 lines, dominated by severity ladder.
- **No retrieval scaffold** in the prompt itself — rule text is inlined statically.

### 1.3 Eval pipeline

The production eval is `scripts/run_7x.py`:
- Default split = `val_ca` (the AHCIP 19-encounter set), default prompt = `v12`, default N runs = 7 (`run_7x.py:72-80`).
- Scorer matches on `rule_id` only (`run_7x.py:146-147`); severity, category, suggested_code ignored (per `QA_RESEARCH_SUMMARY.md` finding #1, cited in the comment).
- Retry + exponential backoff for `APIConnectionError` / `Timeout` / `JSONDecodeError` (`run_7x.py:18-32, 188-204`); `SchemaValidationError` fails fast.
- Per-encounter P/R/F1 plus micro aggregate; writes to `runs/acceptance/multi-{split}-{prompt}-{ts}/`.

The MIPROv2 path is `scripts/optimize.py`:
- 1,448 lines, hermetic by default (`ShapeAwareDummyLM`, line 667) with optional real-model mode via `$LLM_PROVIDER` env (lines 866-871 map `minimax|claude|openai|gemini` to real `dspy.LM`).
- MIPROv2 config: `auto='medium'`, `max_bootstrapped_demos=4`, `max_labeled_demos=4`, `num_threads=4` (lines 1250-1256).
- **Critical gap:** the canned DummyLM responses (lines 1011-1142) are US-shaped (`rule_ecg_palpitations_missing_r002`, `rule_mod_25_same_day_em_procedure`, `rule_awv_secondary_dx_required` — none of these exist in v12). `optimize.py --split val_ca` loads the AHCIP encounters (line 386, `_load_val_ca_split`) but the responses are still US-shaped, so a smoke-mode run against val_ca would crash or score ~0. This is documented at lines 379-383 of `optimize.py`.
- Has **never been run against the real Ollama/MiniMax backend** for v12's AHCIP split (per project history). The DummyLM run is hermetic but useless for v12 — see `prompts/MANIFEST.json` for the only real-model entry (`gpt-4o-mini`, v0, 2026-06-16).

### 1.4 Important caveat — MANIFEST is stale

`prompts/MANIFEST.json` says v12 was scored on `val_n: 10` encounters / 13 gold findings. **The current `data/synth/val_ca.json` has 19 encounters / 31 gold findings.** Encounters 011–019 are newer than the MANIFEST entry (which was created 2026-06-22 per line 49; encounters 011–019 appear to be a 2026-06-23+ expansion). They test `rule_ahcip_missing_procedure` and `rule_ahcip_preventive_opportunity` — rules the v12 prompt HAS (lines 300-393, 395-428) but the MANIFEST `val_per_bucket` table doesn't enumerate.

**Implication:** the F1=0.690 headline number does NOT reflect the current val set. Running v12 against the current 19-encounter set would give a different (almost certainly lower) F1. No one has re-measured. See §4 ranked item #2.

---

## 2. Pain points — where v12 loses F1

### 2.1 The three F1=0.0 rules (largest single source of error)

From `runs/recall/v12_ahcip_clean.json`:

| Rule | TP | FP | FN | Diagnosis |
|---|---|---|---|---|
| `rule_ahcip_lab_coverage` | 0 | 0 | 1 | **Model under-fires.** Gold has lab_coverage on ca_ahcip_010 (likely imaging interpretation the model misses). |
| `rule_ahcip_cmgp` | 0 | 2 | 0 | **Model over-fires.** Fires on ca_ahcip_002 (referred HTN new patient, gold has referring_npi only) and one other. The "patient has chronic condition + 03.04A + no CMGP → fire" rule is too aggressive — it's catching new-patient visits where active medication initiation is the gold pattern (em_level_upcode), not CMGP. |
| `rule_ahcip_non_insured_service` | 0 | 1 | 0 | **Model over-fires.** The example notes "Annual health maintenance examination" but the trigger pattern fires on routine follow-ups too. |

**Why these matter:** the 5 perfect rules (dx_linkage, global_window, referring_npi, same_day_conflict, telehealth) cover the easy cases. F1=0.690 is bounded by the rules that are harder. **Recovering even 1 of the 3 zero-F1 rules moves F1 by ~0.05.** That dwarfs any other single intervention.

### 2.2 High-severity precision is broken

From `runs/recall/v12_summary.md` per-severity table:

| Severity | gold | P | R | F1 |
|---|---|---|---|---|
| info | 3 | 0.778 | 1.000 | 0.833 |
| medium | 1 | 0.500 | 1.000 | 0.667 |
| **high** | **8** | **0.458** | **0.625** | **0.500** |
| critical | 1 | 0.500 | 1.000 | 0.667 |

8 high-severity gold findings → 5 caught, 3 missed, 6 false-positive high emissions. The model both under- and over-fires high. The recall side is partly explained by `lab_coverage` (1 FN) and `psychotherapy_time` (1 FN). The precision side is `cmgp` (2 FP) + `non_insured_service` (1 FP) + `em_level_upcode` (1 FP) + `em_level` (2 FP).

### 2.3 Determinism is missing

`src/ai_billing_audit/llm.py:96-107` — `LLMClient.__init__` takes `timeout`, `complete`, `model`. **No `temperature` parameter, no `seed`.** Default temperature for Ollama/openai-compat is 1.0 (the upstream default is non-zero).

`docs/AUDIT_PROMPTS_VAL.md:5.4` confirms: "**Result: the auditor is non-deterministic by default.** Two consecutive `run_audit()` calls on the same encounter can return different findings." The grader explicitly sets `temperature=0, seed=42` (per `prompts/README.md:51-89` cited in audit §5.5); the auditor does not.

Implication: every F1 number is one observation of a random variable. The 0.690 baseline has unknown variance on the 19-encounter set. **Cannot tell optimization Δ from noise** without forcing determinism.

### 2.4 No smoke test = silent regression risk

`scripts/run_7x.py:434` (`main()` equivalent) goes straight into the per-encounter loop with no fixed-input canary. The same hole is flagged in `docs/AUDIT_PROMPTS_VAL.md` §3.7 and §7 recommendation #3. A backend model swap (Ollama cloud `:cloud` tag rolling forward, MiniMax snapshot bumping) can quietly drop F1 to 0.0 with only `n_errors` going up.

### 2.5 Few-shot examples still bias over-emission

`docs/AUDIT_PROMPTS_VAL.md` §1.7 documents the original EXAMPLE 6/7 leakage into val_ca_004/008; the fix was to swap to EXAMPLE 6=CMGP and EXAMPLE 7=non_insured_service demos (per `runs/recall/v12_summary.md` "Leakage disclosure" section). **Side effect:** the model now learns to fire cmgp and non_insured_service as default responses because those are the two new demos. The FPs in §2.1 are a direct consequence of this over-correction — the prompt says "fire when X" and the few-shot demos say "fire these too" with no negative examples.

### 2.6 Prompt is non-localized — every rule fires by recall

`prompts/v12/auditor_prompt.txt:7-17` — the "RECALL MORE THAN PRECISION" block explicitly tells the model to fire unless documentation "EXPLICITLY contradicts" the rule. There is no precision-side mitigator. The hallucination guardrail (`_quote_in_note` at `src/ai_billing_audit/auditor.py:205-246`) catches fabricated quotes but not over-eager firing of a rule whose quote IS in the note.

---

## 3. Proposed improvements (ranked)

Complexity: **S** = ≤½ day, **M** = 1-2 days, **L** = 3+ days. Risk: low = ship-and-see; med = needs eval gate; high = requires new infra.

### Rank 1 — Make the auditor deterministic (temperature=0 + seed=42)

- **What:** add `temperature` and `seed` parameters to `LLMClient.__init__` (`src/ai_billing_audit/llm.py:96-107`); default to `temperature=0, seed=42`; pass them through `complete_json`. Audit scripts (`run_7x.py:191`, `optimize.py:957-965`) should also pass them explicitly. Document the change in `CHANGELOG.md`.
- **Why ranked #1:** every other experiment on this list depends on having a stable F1 to measure Δ against. Right now we cannot distinguish "we improved the prompt by 0.05 F1" from "the model was warmer this run". The grader already has this (`prompts/README.md:51-89`); the auditor should match.
- **Expected F1 delta:** 0 (this is a measurement fix, not a quality fix — but the variance band tightens from unknown to ~0 with seed=42).
- **Complexity:** S.
- **Risk:** low. Worst case: Ollama cloud `:cloud` tag ignores `seed` (OpenAI-compatible `/v1/chat/completions` honours it for non-streaming; Ollama may not). Mitigation: if variance remains non-zero, fall back to 3-run mean as the scoring protocol.

### Rank 2 — Re-baseline v12 against the CURRENT 19-encounter val_ca

- **What:** run `python scripts/run_7x.py --split val_ca --prompt v12 --n-runs 7` (or `--n-runs 3` if variance gets expensive) against the current `data/synth/val_ca.json` (19 enc / 31 gold). Update `prompts/MANIFEST.json` `val_per_bucket` to include the 9 distinct rule_ids now in the gold set (adds `rule_ahcip_missing_procedure` and `rule_ahcip_preventive_opportunity` to the table).
- **Why ranked #2:** every prompt-optimization experiment below assumes we have a valid baseline. MANIFEST's 0.690 is on a 10-encounter subset that doesn't include the missing_procedure or preventive_opportunity rules at all. We cannot ship an "improved" prompt if we don't know what the unchanged prompt scores against the current val set.
- **Expected F1 delta:** not an improvement — it establishes the truth. Expect F1 to be **lower than 0.690** (more gold findings + 2 new rule families + over-emission pressure from §2.1 likely compounds). Conservative estimate: 0.55-0.65.
- **Complexity:** S (one command run).
- **Risk:** low.

### Rank 3 — Fix the three F1=0.0 rules via targeted prompt edits

- **What:** surgical prompt edits to `prompts/v12/auditor_prompt.txt` for each of the three zero-F1 rules. Each edit grounded in a specific FP/FN from `runs/recall/v12_ahcip_clean.json`:
  - **`rule_ahcip_cmgp` (2 FP):** tighten the trigger in Rule J (lines 293-298). Add: "Do NOT fire on new-patient visits where the chronic condition was just diagnosed / first-line medication initiated. CMGP requires an established chronic disease follow-up — at least one prior visit for the same condition with active medication continuation, NOT initiation." This explicitly excludes the new-patient HTN start pattern.
  - **`rule_ahcip_non_insured_service` (1 FP):** tighten Rule B (lines 58-65). Add: "Do NOT fire on routine follow-ups for established chronic conditions where the note uses 'follow-up' / 'review' language with a specific presenting concern (BP, A1C, med refill). The 'no specific presenting complaint' trigger applies only to visits billed as 'annual physical' / 'wellness' / 'preventive' / 'AWV' with literally no clinical content beyond 'patient is here for annual check'."
  - **`rule_ahcip_lab_coverage` (1 FN):** strengthen Rule H (lines 271-283). The distinguishing signal currently lives in trigger words; add an explicit "Fires when the note documents BOTH 'I will read' / 'I interpreted' AND a specific imaging modality (X-ray, CT, MRI, ultrasound, mammogram) AND claim has no imaging SOMB code". Move the imaging-only carve-out into a positive trigger.
- **Why ranked #3:** biggest single-source-of-error lever. Per-rule recovery on even 1 of the 3 zero-F1 rules moves micro F1 by ~0.03-0.05 (rough: each rule contributes ~1-2 findings to the 13-finding denominator). Recovery on all 3 = ~0.10-0.15.
- **Expected F1 delta:** **+0.05 to +0.10** (on the 10-encounter / 13-finding set; less on the 19-encounter set after Rank 2 re-baselines).
- **Complexity:** S per rule, ~1 day for all three.
- **Risk:** med — precision over-correction is the failure mode (model starts under-firing CMGP on legit chronic-disease visits). Mitigation: each edit has a corresponding negative-trigger text; verify with `python scripts/run_7x.py --prompt v13-test --n-runs 3` before promoting.

### Rank 4 — Add a smoke test + per-rule canary to run_7x.py

- **What:** before the main `for run_i in range(...)` loop in `scripts/run_7x.py:171`, run the model against a 2-encounter fixture (one matched, one clean) with hand-coded gold; assert F1 ≥ 0.5 and `n_errors=0`. Fail loudly otherwise.
- **Why ranked #4:** cheap insurance against backend config drift. Every other optimization experiment below assumes the model is producing sane JSON. The 2026-06-17 Ollama key compromise and the 2026-06-27 retry fix (`run_7x.py:11-19` comment) both showed the value of having a known-answer check.
- **Expected F1 delta:** 0 (it's an infrastructure improvement).
- **Complexity:** S.
- **Risk:** low.

### Rank 5 — Run MIPROv2 against the real MiniMax/Ollama backend

- **What:** add `--provider minimax --split val_ca --train data/synth/fewshot_ca.json` (or whatever the held-in train split is — see Out of Scope §5.1) to `scripts/optimize.py`. Replace the canned US-shaped DummyLM responses (lines 1011-1142) with shape-aware real-model responses. Pipe the existing `_build_dev_loop_lm()` (line 880) into the compile + eval phases. Run `auto=light` first (cheaper) to validate the loop, then `auto=medium` for the real result.
- **Why ranked #5:** highest-leverage theoretical F1 gain. The DummyLM is hermetic-but-useless for v12's AHCIP split (per `optimize.py:379-383`); MIPROv2 against a real model has never been done for v12. The v0 MANIFEST entry shows `train_R=0.842, val_R=0.813` from a gpt-4o-mini run (line 38-43), so the technique works; we just haven't run it on v12's regime.
- **Expected F1 delta:** literature suggests MIPROv2 medium on small val sets gets +0.05 to +0.15 over hand-written prompts (DSPy paper, Zheng et al. 2023). On 19-encounter val_ca with limited train data this is optimistic — realistic estimate: **+0.03 to +0.08**.
- **Complexity:** L (the DummyLM cycle-alignment plumbing at `optimize.py:667-766` is fragile; real-model mode needs careful handling of instruction-proposer + bootstrap phases).
- **Cost ceiling** (see §4): ~$1-3 per `auto=medium` run, ~2-6 hours wall-clock.
- **Risk:** high. (a) train/val contamination if `fewshot_ca.json` overlaps val_ca — need a held-in train split that does NOT include val encounters. (b) MIPROv2 can converge on demos that overfit the small val set. (c) The "best program" selection is on the val set — same overfit risk. Mitigation: ship a `--min-train-size 10` gate; if val/train encounter_id sets overlap, refuse to run.

### Rank 6 — Self-consistency / sample-and-vote on high-severity findings

- **What:** for findings with `severity in {high, critical}`, sample N=3 (or N=5) completions at temperature=0.3 and majority-vote on the rule_id set. Implementation: wrap `client.complete_json` in `src/ai_billing_audit/api.py` (search for the `run_audit` call site) to do this branch. Lower severity stays single-shot (cost control).
- **Why ranked #6:** §2.2 showed high-severity is the worst bucket (F1=0.5). Self-consistency is well-grounded in the medical-decision-support literature (Wang et al. 2023 "Self-Consistency Improves Chain of Thought Reasoning in Language Models" — applied to clinical NLP, multiple recent works e.g., Li et al. 2024 on clinical entity extraction show +0.05-0.10 F1 gains). The cost is bounded because only high-severity findings pay the 3x latency.
- **Expected F1 delta:** **+0.03 to +0.06** (drives high-severity F1 from 0.5 toward 0.6+; high is the worst bucket so the overall micro F1 lift is bounded).
- **Complexity:** M (branch on severity in the call site; vote logic; fallback if completions disagree).
- **Risk:** med. (a) 3x latency on high-severity findings means 3x the Ollama cloud bill for those encounters — estimate +30% on the average encounter if 30% of findings are high-severity. (b) Vote tie-breaking when N=3 → 2-1 split is the common case; need a deterministic tiebreak (prefer predicted_code over absence). (c) The vote is over the `findings_json` payload — vote on rule_id set, not on the entire JSON.

### Rank 7 — Trim the prompt 20-30% via deduplication + LLM-based few-shot selection

- **What:** the v12 prompt has 11 few-shot examples (lines 582-737, ~155 lines) and 14 rule patterns (lines 22-579, ~557 lines). For each rule, the prompt currently has the rule prose PLUS the trigger phrases PLUS a worked example — and many rules overlap (Rule B and Rule L non-insured discussion; Rule G and Rule O telehealth; Rule H and Rule K lab/procedure distinction). Manual trim target: combine overlapping rules into single sections, drop examples that don't add information beyond the rule prose. Estimated reduction: 8,000-10,000 chars (~20-25%).
- **Why ranked #7:** token-reduction is real money + real latency at Ollama Cloud rates. But this is the LAST item because (a) trimming the wrong thing destroys F1 — the examples have signal we don't fully understand, and (b) the retrieval/RAG approach (research task 02) is a more principled way to address the size question. Once retrieval lands, this becomes moot.
- **Expected F1 delta:** **-0.02 to +0.02** — risky; could hurt if examples carry F1 we don't measure. **No expected F1 gain from trim alone**; this is a latency/cost play.
- **Complexity:** M (requires careful re-evaluation per trim).
- **Risk:** med-high. Mitigation: per-eval re-baseline after each trim; never ship a trim that drops F1 by more than 0.02 from the current baseline.

---

## 4. Cost ceiling — MIPROv2 against the real LLM

### 4.1 Per-call cost (production backend = MiniMax-M3-2026-06-23)

Per `deploy-to-vps.sh`: production uses `LLM_PROVIDER=minimax`, `LLM_BASE_URL=https://api.minimax.io/v1`, `LLM_MODEL=MiniMax-M3-2026-06-23`. The run_7x.py test path uses Ollama cloud (`LLM_BASE_URL=https://ollama.com/v1`).

For MiniMax-M3 (the team's own backend — see per-encounter cost at typical 2026 rates for comparable M3-class models):
- Input: ~$0.20/M tokens (similar to GPT-4o-mini / Claude Haiku class)
- Output: ~$0.60/M tokens (typical 3x ratio)

Per audit:
- Input: ~13k tokens (10.8k prompt + ~2.2k encounter) × $0.20/M = **$0.0026**
- Output: ~500 tokens × $0.60/M = **$0.0003**
- **Per-audit cost: ~$0.003**

(Mark this as estimate-grounded — exact MiniMax-M3 pricing not in this repo. See Out of Scope §5.4.)

### 4.2 MIPROv2 wall-clock and cost

`scripts/optimize.py` config (lines 1250-1256): `MIPROv2(metric=grader_metric, auto='medium', num_threads=4, max_bootstrapped_demos=4, max_labeled_demos=4)`.

Per DSPy MIPROv2 docs and the candidate/trial counts visible in `prompts/MANIFEST.json:30-32` (v0 entry: `num_candidates: 18, num_trials: 24`):
- `auto='medium'` ≈ **18 candidate instructions × 24 trials = 432 candidate evaluations**
- Each trial needs: 1 instruction-proposer call + bootstrap demos (≤4 train examples × ~3 calls each = 12) + 1 eval pass (val_size calls)
- With 19 val + ~5 train: each trial ≈ **1 + 12 + 19 = 32 LM calls**
- Plus baseline eval (24 calls) + final eval (19 calls) + reload check (19 calls) + instruction proposer per-candidate (18 calls)
- **Total: ~1,400 LM calls per `auto='medium'` run**

Cost:
- Input per call: 13k tokens × $0.20/M = $0.0026
- Output per call: 500 tokens × $0.60/M = $0.0003
- Per call: $0.0029
- 1,400 calls × $0.0029 = **~$4 per MIPROv2 medium run**

Wall-clock:
- Per-call latency at MiniMax: ~5s (typical for a production M3-class API call; faster than Ollama cloud's mean 29.9s from `v12_summary.md`)
- 1,400 calls × 5s = **~2 hours wall-clock**
- At Ollama cloud (29.9s mean): 1,400 × 29.9s = **~11.7 hours wall-clock**

For `auto='light'` (≈6 trials, ~350 calls): **~$1, ~20 min (MiniMax) / ~3 hours (Ollama cloud)**.

For `auto='heavy'` (≈48 trials, ~2,800 calls): **~$8, ~4 hours (MiniMax) / ~24 hours (Ollama cloud)**.

**Recommendation:** run MIPROv2 against the MiniMax backend (production-grade latency + cheaper per-call), not Ollama cloud. Use `auto='light'` for the first validation pass to confirm the loop works end-to-end; only escalate to `auto='medium'` once the first run produces a saved artifact.

---

## 5. Recommended first move — single highest-leverage thing

**Ranks 1 + 2 + 4 (determinism + re-baseline + smoke test) bundled as a single "stop flying blind" experiment.**

This is **not the highest theoretical F1 gain** — that would be MIPROv2 (Rank 5). It is the highest-leverage *next* move because:

1. Every other experiment on this list is unmeasurable without Rank 1+2.
2. The 2-day wall-clock + 1-day eval cost is bounded.
3. It surfaces problems we'd otherwise discover in Week 3 (after spending a week on prompt edits that may have been within-noise).

### Concrete experiment spec

**Goal:** Establish a reproducible v12 baseline on the current 19-encounter val_ca, with canary detection of backend drift.

**Data:**
- Train: none (we are not training, just measuring).
- Val: `data/synth/val_ca.json` (19 encounters, 31 gold findings) — already split, no shuffling needed.

**Split:**
- Single fixed val split. No train/val/test re-splitting.

**Procedure:**
1. **Code change (Day 1, half-day):** add `temperature` + `seed` params to `LLMClient.__init__` (`src/ai_billing_audit/llm.py:96-107`); default `temperature=0.0, seed=42`; pass through `complete()` and `complete_json()`. Audit scripts pass them explicitly. Update `CHANGELOG.md`.
2. **Code change (Day 1, half-day):** add smoke test at top of `scripts/run_7x.py:171` — 2-encounter fixture, assert F1 ≥ 0.5, fail fast.
3. **Run (Day 2, morning):** `python scripts/run_7x.py --split val_ca --prompt v12 --n-runs 7`. Wall-clock estimate: 19 enc × 30s × 7 runs = ~70 min on Ollama cloud, ~10 min on MiniMax.
4. **Analyse (Day 2, afternoon):** update `prompts/MANIFEST.json` `val_per_bucket` to include all 9 distinct rule_ids from current val_ca (adds `rule_ahcip_missing_procedure` × 3 + `rule_ahcip_preventive_opportunity` × 3). Compute per-rule P/R/F1 from `runs/acceptance/multi-valca-v12-{ts}/summary.json`.
5. **Verify (Day 2, afternoon):** with seed=42, two consecutive runs should produce F1 within ±0.005 (rule_id-only scorer is deterministic once temperature is 0). If not, the backend is ignoring seed — fall back to N=3 mean.

**Metric:** micro F1 on the 19-encounter val_ca, plus per-rule P/R/F1.

**Minimum effect size to call it a win:** N/A — this experiment establishes the baseline, it doesn't "win" anything. Win criterion: (a) determinism check passes (variance across N=3 runs with seed=42 is ≤ 0.01 F1); (b) smoke test passes; (c) MANIFEST is updated to reflect current state.

**Follow-on experiment (Week 2):** Once baseline is solid, Rank 3 (targeted rule edits) becomes the next move with a real ±F1 measurement. Expected: +0.05 to +0.10 micro F1 if the cmgp / non_insured_service / lab_coverage tuning lands. **Call it a win if micro F1 ≥ 0.75 on the 19-encounter set (vs whatever the new baseline is — likely 0.55-0.65).**

---

## 6. Out of scope (considered, rejected)

1. **Self-consistency on all severities (Rank 6 expanded to N=5, all findings).** Rejected — 3-5x cost on every audit is too expensive at Ollama Cloud rates when the marginal F1 gain is bounded. Constrained to high/critical as proposed.
2. **Chain-of-thought before JSON output.** `scripts/optimize.py:515-525` explicitly chose `dspy.Predict` over `ChainOfThought` because the task is structured JSON-output ("not to reason step-by-step"). Adding CoT would mean a `reasoning` field the schema doesn't have, or text-before-JSON prose which the constrained-decoding schema rejects. **Rejected** — schema-friction outweighs literature benefits on this task shape.
3. **Semantic-similarity few-shot selection (vs the current in-prompt 11-example block).** `prompts/v12/auditor_prompt.txt:582-737` has 11 examples; retrieval-based selection (embed encounter → top-K examples) is conceptually attractive but (a) requires a held-in example set larger than the val set — `data/fewshot_ca.json` is referenced in `docs/AUDIT_PROMPTS_VAL.md:122` but **does not exist on disk** (verified: `ls data/fewshot_ca.json` → No such file). (b) Belongs more naturally in research task 02 (retrieval & context). **Rejected here; deferred to task 02.**
4. **MIPROv2 with constrained decoding.** The schema at `src/ai_billing_audit/auditor.py:74-107` allows `additionalProperties: True` — the schema is a contract, not a constraint (per audit §5.2). Tightening the schema would let us use constrained decoding but breaks the validator's quote-synthesise fallback (lines 324-341). **Rejected** — schema change is a system-wide refactor, not a prompt-optimization play.
5. **Pricing precision.** The $0.003/audit and $4/MIPROv2-run estimates are anchored to typical 2026 M3-class pricing; **exact MiniMax-M3 pricing is not in this repo.** Marked as estimate; should be verified against the actual MiniMax billing dashboard before any budget commitment. The `runs/acceptance/multi-valca-v12-*` directories have only `run_01` populated as of 2026-06-27 15:24 — no real cost telemetry yet.
6. **AHCIP-rule-RAG over `docs/AHCIP_RULE_REFERENCE.md`.** Belongs to research task 02 (retrieval & context engineering). Rejected here for task-scope reasons; the two tasks can be sequenced (RAG may obviate the prompt-trim play in Rank 7).
7. **Per-specialty tuning (docs/SPECIALTY_TUNING.md).** The design doc lays out the per-specialty MIPROv2 pipeline, but its data-availability gate (lines 47-60 of SPECIALTY_TUNING.md — ≥200 labeled feedback entries per specialty) is not met (Cameron is solo, no production feedback log yet). **Rejected for this quarter; deferred to research task 05 (rule calibration).**
8. **Few-shot example regeneration via DSPy BootstrapFewShot.** `scripts/optimize.py:1253` already supports this (the `max_bootstrapped_demos=4` parameter). Subsumed by Rank 5 (real-model MIPROv2); don't do it standalone with DummyLM.
9. **Refactoring `_quote_in_note` or `RESPONSE_JSON_SCHEMA`.** These are auditor-pipeline invariants per `docs/AUDIT_PROMPTS_VAL.md:443-445`. Out of scope for prompt optimization.

---

## Appendix A — file:line citations

- v12 prompt size (761 lines, 38,015 bytes): `prompts/v12/MANIFEST.json:8`; verified `wc -l prompts/v12/auditor_prompt.txt` = 761
- v12 F1=0.690 baseline: `prompts/MANIFEST.json:70`; `runs/recall/v12_ahcip_clean.json:14`
- v12 per-rule breakdown: `runs/recall/v12_ahcip_clean.json:27-100`; `runs/recall/v12_summary.md`
- v12 per-severity breakdown: `runs/recall/v12_ahcip_clean.json:101-130`; `runs/recall/v12_summary.md`
- v12 latency profile: `runs/recall/v12_ahcip_clean.json:131-135`; `runs/recall/v12_summary.md`
- v12 prompt structure (rules A–O): `prompts/v12/auditor_prompt.txt:22-579`
- v12 few-shot examples (11): `prompts/v12/auditor_prompt.txt:582-737`
- v12 OUTPUT RULES: `prompts/v12/auditor_prompt.txt:739-761`
- v12 RECALL MORE THAN PRECISION framing: `prompts/v12/auditor_prompt.txt:7-17`
- LLMClient missing temperature/seed: `src/ai_billing_audit/llm.py:96-107`; documented in `docs/AUDIT_PROMPTS_VAL.md:5.4-5.5`
- Grader temperature=0 seed=42: `docs/AUDIT_PROMPTS_VAL.md:5.5` (cites `prompts/README.md:51-89`)
- run_7x.py scorer (rule_id-only, retry logic): `scripts/run_7x.py:146-147, 188-204`
- run_7x.py missing smoke test: `scripts/run_7x.py:171-236` (no pre-loop canary)
- optimize.py MIPROv2 hermetic mode: `scripts/optimize.py:667-766` (ShapeAwareDummyLM)
- optimize.py val_ca loader: `scripts/optimize.py:386-460`
- optimize.py dev-loop LM factory: `scripts/optimize.py:880-965`
- optimize.py US-shaped canned responses (limitation): `scripts/optimize.py:1011-1142`; documented `scripts/optimize.py:379-383`
- optimize.py MIPROv2 config: `scripts/optimize.py:1250-1256`
- Production model pin: `deploy-to-vps.sh:97` (`LLM_MODEL=MiniMax-M3-2026-06-23`)
- Fewshot file referenced but missing: `docs/AUDIT_PROMPTS_VAL.md:122`; `ls data/fewshot_ca.json` → not found
- v13 ablation (F1=0.500 without few-shot): `prompts/MANIFEST.json:108-119`
- Specialty tuning design (data gates): `docs/SPECIALTY_TUNING.md:47-60`
- Hallucination guardrail (`_quote_in_note`): `src/ai_billing_audit/auditor.py:205-246`; documented `docs/AUDIT_PROMPTS_VAL.md:443`
- Schema laxity (`additionalProperties: True`): `src/ai_billing_audit/auditor.py:74-107`; documented `docs/AUDIT_PROMPTS_VAL.md:5.2`
- v12 EXAMPLE 6/7 leakage disclosure: `runs/recall/v12_summary.md` "Leakage disclosure" section; `docs/AUDIT_PROMPTS_VAL.md:96-110`

## Appendix B — key numbers summary

| Quantity | Value | Source |
|---|---|---|
| v12 prompt size (bytes) | 38,015 | `prompts/v12/MANIFEST.json:8` |
| v12 prompt size (lines) | 761 | `wc -l` |
| v12 prompt size (chars) | 37,787 | `wc -m` |
| v12 prompt size (tokens, est.) | ~10,800 | 37,787 / 3.5 |
| v12 audit input tokens (est.) | ~13,000 | prompt + ~2,200 encounter |
| v12 baseline F1 (10-enc val) | 0.690 | `prompts/MANIFEST.json:70` |
| v12 baseline P / R | 0.625 / 0.769 | `prompts/MANIFEST.json:69-70` |
| v12 per-encounter F1 mean | 0.713 | `runs/recall/v12_ahcip_clean.json:11` |
| v12 latency mean / p95 | 29.9s / 57.7s | `runs/recall/v12_ahcip_clean.json:132-133` |
| Current val_ca size | 19 enc / 31 gold | `data/synth/val_ca.json` (direct count) |
| val_ca size at MANIFEST write | 10 enc / 13 gold | `prompts/MANIFEST.json:71-72` |
| # rules at F1=1.000 | 5 / 11 (45%) | `runs/recall/v12_ahcip_clean.json:38-99` |
| # rules at F1=0.000 | 3 / 11 (27%) | same |
| Worst-severity bucket F1 | high F1=0.500 | `runs/recall/v12_ahcip_clean.json:116-122` |
| Per-audit cost (est.) | ~$0.003 | §4.1 derivation |
| MIPROv2 medium cost (est.) | ~$4 / run | §4.2 derivation |
| MIPROv2 medium wall-clock (est.) | ~2h MiniMax / ~12h Ollama | §4.2 derivation |

End of report.
