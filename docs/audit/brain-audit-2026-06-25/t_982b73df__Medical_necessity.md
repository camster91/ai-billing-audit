# t_982b73df — Medical_necessity

**Audit claim:** Diagnosis-procedure medical-necessity check

**Evidence:**
- `grep -ic 'medical necessity\|medically necessary' rules/seed_rules.json` → several hits in the seed (e.g., 'the encounter must be medically necessary')
- `src/ai_billing_audit/judge.py` exists (1 judge-related match) — possibly a downstream medical-necessity judge
- No dedicated dx-procedure linkage rules (LCD/NCD)

**Verdict:** **partial** — General 'medical necessity' phrasing IS in seed rules; missing: per-diagnosis LCD/NCD lookup (CMS Local/National Coverage Determinations) and a 'dx supports procedure' link table.

**Recommended follow-up:** Add `rules/lcd_ncd_linkage.json` (CMS LCD/NCD index) and a `check_dx_procedure_link(dx, proc)` helper. Document in `docs/MEDICAL_NECESSITY.md`.
