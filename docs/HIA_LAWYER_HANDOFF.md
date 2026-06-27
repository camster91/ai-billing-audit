# HIA Information Manager Agreement — Lawyer Handoff Package

**Prepared:** 2026-06-27 by Mavis (Cameron's drafting assistant)
**For:** Alberta-licensed counsel with HIA / privacy-law expertise
**Client:** Cameron Ashley (Ashbi / Zorva — freelance medical-billing auditor)

---

## What's in this package

| File | Purpose |
|---|---|
| `BAA_TEMPLATE_HIA.md` | Draft Information Manager Agreement under Alberta's *Health Information Act* (HIA), framed per HIA s. 64(1) (custodianship of individually identifying health information by an affiliated/contracted party). NOT a "Business Associate Agreement" (PHIPA / HIPAA terminology) — HIA uses "Information Manager" + custodian delegation language. |
| `HIA_LAWYER_REVIEW_CHECKLIST.md` | 19-item numbered review checklist — the things I want a lawyer to look at before this template gets sent to a real clinic. Each item has the section reference, the legal concern, and what "good" looks like. |

---

## How Cameron should use this

1. **Don't send the template to a clinic yet.** It's a draft for counsel, not a counterparty-ready agreement.
2. **Find an Alberta lawyer with HIA / privacy-law expertise.** Look for someone who has done custodian agreements for health-tech vendors before. McMillan, Bennett Jones, or a smaller privacy boutique is fine.
3. **Email both files plus this cover note.** A typical review engagement for a 330-line IMA template like this runs 4–8 hours of lawyer time = $1,500–$4,000 CAD depending on seniority.
4. **Bring answers to the 19-item checklist.** Many of the items have bracketed placeholders (e.g. `[CLINIC NAME]`, `[INSURANCE CARRIER]`, `[SUBCONTRACTOR NAME]`) that the lawyer needs Cameron's input on before they can finalize.

---

## Why this matters

Zorva processes Alberta health information (clinical notes + AHCIP claims) on behalf of clinics. Under HIA s. 64, this means:

1. **Cameron is acting as an "affiliated/contracted party"** to a custodian (the clinic). The clinic remains the custodian of record; Cameron provides processing services.
2. **The IMA must be in writing** (HIA s. 64(1)(b)) and must include specific safeguards — the agreement template covers them, but counsel should verify nothing was missed.
3. **Cross-border data flow** is explicit: Zorva's database lives on a Hostinger VPS outside Alberta, and the LLM provider may be US-based. HIA s. 64(1)(c)(ii) requires custodian consent for cross-border transfer — the template covers this, but it's the item most likely to need legal teeth (e.g. adequacy language, breach-notification timeline).
4. **Breach notification** under HIA s. 65 is the custodian's responsibility, but the IMA must obligate Cameron to notify the custodian within a defined window. The template says "without unreasonable delay" — counsel may want a specific number (24h? 72h?).

---

## Drafting notes for counsel (things I had to decide unilaterally that may need a lawyer's eye)

These are the items where I made a judgement call that counsel should verify rather than take at face value:

1. **"Information Manager" framing (not "Business Associate").** HIA doesn't use the "agent" / "Business Associate" terminology PHIPA uses. The template uses "Information Manager" throughout. If the clinic's existing PHIPA paperwork uses "BA" terminology, there's a translation step.

2. **Cross-border consent explicit.** The template requires the custodian (clinic) to acknowledge that data may leave Alberta. This is HIA s. 64(1)(c)(ii) but it's a politically sensitive provision — clinics may push back. Counsel should advise on whether "acknowledgement" is sufficient or whether affirmative consent language is required.

3. **Subcontractor due diligence.** Cameron uses Ollama Cloud (LLM provider) and Hostinger (VPS). Both are subcontractors in HIA terms. The template requires Cameron to maintain a current list of subcontractors and notify the custodian of changes. Counsel should verify this meets the s. 64(1)(c)(iii) standard.

4. **Insurance.** Template specifies $2M professional liability + $2M cyber liability, with the custodian named as additional insured on the cyber policy. Counsel should advise on whether this is the right floor for a small-volume solo operator or whether clinics will require $5M+.

5. **Audit rights.** Template gives the custodian the right to audit Cameron's records once per 12-month period, with 30 days' notice. Some clinics may want more frequent audit rights; some may accept less. Counsel should advise on the market norm.

6. **Survival clauses.** Template specifies that confidentiality + breach-notification obligations survive termination indefinitely; other obligations survive for 10 years (matching HIA's 10-year retention under s. 8 + Health Information Regulation). Counsel should verify the 10-year figure against current HIA Regulation retention requirements.

7. **Termination for convenience.** Template doesn't include it — termination requires cause (breach, insolvency, change of control). Some clinics may want termination for convenience with 30 days' notice. Counsel should advise on the market norm.

8. **Governing law.** Template specifies Alberta law and Alberta courts. This is correct for HIA-covered data, but if the clinic operates in BC or SK, the analysis changes (each province has its own health-information statute). Counsel should advise on a multi-provincial addendum if Cameron plans to expand beyond Alberta.

---

## What I need from counsel (output of the engagement)

A marked-up version of `BAA_TEMPLATE_HIA.md` plus a short memo (1–3 pages) addressing each of the 19 items in `HIA_LAWYER_REVIEW_CHECKLIST.md`. The memo doesn't need to restate the law — it needs to identify the *specific risk* for a solo-operator medical-billing auditor and recommend a fix.

---

## Contacts in the package

- **Cameron Ashley** — sole proprietor, operator of Zorva (zorva.ashbi.ca) and Ashbi (ashbi.ca)
- **Email:** [Cameron's email]
- **Phone:** [Cameron's phone]
- **Province of operation:** Alberta (Alberta Health Services billing jurisdiction)
- **LLM provider:** Ollama Cloud (model: minimax-m3:cloud)
- **VPS provider:** Hostinger (AlmaLinux 10, VPS in [region])

---

**Generated by:** Mavis orchestrator session
**Package files:** `docs/BAA_TEMPLATE_HIA.md` + `docs/HIA_LAWYER_REVIEW_CHECKLIST.md` + this `HIA_LAWYER_HANDOFF.md`