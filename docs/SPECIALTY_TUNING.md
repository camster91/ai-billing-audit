# Per-Specialty Prompt Fine-Tuning (MIPROv2)

Status: design doc, ready for implementation when feedback log is
populated.
Owner: learning-loop, P5 specialty-tuning task (`t_b3abc8e2`).
Last updated: 2026-06-24.

This document specifies the **per-specialty prompt fine-tuning
pipeline** for the Zorva auditor. The goal is to generate a tuned
prompt variant per medical specialty (e.g. `family_medicine_v1.md`,
`cardiology_v1.md`) using the same MIPROv2 optimizer already wired in
`scripts/optimize.py`, but driven by **specialty-filtered slices** of
the biller feedback log instead of the full corpus.

This is **prompt optimization only** — we are not retraining model
weights, not changing the base v1 prompt, and not altering the
prompt format. We are picking better few-shot examples + instructions
for each specialty, validated on that specialty's held-out encounters.

---

## 1. Why per-specialty

Family medicine, cardiology, and dermatology submit different claim
shapes:

- **Family medicine** has the highest volume of low-acuity visits
  (03.01A, 03.03A) and a high rate of `missing-modifier-25` on
  same-day procedure + E/M.
- **Cardiology** has more high-acuity E/M (03.04A, 03.05A), more
  diagnostic codes (Holter, stress test, ECG), and more denials
  related to `unbundling`.
- **Dermatology** has more procedure codes (biopsy, excision, cryo)
  and a different modifier-25 pattern (procedures drive the visit,
  not the E/M).

A single base prompt dilutes the few-shot examples across all three,
so each specialty sees examples that look nothing like its own
encounters. Per-specialty prompts let us trade global coverage for
specialty-specific precision without losing the base prompt as a
fallback.

---

## 2. Data-availability gate

A specialty is **eligible** for a tuning run when **all** of the
following are true:

1. The specialty has a label in the biller feedback log
   (see `zorva-learning-loop/t_e4d5e4b2` — the feedback log is the
   source of truth for the slice).
2. **≥ 3 months** of feedback-log data exists for the specialty
   (counted from the first feedback entry, not calendar quarters).
3. The specialty slice has **≥ 200 labeled feedback entries**
   (configurable via env var `TUNE_MIN_EXAMPLES`, default 200).
4. The slice has **≥ 50 distinct encounters** (a single encounter
   with 8 findings counts as 1 encounter, not 8).
5. The base prompt has been **stable for ≥ 14 days** (so we're not
   tuning on data that reflects a prompt we just changed).

If any check fails, the tuner **refuses to start** with a clear
message naming which gate failed and what the current value is. This
prevents the "we ran MIPROv2 on 14 examples and shipped the result"
failure mode.

---

## 3. Pipeline

### 3.1 Entry point

```
python -m hermes.prompts.tune --specialty family_medicine \
    [--min-examples 200] [--min-months 3] \
    [--train-frac 0.8] [--seed 42] \
    [--dry-run]
```

`--dry-run` runs the data-availability gate and prints the slice stats
without invoking the optimizer. Use this in the cron precheck.

### 3.2 Steps

1. **Load feedback log slice.** Query the feedback log for entries
   where `encounter.physician.specialty == <specialty>`. Pull the
   `accept | dismiss | modify` label and the free-text
   `what_should_this_have_been` field (when present).
2. **Pair to base-prompt outputs.** Each feedback entry joins to the
   original auditor finding via `encounter_id + finding_id`. We get
   (input, predicted_finding, biller_decision) tuples.
3. **Split train/eval.** Stratified 80/20 split on `biller_decision`.
   Set seed for reproducibility.
4. **Filter train set.** Keep only entries where the biller's
   decision implies a signal:
   - `accept` → predicted finding is a positive example
   - `dismiss` → predicted finding is a negative example
     (trainer should learn to NOT fire this rule on this input)
   - `modify` → the `what_should_this_have_been` field becomes the
     positive example (we *want* the alternative output)
5. **Run MIPROv2.** Same optimizer config as
   `scripts/optimize.py` (currently: `bootstrap-fewshot`, `auto=medium`,
   `num_candidates=18`, `num_trials=24`,
   `max_bootstrapped_demos=4`, `max_labeled_demos=6`).
6. **Evaluate.** Score on the held-out 20% slice with
   `scripts/eval_holdout.py` (the grader metric, P/R/F1 at the
   finding level).
7. **Persist.** Write the tuned prompt to
   `prompts/specialty/<specialty>_v1.md`. Write the eval report
   (metrics + 5 sample traces) to
   `prompts/specialty/<specialty>_v1.eval.json`.
8. **Update registry.** Update the per-specialty status file
   `prompts/specialty/_status.json` with
   `{status: "tuned", last_tuned_at, base_hash, val_R, val_P, val_F1}`.
