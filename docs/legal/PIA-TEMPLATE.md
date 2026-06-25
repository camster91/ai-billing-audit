# Privacy Impact Assessment (PIA) — Zorva AI Claims Audit

> **DRAFT — LEGAL REVIEW REQUIRED.** This template is a working draft for use with
> Alberta and Ontario clinics in the 60-day Zorva pilot. It is **not** legal
> advice. A privacy officer can sign it for the pilot after a 10-minute review,
> but clinics should obtain independent legal review for any post-pilot paid
> engagement. This template aligns with the *Alberta Health Information Act*,
> R.S.A. 2000, c. H-5 ("HIA"), the *Personal Information Protection and
> Electronic Documents Act*, S.C. 2000, c. 5 ("PIPEDA"), the *Ontario Personal
> Health Information Protection Act*, 2004, S.O. 2004, c. 3 ("PHIPA"), and the
> respective Information and Privacy Commissioner (OIPC) guidelines for PIAs.
>
> **How to use this template:** the plain prose sections (≈80% of the document)
> are pre-filled for the standard Zorva 60-day pilot. The privacy officer at
> the clinic only needs to fill in the **[CLINIC]** placeholders (about 20
> fields, ~10 minutes). The signed PIA then attaches to the HIA / PHIPA
> Data Processing Agreement (`docs/legal/HIA-DPA-TEMPLATE.md`).

---

## 1. Project description

### 1.1 Project name

**Zorva 60-day Pilot — AI-Assisted Pre-Submission Claims Audit**

### 1.2 Project sponsor

**Provider (Processor):** Ashbi Design Inc. ("Ashbi"), operating the Zorva
pre-submission claim-audit service.

**Project lead:** Cameron Ashley, c/o Ashbi Design Inc., `cameron@ashbi.ca`.

### 1.3 Custodian (Clinic)

**[CLINIC LEGAL NAME]**, operating as **[CLINIC OPERATING NAME]**.

Custodian contact: **[PRIVACY OFFICER NAME, TITLE, EMAIL, PHONE]**.

### 1.4 Project description

Zorva is a pre-submission claim-audit service. The clinic uploads a claim
encounter (an 837P X12 file or a CSV row, plus an associated clinical note)
to the Zorva API; Zorva returns a list of findings — specific AHCIP / SOMB
(or OHIP / Schedule of Benefits) rules the auditor believes the claim is
missing, miscoding, or at risk of denial on. The clinic's biller reviews each
finding, accepts it, edits the claim, or dismisses it.

The auditor is **advisory only**. It does not submit claims, modify claims,
or communicate with Alberta Health / Ontario Ministry of Health. Every
decision to submit, edit, or hold a claim remains with the clinic and its
biller.

The pilot runs for 60 days. At the end of the pilot the clinic either rolls
into a paid engagement or asks for hard-delete of all data; either way the
data leaves the system.

### 1.5 Why this PIA is being done

A PIA is required because the project involves:

- **Personal health information** (clinical notes attached to claims) being
  transmitted to and processed by a third-party AI service.
- A **new collection, use, or disclosure** pathway not previously covered by
  the clinic's existing privacy framework (the clinic has historically
  submitted claims directly to Alberta Health / OHIP without a third-party
  processor).
- A **new information system** (the Zorva stack) holding PHI for a defined
  retention window.

The PIA satisfies:

- **HIA s. 64** (affiliate compliance — a custodian must ensure that its
  affiliates and agents comply with the HIA).
- **OIPC PIA Guidelines (2015, rev. 2022)** — required for any new
  information system or service involving individually identifying health
  information.
- **PHIPA s. 12(1)** and the **IPC Ontario PIA Guide (2023)** — required
  for a health information custodian that engages an agent to perform
  services involving PHI on its behalf.
- **PIPEDA s. 4.1 / Schedule 1 (Principle 4.1.3)** — collection, use, and
  disclosure limited to purposes that a reasonable person would consider
  appropriate in the circumstances.

---

## 2. Authority and purpose

