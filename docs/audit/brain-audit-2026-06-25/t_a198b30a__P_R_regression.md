# t_a198b30a — P_R_regression

**Audit claim:** Track per-prompt-version P/R over time (regression detection)

**Evidence:**
- `src/ai_billing_audit/grading.py` (per-clinic grading) and `per_clinic_f1.py` exist
- `feedback.py` exists (1 reference)
- No `metrics_history` table or time-series regression detector
- `docs/ITERATION_LOG.md` exists but appears manual

**Verdict:** **partial** — Per-version grading tools exist (`per_clinic_f1.py`, `grading.py`) but no automated regression alarm; `ITERATION_LOG.md` is a manual ledger.

**Recommended follow-up:** Add `metrics_history` table to the SQLite store (run_id, prompt_version, precision, recall, f1, ts), and a `detect_regression(window=5)` function that fires when f1 drops >2 std.
