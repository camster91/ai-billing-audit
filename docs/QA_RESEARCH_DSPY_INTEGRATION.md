# QA Research: DSPy MIPROv2 Integration Status

**Date:** 2026-06-17 · **Author:** Hermes subagent (read-only research pass)

## TL;DR

`scripts/optimize.py` is **not wired into the iteration loop**. It is a hermetic
self-test that compiles against 8 synthetic encounters it builds inline and
saves the artifact to `artifacts/miprov2_best_*.json`. It never reads
`prompts/v0/auditor_prompt.txt`, never runs against the 50-encounter val set,
and never writes to `prompts/_candidate_*/`. The README's `python run.py`
shim does dispatch to it, but only for the smoke check, not as an iteration
primitive.

## What optimize.py actually does

- **Train/val split is inline.** Lines 155-342 hand-build 8 deterministic
  encounters (`enc_train_1..5`, `enc_val_1..3`) inside the script. The
  `data/val.json` 50-encounter split is never loaded.
- **LM is `ShapeAwareDummyLM`** (lines 533-632), a fake that returns canned
  findings payloads based on the field marker in the prompt. No Ollama /
  MiniMax / Claude call is ever made in smoke mode.
- **Teleprompter spec is correct** (line 11 comment matches
  `MIPROv2(metric=grader_metric, auto='medium', num_threads=4, max_bootstrapped_demos=4, max_labeled_demos=4)`).
- **Output path:** `artifacts/miprov2_best_val_f1_<score>.json` plus a
  `artifacts/miprov2_best.json` symlink/copy (line 23-24 docstring). **Not**
  `prompts/_candidate_*/auditor_prompt.txt`.
- **Exit code:** 0 on success, 1 on loop error. The metric wrapper at
  line 481 (`grader_metric`) tracks the best F1 via a thread-local collector
  (`_trial_log`), and the saved program is the one that achieved best F1
  during MIPROv2's internal trials.

## How run.py / run_v0_auditor.py relate

- `run.py` (87 lines) is a **shim**. It resolves `scripts/optimize.py` and
  calls it via `runpy.run_path`. It does no prompt loading.
- `scripts/run_v0_auditor.py` (344 lines) is the **v0 baseline harness**.
  It reads `prompts/v0/auditor_prompt.txt` (line 91), pins its sha256 against
  `prompts/v0/MANIFEST.json` (lines 167-179), and writes
  `data/predictions_v0.jsonl`. It is the script that produced the
  `runs/acceptance/multi-20260617T194715Z/run_01/predictions.jsonl` we
  just inspected (50 records, F1=0.268, P=1.000, R=0.155). It uses a
  deterministic LLM keyed on `encounter_id`, **not** the DSPy-compiled
  program. The two scripts are disjoint.

## Wiring gap → `scripts/iterate_with_dspy.sh`

The smallest change to make `optimize.py` callable as an iteration step:

1. **Replace the inline 8-encounter SYNTHETIC list** with a loader for
   `data/val.json` (50 encounters) plus a held-out 5-encounter train split.
   The current synthetic data is too small to discriminate prompts (5 train,
   3 val → MIPROv2 has no signal to optimize against).
2. **Add a `--base-prompt` CLI flag** that reads `prompts/v0/auditor_prompt.txt`
   and seeds the MIPROv2 instruction proposer from it (currently the script
   starts from the default prompt the DSPy signature generates).
3. **Change the output path** from `artifacts/miprov2_best_*.json` to
   `prompts/_candidate_${TS}/auditor_prompt.txt` (plain text, not DSPy
   JSON checkpoint) so the existing v0 archive mechanism can promote it.
4. **Add a baseline-vs-candidate F1 delta check**: re-run
   `run_v0_auditor.py` against the candidate prompt, diff mean F1 against
   the v0 pinned F1, and `exit 1` if the candidate is ≤ v0.

A 30-line bash wrapper around the patched `optimize.py` is enough. The
current `run.py` shim does not need to change; just point the loop at the
new entry point.
