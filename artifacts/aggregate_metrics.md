# Aggregate grader metrics

Source: `data/val.json` with prompt `prompts/v0/auditor_prompt.txt` (LLM provider: `smoke`).

Encounters: **50** (errored: 0).

## Headline metrics

| scope | precision | recall | f1 | support |
| --- | --- | --- | --- | --- |
| overall (micro) | 1.0000 | 1.0000 | 1.0000 | 164 |
| macro (mean across encounters) | 1.0000 | 1.0000 | 1.0000 | 50 |

## Per-category recall

| category | precision | recall | f1 | support |
| --- | --- | --- | --- | --- |
| under_coding | N/A | N/A | N/A | 0 |
| missed_charge | N/A | N/A | N/A | 0 |
| modifier | N/A | 1.0000 | N/A | 3 |
| **overall (micro)** | 1.0000 | 1.0000 | 1.0000 | 164 |

## Notes

- under_coding and missed_charge are NOT categories in the current ground-truth taxonomy (the project uses granular clinical categories: cardiology, diagnosis, evaluation, imaging, laboratory, missing-dx, modifier, preventive, procedure, duplicate). They are reported as support=0, recall=null. modifier is a real category.
- Macro convention: unweighted mean of per-encounter precision/recall/F1 across all encounters with metrics. Per-encounter P/R is 1.0 for encounters with zero gold AND zero predicted (true negative; matches the grader's MatchResult convention). Encounter-level errors contribute 0.0 for P/R/F1..
- Per-category recall convention: sum_of_tp_in_category / sum_of_gold_in_category over the whole split; support = total gold findings in category. Categories with zero gold are reported as recall=null, support=0 rather than silently zeroed..
- Overall convention: pooled micro precision/recall/F1 across all categories and all encounters. 0/0 returns 0.0 to avoid inflating precision over zero examples; support is reported alongside..

Generated at 2026-06-17T00:35:13Z (wall clock 0.003s).
