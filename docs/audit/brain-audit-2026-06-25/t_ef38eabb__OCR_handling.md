# t_ef38eabb — OCR_handling

**Audit claim:** OCR'd note handling (degraded text from PDF scans)

**Evidence:**
- `grep -ric 'OCR\|pdf\|scanned' src/ai_billing_audit/` → 0 matches
- No OCR preprocessor
- `src/ai_billing_audit/x12_parser.py` exists but is for X12 EDI, not PDFs

**Verdict:** **missing** — No OCR pipeline. Faxed/scanned notes (still common in US healthcare) arrive as raw text with errors; the auditor will mis-parse 'metformin' as 'rnetfonnin'.

**Recommended follow-up:** Add `src/ai_billing_audit/ocr_normalize.py` that runs Tesseract on PDF uploads, then a fuzzy-match spell-corrector over known drug names; document in `docs/OCR_NOTES.md`.
