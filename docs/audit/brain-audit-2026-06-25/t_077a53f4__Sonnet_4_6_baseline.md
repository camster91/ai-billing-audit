# t_077a53f4 — Sonnet_4_6_baseline

**Audit claim:** Test claude-sonnet-4-6 as a baseline (compare to current Ollama cloud minimax-m3)

**Evidence:**
- `src/ai_billing_audit/auditor_module.py` uses `dspy.LM('anthropic/claude-sonnet-4-5')`
- No `minimax-m3` reference in code (the model name suggests a previous Ollama cloud pin)
- `docs/llm-pinning.md` exists

**Verdict:** **missing** — Sonnet 4.6 is NOT tested as a baseline. The current pin is Sonnet 4.5. No head-to-head benchmark vs minimax-m3.

**Recommended follow-up:** Add `src/ai_billing_audit/eval_models.py` that runs the v12 prompt against {sonnet-4-5, sonnet-4-6, haiku-4-5, minimax-m3} on the 20-encounter ground-truth set; record P/R/F1/latency/cost.
