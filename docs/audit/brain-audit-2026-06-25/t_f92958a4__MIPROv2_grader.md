# t_f92958a4 — MIPROv2_grader

**Audit claim:** Wire DSPy MIPROv2 with a real grader (not self-agreement)

**Evidence:**
- `src/ai_billing_audit/auditor_module.py` uses `dspy.Predict` (NOT MIPROv2)
- `src/ai_billing_audit/grader.py` exists (grader module)
- `src/ai_billing_audit/grader_config.json` exists in `prompts/`
- No `src/optimize.py` MIPROv2 invocation; that file exists but is not yet MIPROv2

**Verdict:** **partial** — DSPy module IS wired (`dspy.Predict` over `AuditClaim`); grader module exists; missing: the actual MIPROv2 optimizer instantiation, a real-grader metric function, and an `optimize.py` runner that produces a saved program.

**Recommended follow-up:** Implement `metric_for_grader` in `src/ai_billing_audit/grader.py`, add `src/ai_billing_audit/optimize_mipro.py` that calls `dspy.MIPROv2(metric=...)`, save optimized program to `artifacts/auditor_v14/`.
