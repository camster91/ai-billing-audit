# Iteration Guide — DSPy MIPROv2 for the Auditor Prompt

**Status:** Scaffold. `scripts/optimize.py` is currently a hermetic self-test
(see `docs/QA_RESEARCH_DSPY_INTEGRATION.md` for the gap analysis). This guide
documents how to *use* the scaffold today (smoke check) and how to extend it
into a real iteration primitive.

---

## TL;DR

```bash
# Smoke check — runs the hermetic MIPROv2 loop, saves the best artifact.
python run.py

# Inspect the result.
cat artifacts/miprov2_summary.json
ls -la artifacts/miprov2_best*.json
```

A green smoke check proves the MIPROv2 wiring is intact (signature, metric,
teleprompter config, save path). It does **not** prove the prompt is any good
— the run is against 8 hand-built encounters with `ShapeAwareDummyLM`.

---

## What `scripts/optimize.py` actually does

1. **Builds 8 deterministic synthetic encounters** (5 train, 3 val) inline
   (lines ~155-340). The split is hard-coded; `data/val.json` is not loaded.
2. **Configures a deterministic `ShapeAwareDummyLM`** (lines ~530-630) that
   returns canned `proposed_instruction` and `findings_json` payloads based on
   which output field the adapter is asking for. No external LM is ever called.
3. **Builds the MIPROv2 teleprompter** with the spec from the kanban body:

   ```python
   teleprompter = dspy.MIPROv2(
       metric=grader_metric,
       auto="medium",
       num_threads=4,
       max_bootstrapped_demos=4,
       max_labeled_demos=4,
   )
   ```

4. **Compiles** the student program against the 5-encounter train split.
5. **Evaluates** the compiled program on the 3-encounter val split using
   `grader_metric` (the mean F1 of `match_findings(predicted, ground_truth)`).
6. **Persists** the best program to `artifacts/miprov2_best_val_f1_<score>.json`
   plus a `artifacts/miprov2_best.json` symlink/copy.
7. **Writes** a final summary to `artifacts/miprov2_summary.json` containing
   train size, val size, best val F1, final val F1, total trials, wall-clock
   time, and the path to the saved artifact.

The grader metric is wrapped in a thread-local collector (`_trial_log`) so the
post-processing pass can recover the best F1 MIPROv2 saw across its internal
trials (not just the F1 of the program it returns at the end).

---

## Reading the summary

`artifacts/miprov2_summary.json` is the artifact to read after a run. Schema:

```json
{
  "train_size": 5,
  "val_size": 3,
  "best_val_f1": 0.83,
  "final_val_f1": 0.83,
  "total_trials": 7,
  "wall_clock_seconds": 12.4,
  "artifact_path": "artifacts/miprov2_best_val_f1_0.83.json"
}
```

| Field              | Meaning                                                              |
| ------------------ | -------------------------------------------------------------------- |
| `train_size`       | Number of encounters in the train split.                             |
| `val_size`         | Number of encounters in the val split.                               |
| `best_val_f1`      | Highest F1 MIPROv2 saw across its internal trials.                    |
| `final_val_f1`     | F1 of the program MIPROv2 returned (may be < best if it regressed).  |
| `total_trials`     | How many candidate prompts MIPROv2 evaluated.                         |
| `wall_clock_seconds` | End-to-end runtime, useful for budgeting a real-LM run.            |
| `artifact_path`    | Where the best compiled program is saved.                            |

If `best_val_f1 == final_val_f1` and `total_trials >= 1`, the compile loop
converged on its best-so-far candidate. If they diverge, MIPROv2's selection
step picked a different program than its best — worth a comment, but not
necessarily a bug.

---

## Re-loading a saved program

```python
import dspy
program = dspy.load("artifacts/miprov2_best.json")
```

The acceptance check (in `scripts/optimize.py` near the end) re-loads and
re-evaluates on the same val split, asserting F1 == `best_val_f1` within
1e-6. This is the round-trip reproducibility contract.

---

## Extending into a real iteration primitive

The 4-step patch plan from `docs/QA_RESEARCH_DSPY_INTEGRATION.md`:

1. **Replace the inline 8-encounter synthetic list** with a loader for
   `data/val.json` (50 encounters) plus a held-out 5-encounter train split.
   The current 5/3 split is too small for MIPROv2 to discriminate prompts.

2. **Add a `--base-prompt` CLI flag** that reads
   `prompts/v12/auditor_prompt.txt` and seeds the MIPROv2 instruction
   proposer from it. Currently the script starts from the default prompt
   the DSPy signature generates; the v12 prompt is what the rest of the
   pipeline actually uses, so MIPROv2's starting point should be it.

3. **Change the output path** from `artifacts/miprov2_best_*.json` to
   `prompts/_candidate_${TS}/auditor_prompt.txt` (plain text, not DSPy JSON
   checkpoint) so the existing v0/v1/v2 archive mechanism can promote it.

4. **Add a baseline-vs-candidate F1 delta check**: re-run
   `run_v0_auditor.py` against the candidate prompt, diff mean F1 against
   the v12 pinned F1, and `exit 1` if the candidate is ≤ v12.

After those four steps, add `scripts/iterate_with_dspy.sh` as a 30-line
wrapper:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
N_TRIALS="${N_TRIALS:-10}"
BASE_PROMPT="${BASE_PROMPT:-prompts/v12/auditor_prompt.txt}"
OUT_DIR="prompts/_candidate_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"
python scripts/optimize.py \
    --base-prompt "$BASE_PROMPT" \
    --out-dir "$OUT_DIR" \
    --n-trials "$N_TRIALS"
echo "Candidate prompt written to: $OUT_DIR/auditor_prompt.txt"
```

---

## What the scaffold proves today

A green `python run.py` proves:

- DSPy is installed and importable in this environment.
- The `MIPROv2(metric=..., auto='medium', num_threads=4, ...)` spec from
  the kanban body actually compiles in the current DSPy version.
- The grader metric (`match_findings` F1) is wired through to the
  teleprompter.
- The save/load round-trip is reproducible (the post-run re-evaluation
  asserts F1 within 1e-6 of the reported `best_val_f1`).
- The wall-clock budget for a 5/3 split with a DummyLM is sub-second,
  giving you a lower bound for budgeting a real-LM run.

It does **not** prove:

- The compiled program is better than the hand-written v12 prompt (the
  DummyLM returns canned responses that don't reflect LM behavior).
- MIPROv2 can find improvements against real audit data (5 train / 3 val
  is too small to discriminate).
- The artifact is a deployable prompt file (it's a DSPy JSON checkpoint,
  not a `.txt` file the v0/v1/v2 archive mechanism consumes).

---

## Related docs

- `docs/QA_RESEARCH_DSPY_INTEGRATION.md` — the audit that flagged the wiring gap.
- `docs/ITERATION_LOG.md` — iteration history (v0 → v12 prompt changes).
- `docs/QA_AUDIT_CHAIN.md` — the audit chain that consumes prompts/vN/auditor_prompt.txt.
- `scripts/optimize.py` — the scaffold itself.
- `scripts/improve_iteration.sh` — the current top-level iteration loop wrapper.
