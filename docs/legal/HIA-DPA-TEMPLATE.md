# Data Processing Agreement — Alberta Health Information Act (HIA)

> **DRAFT — LEGAL REVIEW REQUIRED.** This template is a working draft for use
> with Alberta clinics in the 60-day Zorva pilot. It is **not** legal advice.
> A privacy officer can sign it for the pilot after a 10-minute review, but
> clinics should obtain independent legal review for any post-pilot
> paid engagement. This template aligns with the Alberta *Health Information
> Act*, R.S.A. 2000, c. H-5 ("HIA") and the federal *Personal Information
> Protection and Electronic Documents Act*, S.C. 2000, c. 5 ("PIPEDA").

---

## 1. Parties & Effective Date

**Provider (Processor):** Ashbi Design Inc., operating the Zorva
pre-submit claim-audit service ("Ashbi").

**Customer (Custodian):** **[Clinic Name]**, an Alberta health services
provider (the "Clinic").

**Effective Date:** **[YYYY-MM-DD]**

---

## 2. What this DPA covers

This is the data-processing addendum to the Zorva pilot agreement. It
governs how Ashbi handles the four categories of Clinic Data uploaded
to Zorva: (a) billing claims (837P X12 or CSV), (b) clinical notes,
(c) Zorva audit findings, and (d) biller accept/edit/dismiss actions.
It is intentionally **short** (2 pages when printed) because the
underlying pilot already scopes the use to pre-submit audit only.

---

## 3. HIA Roles

Under HIA, the Clinic is the **custodian** of the diagnostic and
treatment information it generates. Ashbi is an **affiliate** acting
solely on the custodian's written instructions. The Clinic retains
all HIA custodian duties (s. 3 HIA), including the duty to notify the
Office of the Information and Privacy Commissioner (OIPC) of any
breach (s. 70 HIA).

---

## 4. Data residency (Canadian data centre only)

- **At rest and in transit:** All Clinic Data is stored and processed
  inside a Canadian data centre (currently AWS `ca-central-1`
  Montréal, or an equivalent Canadian region under a comparable
  provider).
- **No cross-border access.** Ashbi staff access Clinic Data only from
  devices located in Canada. Subprocessors with cross-border data
  exposure are not permitted under this DPA.
- **Backups.** Encrypted at rest (AES-256), retained in Canada, and
  excluded from any DR failover that leaves Canadian jurisdiction.
- **Verification.** On request, Ashbi will provide a written attestation
  of the region in use and a SOC 2 / equivalent third-party audit
  report for the underlying infrastructure provider.

---

## 5. No shared model training (clinic data is never used for AI training)

Ashbi's product is a **pre-submit auditor**, not a model fine-tuning
service. Clinic Data uploaded to Zorva is processed at audit time and
then handled per the retention rule in §7.

- **No training on Clinic Data.** Clinic Data is never used to train,
  fine-tune, evaluate, benchmark, or otherwise improve any
  general-purpose or foundation model — including any model that Ashbi
  or a subprocesssor operates. This applies to raw clinical notes,
  claim data, audit findings, and biller actions.
- **Ephemeral LLM prompts.** When the auditor calls an LLM (e.g.
  OpenAI, Anthropic, Ollama-hosted, or a local model), the prompt is
  processed for the audit transaction only. Per our subprocessor
  agreements, the LLM provider does not retain, log, or train on
  these prompts beyond what is contractually required to complete the
  request and provide abuse-prevention monitoring.
- **LLM keys are yours.** Zorva supports "bring your own LLM key"
  (BYOK). When the Clinic provides its own key, the prompt and the
  response are governed by the Clinic's contract with the LLM provider
  — Ashbi is not an additional party to that exchange.

---

## 6. Access controls

- **Role-based access (RBAC).** Each user has a documented role
  (biller, clinic manager, IT contact) and only the permissions
  required for that role.
- **MFA required** on all accounts that touch Clinic Data.
- **Least privilege.** Ashbi engineers access Clinic Data only on a
  documented support request, via time-bounded credentials, with the
  action logged to a hash-chained audit trail.
- **Personnel security.** Ashbi staff with access to Clinic Data are
  bound by confidentiality undertakings and receive HIA/PIPEDA
  awareness training at hire and annually.

---

## 7. Retention and Pilot-end purge (60-day hard delete)

- **During the 60-day pilot:** Clinic Data is retained for the duration
  of the pilot.
- **Pilot end (default):** Within 7 days before pilot end, Ashbi sends
  the Clinic a **Data Export Notice** with download instructions. The
  Clinic has 15 days to download a full export (CSV / JSON / 837P as
  applicable).
