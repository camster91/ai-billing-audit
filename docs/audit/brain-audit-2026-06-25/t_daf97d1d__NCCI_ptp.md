# t_daf97d1d — NCCI_ptp

**Audit claim:** NCCI / procedure-to-procedure edits coverage

**Evidence:**
- `grep -ic 'NCCI' rules/seed_rules.json` → 12+ hits for 'NCCI' / 'PTP'
- `grep -ic 'NCCI\|MUE\|modifier' prompts/v12/auditor_prompt.txt` → 19 hits
- `rules/seed_rules.json` _meta.counts.ncci = 12 (seeded)
- No file `docs/NCCI_REFERENCE.md` (`ls docs/ | grep -i ncci` → empty)

**Verdict:** **partial** — NCCI PTP edits ARE in seed rules with 12 example edits and the prompt references NCCI; missing: a comprehensive PTP table linked to specific code pairs, no automated pair-lookup, no quarterly refresh process.

**Recommended follow-up:** Build `rules/ncci_ptp.json` (full PTP edits, ~50K rows from CMS quarterly release) and a lookup helper used by `auditor.py` to inject pair-specific context.
