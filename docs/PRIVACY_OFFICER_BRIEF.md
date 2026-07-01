# Zorva — Privacy Officer Brief

**For:** Privacy officers and IT leads at Alberta clinics evaluating Zorva for a 60-day pilot.
**Date:** 2026-06-30
**Author:** Ashbi Design (Cameron Ashley) — Zorva is a product of Ashbi Design
**Status:** Pre-pilot; this brief is the first read for any privacy officer before the deep-dive.

This brief is one page of plain English + one page of evidence links. It is not legal advice. A privacy officer's review is still required before any clinic signs a pilot agreement.

---

## 1. What is Zorva?

Zorva is a pre-submit auditor for Alberta medical claims. It reads every claim + clinical note your billing team would normally submit to AHCIP, and flags what would otherwise come back denied, underpaid, or recouped. Your biller reviews the findings, accepts the good ones, dismisses the false alarms, then submits the corrected claim to AHCIP as normal. Zorva does not submit claims and does not store patient data after the pilot.

Zorva is built and operated by Ashbi Design (Cameron Ashley), a Toronto-based independent developer. There is no third party operating the service. The database, the audit pipeline, and the operator outbox all run on infrastructure contracted directly by Ashbi.

## 2. The data flow (plain English)

1. **Upload.** Your billing system exports a file (837P standard or CSV). The file goes to a Zorva tenant (a single-tenant Postgres database in the region you choose at sign-up).
2. **Pseudonymize.** The encounter ID is hashed (salted SHA-256) before it is written to the audit log. The audit log never carries raw patient identifiers. Patient names, PHNs, MRNs, and DOBs live only in the encrypted encounter table, separate from the audit log.
3. **Audit.** An LLM reads the encounter, the billed codes, and a set of AHCIP / SOMB rules, and emits a list of findings. The LLM call is over TLS; the prompt carries only the pseudonymized encounter, the scrubbed clinical note excerpt, and the rule list.
4. **Review.** Your biller reviews each finding in the dashboard (accept / dismiss / flag / re-run). Every action is appended to a hash-chained audit log.
5. **Delete.** At the end of the pilot, you get a full export of every claim, every finding, and every log line. Within 30 days the tenant is purged, the backups are purged, and a deletion certificate is sent.

## 3. The four frameworks + current status

| Framework | Jurisdiction | Status today |
|---|---|---|
| **HIA** (Health Information Act) | Alberta | **Active.** Affiliate / Information Manager Agreement template (IMA) ready for lawyer review. The IMA is a draft in `docs/BAA_TEMPLATE_HIA.md`; lawyer review is the next step before any Alberta clinic signs. |
| **PIPEDA** (Personal Information Protection and Electronic Documents Act) | Federal Canada | **Active as floor.** Applied to any non-health personal data we handle. |
| **HIPAA** (Health Insurance Portability and Accountability Act) | United States | **Template available on request.** No US customers in production today. The BAA template exists in `docs/BAA_TEMPLATE_HIPAA.md` for any US pilot. |
| **NOM-024** (Norma Oficial Mexicana) | Mexico | **Roadmap 2027.** No Mexican customers or production work today. |

If your clinic is in Alberta, the IMA is what you sign. The IMA is the contract artefact that lets Zorva process individually identifying health information on the clinic's behalf (HIA s. 64).

## 4. The seven controls (one line each)

| Control | What it does |
|---|---|
| **Data residency** | Region is locked at sign-up. Canadian customers in a Canadian-region facility. No cross-region replication. |
| **Encryption in transit** | TLS 1.3 on every public edge. Service-to-service calls inside the VPC use mTLS. |
| **Encryption at rest** | AES-256 on every volume, snapshot, and backup. |
| **Hash-chain audit trail** | Every privileged action is appended to an append-only log with a SHA-256 hash chain. Tampering breaks the chain. |
| **Role-scoped access** | Per-tenant isolation. Roles: admin / biller / viewer. Two-person approval on destructive actions. |
| **PII handling** | The encounter ID is salted SHA-256 before any audit row. Raw patient identifiers (PHN, MRN, name, DOB) live only in the encrypted encounter table and are purged within 30 days of pilot termination. |
| **Sub-processor list** | Published on `/security` and named in the IMA. The current sub-processor list is the cloud hosting provider + the LLM inference provider. |

## 5. The five questions to ask the operator

These are the questions a privacy officer should be able to answer "yes" to before signing. If any answer is "let me check" or "I don't know", that is the IMA review conversation.

1. **Where exactly does the data live?** A region is pinned at sign-up. The hosting provider, facility, and any third-party attestations they hold are named in the IMA. *Ask: can you show me the IMA with the facility and provider named?*

2. **Who can see raw patient data?** Only the Zorva LLM during a single audit call (pseudonymized encounter + scrubbed clinical note excerpt). No human at Ashbi Design reads patient data unless you explicitly ask us to (e.g. via a support ticket). All human access is logged.

3. **What happens if there's a breach?** The IMA obligates Ashbi to notify the clinic "without unreasonable delay" on confirmed breach. The IMA also names the insurance carrier and the policy limits ($2M professional + $2M cyber). *Ask: can you name the breach-notification window you commit to?*

4. **What happens at the end of the pilot?** Within 30 days, full data export (JSON + CSV) is sent to the clinic. The tenant database, the backups, and the operator outbox are purged. A one-page deletion certificate is sent. *Ask: can you show me the deletion certificate template?*

5. **Can we audit your security?** The IMA gives the clinic the right to audit Zorva's records once per 12-month period with 30 days' notice. The audit_trail chain is verifiable end-to-end with the `verify_chain()` function. *Ask: how do we run a chain verification ourselves?*

---

## 6. Evidence links (read in this order)

If the answers above are not enough, the following artifacts back every claim in this brief:

1. **`/security`** — the public controls matrix (what is wired in code today, region by region, with file:line evidence for each control).
2. **`/technical`** — for the privacy officer who wants to see the prompt pipeline, the F1 measurement, the chain shape, and exactly which fields cross the network boundary.
3. **`docs/BAA_TEMPLATE_HIA.md`** — the draft IMA. This is what the clinic's lawyer reviews and negotiates.
4. **`docs/HIA_LAWYER_HANDOFF.md`** — a 4-page cover note for the IMA review engagement (what is in the package, the 8 items where Ashbi made a unilateral drafting call, the 6 items where counsel should verify).
5. **`docs/AUDIT_SECURITY.md`** — an internal security audit from 2026-06-23. Includes the 4 severe issues found and the mitigations applied since (most recently: FastAPI patient_hash now uses the same salted SHA-256 as the portal, deployed 2026-06-30).

If the privacy officer's review surfaces something this brief doesn't answer, email `security@ashbi.ca` — the response is within one business day.

---

**For the auditor at the clinic:** The five questions in section 5 are the IMA review checklist. The IMA template is the contract artefact. Nothing in this brief is a substitute for lawyer-reviewed IMA before any data is uploaded.
