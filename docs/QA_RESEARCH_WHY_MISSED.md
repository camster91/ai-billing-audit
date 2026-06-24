# Task 1 — Why the model returns 0 findings on flagged encounters

**Source:** `runs/acceptance/multi-20260617T194715Z/run_01/predictions.jsonl` + `scores.json` + `scripts/run_7x.py` + `scripts/score_ollama_audit.py`

## The single bug that explains almost everything

`scripts/run_7x.py:81` and `scripts/score_ollama_audit.py:11` both define:

```python
def finding_key(f):
    return (f.get('category', ''), f.get('rule_id', ''))
```

The scoring key is **`(category, rule_id)`**. The v0 prompt (`prompts/v0/auditor_prompt.txt`) never tells the model to emit a `category` field, so for every finding the model produces, `f.get('category', '')` is the empty string. The GT side has the actual category (`"evaluation"`, `"diagnosis"`, `"cardiology"`, `"missing-dx"`, `"duplicate"`, etc.), so the sets almost never intersect.

I verified: in the 48 successful run-01 predictions, the model emitted **17 findings total**, of which only **2** contained a `category` field (`enc_10024` → `"category": "duplicate"`, `enc_10041` → `"category": "missing-dx"`). Those two coincidences are the **entire** reason run_01 has TP=2. The other 15 model findings are FPs because their category is empty.

This single fact reframes the "40/44 always-missed" diagnosis. **The model is not detecting nothing — it is detecting findings that the scorer cannot match.** Recall of 0.012 is an artefact of the scoring contract, not a model capability floor.

## What is the model actually producing?

For the 10 sampled always-missed encounters, I read the model output and the GT:

| enc_id | model findings returned | GT findings | match? |
|---|---|---|---|
| enc_10000 | `rule_missing_dx_001` (critical) | 4: em/icd/ecg/missing-dx | no category field |
| enc_10001 | 0 (model says "all five billed items ... directly supported") | 5: em/imaging/icd/icd/lab | conservative refusal |
| enc_10002 | `rule_overlap_001` (high), `rule_preventive_001` (info) | 2: preventive/duplicate | no category field |
| enc_10003 | 0 (says "fully supported") | 4: em/icd/lab/imaging | conservative refusal |
| enc_10004 | 0 (says "directly supported") | 3: em/procedure/icd | conservative refusal |
| enc_10005 | `rule_modifier_25_001` (high) | 4: em/icd/modifier/lab | no category field |
| enc_10006 | 0 (says "directly supported") | 5: em/icd/ecg/ecg/imaging | conservative refusal |
| enc_10007 | 0 (says "directly supported") | 5: em/lab/injection/icd/icd | conservative refusal |
| enc_10010 | 0 (says "supports each billed code") | 4: ecg/ecg/imaging/icd | conservative refusal |
| enc_10012 | 0 (says "no findings apply") | 4: lab/injection/icd/icd | conservative refusal |

Two failure modes, roughly split 50/50:

### A. "Category missing" mode (5/10) — the silent scoring bug

For 5 of the 10 sampled encounters, the model DID emit a finding with the right `rule_id` and a sensible `quote` (e.g., enc_10000 → `rule_missing_dx_001` with the correct "documentation lacks diagnosis linkage" quote; enc_10005 → `rule_modifier_25_001` with the correct "modifier 25 applied" quote; enc_10002 → `rule_overlap_001` and `rule_preventive_001`). The scorer is rejecting these because `category` is missing.

The prompt instructs: `"Each finding must cite at least one retrieved rule by rule_id and include a verbatim quote..."` — but says nothing about category. Fixable by adding one sentence to the prompt and the JSON schema (see Task 5).

### B. "Conservative refusal" mode (5/10) — the prompt is too strict

For the other 5, the model's `summary` literally enumerates every billed item as "directly supported" or "fully supported" — i.e., the model *sees* the rules but interprets the v0 prompt's "Be conservative. A claim that is not clearly contradicted by the retrieved rules is not a finding" as a licence to emit zero findings when the documentation is internally consistent.

This is real. Look at the GT for enc_10004: 3 findings (evaluation/procedure/icd). The model says "All three billed codes (99214, 90686, I10) are directly supported by verbatim phrases in the clinical note and align with the corresponding retrieved payer rules (rule_em_001, rule_injection_001, rule_icd_004); no compliance issues were identified." It is **correct that there are no compliance issues** — but the GT counts every matched rule as a finding.

**This is a ground-truth semantics problem**, not (only) a model problem. The synth's GT is "list every rule that applies," not "list only findings that flag a compliance problem." v1's "Favor recall" change addresses this for the model side, but the GT format still rewards a strict, rule-by-rule report.

## The 2 errors (enc_10021, enc_10036) are unrelated to the missing-recall story

Both errored with `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` after 44s and 41s. The patch in `llm.py:168-171` strips ```json``` fences, but other failure modes exist (see Task 4).

## What "always-missed" actually means

The failure_modes.md file says `enc_10000` is "always-missed" because TP=0 in all runs. But `enc_10000` has `rule_missing_dx_001` in its output *every run* — the scorer just can't see it. Once the scoring contract and the prompt agree on `category`, the "40/44 always-missed" number is likely to drop to something like 5-15/44, and the v1 "favor recall" change will handle the rest.

## Recommendations (rank-ordered by likely R/P impact)

1. **Scoring contract fix (highest impact, lowest risk):** change `finding_key` to use only `rule_id`, OR derive `category` from the `rules` list passed to the prompt. The GT already carries `category`, so just look it up by `rule_id` in the GT dict.
2. **Add `category` to the prompt's required-output schema (high impact, low risk):** one sentence in v1: "Each finding's `category` field MUST equal the `category` of the rule it cites (e.g., `evaluation`, `diagnosis`, `cardiology`, `missing-dx`, `duplicate`, `preventive`, `imaging`, `laboratory`, `procedure`, `modifier`)."
3. **v1 "favor recall" change (medium impact):** will lift the 5/10 conservative-refusal cases.
4. **Optionally redefine GT semantics to "compliance findings only"** — the synth's every-rule-is-a-finding contract is non-standard for a billing-audit product (real auditors report denials and under-codings, not "99214 is correctly supported"). See Task 2.
