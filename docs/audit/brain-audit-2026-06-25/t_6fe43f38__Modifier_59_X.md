# t_6fe43f38 — Modifier_59_X

**Audit claim:** Modifier -59 / X{E,S,U} (distinct procedural service)

**Evidence:**
- `grep -ic '\-59\|XE\|XS\|XP\|XU' rules/seed_rules.json` → multiple hits; 'X{ESU}' referenced in PTP context
- No dedicated modifier-59 example set
- No automated detector for missing -59 on bundled-but-separate procedure pairs

**Verdict:** **partial** — Modifier -59 and the X{E,S,U} family ARE referenced in the NCCI PTP rules with a -59-required example; missing: dedicated examples, X{E,S,U} disambiguation guidance, automated detector for 'two procedures same anatomic site, was -59 appended?'.

**Recommended follow-up:** Add 15 examples of -59 correct use + 5 overused -59 to v0 prompt, and add a `check_distinct_procedural_service` helper that walks the (claim_codes, anatomic_site) tuple.