- **60-day purge:** **60 calendar days** after pilot end, **all Clinic
  Data is permanently deleted** from production systems, encrypted
  backups, and operational logs. Backups rotate out within 90 days.
  Ashbi provides a written deletion certificate within 10 business
  days of deletion.
- **No aggregated retention without opt-in.** De-identified aggregated
  metrics may be retained beyond pilot **only** if the Clinic has
  signed Schedule A opting in. The default is opt-out.

---

## 8. Breach notification — 72 hours

If Ashbi becomes aware of an actual or reasonably suspected breach of
safeguards involving Clinic Data, Ashbi will notify the Clinic's
designated security contact **within 72 hours** of confirmation.

The notice will include:

- Date(s) and nature of the breach.
- Categories and approximate volume of records affected.
- Steps taken to contain and remediate.
- Ashbi's designated contact for follow-up.

The Clinic, as HIA custodian, is responsible for any further
notifications to the OIPC under s. 70 HIA and to affected individuals
under s. 25 HIA. Ashbi will provide reasonable cooperation, including
incident reconstruction from the hash-chained audit trail.

---

## 9. Audit trail (hash-chained, immutable)

Zorva produces a hash-chained audit trail of every action that touches
Clinic Data: uploads, audit runs, finding decisions, exports, account
changes, and access events. The chain is SHA-256 linked, with a
genesis block on tenant creation. A clinic can verify chain integrity
from the portal at any time. The audit trail itself is treated as
Clinic Data and is purged with the rest under §7.

---

## 10. Subprocessors (current)

| Subprocessor | Purpose | Region |
|---|---|---|
| Cloud infrastructure (AWS `ca-central-1` or equivalent) | Encrypted Postgres, compute, storage | Canada |
| Transactional email (Resend) | Pilot welcome, finding digests | Canada / US — message bodies are Clinic Data; metadata is not |
| Error tracking | Application errors | Canada where available; otherwise de-identified metadata only |

A current list is maintained at the URL listed in Schedule B and is
updated with 30 days' notice to the Clinic before any new subprocesssor
touches Clinic Data.

---

## 11. Patient access requests (s. 35 HIA)

If Ashbi receives an access, correction, or complaint from a patient
whose information may be in Clinic Data, Ashbi will acknowledge within
2 business days and **forward the request to the Clinic within 5
business days**. The Clinic, as custodian, is responsible for the
substantive response. Ashbi will not respond directly to the patient
and will not provide Clinic Data to anyone other than the Clinic.

---

## 12. Limitation of liability

Each party's aggregate liability under this DPA is limited to the
fees paid by the Clinic to Ashbi in the 12 months preceding the claim
(or, during the free pilot, **CAD $1,000**). Neither party is liable
for indirect, incidental, or consequential damages. This clause does
not limit liability for breach of confidentiality, gross negligence,
or wilful misconduct.

---

## 13. Signatures

**ASHBI DESIGN INC.**

- Signature: ______________________________
- Name: **[Full Name]**
- Title: **[Title]**
- Date: **[YYYY-MM-DD]**

**[CLINIC NAME]**

- Signature: ______________________________
- Name: **[Full Name]**
- Title: **[Privacy Officer / Clinic Manager]**
- Date: **[YYYY-MM-DD]**

---

## Schedule A — Opt-in for aggregated, de-identified metrics (default: NO)

- [ ] **YES** — the Clinic opts in to Ashbi retaining aggregated,
      de-identified metrics derived from Clinic Data beyond the pilot
      term. Data is k-anonymized (k ≥ 10) and stripped of direct
      identifiers before any retention.
- [ ] **NO** (default) — aggregated data is purged with Clinic Data
      under §7.

**Clinic representative:**

- Signature: ______________________________
- Name / Title: **[Full Name / Title]**
- Date: **[YYYY-MM-DD]**

---

## Schedule B — Subprocessor list URL & breach contacts

- **Subprocessor list URL:** `https://ai-billing-audit.ashbi.ca/trust/subprocessors`
- **Clinic security contact:** `[Name, Title, Email, Phone]`
- **Clinic privacy officer:** `[Name, Title, Email, Phone]`
- **Ashbi security contact:** `security@ashbi.example`

---

*Companion documents: `docs/DATA_AGREEMENT_TEMPLATE.md` (master pilot
agreement, 17 sections), `docs/BAA_TEMPLATE_HIPAA.md` (US BAA
template, retained for cross-border future use), and
`docs/security/SEC_REVIEW_phi.md` (technical safeguards detail).*
