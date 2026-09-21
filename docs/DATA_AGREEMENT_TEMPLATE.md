# Zorva Pilot Data Agreement — Alberta Health Services Provider

> **DRAFT — LEGAL REVIEW REQUIRED.**
> This template has **not** been reviewed by a lawyer.
> **Do not use for any real pilot until reviewed by qualified Canadian counsel** familiar with Alberta's *Health Information Act* (HIA) and federal *Personal Information Protection and Electronic Documents Act* (PIPEDA).
> Replace every `[...]` placeholder before signing. Clauses are intentionally short and may require tailoring to the clinic's specific circumstances.

---

## 1. Parties

**Provider:** Ashbi Design ("Ashbi"), operating the Zorva pre-submit claim-audit service.

**Customer:** **[Clinic Name]**, an Alberta health services provider (the "Clinic").

**Effective Date:** **[YYYY-MM-DD]**

---

## 2. Scope of Pilot

- **Term:** Sixty (60) calendar days from the Effective Date ("Pilot Term").
- **Purpose:** Pre-submit audit of physician billing claims only. Zorva does not submit claims to Alberta Health Services and is not a replacement for the Clinic's billing system.
- **Users:** Designated Clinic personnel (billers, clinic manager, IT contact) authorized to upload encounters and review audit findings.
- **Out of scope:** Claim submission, payment reconciliation, AHS portal integration, clinical decision support.

---

## 3. Data Covered

Ashbi will process only the following categories of data uploaded by or on behalf of the Clinic:

1. **Billing claims** — in 837P (X12 EDI) format or CSV extract.
2. **Clinical notes** — the source documentation the biller attaches to support each claim (free text, PDFs).
3. **Audit findings** — Zorva's risk scores, rationale, and recommended corrections produced from the input data.
4. **Biller actions** — accept / edit / dismiss decisions the Clinic makes on each finding.

No other categories of personal or health information are authorized for upload. The Clinic is responsible for redacting any data outside the four categories above before upload.

---

## 4. Governing Law & Compliance

This Agreement is governed by the laws of the Province of Alberta and the applicable federal laws of Canada, including:

- **PIPEDA** — *Personal Information Protection and Electronic Documents Act*, S.C. 2000, c. 5.
- **PIPEDA Schedule 1** — the *Canadian Standards Association Model Code for the Protection of Personal Information* (accountability, consent, limiting collection/use/disclosure, accuracy, safeguards, openness, individual access, challenging compliance).
- **HIA (Alberta)** — *Health Information Act*, R.S.A. 2000, c. H-5, including the duties of a "custodian" and "affiliate" under that Act, and the requirement to notify the Office of the Information and Privacy Commissioner (OIPC) of breaches.

The Clinic remains the health-information custodian under HIA. Ashbi acts as an affiliate / information-manager handling health information on the custodian's behalf.

---

## 5. Data Residency

All Customer Data — at rest and in transit — is stored and processed in a **Canadian data centre** (currently `ca-central-1` Montréal or an equivalent Canadian region). No Customer Data is transferred to, accessed from, or stored in any jurisdiction outside Canada. The specific cloud region in use is documented in the underlying Business Associate Agreement / processing addendum ("BAA") referenced in §14.

Backups are encrypted and kept within Canada. Disaster-recovery failover does not exit Canadian jurisdiction.

---

## 6. Data Handling Commitments

Ashbi commits to the following during and after the Pilot Term:

1. **No training on Customer Data.** Customer Data is **never** used to train, fine-tune, evaluate, or otherwise improve any general-purpose or foundation model. LLM vendor prompts that include Customer Data are ephemeral and are not retained by the model provider beyond what is contractually permitted for the transaction (see §6.3).
2. **No third-party sharing without consent.** Ashbi does not sell, rent, or disclose Customer Data to any third party except: (a) subprocessors listed in §14, (b) as required by Canadian law, or (c) with the Clinic's prior written consent.
3. **Aggregated metrics only with explicit opt-in.** De-identified, aggregated metrics (e.g. "median claim value", "finding-rate by category") may be retained beyond the Pilot Term **only if the Clinic has opted in** in writing via Schedule A. Aggregated data is stripped of direct identifiers and k-anonymized (k ≥ 10) before any retention.
4. **Encryption.** Customer Data is encrypted in transit (TLS 1.2+) and at rest (AES-256 or stronger).
5. **Access controls.** Access to Customer Data is limited to Ashbi personnel with a documented business need, under role-based access control, multi-factor authentication, and Canadian jurisdiction.

---

## 7. Retention

- **During Pilot:** Customer Data is retained for the duration of the Pilot Term plus a 30-day post-pilot deletion window (§8).
- **Post-Pilot default:** Customer Data is deleted within thirty (30) calendar days of Pilot Term end, unless the Clinic requests an export.
- **Long-term retention option:** If the parties sign a paid subscription Agreement after the Pilot, the standard retention is up to **seven (7) years** for audit-trail and billing-record purposes. **Note:** The 7-year figure tracks PHIPA (Ontario) guidance; Alberta HIA does not specify a fixed retention period and instead requires custodians to retain information "as long as needed for the purpose" plus any minimum required by other Alberta law (e.g. records retention schedules under the *Alberta Public Agencies Land Act* or professional college rules). For the Pilot, the shorter of (a) end of Pilot + 60 days or (b) 7 years applies.

---

## 8. Pilot-End Data Handling

