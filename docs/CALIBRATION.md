# Calibration report

> Public-facing P/R numbers for the AI billing auditor. Source of
> truth: `scripts/calibration_report.py` regenerates this file on
> every cron run; the JSON sibling `artifacts/calibration.json`
> has the per-encounter detail.

Generated: 2026-06-19 22:42:46 UTC

Split: `data/val.json`
LLM: `smoke`
Encounters evaluated: **3**
Audit errors: **3**

## Headline metrics

| metric | value |
| --- | --- |
| Precision (micro) | **0.0000** |
| Recall (micro) | **0.0000** |
| F1 (micro) | **0.0000** |
| True positives | 0 |
| False positives | 0 |
| False negatives | 11 |
| Total gold findings | 11 |
| Total predicted findings | 0 |

## What this means

- **Precision** = of the findings the auditor raised, what fraction
  were real (1.0 = every flagged finding was a true positive).
- **Recall** = of the real findings in the source data, what
  fraction the auditor caught (1.0 = every issue was found).
- **F1** = harmonic mean of precision and recall.

A claim like "94% precision, 71% recall" is honest and gives
prospects what they need to evaluate the product. We commit to
publishing these numbers monthly and to re-running this script
whenever the prompt changes, so the report always reflects the
current production model.

## Per-rule ground-truth coverage

The number of gold findings per rule family in this split. The
detailed TP/FN per rule lives in `artifacts/calibration.json`.

| rule_id | gold count |
| --- | --- |

## How we measure

Run `python3 scripts/calibration_report.py` from the repo root. The
script loads each encounter, builds the audit message via
`ai_billing_audit.auditor.build_messages`, dispatches it through
`LLMClient` (which reads `LLM_PROVIDER` / `LLM_BASE_URL` /
`LLM_MODEL` from the environment), parses the JSON response, and
compares the predicted `rule_id` set against the gold `rule_id` set.

No cherry-picking: we run the entire split, not a hand-picked subset.
We don't suppress errored encounters; the errored count is reported
in the headline. The held-out split (`data/holdout_seed9999.json`)
was never seen during prompt iteration.