### 2.1 Authority for the collection

The clinic collects the underlying health information under the usual
physician-patient relationship: HIA s. 20 (collection by a custodian) for
Alberta clinics, PHIPA s. 30 (consent) for Ontario clinics, and PIPEDA
Schedule 1 (consent — implied or express, depending on sensitivity) federally.

### 2.2 Purpose of the new use and disclosure

The clinic is disclosing a subset of that information (the claim line, the
clinical note, the diagnosis codes) to the Zorva service for the purpose of
**pre-submission audit**. The purpose is to catch errors that would result
in denial, under-coding, or auto-rejection of the claim — i.e. to recover
revenue that the clinic is contractually entitled to under the AHCIP / OHIP
fee schedule and that would otherwise be lost due to routine billing errors.

This purpose is **within the reasonable expectations of the patient** who
consented to the original collection: a patient consents to a physician
billing the provincial health plan on their behalf, and a reasonable patient
expects the physician to use reasonable tools to do so correctly. The Zorva
PILOT consent form (`docs/PATIENT_CONSENT_FLOW.md`) covers the disclosure
specifically.

### 2.3 Limiting the use

Zorva will not use the disclosed information for any purpose other than the
audit. Specifically:

- Zorva does **not** train a model on the clinic's claims. The v12 auditor
  uses a frozen prompt bundle + a frozen model checkpoint. No fine-tuning,
  no embedding-store learning, no prompt learning on customer data.
- Zorva does **not** aggregate or sell findings across clinics. Findings are
  tenant-scoped.
- Zorva does **not** communicate with the patient, with Alberta Health, or
  with the Ontario Ministry of Health on the clinic's behalf.
- Zorva does **not** retain data past the pilot window unless the clinic
  signs a paid engagement.

---

## 3. Description of the personal / health information

### 3.1 What is disclosed to Zorva

For each audit, the clinic transmits the following fields. The list is
deliberately short — anything not on this list is never sent to Zorva.

| Field | Example | Source system |
|---|---|---|
| Patient identifier (hashed) | SHA-256 of PHN / OHIP card number | Clinic's billing system, hashed client-side before upload |
| Encounter date | 2026-04-12 | Billing system |
| Encounter type | Office visit, telehealth, procedure | Billing system |
| Claim line items (SOMB / OHIP codes) | 03.04A, 03.01A, J18.9 | Billing system |
| Diagnosis codes (ICD-10-CA) | J18.9, I10 | Billing system |
| Clinical note (free text) | "67M with productive cough x 5d…" | EMR |
| Service provider identifier | AHCIP practitioner ID | Billing system |

### 3.2 What is explicitly **not** disclosed

- Full patient name
- Full PHN / OHIP card number (only SHA-256 hash)
- Full date of birth (year-only is acceptable; full DOB never)
- Address, phone number, email
- Family / next-of-kin identifiers
- Lab values, imaging, or other diagnostic data not on the claim
- Any prior-encounter information beyond what is in the current claim

### 3.3 Volume

For an average Alberta FP practice: ~1,500 claims/month, of which Zorva
audits all in the pilot window. For a typical pilot: ~3,000–5,000 encounters
over 60 days.

For an average Ontario GP practice: ~2,000–3,000 claims/month.

### 3.4 Sensitivity

The clinical note associated with a claim can include sensitive
information: mental-health diagnoses, substance-use history, sexual-health
information, genetic information. The disclosure pathway in this PIA
covers all of it; the safeguards in §6 are calibrated to that sensitivity.

---

## 4. The data flow

```
[Clinic EMR / billing system]
        │
        │  TLS 1.3 (HTTPS) — strong cipher suite only
        │  Auth: per-tenant API key (Bearer) + per-clinic IP allowlist
        ▼
[Zorva API container] ──── stores ────► [Postgres: claims table]
        │                                  [Postgres: notes table (separate schema)]
        │                                  [Postgres: findings table]
        │                                  [Postgres: audit_trail (hash-chained)]
        ▼
[v12 LLM call] — frozen model, frozen prompt, no logging of prompt contents
        │
        │  findings returned to API container
        ▼
[Zorva API] ──── returns findings JSON ────► [Clinic dashboard]
        │
        │  Biller reviews, accepts/edits/dismisses
        ▼
[Biller action recorded in audit_trail — hash-chained, append-only]
```

