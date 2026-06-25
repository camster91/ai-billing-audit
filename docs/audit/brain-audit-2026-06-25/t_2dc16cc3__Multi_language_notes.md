# t_2dc16cc3 — Multi_language_notes

**Audit claim:** Multi-language notes (Spanish, Mandarin, French-Canadian)

**Evidence:**
- `grep -ric 'spanish\|mandarin\|french' src/ai_billing_audit/` → 0 matches
- No translation layer; no language-detection
- AHCIP is English/French (Canadian); Spanish is rare in this market

**Verdict:** **missing** — No multi-language handling. Notes in Spanish/Mandarin will be silently misread. AHCIP needs French at minimum (per Canadian bilingual requirements).

**Recommended follow-up:** Add `src/ai_billing_audit/lang_detect.py` (langdetect or fasttext) and an English-translation step (cheap model) before the auditor runs; document AHCIP French-language obligation.