1. Within seven (7) days before Pilot Term end, Ashbi sends the Clinic a written **Data Export Notice** with instructions for downloading a full export of Customer Data (CSV / JSON / 837P as applicable).
2. The Clinic has fifteen (15) days from the Data Export Notice to download the export.
3. Thirty (30) days after Pilot Term end, all Customer Data is **permanently deleted** from production systems, backups, and logs, and Ashbi provides a written deletion certificate within ten (10) business days of deletion.
4. Aggregated, de-identified metrics retained under §6.3 survive deletion of Customer Data only to the extent the Clinic has opted in.

---

## 9. Patient Access Requests

If Ashbi receives an access, correction, or complaint request from a patient whose information may be in Customer Data, Ashbi will:

- Acknowledge receipt within two (2) business days.
- **Forward the request to the Clinic within five (5) business days** of receipt.
- Cooperate with the Clinic's response but will not respond directly to the patient (the Clinic is the HIA custodian).

---

## 10. Breach Notification

Ashbi will notify the Clinic's designated security contact **within 72 hours** of becoming aware of any actual or reasonably suspected breach of safeguards involving Customer Data ("Breach"). Notification will include:

- Date(s) and nature of the Breach.
- Categories and approximate volume of data affected.
- Steps taken to contain and remediate.
- Ashbi's designated contact for follow-up.

The Clinic, as HIA custodian, is responsible for any further notifications to the OIPC and affected individuals. Ashbi will provide reasonable cooperation.

---

## 11. Termination

Either party may terminate this Agreement and the Pilot **with seven (7) days' written notice** for any reason. Upon termination, §8 (Pilot-End Data Handling) applies. Termination does not relieve either party of obligations that by their nature survive, including §§5, 6, 9, 10, 12, and 13.

---

## 12. Confidentiality

Each party will protect the other's Confidential Information with at least the same standard of care it uses for its own confidential information of similar importance, and in any event no less than reasonable care. Confidential Information includes Customer Data, audit findings, security architecture, and pricing.

---

## 13. Limitation of Liability & Indemnity

- **Liability cap:** Each party's aggregate liability under this Agreement is limited to the fees paid by the Clinic to Ashbi in the twelve (12) months preceding the claim (or, during the Pilot, the **CAD $1,500** Pilot Fee paid).
- **No consequential damages:** Neither party is liable for indirect, incidental, or consequential damages.
- **Indemnity:** Ashbi will indemnify the Clinic against third-party claims arising from Ashbi's breach of §§5, 6, or 10.
- **Mutual cooperation:** Both parties will cooperate on OIPC inquiries, audits, and patient access requests.

These are placeholder terms only and **must be reviewed by counsel** before signing.

---

## 14. Subprocessors, BAA & Contact

| Item | Value |
|---|---|
| Cloud region | `ca-central-1` (or equivalent Canadian region) — see BAA for current assignment |
| Subprocessors (current) | Cloud infrastructure provider, encrypted Postgres hosting, transactional email, error-tracking (all Canadian-region where available) |
| Business Associate / Processing Addendum | Referenced as "BAA"; the active version is filed under `legal/baa/` and forms part of this Agreement |
| Ashbi security contact | security@ashbi.example |
| Clinic primary contact | `[Name, Title, Email, Phone]` |
| Clinic privacy/officer | `[Name, Title, Email, Phone]` |
| Clinic breach-notification contact | `[Name, Title, Email, Phone]` |

---

## 15. Pricing

- **Pilot (60 days):** CAD $1,500, one time, invoiced at the start of the Pilot. Credited against the first month of a Subscription if the Customer elects to continue. No per-claim charges, no setup fee, and no automatic conversion to paid.
- **Post-pilot subscription (if elected):** Per Ashbi's published tiers at the Effective Date:
  - **Starter:** CAD $499 / month
  - **Growth:** CAD $1,499 / month
  - **Scale:** CAD $2,999 / month
- Prices are exclusive of GST. Invoiced monthly in advance; net-30 terms.

---

## 16. General

- **Entire agreement:** This Agreement, the BAA referenced in §14, and Schedule A (Opt-In for Aggregated Metrics) together constitute the entire agreement between the parties on its subject matter.
- **Amendments:** Only in writing signed by both parties.
- **Severability:** If any provision is held unenforceable, the remainder stays in effect.
- **Order of precedence:** In conflict, the order is: (1) HIA, (2) PIPEDA, (3) this Agreement, (4) the BAA, (5) Schedule A.

---

## 17. Signatures

**ASHBI DESIGN**

- Signature: ______________________________
- Name: **[Full Name]**
- Title: **[Title]**
- Date: **[YYYY-MM-DD]**

**[CLINIC NAME]**

- Signature: ______________________________
- Name: **[Full Name]**
- Title: **[Title — e.g. Clinic Manager, Privacy Officer]**
- Date: **[YYYY-MM-DD]**

---

## Schedule A — Opt-In for Aggregated, De-Identified Metrics

By signing below, the Clinic opts in to Ashbi retaining aggregated, de-identified metrics derived from Customer Data beyond the Pilot Term, under the safeguards in §6.3.

- [ ] **YES — opt in** to aggregated-metrics retention beyond pilot.
- [ ] **NO — do not opt in** (default; aggregated data deleted with Customer Data).

**Clinic representative:**

- Signature: ______________________________
- Name: **[Full Name]**
- Title: **[Title]**
- Date: **[YYYY-MM-DD]**

---

*End of draft template. Review by Canadian counsel familiar with Alberta HIA and PIPEDA is required before any use.*