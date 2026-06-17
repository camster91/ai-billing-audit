# v0 prediction metrics

Source: predictions `data/predictions_v0.jsonl` scored against manifest `data/val_manifest.json`.

Encounters: **50** (predictions: 50, errors: 0, missing from predictions: 0, extra with no gold: 0).

Scoring key: category (multiset). Per-category block below covers every category that appears in either predicted or gold.

## Headline

| scope | precision | recall | f1 | support |
| --- | --- | --- | --- | --- |
| micro (pooled) | 1.0000 | 1.0000 | 1.0000 | 148 |
| macro (mean across categories) | 1.0000 | 1.0000 | 1.0000 | 10 |

## Targets

- R >= 0.70: **met** (micro R = 1.0000)
- P >= 0.60: **met** (micro P = 1.0000)

## Per-category

| category | precision | recall | f1 | support | predicted |
| --- | --- | --- | --- | --- | --- |
| diagnosis | 1.0000 | 1.0000 | 1.0000 | 40 | 40 |
| evaluation | 1.0000 | 1.0000 | 1.0000 | 27 | 27 |
| laboratory | 1.0000 | 1.0000 | 1.0000 | 20 | 20 |
| cardiology | 1.0000 | 1.0000 | 1.0000 | 14 | 14 |
| imaging | 1.0000 | 1.0000 | 1.0000 | 13 | 13 |
| missing-dx | 1.0000 | 1.0000 | 1.0000 | 10 | 10 |
| procedure | 1.0000 | 1.0000 | 1.0000 | 8 | 8 |
| duplicate | 1.0000 | 1.0000 | 1.0000 | 7 | 7 |
| preventive | 1.0000 | 1.0000 | 1.0000 | 6 | 6 |
| modifier | 1.0000 | 1.0000 | 1.0000 | 3 | 3 |

## Notes

- Micro P/R/F1 are pooled across all categories (sum of TP, sum of FP, sum of FN). Support is total gold categories across the split (148).
- Macro is the unweighted mean of per-category P/R/F1 across the 10 categories that appear in the split.
- Predictions with `ok=false` (0) are included in the count but contribute empty `predicted_categories` lists, so they count as 100% miss on their gold categories.

Generated at 2026-06-17T01:17:01Z (wall clock 0.0009s).
