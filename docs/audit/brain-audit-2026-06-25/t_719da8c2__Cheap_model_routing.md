# t_719da8c2 — Cheap_model_routing

**Audit claim:** Cheap-model-first routing (Haiku for easy, Sonnet for hard)

**Evidence:**
- `src/ai_billing_audit/auditor_module.py` pins `dspy.LM('anthropic/claude-sonnet-4-5')`
- No model-router logic; no easy/hard classifier
- `docs/llm-pinning.md` likely documents the pinned choice

**Verdict:** **missing** — Single model pinned (Sonnet 4.5); no easy/hard routing. Cost-saving is achieved via prompt pinning, not model selection.

**Recommended follow-up:** Add a `difficulty_classifier` (small, rule-based) in `src/ai_billing_audit/llm.py` that picks Haiku vs Sonnet per encounter; benchmark quality delta before promoting.
