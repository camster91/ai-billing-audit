# t_90ba3e58 — Uncertainty_flags

**Audit claim:** Add uncertainty flags (auditor 'not sure' vs 'definitely wrong')

**Evidence:**
- `prompts/v12/auditor_prompt.txt` uses 'severity' (info/low/medium/high/critical) but no 'confidence'
- No `confidence: float` in the finding schema
- Coders cannot triage by auditor confidence

**Verdict:** **missing** — No confidence output. Severity is set by the auditor subjectively; no separate signal for 'I think this is wrong' vs 'I'm sure'.

**Recommended follow-up:** Add `confidence: float (0..1)` to finding schema; have v12 prompt emit a low confidence (<0.6) when the rule is plausible but the note is ambiguous; surface in the UI as a yellow dot.
