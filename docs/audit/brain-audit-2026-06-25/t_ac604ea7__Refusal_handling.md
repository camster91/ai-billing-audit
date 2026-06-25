# t_ac604ea7 — Refusal_handling

**Audit claim:** Refusal handling: auditor says 'note is unclear, need more info'

**Evidence:**
- `prompts/v0/auditor_prompt.txt` includes 'If the encounter is not flagged, return an empty findings list and a one-sentence summary explaining why no findings apply'
- `docs/BUGS_refusal_2026_06_17.md` exists — prior refusal-related bug was filed
- No explicit refusal signal in the schema (no 'needs_more_info: bool' field)

**Verdict:** **partial** — The prompt allows empty findings with a summary but does not define a structured 'needs more info' signal. Coders cannot reliably tell 'no findings' from 'I gave up'.

**Recommended follow-up:** Add `needs_more_info: bool` and `clarification_questions: list[str]` to the finding schema; update v12 prompt to require filling these when the note is ambiguous.
