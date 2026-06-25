# t_f08506de — EM_documentation

**Audit claim:** E/M level documentation adequacy (2021+ guidelines)

**Evidence:**
- `rules/seed_rules.json` has 14 E/M rules (EM-001..EM-014 in _meta.counts.em)
- EM-002 covers MDM, EM-003 covers time ranges, EM-005/006/007 cover MDM elements
- `grep -ic 'MDM\|medical decision' prompts/v12/auditor_prompt.txt` → multiple hits
- No 2021-guideline-specific training set; no undercode/overcode scenarios

**Verdict:** **partial** — 2021 MDM framework IS in seed rules with element-by-element breakdown; missing: a labeled test set of correct-vs-wrong MDM level selection per encounter, and a per-specialty calibration.

**Recommended follow-up:** Create `tests/fixtures/em_mdm_examples.jsonl` with 30+ encounters tagged with correct code (99212-99215) and an evaluator that compares auditor picks to ground-truth.
