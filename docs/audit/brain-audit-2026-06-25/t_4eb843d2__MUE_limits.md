# t_4eb843d2 — MUE_limits

**Audit claim:** MUE (medically unlikely edits) limits per code

**Evidence:**
- `grep -ic 'MUE' rules/seed_rules.json` → several 'CMS Medically Unlikely Edits' references in _meta.sources and a few rule texts
- No `rules/mue.json` lookup table
- `grep -ic 'MUE' prompts/v12/auditor_prompt.txt` → 0 matches for the prompt itself

**Verdict:** **missing** — MUE concept IS mentioned but no per-code MUE limit table, and the v12 auditor prompt (AHCIP) does not invoke MUE at all (correct for Alberta SOMB, but the v0/v3 US-CMS prompts should).

**Recommended follow-up:** Add `rules/mue_limits.json` (CMS quarterly release), wire a `check_mue(code, units)` helper in `src/ai_billing_audit/auditor.py`, and add 5 labeled examples to the v3 prompt.
