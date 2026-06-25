# t_d8acb516 — Two_pass_audit

**Audit claim:** Two-pass audit: quick triage + detailed review

**Evidence:**
- `prompts/v0` is 25 lines (the 'quick' baseline); v12 is 761 lines (the 'detailed' one)
- No orchestration between v0 and v12
- The audit pipeline calls one prompt version per claim

**Verdict:** **missing** — Two prompt versions exist (v0 short, v12 long) but no orchestrated two-pass flow. Cost is always paid at v12-level.

**Recommended follow-up:** Add `src/ai_billing_audit/two_pass.py` that runs v0 first, only escalates to v12 if v0 returns any 'medium+' severity finding; benchmark cost savings.
