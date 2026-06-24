# AI Billing Audit — Continuous QA System

**Date:** 2026-06-17
**Status:** v0.1 of a daily-run system. Starting point: 7-run audit (in progress).

## Why

One audit run is one data point. The MVP needs:

1. **Variance tracking.** If R/P/F1 swings 0.20 between runs, we don't know what "the model performs" means. We need a mean + stdev to plan.
2. **Failure-mode triage.** Which encounters are *consistently* missed? Which are *consistently* false-positived? These tell us where the prompt is failing.
3. **Prompt iteration loop.** Each prompt change gets A/B'd against the previous version. Keep the change only if mean F1 improves by ≥ 0.05.
4. **Cost/time tracking.** Each run is real LLM spend. Track $/run and run-length so we can budget and predict.
5. **Live deploy parity.** The same eval should run against `ai-billing-audit.ashbi.ca` (live URL) periodically, not just locally, to catch deploy drift.

## Components

### 1. Multi-run orchestrator (`scripts/run_7x.py`)

Runs the val split (50 encounters) N times against the configured LLM provider.
Writes:
- `runs/acceptance/multi-<ts>/run_NN/predictions.jsonl` — per-encounter predictions
- `runs/acceptance/multi-<ts>/run_NN/scores.json` — per-run R/P/F1
- `runs/acceptance/multi-<ts>/summary.json` — aggregate mean/stdev/min/max

**Usage:**
```bash
# Local run
.venv/bin/python scripts/run_7x.py

# Against live deploy
LIVE_URL=https://ai-billing-audit.ashbi.ca .venv/bin/python scripts/run_live.py
```

Default: 7 runs. Configurable via `N_RUNS` env var.

### 2. Failure-mode analyzer (`scripts/analyze_failures.py`)

Reads the latest multi-run output, computes per-encounter stats:
- **Always-missed** (TP=0 in every run): prompt can't see this finding pattern
- **Always-FP** (FP>0 in every run, GT=0): model is inventing findings
- **High-variance** (TP swings 0→2 across runs): flaky, not a stable signal
- **High-confidence TP** (TP>0 in every run, FP=0): reliable detection

Output: `runs/acceptance/multi-<ts>/failure_modes.md` with each category ranked.

### 3. Prompt A/B comparator (`scripts/ab_prompt.py`)

Given two prompt versions, run each against the same val split N times. Output a comparison table:
- Mean F1, precision, recall per version
- Stdev per version
- p-value (Welch's t-test on the per-run F1s) for "is the new version actually better?"

Usage:
```bash
.venv/bin/python scripts/ab_prompt.py \
  --baseline prompts/v0/auditor_prompt.txt \
  --candidate prompts/v1/auditor_prompt.txt \
  --runs 5
```

Decision rule: only promote `candidate` to `v1` if `mean_f1_candidate > mean_f1_baseline + 0.05` AND p < 0.10.

### 4. Live deploy parity check (`scripts/check_live.py`)

Every 6 hours, fire 5 encounters at the live URL `https://ai-billing-audit.ashbi.ca/encounters/upload/preview`, capture findings, compare against the same encounters run locally. Alert if live R < local R - 0.10 (deploy drift).

### 5. Daily report (`scripts/daily_report.py`)

Generates a markdown report combining:
- Latest multi-run aggregate (mean R/P/F1)
- Failure-mode summary (always-missed, always-FP)
- Live parity check status
- Cost: total tokens × $/M tokens
- Trend: F1 over the last 7 days
- Recommended next action

Posts to Telegram via Maton.

### 6. Cron schedule

```
0 6,14,22 * * *   /Users/biancabienaime/projects/ai-billing-audit/scripts/daily_report.py
0 7 * * *        /Users/biancabienaime/projects/ai-billing-audit/scripts/run_live.py
0 8 * * 1        /Users/biancabienaime/projects/ai-billing-audit/scripts/run_7x.py
```

Three runs/day local, one live parity check/day, one full 7x/week on Mondays.

## What the system does NOT do (yet)

- No automated prompt generation. The DSPy MIPROv2 loop is built but not wired to the daily system.
- No automatic rollback. If F1 drops 0.20 between days, a human reads the report and decides.
- No regression tests on the x12 parser. Those are still manual.
- No PHI/secret redaction in the daily report. The Ollama key + Stripe key + audit log content are all sensitive.

## Initial baseline

After the first 7-run completes, set the baseline. The system will compare every future run to it. Promoted-prompt changes get compared to the prior prompt's baseline. Deploy changes get compared to the local baseline.

## Acceptance gates

- **First ship (friendly clinic):** mean F1 ≥ 0.70 over 3 consecutive multi-runs
- **First dollar ($1,200/mo):** mean F1 ≥ 0.85, stdev < 0.10, live parity < 5% drift
- **Scaling past 5 clinics:** mean F1 ≥ 0.90, stdev < 0.05, zero always-FP, always-missed < 10% of flagged encounters

## File layout

```
scripts/
  run_7x.py                # Multi-run local eval
  run_live.py              # Multi-run against live URL
  analyze_failures.py      # Per-encounter failure categorization
  ab_prompt.py             # A/B prompt comparator
  check_live.py            # Live parity check
  daily_report.py          # Markdown + Telegram report
  score_ollama_audit.py    # R/P/F1 scorer

runs/acceptance/
  ollama-<ts>/             # Single run
    predictions.jsonl
    predictions.meta.json
    scores.json
  multi-<ts>/              # Multi-run
    run_01/..run_07/
    summary.json
```

## Cost estimate (per full 7-run)

50 encounters × 7 runs × 2K input tokens × $0.30/M = $0.21
50 encounters × 7 runs × 1K output tokens × $1.20/M = $0.42
Total: ~$0.65 per multi-run

Daily report (3×/day): $0.65 × 3 = $1.95/day
Weekly 7x: $0.65/week
Monthly: ~$60

Cheap. Run as often as you want.