At the end of the 60-day pilot, on one email from the clinic's privacy
officer, all data is hard-deleted (Postgres DROP TABLE; Postgres file
shred with `shred -n 3`; backup snapshots pruned). A written confirmation
is sent within 7 business days.

---

## 5. The legal bases (per jurisdiction)

### 5.1 Alberta — HIA

The clinic is the **custodian** under HIA s. 1(1)(f)(i). Ashbi is an
**affiliate** of the custodian under HIA s. 5(2) — an agent performing
services on the custodian's behalf. The HIA-DPA template
(`docs/legal/HIA-DPA-TEMPLATE.md`) implements the affiliate obligations in
HIA s. 64.

The specific authorities for disclosure are:

- **HIA s. 50** — disclosure to an affiliate for the purpose of carrying
  out a purpose of the custodian (the pre-submission audit is a purpose
  of the custodian's billing-and-collection workflow).
- **HIA s. 35(1)(b)** — use of individually identifying health information
  by an affiliate is permitted where the use is necessary to carry out a
  purpose of the custodian.
- **HIA s. 60** — the duty to safeguard the information applies to the
  affiliate (Ashbi) just as it does to the custodian.

### 5.2 Ontario — PHIPA

The clinic is the **health information custodian** ("HIC") under PHIPA
s. 3(1). Ashbi is an **agent** of the HIC under PHIPA s. 17 — an agent
performs services on behalf of the HIC and the HIC remains responsible
for the agent's actions.

The specific authorities for disclosure are:

- **PHIPA s. 20** — implied consent within the circle of care (the
  agent relationship is treated as within the circle for the purpose of
  the HIC's billing-and-collection workflow).
- **PHIPA s. 12(1)** — the agent agreement (HIA-DPA, applied to PHIPA
  context) satisfies the written-agreement requirement for an agent
  relationship.
- **PHIPA s. 13** — the HIC remains accountable for the agent's
  compliance, including breach notification.

### 5.3 Federal — PIPEDA

The Zorva service is a "service provider" processing data on behalf of
the clinic (which is the organization). PIPEDA Schedule 1 Principle 4.1.3
permits the organization to disclose to a service provider where the
disclosure is necessary and the service provider is bound by comparable
obligations.

Ashbi is bound by comparable obligations via the HIA-DPA, which
incorporates HIA / PHIPA-equivalent safeguards by reference.

---

## 6. Safeguards

### 6.1 Technical safeguards

- **TLS 1.3 in transit** with a strong cipher suite only (no TLS 1.0/1.1;
  no RC4; no 3DES).
- **AES-256 at rest** in Postgres; per-tenant data encryption keys scoped
  to the pilot tenant.
- **Hash-chained audit log** (`audit_trail.sql`) — append-only, each row
  contains `prev_hash` and `row_hash`, tamper-evident (any modification
  invalidates the chain).
- **No logging of prompt contents** — the v12 LLM call is configured to
  not log the clinical note; the model provider's standard request log
  is disabled via the LLM-side `no_log` flag where supported.
- **No shared model training** — no fine-tuning, no embedding learning,
  no prompt learning on customer data.
- **Per-tenant API keys** with optional IP allowlist.
- **MFA on the clinic dashboard** — TOTP required for all biller /
  privacy-officer / admin accounts.
- **Role-based access control** — biller can read claims and findings,
  cannot export; privacy officer can export the audit log; admin can
  manage users; viewer is read-only.

### 6.2 Administrative safeguards

- **BAA / DPA in place** before any data moves (`docs/legal/HIA-DPA-TEMPLATE.md`).
- **Privacy officer sign-off** on this PIA before pilot kickoff.
- **Sub-processor list** maintained and disclosed — current list is
  Ashbi Design Inc. (processor) + the LLM provider (sub-processor for
  the audit call only; clinical note is sent, response is findings only).
- **Breach notification** — Ashbi commits in the DPA to notify the
  clinic within **72 hours** of becoming aware of any unauthorized
  disclosure or breach.
- **Personnel training** — all Ashbi staff with access to the audit
  environment sign a confidentiality undertaking and complete the annual
  privacy training.

### 6.3 Physical safeguards

- **Canadian data residency** — the Postgres cluster runs in Canada
  (currently in Alberta, in a SOC 2 Type II audited data centre). No
  data leaves Canada during the pilot.
- **Restricted access to the production environment** — production
  access is via SSH key + 2FA, logged, and reviewed quarterly.
- **Backups encrypted** — backups are AES-256, retention 30 days,
  destroyed on the same schedule as the primary data.

---

## 7. Risk assessment and mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Unauthorized disclosure via API key compromise | Low | High | Per-tenant keys, optional IP allowlist, 72h breach notice, key rotation procedure |
| LLM provider logging prompt content | Low | High | `no_log` flag where supported; DPA prohibits logging; quarterly audit of provider's no-log status |
| Insider access at Ashbi | Low | High | Background checks, confidentiality undertakings, least-privilege RBAC, all access logged |
| Data residency violation | Very low | High | Canadian-only infra; CI/CD pipeline rejects non-Canadian region deploys |
| Breach during 60-day retention window | Low | High | Hash-chained audit log means any breach is detectable; 72h notification; hard-delete procedure documented and tested |
| Patient consent gap | Low | Medium | Standard PILOT consent form (`docs/PATIENT_CONSENT_FLOW.md`) included in the onboarding packet |
| Vendor lock-in / portability | Low | Low | All data exportable as CSV + JSON; HIA-DPA includes portability clause |
| Re-identification of hashed PHN | Low | Medium | Hash is per-tenant-salted; hash + claim context are not shared outside the tenant |

### 7.1 Residual risk

After mitigation, residual risk is rated **LOW**. The pilot is short
(60 days), the data scope is narrow (claims + clinical note only, no
demographic enrichment), and the safeguards exceed the OIPC's minimum
guidance for a third-party AI service.

---

## 8. Patient notification and consent

### 8.1 What the patient is told

The clinic's PILOT consent form (template at `docs/PATIENT_CONSENT_FLOW.md`)
states, in plain English:

> "Your doctor's office uses an AI-assisted billing review service called
> Zorva. Before your visit is billed to Alberta Health (or OHIP), a
> computer reviews the claim and the doctor's notes for coding errors.
> This may include a service operated by another company. The review
> happens on the doctor's computer network, then the data is deleted at
> the end of the 60-day pilot. If you have questions, ask the front desk
> or contact our privacy officer."

### 8.2 What the patient can do

- **Ask questions** — privacy officer contact is on the consent form.
- **Opt out** — the clinic can submit the claim without Zorva review
  (manual review only). Opting out does not affect care.
- **Withdraw** — the patient can withdraw consent at any time; the
  clinic will stop sending future claims to Zorva and request hard-delete
  of any historical claims already audited.

---

## 9. End-of-pilot data handling

### 9.1 Decision point

At the end of the 60-day pilot, the clinic makes one of two decisions:

1. **Continue** — sign a paid engagement; data persists under the same
   HIA-DPA terms, with an updated PIA reflecting the longer retention
   window.
2. **End** — email `privacy@ashbi.ca` and request hard-delete. Within
   7 business days:
   - All Postgres rows scoped to the tenant are deleted (DROP TABLE
     for the tenant-scoped schemas; DELETE for the audit_trail rows).
   - All backup snapshots older than the deletion request are pruned.
   - LLM provider request logs (if any) are requested to be purged
     via the provider's data-subject-deletion API.
   - A written confirmation is sent to the privacy officer.

### 9.2 Audit trail retention

The audit_trail hash chain is preserved for **30 days** after the end of
the pilot, then hard-deleted. This is sufficient for the clinic to
respond to any retroactive complaint or audit request during the
30-day window. (Ontario IPC and Alberta OIPC guidance permit a
shorter-than-default retention for completed audit logs.)

---

## 10. Sign-off

### 10.1 Custodian (Clinic)

| Field | Value |
|---|---|
| Clinic legal name | **[CLINIC LEGAL NAME]** |
| Clinic operating name | **[CLINIC OPERATING NAME]** |
| Jurisdiction | **[Alberta / Ontario]** |
| Privacy officer name | **[PRIVACY OFFICER NAME]** |
| Privacy officer title | **[TITLE]** |
| Privacy officer email | **[EMAIL]** |
| Privacy officer phone | **[PHONE]** |
| Pilot start date | **[YYYY-MM-DD]** |
| Pilot end date | **[YYYY-MM-DD]** (start + 60 days) |
| Signature | _________________________ |
| Date | **[YYYY-MM-DD]** |

### 10.2 Processor (Ashbi)

| Field | Value |
|---|---|
| Legal entity | Ashbi Design Inc. |
| Signing officer | Cameron Ashley |
| Title | Founder / Privacy Officer (interim) |
| Email | `privacy@ashbi.ca` |
| Signature | _________________________ |
| Date | **[YYYY-MM-DD]** |

---

## Sources and references

### Alberta

- **Health Information Act**, R.S.A. 2000, c. H-5 — <https://www.qp.alberta.ca/documents/Acts/h05.pdf>
- **OIPC PIA Guidelines** (2015, rev. 2022) — <https://www.oipc.ab.ca/media/1034963/pia_guidelines_2022.pdf>
- **OIPC "Privacy Impact Assessment" guidance page** — <https://www.oipc.ab.ca/action-comply/privacy-impact-assessments.html>
- **HIA s. 64 — affiliate compliance** — <https://www.qp.alberta.ca/documents/Acts/h05.pdf>
- **Alberta Schedule of Medical Benefits (SOMB)** — <https://www.alberta.ca/fees-health-professionals.aspx>

### Ontario

- **Personal Health Information Protection Act, 2004**, S.O. 2004, c. 3 (PHIPA) — <https://www.ontario.ca/laws/statute/04p03>
- **IPC Ontario "Guide to the Personal Health Information Protection Act"** (2023) — <https://www.ipc.on.ca/health-individuals/file-health-privacy-complaint/guide-phipa/>
- **IPC Ontario "Privacy Impact Assessment" guidance** — <https://www.ipc.on.ca/directives-and-policies/privacy-impact-assessments/>
- **PHIPA s. 17 — agents** — <https://www.ontario.ca/laws/statute/04p03#BK19>
- **Ontario Schedule of Benefits — Physician Services** — <https://www.health.gov.on.ca/en/pro/programs/ohip/sob/>

### Federal

- **Personal Information Protection and Electronic Documents Act**, S.C. 2000, c. 5 (PIPEDA) — <https://laws-lois.justice.gc.ca/eng/acts/p-8.6/>
- **PIPEDA Schedule 1 — Fair Information Principles** — <https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/>
- **OPC "Privacy Impact Assessment" guidance** — <https://www.priv.gc.ca/en/privacy-topics/privacy-rights/pia/>

### Cross-reference within this project

- `docs/legal/HIA-DPA-TEMPLATE.md` — the HIA/PHIPA-compliant DPA that
  this PIA attaches to.
- `docs/PATIENT_CONSENT_FLOW.md` — the PILOT consent template that
  satisfies §8 above.
- `docs/DEPLOYMENT.md` — where the technical safeguards in §6.1 are
  implemented in code.
- `audit_trail.sql` — the hash-chained audit-log schema referenced
  in §6.1.
- `docs/AHCIP_RULE_REFERENCE.md` — the rule catalogue that defines
  what the v12 auditor actually does with the data.
