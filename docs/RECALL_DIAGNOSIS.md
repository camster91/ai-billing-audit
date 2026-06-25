# Recall Diagnosis — 7-run v0 baseline

> Generated from `runs/acceptance/ollama-20260617T173927Z/per_rule_scores.json`
> (per-rule breakdown produced by `python3 -m ai_billing_audit.eval.per_rule_scorer`).
>
> Overall on the 50-encounter val set:
> **P=1.000 R=0.140 F1=0.246** (TP=23, FP=0, FN=141).
> 1 of 50 encounters errored out.

## TL;DR

The model is **not hallucinating** — zero false positives across 50 encounters. It is **systematically under-detecting** findings that the synth ground truth credits. Recall of 0.14 means we are missing ~86% of the things the synth says we should flag.

The breakdown shows the under-detection is concentrated in **`imaging` and `lab`** code-level buckets, and the model never emits a modifier-25 finding at all in this run, even though the synth GT credits one for ~6 encounters. Modifier sub-rule buckets are empty for this run.

## Method

```
python3 -m ai_billing_audit.eval.per_rule_scorer \
  --val data/synth/val.json \
  --preds runs/acceptance/ollama-20260617T173927Z/predictions.jsonl \
  --out runs/acceptance/ollama-20260617T173927Z/per_rule_scores.json
```

The scorer buckets each ground-truth and predicted `rule_id` into a
`rule_family` (modifier, code_level, dx_procedure, ncci_mue_time,
doc_adequacy, other) and reports P/R/F1 per family. Modifier sub-rules
(−25, −59, −24, −57, etc.) get their own bucket so we can see if one
specific modifier is dragging the family average.

## Bucketed results (overall)

| bucket          | n   | P     | R     | F1    | TP | FP | FN |
|-----------------|-----|-------|-------|-------|----|----|----|
| other (catchall)| 164 | 1.000 | 0.140 | 0.246 | 23 | 0  | 141 |

**Why only one row?** The rule_id space used by `data/synth/val.json`
prefixes are `rule_em_*`, `rule_ecg_*`, `rule_icd_*`, `rule_missing_dx_*`,
`rule_lab_*`, `rule_imaging_*` — none match the `MOD-`, `E/M-`, `NCCI-`,
etc. prefixes in the scorer's `RULE_FAMILY_PREFIXES` table. They all
fall into `other`. This is a known mismatch (see "Action item #1" below).

## By code level

| code level | n   | P     | R     | F1    |
|------------|-----|-------|-------|-------|
| imaging    | 13  | 0.000 | 0.000 | 0.000 |
| lab        | 20  | 0.000 | 0.000 | 0.000 |
| other      | 131 | 1.000 | 0.176 | 0.299 |

**Imaging and lab are the worst buckets** — the model emits zero findings
in either bucket despite the synth crediting 13 imaging and 20 lab findings
across the val set. This is the largest single fix target.

## Per-encounter summary

- 27/50 encounters had **zero matching findings** (zero TP).
- 23/50 had at least one matching finding, but typically only 1 — the
  synth credits an average of ~3.3 findings per flagged encounter.
- 1/50 errored (the LLM call returned `ok: false`).

## Diagnosis

The model is "under-eager" in three specific ways:

1. **Code-level buckets it can't see.** It only emits findings for the
   `other` family, which (after the prefix mismatch) is dominated by
   E/M and diagnosis-procedure findings. It never emits an imaging or
   lab finding.
2. **Modifiers completely missing.** Modifier-25 (separate E/M on the
   same day as a procedure) is the single biggest "missed revenue"
   category in real-world billing. The synth GT credits ~6 modifier-25
   findings; the model emits zero.
3. **Per-encounter coverage is shallow.** Even when it finds something,
   it finds fewer findings per encounter than the synth says are there.
   This is the classic "be conservative" bias from the v0 prompt.

## Ranked fix targets

1. **v1 prompt** (already in `prompts/v1/auditor_prompt.txt`) — relaxes
   the "be conservative" clause to favor recall. Target: R jumps from
   0.14 → 0.45+ without P dropping below 0.85.
2. **Add explicit rule_id prefixes for lab and imaging rules** to the
   synth (e.g. `LAB-` and `IMG-` prefixes), so the per-family scorer
   can show imaging vs. lab family-level buckets. Until then, we use
   the `by_code_level` view as the proxy.
3. **Wire modifier-25 examples into the few-shot prompt.** The model
   has clearly learned "don't double-bill" and is over-applying it to
   modifier-25, which is exactly when you *should* double-bill.
4. **Iterate with DSPy MIPROv2** (task A4) once the per-rule scorer
   (task A2) gives it a real signal to optimize.

## Action items

- [ ] **A2 DONE.** `src/ai_billing_audit/eval/per_rule_scorer.py`
      provides per-rule-family breakdown. CLI usage shown above.
- [ ] **A2 follow-up:** extend the prefix table so `rule_lab_*`,
      `rule_imaging_*`, and `rule_missing_dx_*` get their own family
      buckets (not just the code-level bucket).
- [ ] **A3 DONE.** v1 prompt exists in `prompts/v1/auditor_prompt.txt`
      and supersedes v0's "be conservative" line. A/B harness exists at
      `scripts/ab_prompt.py`.
- [ ] Re-run the 7× baseline against v1 and re-score with this same
      per-rule scorer. Expected: `imaging` and `lab` recall >0.

## How to reproduce

```bash
source .venv/bin/activate
PYTHONPATH=src:. python3 -m ai_billing_audit.eval.per_rule_scorer \
  --val data/synth/val.json \
  --preds runs/acceptance/<your-run>/predictions.jsonl \
  --out runs/acceptance/<your-run>/per_rule_scores.json
```

Also see `scripts/score_ollama_audit.py` for the original global-only
scorer that this was promoted from.
