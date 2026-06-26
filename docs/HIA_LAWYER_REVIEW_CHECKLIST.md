# HIA Template — Lawyer Review Checklist

> Hand this doc + `docs/BAA_TEMPLATE_HIA.md` to Alberta counsel.
> Every item below is a real risk we could not resolve without a
> lawyer; the draft template represents our best non-legal effort.

## Background for the lawyer

- **Product:** Zorva pre-submit medical claims auditor. Reads
  clinical notes + claim codes; flags AHCIP denials before submission.
- **Custodian model:** Each Alberta pilot clinic is the Custodian
  (HIA s. 1(1)(f)). Ashbi Design Inc. is the Information Manager.
- **PHI involved:** Clinical notes, patient identifiers, billing
  codes, provider NPIs. No lab results, no imaging, no genomics.
- **Why an IMA (not an agent agreement):** Ontario's PHIPA uses
  "agent" terminology (PHIPA s. 2). Alberta's HIA does not. The
  HIA-equivalent instrument is an Information Manager Agreement
  under HIA s. 65.
- **Cross-border disclosure:** The service runs on a Hostinger VPS
  outside Canada and uses an LLM provider (ollama / minimax-m3:cloud)
  outside Alberta. Both are cross-border disclosures under HIA
  s. 64(1) and require the Custodian's express written consent.

## Items the lawyer must review

### 1. Section 3.2 — s. 65(1) "comply as if custodian"
- Confirm s. 65(1) is the right reference for an IMA's compliance
  duty. The Manager (Ashbi) is bound "as if it were the custodian"
  — this is a strong duty and the breach consequences are the same
  as a custodian breach.
- Confirm whether any HIA section does NOT apply to an IM (e.g. s. 8
  safeguards language may be tailored differently for IMs).

### 2. Section 4 — Cross-border disclosure
- HIA s. 64(1) requires "express written consent" before disclosure
  outside Alberta. Is the Custodian's signature on this Agreement
  sufficient "express written consent" for the duration of the pilot,
  or does each cross-border disclosure need separate written consent?
- Is disclosing the clinical note to an LLM provider a single
  "disclosure" (one consent covers all calls to that provider for
  the duration of the IMA) or N disclosures (one consent per call)?
  The Auditor makes roughly one LLM call per audit.
