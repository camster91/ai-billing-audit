# t_574a6c03 — Modifier_24_57

**Audit claim:** Modifier -24 / -57 (unrelated E/M, decision for surgery)

**Evidence:**
- `rules/seed_rules.json` mentions 'modifier -57' (decision for surgery)
- No modifier -24 in seed
- No AHCIP equivalent (v12 prompt correctly notes 'Alberta does NOT have a -24 modifier')

**Verdict:** **partial** — -57 is present; -24 is missing for the US-CMS path. The AHCIP side is correctly documented as not having -24.

**Recommended follow-up:** Add a -24 rule to seed_rules.json for the US-CMS path ('Unrelated E/M during global period'); add 5 labeled examples to v3 prompt.
