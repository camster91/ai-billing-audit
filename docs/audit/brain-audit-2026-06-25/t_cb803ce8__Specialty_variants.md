# t_cb803ce8 — Specialty_variants

**Audit claim:** Per-specialty prompt variants (cards vs surgery vs ED vs psych)

**Evidence:**
- `docs/SPECIALTY_TUNING.md` exists
- `grep -ril 'specialty\|cards\|surgery' prompts/` → only references in v12 SOMB context
- No `prompts/v*-cards.txt`, `v*-surgery.txt`, etc.

**Verdict:** **missing** — A specialty tuning doc exists but no per-specialty prompt files. The auditor runs the same prompt for all specialties.

**Recommended follow-up:** Create `prompts/v14/auditor_prompt_cards.txt`, `_surgery.txt`, `_ed.txt`, `_psych.txt`; add a specialty-routing helper that picks the variant from the encounter's specialty field.
