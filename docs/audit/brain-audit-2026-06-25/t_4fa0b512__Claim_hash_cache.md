# t_4fa0b512 — Claim_hash_cache

**Audit claim:** Cache the LLM response per (claim_hash, prompt_version)

**Evidence:**
- `src/ai_billing_audit/demo_registry.py` has a `cache: dict` for parsed JSONL
- `feedback.py` has a comment-cache
- No `(claim_hash, prompt_version)` response cache
- `grep -r 'claim_hash' src/` → 0 production matches

**Verdict:** **missing** — No response cache keyed on (claim_hash, prompt_version). Re-running the same claim through the same prompt version re-pays the LLM cost.

**Recommended follow-up:** Add `src/ai_billing_audit/response_cache.py` with a SQLite-backed `get/set` keyed on `sha256(claim_json) + prompt_version`; TTL 30d; wire into `auditor.py` before the LLM call.
