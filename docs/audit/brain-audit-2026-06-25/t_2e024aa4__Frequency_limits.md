# t_2e024aa4 — Frequency_limits

**Audit claim:** Frequency limits (per-year, per-condition)

**Evidence:**
- `grep -ic 'frequency\|cap' rules/seed_rules.json` → 4 hits (MUE Frequency Threshold, Anatomic Site Cap mentions)
- No `rules/frequency_limits.json` — per-code annual cap table
- `grep -ric 'frequency.*limit\|annual.*limit\|prior.year' src/ai_billing_audit/` → 0 matches in production code
- Per-day MUE caps ARE in seed (4 hits); per-year/per-condition caps are NOT

**Verdict:** **partial** — Per-day MUE caps are in seed rules (4 hits) but no per-year / per-condition annual-cap table. E.g., '1 preventive visit per year' or '12 psychotherapy sessions' are not enforced.

**Recommended follow-up:** Add `rules/frequency_limits.json` with per-code annual/per-condition caps, plus `check_frequency(code, patient_history)` helper that counts prior-year occurrences from claims.
