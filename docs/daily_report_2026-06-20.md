# AI Billing Audit — Daily Report
**2026-06-20**

## Aggregate over 7 runs of 50 encounters

| metric | mean | stdev | min | max |
|---|---|---|---|---|
| precision | 1.000 | 0.000 | 1.000 | 1.000 |
| recall    | 0.155 | 0.021 | 0.128 | 0.189 |
| F1        | 0.268 | 0.031 | 0.227 | 0.318 |

**Estimated cost this run:** $0.63

## Failure modes

## Always-missed (model never finds these findings)
## Always-false-positive (model invents findings on clean claims)
## High-variance (TP or FP swings across runs)
## Solid-TP (model reliably finds these)
## Solid-clean (correctly skipped)
## Mixed (errors or partial failures)
## Recommendations


## Recommendations

- If F1 < 0.70: prompt is too conservative. Tighten instructions to favor recall.
- If F1 stdev > 0.10: model output is too random. Set temperature=0 and re-run.
- If always-missed encounters > 30%: data + prompt mismatch. Inspect 3 examples by hand.
- If always-FP encounters > 10%: model is over-eager. Add "be conservative" or limit finding count.

## Next actions

1. Read this report
2. If F1 trending down vs last week's report, run `scripts/analyze_failures.py`
3. If a prompt fix is identified, run `scripts/ab_prompt.py` to A/B test
4. Promote only if `promote_candidate == YES`

## Source artifacts

- Multi-run summary: `runs/acceptance/multi-20260617T194715Z/summary.json`
- Per-run scores: `runs/acceptance/multi-20260617T194715Z/run_NN/scores.json`
- Failure modes: `runs/acceptance/multi-20260617T194715Z/failure_modes.md`