9. **Log.** Emit a structured log line so the dispatcher can see
   "tuned family_medicine in 14m, val_F1=0.78 (+0.04 vs base)".

### 3.3 Output files

```
prompts/specialty/
  _status.json                    # registry: {specialty: status_record}
  family_medicine_v1.md           # tuned prompt (Markdown, same format as base)
  family_medicine_v1.eval.json    # metrics + sample traces
  cardiology_v1.md
  cardiology_v1.eval.json
  dermatology_v1.md
  dermatology_v1.eval.json
```

The Markdown format of the tuned prompt must be **byte-compatible**
with the base prompt format (same front-matter, same section
headings). This is what the marketplace loader expects.

---

## 4. Marketplace prompt loader

The marketplace prompt loader is the runtime path that picks which
prompt to serve to a given tenant. Pseudocode:

```python
def load_prompt(tenant: Tenant) -> LoadedPrompt:
    specialty = tenant.specialty  # e.g. "family_medicine"
    candidate = f"prompts/specialty/{specialty}_v1.md"

    if file_exists(candidate):
        status = read_status(specialty)
        if status["status"] == "tuned":
            log.info(f"serving specialty variant: {specialty}")
            return LoadedPrompt(
                path=candidate,
                source="specialty",
                base_hash=read_base_hash(),
                last_tuned_at=status["last_tuned_at"],
            )

    log.info(f"serving base prompt (no tuned {specialty} variant)")
    return LoadedPrompt(
        path="prompts/v12/auditor_prompt.txt",
        source="base",
        base_hash=read_base_hash(),
        last_tuned_at=None,
    )
```

Every served prompt is **logged with its source** ("base" vs
"specialty:family_medicine") so the audit chain can attribute
findings to the right model configuration. This matters for
debugging denials and for the per-clinic F1 dashboard
(`t_c34bf190`).

### 4.1 Loader fallback rules

- File missing → fall back to base, log "no variant for {specialty}".
- Variant exists but status is "tuning" → **do not serve** the
  half-written file; fall back to base, log "tuning in progress".
- Variant exists but `last_tuned_at` is > 90 days old → log a
  warning ("stale variant, consider re-running") but **still serve
  it**. Stale > 0 is better than serving nothing.
- Both base and variant unreadable → raise (this is a deployment
  bug, not a normal-path failure).

---

## 5. Re-tuning cadence

Specialties don't tune on a fixed schedule. The tuner re-runs when
**any** of the following is true:

1. The slice grows by ≥ 25% since the last tune.
2. The base prompt changed (we always re-tune after a base bump).
3. The per-clinic F1 dashboard shows the specialty's F1 has dropped
   by ≥ 0.05 over a 30-day window.
4. A manual operator triggers it via
   `python -m hermes.prompts.tune --specialty family_medicine`.

The re-tune **overwrites** the previous file and updates
`last_tuned_at` in the status registry. There's no "v2" suffix per
re-run — we keep one file per specialty and track lineage via the
status record.

---

## 6. Tests

Three test files, all in `tests/`:

| Test file                          | Covers                                |
|------------------------------------|---------------------------------------|
| `test_specialty_tuning_gate.py`    | Data-availability gates (min examples, min months, base stability) |
| `test_specialty_tuning_output.py`  | Output file shape (byte-valid Markdown, eval JSON has metrics + traces) |
| `test_marketplace_loader.py`       | Base-vs-specialty fallback paths, stale-variant warning, "tuning in progress" guard |

Mock the optimizer in tests; don't run MIPROv2 in CI. The integration
test that actually runs the optimizer is a **nightly** job, gated on
the data-availability check (so it no-ops until enough data exists).

---

## 7. Out of scope (explicitly)

- **Not** retraining model weights. Prompt optimization only.
- **Not** changing the base v1 prompt content. The base is the
  source of truth; the specialty variants are forks of it.
- **Not** building the feedback-log collection mechanism. That's
  `t_e4d5e4b2` (already done).
- **Not** building the marketplace prompt marketplace UI. This
  spec is the loader logic only.

---

## 8. Acceptance checklist

When the task moves to "done":

- [ ] `python -m hermes.prompts.tune --specialty family_medicine
      --dry-run` exits 0 with a clear data-availability report.
- [ ] A real tuning run produces `prompts/specialty/family_medicine_v1.md`
      and the matching `.eval.json`.
- [ ] The marketplace loader serves the variant when a tenant's
      specialty matches and a tuned file exists.
- [ ] The marketplace loader falls back to the base prompt and
      logs the decision when the variant is missing / stale /
      half-written.
- [ ] The status registry (`_status.json`) updates on every
      successful run.
- [ ] All three test files pass in CI.
- [ ] A nightly integration job is wired but no-ops until the
      first specialty passes the data-availability gate.
