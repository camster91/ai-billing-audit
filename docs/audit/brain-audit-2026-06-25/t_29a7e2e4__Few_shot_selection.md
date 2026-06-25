# t_29a7e2e4 — Few_shot_selection

**Audit claim:** Few-shot example selection (best 30 examples per rule family)

**Evidence:**
- `prompts/v12/auditor_prompt.txt` includes 11+ EXAMPLE blocks (EXAMPLE 1..11)
- No per-rule-family few-shot selection algorithm
- Examples appear hand-curated, not auto-selected from a labeled pool

**Verdict:** **partial** — Few-shot examples ARE present in v12 but they're static, hand-curated, and not per-rule-family selected from a scored pool.

**Recommended follow-up:** Build `src/ai_billing_audit/few_shot.py` with `select_top_k(rule_family, k=30, pool=data/few_shot_pool.jsonl)` using a rule-aware diversity scorer; refactor v12 to call it.
