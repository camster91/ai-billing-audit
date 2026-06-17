# MVP acceptance run

End-to-end cross-provider acceptance test for the auditor harness. Runs
the v0 auditor prompt + RESPONSE_JSON_SCHEMA against the 150-encounter
test sample once per LLM provider and produces a side-by-side
comparison with a PASS/FAIL verdict.

## What this proves

The task body asks for proof of **LLM-agnosticism**: the auditor
harness produces comparable results regardless of which LLM backend
served the request. The acceptance criteria are strict and the verdict
is automatic:

  * All 4 providers (minimax, claude, openai, gemini) ran end-to-end
    without unhandled exceptions.
  * Every provider produced 100% valid output on the pinned split
    (no `ok: false` records; every findings list parses cleanly).
  * Aggregate scores (micro-P, micro-R, micro-F1, macro-F1) are
    within 5% of each other across providers
    ((max - min) / mean <= 0.05 per metric).

Any failure breaks the contract and the verdict is FAIL with the
specific provider(s) and metric(s) named.

## Pinned inputs

  * **Test sample** (data/test_sample.jsonl, 150 encounters)
    100 from train.json + 50 from val.json; coverage matrix in
    data/test_sample_NOTE.md.
  * **Gold manifest** (data/test_sample_manifest.json)
    Built by scripts/build_test_sample_manifest.py. Holds
    per-encounter `gold_categories` derived from each encounter's
    `ground_truth` findings. Source checksums for train.json and
    val.json are recorded in the manifest header and pinned to the
    values in data/test_sample_NOTE.md.
  * **Auditor prompt** (prompts/v0/auditor_prompt.txt)
    The v0 prompt, byte-identical to src/ai_billing_audit/auditor_prompt.txt.
    SHA-256 recorded in every predictions.meta.json.
  * **Response schema** (src/ai_billing_audit/auditor.py:RESPONSE_JSON_SCHEMA)
    The findings shape every provider must conform to.

## How to run

### One-shot (recommended)

```bash
cd /Users/biancabienaime/projects/ai-billing-audit
.venv/bin/python scripts/aggregate_acceptance.py
```

This runs all 4 providers in series (sequential, not parallel — real
LLM calls should not race on rate limits), then runs the comparator
and writes `runs/acceptance/comparison.{json,md}` and `VERDICT.txt`.

### Dry-run (no API key, no network, no cost)

```bash
.venv/bin/python scripts/aggregate_acceptance.py --dry-run
```

Uses a deterministic in-process LLM that returns each encounter's
ground truth. Proves the wiring end-to-end. Trivially PASSes because
all 4 providers see identical input.

### Per-provider (cost control, retry after a transient failure)

```bash
.venv/bin/python scripts/run_cross_provider.py --provider minimax
.venv/bin/python scripts/run_cross_provider.py --provider claude
.venv/bin/python scripts/run_cross_provider.py --provider openai
.venv/bin/python scripts/run_cross_provider.py --provider gemini
.venv/bin/python scripts/compare_acceptance.py
```

Or use the smoke cap:

```bash
.venv/bin/python scripts/run_cross_provider.py --provider claude --n 5
```

### Compare only (existing runs/)

```bash
.venv/bin/python scripts/aggregate_acceptance.py --compare-only
```

Re-runs the comparator without re-paying for the LLM calls. Useful
when you tweak the comparator and want to re-score.

## Required environment

For real runs, the following env vars must be set in the shell that
invokes the script. A missing key causes the per-provider run to
fail with a loud error and the aggregate to stop.

  * `MINIMAX_API_KEY`
  * `ANTHROPIC_API_KEY`
  * `OPENAI_API_KEY`
  * `GEMINI_API_KEY` (or `GOOGLE_API_KEY` as a fallback)

`LLM_PROVIDER` is **not** required — the runner sets it per
invocation. `ANTHROPIC_BASE_URL` should be unset or point at the
real Anthropic API; the worker subprocesses spawned by the kanban
dispatcher must not inherit the `ANTHROPIC_BASE_URL=https://api.ollama.com`
that was breaking the v0 run (attempt 2 of this task, 2026-06-16).

## Output layout

```
runs/acceptance/
  <provider>-<UTC-timestamp>/
    predictions.jsonl       # one record per encounter, run_v0_auditor.py shape
    predictions.meta.json   # per-provider run metadata + token totals
    predictions.errors.log  # stack traces for any ok=false records
  comparison.json           # machine-readable cross-provider report
  comparison.md             # human-readable side-by-side table + verdict
  VERDICT.txt               # one line: PASS or FAIL
```

Each per-provider run is timestamped so multiple runs against the
same provider don't clobber each other; the comparator picks the
lexicographically-latest (== chronologically-latest) run per
provider.

## What "valid output" means

A record is valid iff:

  * `ok: true` — no exception escaped the auditor
  * `findings` is a list of objects each with `category`,
    `suggested_code`, `quote`, `severity`, and `rule_ids` populated
    (the v0 RESPONSE_JSON_SCHEMA)
  * `predicted_categories` is the sorted unique category list derived
    from `findings`

`predictions.meta.json` records `n_errors` and `error_type_tally`
for any record that wasn't valid; the comparator checks
`valid_output_rate == 1.0` per provider.

## Cost

Real-mode rough estimate per provider (150 encounters, ~600 prompt
tokens, ~200 completion tokens per call):

  * minimax / MiniMax-M3 — depends on team rate
  * claude / claude-3-5-sonnet — ~$0.50 per run
  * openai / gpt-4o-mini — ~$0.05 per run
  * gemini / gemini-1.5-flash — ~$0.02 per run

For a first smoke test, use `--n 5` to drive 5 encounters per
provider and confirm the wiring before paying for 150×4.
