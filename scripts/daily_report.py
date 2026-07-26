"""Daily report: combines latest multi-run, failure modes, live parity, cost.
Outputs markdown + sends to Telegram via Maton.

Usage: python scripts/daily_report.py
"""
import os, json, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone

base = Path('runs/acceptance')
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# Find latest multi-run with a usable summary.json
# Matches both the legacy multi-<ts>/ naming AND the new
# multi-<split>-<prompt>-<ts>/ naming introduced 2026-06-27.
# The freshest by mtime is the most recent run regardless of naming.
# Skip any multi-* dirs that don't have a summary.json yet — a partially-
# written or interrupted run leaves the dir present but unreadable.
candidates = [p for p in base.glob('multi-*') if (p / 'summary.json').exists()]
multis = sorted(candidates, key=lambda p: p.stat().st_mtime)
if not multis:
    print("No usable multi-run output (every multi-* dir is missing summary.json). "
          "Re-run scripts/run_7x.py to regenerate.")
    sys.exit(1)
latest = multis[-1]
summary = json.load(open(latest / 'summary.json'))
agg = summary['aggregate']

# What is this report measuring? Be explicit so a reader can tell at a
# glance whether the F1 number reflects the production AHCIP val set
# (val_ca + v12 prompt) or the legacy US-shaped baseline (val + v0).
# Older summaries (pre-2026-06-27) don't carry these fields; default
# to legacy so we don't lose the historical numbers.
split_label = summary.get('split', 'val (legacy)')
prompt_label = summary.get('prompt_version', 'v0 (legacy)')
split_path = summary.get('split_path', 'data/val.json')
prompt_path = summary.get('prompt_path', 'prompts/v0/auditor_prompt.txt')
is_production = split_label == 'val_ca' and prompt_label == 'v12'

# Cost: assume ~$0.30/M input, $1.20/M output
# Estimate per encounter: 2K input, 1K output
n_per_run = summary['n_encounters_per_run']
n_runs = summary['n_runs']
est_cost = n_per_run * n_runs * (2_000 * 0.30 + 1_000 * 1.20) / 1_000_000

# Latest failure-modes
fm = latest / 'failure_modes.md'
fm_exists = fm.exists()
fm_summary = ''
if fm_exists:
    text = fm.read_text()
    for line in text.split('\n'):
        if line.startswith('## '):
            fm_summary += line + '\n'

md = f"""# AI Billing Audit — Daily Report
**{today}**

## What this report measures

- **Split:** `{split_label}` — `{split_path}` ({n_per_run} encounters, {summary.get('n_gold_findings', '?')} gold findings)
- **Prompt:** `{prompt_label}` — `{prompt_path}`
- **Production-tracking:** {'YES — matches the live auditor' if is_production else 'NO — this is a legacy baseline run; the daily cron should produce val_ca/v12 runs by default'}

## Aggregate over {n_runs} runs of {n_per_run} encounters

| metric | mean | stdev | min | max |
|---|---|---|---|---|
| precision | {agg['precision_mean']:.3f} | {agg['precision_stdev']:.3f} | {agg['precision_min']:.3f} | {agg['precision_max']:.3f} |
| recall    | {agg['recall_mean']:.3f} | {agg['recall_stdev']:.3f} | {agg['recall_min']:.3f} | {agg['recall_max']:.3f} |
| F1        | {agg['f1_mean']:.3f} | {agg['f1_stdev']:.3f} | {agg['f1_min']:.3f} | {agg['f1_max']:.3f} |

**Estimated cost this run:** ${est_cost:.2f}

## Failure modes

{fm_summary or '(failure-mode report not yet generated; run scripts/analyze_failures.py)'}

## Recommendations

- If F1 < 0.70 on the production split (val_ca + v12): prompt is too conservative. Tighten instructions to favor recall.
- If F1 stdev > 0.10: model output is too random. Set temperature=0 and re-run.
- If always-missed encounters > 30%: data + prompt mismatch. Inspect 3 examples by hand.
- If always-FP encounters > 10%: model is over-eager. Add "be conservative" or limit finding count.

## Next actions

1. Read this report
2. If F1 trending down vs last week's report, run `scripts/analyze_failures.py`
3. If a prompt fix is identified, run `scripts/ab_prompt.py` to A/B test
4. Promote only if `promote_candidate == YES`

## Source artifacts

- Multi-run summary: `{latest}/summary.json`
- Per-run scores: `{latest}/run_NN/scores.json`
- Failure modes: `{fm}`
"""

out = Path('docs') / f'daily_report_{today}.md'
out.write_text(md)
print(f"Wrote {out}")
print()
print(md[:2000])
print('...')

# Optionally send to Telegram via Maton
MATON_KEY = os.environ.get('MATON_API_KEY')
if MATON_KEY:
    try:
        # Simple Telegram send via Maton (placeholder, actual call needs the
        # Maton telegram-send endpoint or a bot token)
        print("MATON_API_KEY set but Telegram send not yet implemented in this script.")
    except Exception as e:
        print(f"Maton send failed: {e}")
