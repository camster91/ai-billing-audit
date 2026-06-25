# t_07fa3b10 — Cost_guardrail

**Audit claim:** Per-tenant cost guardrail (alert when LLM spend > $X/month)

**Evidence:**
- `src/ai_billing_audit/roi.py` exists (12 references) — tracks SAVINGS, not spend
- No spend tracker; no per-tenant budget; no alert hook
- `grep -ric 'monthly.*budget\|cost.*alert' src/` → 0 matches

**Verdict:** **missing** — No spend tracking. ROI module tracks clinic-side savings but Zorva has no visibility into its own LLM spend per tenant.

**Recommended follow-up:** Add `src/ai_billing_audit/spend_tracker.py` with per-tenant counters, a monthly aggregation job, and an alert webhook at $X/month configurable in `.env`.
