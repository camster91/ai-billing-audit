# t_195e7080 — Rule_citation_field

**Audit claim:** Add 'rule_citation' field to findings (formal citation, not just rule_id)

**Evidence:**
- `src/ai_billing_audit/scenario_schema.json` and `scenario_schema.py` define the finding shape
- The current schema has `rule_ids: [str, ...]` but no `rule_citation: str` (formal citation like 'CMS IOM 100-04 §30.6.1')
- `rules/seed_rules.json` rule entries have `source: str` (e.g., 'CMS E/M') but no formal §/page citation

**Verdict:** **missing** — Schema has `rule_ids` (referencing our internal IDs) but no formal payer-document citation. Audits cite 'EM-002' rather than 'CMS IOM 100-04 §30.6.1' which a coder cannot look up without us.

**Recommended follow-up:** Add `rule_citation: str` to finding schema; populate `source_citation` field in each seed rule with formal CMS/AHCIP citation; update v12 prompt to require emitting the formal citation.
