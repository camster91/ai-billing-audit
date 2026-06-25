# t_c41a7ebe — Streaming_responses

**Audit claim:** Streaming responses (show partial findings as they come in)

**Evidence:**
- `grep -ric 'stream\|chunk' src/ai_billing_audit/` → 4 matches in api.py, 3 in auditor_module.py (likely non-streaming use)
- No `async def stream_audit` or SSE endpoint
- DSPy's `dspy.streaming` package is vendored but unused

**Verdict:** **missing** — No streaming endpoint. Findings arrive in a single blocking response. Long audits (high MDM-level cases with many findings) feel slow.

**Recommended follow-up:** Add `POST /api/v1/audit/stream` SSE endpoint that yields findings one-at-a-time as the LLM emits them; use DSPy's `streamify` adapter for the LM call.
