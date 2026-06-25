# t_fcd5b1c9 — Adversarial_examples

**Audit claim:** Adversarial examples: notes designed to fool the auditor

**Evidence:**
- `src/ai_billing_audit/synth_agent.py` exists (31 references) — synthetic-note generator
- `src/ai_billing_audit/synth/` directory present
- No dedicated adversarial set; `docs/BUGS_overfit.md` and `BUGS_overfit_curve.txt` suggest overfit was a real problem but no adversarial test fixture

**Verdict:** **missing** — A synthetic-note generator exists but no adversarial fixture (notes designed to look correct but contain hidden denials). The overfit BUGS docs suggest this is a known risk.

**Recommended follow-up:** Author `data/adversarial/v1.jsonl` with 30 notes containing: (a) plausible-but-wrong codes, (b) boilerplate that masks missing time statement, (c) cut-and-paste prior-note reuse, (d) upcoded MDM. Wire into `tests/test_adversarial.py`.