- Should we list each LLM provider individually in Appendix A, or
  is a category (e.g. "any LLM subprocessor that meets the safeguards
  in s. 5") acceptable?
- The 30-day notice before adding a new provider — is this enforceable?
  Or should it be 60 / 90 days for Custodian's privacy officer to
  complete a DPIA?

### 3. Section 5.2(c) — Retention period
- The Health Information Regulation (Alta Reg 70/2001) sets retention
  periods by record type. The Manager retains audit log entries for
  10 years; the Custodian's retention for clinical notes may be
  different. Confirm that the Manager's 10-year retention does not
  exceed (and therefore force the Manager to keep) data the Custodian
  has destroyed.
- HIA s. 8 + the Regulation: confirm the 10-year period is the right
  number for the records the Manager holds (mostly audit log entries,
  not the clinical notes themselves).

### 4. Section 7 — Breach notification
- HIA s. 67.1-67.4 (added in 2018): the Custodian (not the Manager)
  notifies the Commissioner. Confirm our split is right: Manager
  notifies Custodian within 72h; Custodian notifies the OIPC and
  individuals.
- HIA does not specify a Manager-side notification deadline. Is 72h
  reasonable, or should it be tighter (24h, 48h) for "real risk of
  significant harm" cases?
- "Real risk of significant harm" is the OIPC's threshold. Confirm
  our draft doesn't accidentally widen the Manager's notification
  duty beyond what HIA requires.

### 5. Section 8 — Access / correction / complaints
- HIA has NO statutory deadline for custodian responses to access
  or correction requests (contrast: PIPEDA's 30 days, PHIPA's 30
  days). Our draft says "30 days." Confirm this is reasonable.
- For complaints to the Manager directly: 30 days is reasonable but
  not statutory. Confirm we should soften to "as soon as practicable"
  to match the OIPC's expectation.

### 6. Section 9 — Return / destruction
- 30-day window for return/destruction on termination: confirm this
  is a reasonable SLA. Some HIA practitioners prefer 60 days for
  large-scale returns.
- "Written certification of destruction" within 7 days: confirm this
  language is enforceable and the Custodian will accept a digital
  signature on the cert.

### 7. Section 11 — Termination
- HIA s. 65(2) (terminate an IMA): confirm the Custodian's right to
  terminate on 30 days' notice is enforceable, including during a
  pending breach investigation.
- "Material breach" definition: our draft doesn't define material.
  Should we add a definition (e.g. "a breach that results in actual
  or reasonably suspected unauthorized disclosure of Health
  Information")?

### 8. Missing: Insurance
- Real HIA IMAs typically require the IM to carry professional
  liability insurance (often $1M-$5M per occurrence / $5M-$10M
  aggregate) and to name the Custodian as an additional insured.
  We do NOT have an insurance clause. Add one.
- Cyber liability coverage specifically — many IMAs exclude this
  from "professional liability" so we should call it out separately.

### 9. Missing: Audit rights
- The Custodian should have the right to audit the Manager's
  compliance with the IMA on reasonable notice (e.g. 30 days).
  HIA s. 65(3) gives the Commissioner audit powers; the
  Custodian's contractual right is separate. Add a clause.
- Should this extend to the Manager's subprocessors (LLM provider)?
  Practical concern: ollama/minimax-m3:cloud likely won't allow
  a Zorva customer to audit them. Document this gap.

### 10. Missing: Amendment of law
- What happens if HIA is amended during the term of the IMA? Most
  IMAs include an "amendment of law" clause that requires the
  parties to negotiate in good faith to bring the IMA into
  compliance within a stated period (typically 90 days). Add one.

### 11. Missing: Survival
- Sections 5 (Safeguards), 7 (Breach notification), 8 (Access /
  correction / complaints), and 9 (Return / destruction) should
  survive termination of the IMA for a defined period (typically
  the longer of the statutory retention period or 2 years post-
  termination). Add a "Survival" clause.

### 12. Missing: Specific penalty / remedies reference
- HIA s. 75-80 (offences + fines) is the statutory penalty regime.
  Our draft doesn't reference it. The Manager's exposure to
  prosecution under HIA is real (up to $50K individuals / $500K
  organizations per offence). Should we include a "the parties
  acknowledge the statutory penalties" clause to make the
  seriousness explicit?

### 13. Missing: Subprocessor due-diligence
- The ollama / minimax-m3:cloud LLM is a critical subprocessor.
  We have a row in Appendix A but no contractual commitment that
  the LLM provider meets specific safeguards. Either:
  (a) negotiate a subprocessor agreement with the LLM, OR
  (b) document the Manager's due diligence (their DPA, security
  posture, location, breach history) and append to the IMA.
  Option (b) is the realistic path. Add a "Subprocessor Due
  Diligence" clause.

### 14. Missing: Definitions for technical terms
- The draft says "TLS 1.3" and "AES-256" without defining them.
  Real IMAs append a glossary or define inline. Decide which.

### 15. Missing: Document the Hostinger VPS in writing
- The VPS is on Hostinger (jurisdiction: Lithuania, EU). The
  IMA should explicitly state where the data is stored and the
  legal regime governing that storage (GDPR + Lithuanian law).
  Currently this is only mentioned in passing in s. 4.2(a).

### 16. Missing: Data residency claim in marketing copy
- The marketing site (apps/portal/src/app/legal/privacy/page.tsx)
  may say "data residency: Canada" but the VPS is in Lithuania.
  The IMA's cross-border consent is the legal mechanism; the
  marketing copy needs to align. Flag this so the marketing
  team can update in the same change.

### 17. Order of review
1. Items 1, 2, 11 (foundational — these define what the IMA is and
   what survives termination).
2. Items 4, 9, 12 (high-impact — breach notification, audit rights,
   penalty acknowledgement).
3. Items 8, 13 (operational — insurance + subprocessor due diligence).
4. Items 3, 5, 6, 7, 10, 14, 15, 16 (polish — refine retention periods,
   timeframes, glossary, residency language).

### 18. Estimated effort
- Initial review + comments: 4-6 hours of lawyer time at standard
  Alberta commercial rates.
- Negotiation of redlines: 2-4 hours.
- Final review + sign-off: 1 hour.

### 19. Realistic outcome
- The current draft is structurally sound (HIA s. 65 is the right
  instrument, cross-border consent is explicit, breach notification
  flows to the right party). Expect redlines on items 8 (insurance),
  9 (audit rights), and 11 (survival).
- The cross-border section (item 2) is the highest-risk area —
  HIA s. 64(1) is strictly enforced. Confirm the LLM provider's
  safeguards and data-handling location with the LLM's
  legal/security team BEFORE the lawyer finalizes the IMA.

## After the lawyer signs off

1. Have the Custodian's privacy officer (or external counsel)
   review the same draft.
2. Negotiate Custodian-specific changes (governing law,
   jurisdiction, insurance limits, audit-notice period).
3. Get written signatures from both parties.
4. File the signed copy at `/opt/projects/ai-billing-audit/contracts/`
   (chmod 600, NOT in git).
5. Add a row to `prompts/MANIFEST.json`-style audit log of every
   IMA signed (custodian name, effective date, renewal date,
   signed-by, lawyer who reviewed).

## Reference

- **Health Information Act**, RSA 2000, c H-5 — full text at
  https://www.albertacannabis.ca/wp-content/uploads/2024/07/HIA.pdf
- **Health Information Regulation**, Alta Reg 70/2001
- **Office of the Information and Privacy Commissioner of Alberta**
  (OIPC) — https://www.oipc.ab.ca/
- HIA s. 1(1)(f) — definition of "custodian"
- HIA s. 8 — duty to protect
- HIA s. 30 — combining records
- HIA s. 56-65 — Information Manager regime
- HIA s. 64(1) — cross-border disclosure consent
- HIA s. 65(1) — IM compliance duty
- HIA s. 67.1-67.4 — breach notification
- HIA s. 75-80 — offences and penalties
