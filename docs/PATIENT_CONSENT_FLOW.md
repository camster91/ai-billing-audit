# Patient consent flow — PHIPA s.18 implied consent

PHIPA Section 18 establishes **implied consent** for health-information custodians (the clinic) to use or disclose personal health information (PHI) for the purpose of providing or assisting in providing health care to the individual.

Zorva is an **Agent** under PHIPA — we handle PHI on behalf of the clinic, but we don't have a direct relationship with the patient. The clinic's implied consent covers us, but only for the services the clinic has told patients it provides.

## What this means for the clinic

The clinic's patient consent form (or its posted notice of information practices) must include a reference to **third-party billing-assistance services**. A generic "we may use your information for billing purposes" usually covers this, but explicit language is better.

### Recommended consent-form language (Ontario / Alberta)

The clinic should add a sentence like one of these to its patient consent form:

> We use third-party billing-assistance services (including Zorva AI Billing Audit) to review claims for coding accuracy, denial-risk, and appeal-letter drafting before submission. These services process your clinical documentation and claim metadata on our behalf under our Business Associate Agreement / Health Information Custodian Agent agreement.

> We engage third-party agents to assist with billing, coding, and audit functions. These agents process de-identified claim metadata and your clinical documentation under contract with us.

The exact wording should be reviewed by the clinic's privacy officer or counsel.

### Onboarding checklist item

During the first call with a new pilot clinic, the Zorva onboarding lead should explicitly confirm with the clinic owner (or privacy officer):

- [ ] The clinic's patient consent form (or posted privacy notice) mentions third-party billing-assistance services, OR the clinic owner confirms this is implied by existing language and will be added before the first audit runs.
- [ ] The clinic has reviewed Zorva's privacy policy at `/legal/privacy` and the BAA / HIC-Agent agreement.
- [ ] The clinic's patient roster includes only patients who have been seen under the clinic's standard consent flow (no walk-in consent bypass, no third-party referrals without documented consent).
- [ ] For patients who have explicitly opted out of any data processing (rare but exists), Zorva's encounters must be excluded from automated audit. Use the doctor email opt-out flow at `/api/tenants/{tenant_id}/...` (or contact support for a bulk exclusion list).

## What Zorva does and doesn't do

**Zorva DOES:**
- Process clinical documentation and claim metadata under the clinic's BAA / HIC-Agent agreement.
- Read-only access to clinical notes; write access is limited to the audit-trail and (when authorized) appeal letters.
- Send summary emails to the physician on duty (not to the patient directly).
- Maintain a SHA-256 audit trail of every action.
- Honor patient opt-out requests via `/api/tenants/{tenant_id}/...` endpoints.

**Zorva DOES NOT:**
- Contact patients directly. Ever.
- Train AI models on tenant data.
- Share tenant data with anyone outside the BAA / HIC-Agent scope.
- Persist patient names, addresses, phone numbers, or other directly identifying information. All patient identifiers are pseudonymized at the application boundary using SHA-256 with a tenant-scoped salt.

## Other regimes

- **PIPEDA (federal Canada commercial)**: covered by the BAA + the privacy policy at `/legal/privacy`.
- **US HIPAA**: covered by the BAA. Business Associate Agreements explicitly authorize Zorva to process PHI on behalf of the covered entity (the clinic).
- **Mexico NOM-024**: similar implied-consent regime; the clinic's notice of privacy practices must cover third-party processing.
- **Colombia Ley 1581**: requires explicit consent for non-treatment uses of PHI. The clinic should obtain written consent for billing-assistance processing under Ley 1581 Habeas Data requirements.

## Summary

The clinic's existing consent flow covers Zorva's processing under PHIPA s.18 implied consent, provided the clinic's notice of information practices covers "third-party billing assistance" or equivalent language. Zorva's onboarding checklist should explicitly confirm this at the first call. If the clinic does NOT have such language, the onboarding lead should recommend adding it before the first audit runs.

The full privacy policy is at `/legal/privacy` on the live product. The PHIPA s.53 right-of-access workflow (PHIPA s.53) is implemented at `/api/tenants/{tenant_id}/export.jsonl` and `/api/tenants/{tenant_id}` (delete).

## References

- PHIPA (Ontario): S.O. 2004, c. 3, Sched. A, s. 18 (Implied consent within the circle of care).
- HIA (Alberta): R.S.A. 2000, c. H-5, s. 24 (Disclosure to affiliates).
- PIPEDA: Personal Information Protection and Electronic Documents Act, S.C. 2000, c. 5.
- HIPAA: 45 CFR §164.502 (Uses and disclosures of PHI), §164.504(e) (Business Associate Contracts).
- NOM-024-SSA3-2012 (Mexico): Art. 5 (consentimiento informado).
- Ley 1581 de 2012 (Colombia): Art. 9 (consentimiento expreso yícito).

v1 stub copy. Replace with lawyer-reviewed text before the first paying pilot signs.
