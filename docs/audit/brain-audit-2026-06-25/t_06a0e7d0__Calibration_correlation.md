# t_06a0e7d0 — Calibration_correlation

**Audit claim:** Calibration: do confidence scores actually correlate with accuracy?

**Evidence:**
- See t_90ba3e58 — no confidence score exists yet
- `docs/CALIBRATION.md` exists but its scope is unclear
- No reliability-diagram (calibration plot) generator

**Verdict:** **blocked-by-t_90ba3e58** — Cannot measure calibration until confidence scores exist.

**Recommended follow-up:** Once confidence is added: add `src/ai_billing_audit/calibration.py` that bins findings into 10 confidence deciles and computes empirical accuracy per bin; emit a reliability-diagram PNG to `docs/calibration_plots/`.
