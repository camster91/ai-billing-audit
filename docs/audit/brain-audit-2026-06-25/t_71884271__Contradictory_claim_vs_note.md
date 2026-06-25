# t_71884271 — Contradictory_claim_vs_note

**Audit claim:** Contradictory claim vs note (biller said one thing, note says another)

**Evidence:**
- `src/ai_billing_audit/judge.py` exists (2 references) — may have contradiction logic
- No dedicated contradiction detector; no claim-vs-note diff
- `prompts/v12/auditor_prompt.txt` does not explicitly require claim-vs-note contradiction check

**Verdict:** **missing** — No explicit contradiction detector; the auditor may silently accept a claim that's directly contradicted by the note.

**Recommended follow-up:** Add `detect_contradictions(claim, note)` in `judge.py` and a `rule_citation` that emits 'claim contradicted by note: <quote>' as a high-severity finding.
