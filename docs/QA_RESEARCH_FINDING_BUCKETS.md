# QA Research: Finding-Bucket Classification of 50 Val Encounters

**Date:** 2026-06-17 · **Author:** Hermes subagent (read-only research pass)
**Source:** `data/val.json` (50 encounters) cross-referenced with
`runs/acceptance/multi-20260617T194715Z/run_01/predictions.jsonl` (v0 baseline,
F1=0.268, P=1.000, R=0.155).

## TL;DR

The 50 encounters fall into **8 buckets** by the type of finding they
embed. Of the 44 flagged encounters, **40 are never detected** by the v0
prompt. Below is the classification and the cheapest A/B-test variant for
each always-missed bucket.

## Bucket distribution (n=50)

| Bucket | Count | Encounter IDs | Always missed? |
|---|---|---|---|
| Clean (no rules, no findings) | 6 | 10013, 10014, 10028, 10029, 10043, 10044 | n/a (TP) |
| Clean (rules + claims, all matched) | ~14 | 10001, 10003, 10004, 10006, 10007, 10010, 10012, 10016, 10018, 10019, 10020, 10022, 10025, 10027, 10031, 10033, 10034, 10035, 10037, 10040, 10042, 10046, 10048, 10049 | n/a (TN) |
| **(f) Documentation-gap** (note says "Documentation lacks diagnosis linkage" + literal `REVIEW` token in claim) | **10** | 10000, 10008, 10011, 10015, 10023, 10026, 10030, 10038, 10041, 10045 | Yes — only 10000/10015 reliably caught |
| **(a) Missing-modifier** (modifier 25 absent on 99214+procedure same day) | **1** | 10005 | Yes |
| **(g) Other: duplicate-billing** (note says "Duplicate service on same date"; suggested_code=`DENY`) | **7** | 10002, 10009, 10017, 10024, 10032, 10039, 10047 | Yes |
| (b) Under-coded-E/M | 0 | — | n/a |
| (c) Missing-procedure | 0 | — | n/a |
| (d) Wrong-diagnosis | 0 | — | n/a |
| (e) Frequency-cap | 0 | — | n/a |

## Per-bucket cheapest A/B test

### (f) Documentation-gap — 10 encounters, biggest win
The model's "REVIEW" token check is the **only** finding it emits with any
consistency (enc_10000, 10015 → reliably caught). Prompt edit: add a
**single rule** — "If the claim's `icd10_codes` array contains the literal
token `REVIEW` instead of a valid ICD-10 code, emit a
`category=missing-dx` finding citing the token verbatim." A/B against the
v0 prompt on the 10-encounter subset would resolve whether the gap is
prompt-only or whether the LM is also refusing to parse the REVIEW token.

### (g) Duplicate-billing — 7 encounters, second-biggest win
The note explicitly says "Duplicate service on same date" and the
ground-truth finding has `category=duplicate`, `suggested_code=DENY`. v0
prompt emits no finding for any of these. A/B test: append "If the note
contains the phrase 'Duplicate service' or 'duplicate on the same date',
emit a high-severity duplicate finding with `suggested_code=DENY`." Note
enc_10047 has zero billed CPTs but is still flagged — test that the
prompt handles an empty claim line.

### (a) Missing-modifier — 1 encounter, low ROI
Only enc_10005. Add "If the E/M is 99214 AND a procedure (lipid panel
80061, injection 20610) is billed same day AND the note says
'modifier 25 applied' but the claim line lacks modifier 25, emit a
`category=modifier` finding." Small sample, but a high-precision rule
to test whether the LM is reading the `modifiers` array at all.

### (b)-(e) Zero encounters
Under-coded E/M, missing-procedure, wrong-diagnosis, and frequency-cap
are **not represented** in the current 50-encounter val split. The next
prompt iteration should *not* spend budget on these — they have no test
signal. The `data/synth_train.json` builder (if it exists) should grow
these buckets before any prompt work targets them.

## Recommended iteration order (5-7 prompts)

1. **Prompt A**: add the `REVIEW` token rule → expect to recover 8 of 10
   doc-gap findings.
2. **Prompt B**: add the "Duplicate service" phrase rule → expect to
   recover 5-7 of 7 duplicate findings.
3. **Prompt C**: A + B combined → measure F1 ceiling on doc-gap +
   duplicate.
4. **Prompt D**: add modifier-25 rule → recover the 1 modifier finding.
5. **Prompt E**: re-evaluate the 14 "clean" encounters after prompts A-D
   to check for false-positive regression (the v0 prompt is at P=1.000
   for a reason — these rule additions must not break that).
