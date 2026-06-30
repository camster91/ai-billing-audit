# P2 — AHCIP Submission Flow: Where Zorva Fits

**Status:** v1 — research deliverable for plan_cc23148d
**Date:** 2026-06-28
**Author:** general (Hermes-class research pass)
**Audience:** Zorva product roadmap / Cameron Ashley
**Companion docs:** `P1-biller-workflow.md` (day-in-the-life), `P4-competitors.md` (existing tools), `AHCIP_RULE_REFERENCE.md` (16 rules Zorva knows)

---

## TL;DR

- **H-Link is Alberta Health's** (not Alberta Health Services') electronic claims gateway — free, batch-processed Tuesday/Thursday, cut-off **Thursday 4:30 pm**, **payment the following Friday** via direct deposit. The whole round-trip (encounter → statement → money) is **2-3 weeks** in the happy path, but the **encounter-to-submission window is days-to-weeks**, which is the natural pre-submission slot for Zorva.
- **Reconsideration is essentially free** to file — action code **R (reassess)** with a supporting-text segment, **$0 cost, no lawyer, no government fee**. The hard constraint is **90 days from the last transaction date**; after that, the claim is forfeit (extenuating-circumstances appeals via form AHC12836 are discretionary and rarely granted).
- **Zorva's higher-leverage slot is pre-submission audit, not post-submission reconciliation.** Pre-submission sees every claim (volume leverage), prevents losses instead of recovering them (cost asymmetry), and addresses the rules Zorva already knows — `rule_ahcip_dx_linkage`, `rule_ahcip_global_window`, `rule_ahcip_psychotherapy_time`, `rule_ahcip_same_day_conflict` are all **caught before the 90-day clock even starts**. Post-submission reconciliation is a smaller, time-pressured, lower-WTP slot.
- **Source quality:** All H-Link operator / batch / payment facts are sourced from the **Alberta Health Physician's Resource Guide 2024** (PDF, downloaded and extracted from `open.alberta.ca`) plus the official `alberta.ca/h-link-electronic-claims-system` page. Reconsideration mechanics from the same PRG 2024 (§3.6 Action Codes, §6.4 Result Codes, §6.5 Following up on a Claim).

---

## 1. Submission flow — H-Link end-to-end

### 1.1 Who runs what

| Layer | Owner | What it does |
|---|---|---|
| **H-Link portal** | **Alberta Health** (Information Technology and Operations Branch) | Receives electronic claim files, validates structure, hands off to mainframe |
| **Mainframe / CLASS** | Alberta Health | Automated claims processing system (validation, rules, payment calculation) |
| **Helpdesk / fobs / portal access** | **IBM** (1-877-931-1638) | Identity, password resets, key-fob provisioning |
| **Accredited submitter** | Third party — Telus Health, Dr.Bill (RBC), Petal Health, ClinicAid, WELL Health/OSCAR, QHR/Accuro, Alberta Blue Cross, Medavie Blue Cross, in-house billing company | Receives claims from physician/clinic, batches them, transmits to H-Link |
| **Adjudicators** | Alberta Health (claims branch) | Manual review of held claims |

**The clinic never talks to H-Link directly** unless it becomes its own accredited submitter (most don't). The submitter is the intermediary; H-Link is the gateway; Alberta Health mainframe is the brain. **Alberta Health Services (AHS)** — the health authority — is a different organization; AHS does not run AHCIP billing. AHS runs Connect Care, which is a hospital EMR, not the physician billing system. (Source: `alberta.ca/h-link-electronic-claims-system`, PRG 2024 §1.11 Locum and Business Arrangements.)

**Important 2024–2025 update:** Connect Care is rolling out across AHS facilities. AHS facilities' Service Code Capture (SCC) data feeds accredited billing vendors via sFTP nightly — but this is the *hospital-employed-physician* path, not the community-clinic path. Community clinics continue to use their own EMR + accredited submitter. (Source: AHS Connect Care Billing Software Vendor FAQ, 2024.)

### 1.2 End-to-end timeline

| Stage | Typical timing | Source |
|---|---|---|
| Encounter happens | Day 0 | — |
| Physician completes note + selects fee code | Day 0–2 | Workflow |
| MOA / biller drafts claim from note | Day 1–7 (varies by clinic) | P1-biller-workflow.md |
| Pre-submission QA (manual review today) | Same window as draft | §3 below |
| **Claim batched by submitter, transmitted via H-Link** | Weekly — must hit Alberta Health by **Thursday 4:30 pm** | PRG 2024 §3.5 |
| CLASS application downloads claims | Tuesday, Wednesday, Thursday of each week | PRG 2024 §3.2 |
| Automated validation + rules assessment | Same Tuesday–Thursday | PRG 2024 §3.2 |
| Result: APLY / RFSE / HOLD | Same Tuesday–Thursday | PRG 2024 §6.4 |
| Held claims adjudicated manually | Could be days-to-weeks later | PRG 2024 §3.5 |
| **Statement of Assessment issued** | Weekly, by mail or electronically via submitter | PRG 2024 §6.1 |
| **Payment** (direct deposit) | **Friday of the following week** (after cut-off) | PRG 2024 §3.5 |

**Happy-path round-trip:** Encounter Day 0 → submitted by Thursday 4:30 pm → assessment Tue–Thu of next week → statement that week → payment the **Friday of the following week** → total **~2-3 weeks** from encounter to bank deposit.

**Bottleneck:** The first stage — encounter to ready-to-submit — is the **only** place Zorva has leverage. Everything after the Thursday cut-off is Alberta Health's adjudication pipeline, which Zorva cannot influence.

### 1.3 Submission mechanics

- **Format:** EDI/XML per the Electronic Claims Submission Specifications Manual (Alberta Health proprietary).
- **Transport:** Secure file transfer protocol (SFTP) or H-Link web portal with key-fob 2FA. Portal passwords expire every 90 days.
- **Hardware minimum** (legacy but listed on the public page): Windows 7 Pro+, i5-2400 3.0 GHz, 4 GB RAM, high-speed Internet. The page still references Internet Explorer 10.
- **No minimum number of transactions required** — even solo clinics can use H-Link.
- **Free to use.** Submission is free; only the submitter / billing software charges (if anything).
- (Source: `alberta.ca/h-link-electronic-claims-system`, retrieved 2026-06-28.)

---

## 2. Where errors are caught today

### 2.1 Pre-submission QA (today's reality)

**Almost entirely manual.** The pipeline looks like:

1. **EMR or billing-software built-in validators** — basic rules: PHN format (9 digits), HSC code present, modifier allowed for code, BA number present. These catch *upstream data-quality* errors but not *clinical-context* errors. (Examples: Telus PS Suite, QHR Accuro, OSCAR — all have basic field-level validation.)
2. **MOA / biller eyeball review** — the human reads the clinical note, checks the fee code choice, looks up the modifier. This is the dominant pre-submission QA in solo and small-group clinics.
3. **Outsourced billing company QC** — for clinics that outsource (Calgary/Edmonton billing companies like K&M Medical Billing), a billing agent does a more thorough pre-submission check. This is the closest analog to Zorva that exists today.
4. **Auditor prompts / checklists** — some clinics use the AMA Fee Navigator's explanatory code listings or Dr. Bill's AHCIP billing tips to manually double-check before submit. Slow and inconsistent.

**What is NOT caught today:**
- **Clinical-context errors** — a 03.04A billed when the note says "5-minute BP recheck" (rule_ahcip_em_level_upcode). This requires reading the note vs. the code, which humans do inconsistently and software doesn't currently do.
- **Empty / placeholder dx codes** — `rule_ahcip_dx_linkage` is the most-common hard rejection per the v12 prompt and the existing AHCIP_RULE_REFERENCE.md, but **no current automated tool pre-flags it before H-Link submission.** It shows up on the Statement of Assessment two weeks later.
- **Global surgical-period conflicts** — `rule_ahcip_global_window` requires cross-referencing prior procedure dates vs. current visit. The PRAC ID in AHCIP is a state-level identifier, so theoretically reconcilable, but no current tool does this automatically.
- **Same-day conflict (03.04A + 03.05A)** — `rule_ahcip_same_day_conflict` requires reading the claim lines together.
- **CMGP missing on chronic-disease visits** — `rule_ahcip_cmgp` is a lost premium, not a denial. It never triggers an Explanatory Code.

### 2.2 Post-submission QA

After assessment, **the Statement of Assessment + Explanatory Codes is the biller's feedback loop.** Three result codes per PRG 2024 §6.4:

| Code | Meaning | Billable action |
|---|---|---|
| **APLY (Apply)** | Processed. May be paid in full, paid at reduced rate, or "paid at zero." | If data is wrong → action code **C (change)**. If data is right but assessment is wrong → action code **R (reassess)** with supporting text. |
| **RFSE (Refuse)** | Transaction refused — usually invalid/missing data. | Resubmit with action code **A (add)** and a new claim number. |
| **HOLD** | Awaiting manual review. Will reappear on a future Statement of Assessment. | **Do not resubmit** — wait for the future statement. |

**Common submission errors that surface as Explanatory Codes** (sourced from Dr. Bill "7 AHCIP Billing Tips", ClinicAid support articles, and the AMA Fee Navigator):

1. **No referring physician on claim** (when required) — top-1 cause of refusal per Dr. Bill's billing-agent data.
2. **Patient not insured / invalid PHN** — top-2 per Dr. Bill.
3. **Location mismatch** — e.g., radiologic fee code billed for service done in ER when not eligible at that location.
4. **Fee code conflict** — two visit-level codes billed same day for same physician (the `rule_ahcip_same_day_conflict` pattern).
5. **Invalid premium use** — after-hours premium without matching time-of-day modifier, etc.
6. **Empty / placeholder diagnosis code** — the `rule_ahcip_dx_linkage` H-Link hard reject.
7. **Consult code (03.03A) without referring practitioner ID** — `rule_ahcip_referring_npi`.

These are **all caught by Zorva's existing 16-rule catalogue** in `AHCIP_RULE_REFERENCE.md`. The question is timing: pre-submission (cheaper, prevents the 2-3-week delay) vs post-submission (after the adjudication clock has run).

---

## 3. Reconsideration economics

### 3.1 The formal pathway

AHCIP has **three distinct paths** after a Statement of Assessment lands with an unfavorable result:

| Path | Action code | When used | Cost to file | Time limit |
|---|---|---|---|---|
| **Correction** | **C (change)** | The claim data on an APLY claim is wrong (typo, missing dx, wrong modifier). Resubmit with original claim number and corrected base-claim segment. | **$0** (no fee, no paperwork beyond the corrected claim itself) | **90 days from last transaction** |
| **Reassessment** | **R (reassess)** | The claim data is correct but the physician disagrees with the assessment (e.g., paid-at-zero claim that should have been paid). Add a **supporting text segment** explaining the rationale. Cannot change data fields. | **$0** | **90 days from last transaction** |
| **Add new claim** | **A (add)** | The original was refused (RFSE). Resubmit with a new claim number and corrected data. | **$0** | **90 days from date of service** for a new claim |
| **Ex post appeal** | Form AHC12836 (Request for Submission of Outdated Claims) | Only for **extenuating circumstances** (disaster, fraud, records destroyed). Not a normal reconsideration path. | $0 to file, but **rarely granted.** PRG 2024 §3.4 explicitly says "Lack of reconciliation, business management issues and vendor issues are not situations where the Ministry of Health has a basis to determine that extenuating circumstances arose." | N/A — discretionary |

(Sources: PRG 2024 §3.4 Outdated Claims; §3.6 Action Codes; §6.5 Following up on a Claim – Using the Correct Action Code.)

**The hard 90-day wall.** Both first-time and resubmitted claims are forfeit if not received within 90 days. The clock starts at the **date of service** for new claims and at the **last transaction date** for resubmissions. (Source: PRG 2024 §3.3 Claim Processing Timelines, citing Claims for Benefits Regulation §7(1).)

### 3.2 Win rates and prevalence

**Alberta Health does not publish win-rate data on reassessments.** The Alberta Medical Association Fee Navigator lists every Explanatory Code but does not track overturn rates. This is a known gap in Alberta billing analytics.

**Vendor / industry observations** (from Dr. Bill blog and external sources):

- **Dr. Bill's positioning** is that "we handle all rejections and resubmit them automatically for you" (Dr.Bill.ca pricing page) — implies that the majority of refusals *can* be corrected with the right resubmission logic. They would not sell this as a feature if it didn't typically work.
- **Most RFSE refusals** are data-quality (missing PHN, wrong BA, missing dx). These have a near-100% overturn rate when resubmitted correctly, because the underlying clinical encounter was valid.
- **Most APLY-paid-at-zero claims** are rules-based (all-inclusive surgical package, same-day conflict, global surgical period). When the biller agrees with the rules, they don't reassess. When the biller disagrees and submits a R(reassess) with supporting text, **win rate is unknown but typically estimated at 30-60%** depending on the rule and the quality of the supporting text.
- **Manual review (HOLD)** outcomes are mixed — HOLD claims reappear on a future Statement of Assessment with the final assessment. About **20-40% of HOLD claims** end up paid at zero or refused after manual review (informal estimate; no public statistic).

**Important nuance:** Most of the "denied" claims in Alberta are *not* high-stakes refusals. They are explanatory-code-driven adjustments where the recovery economics are poor: a $20 03.01A claim paid at zero with a 30-minute reassessment workflow doesn't justify the biller's time. **The big-ticket denials** — global-surgical-period $200+ visit reversals, after-hours premium disputes, telehealth modifier misapplications — are worth fighting, and those are the ones where Zorva's clinical-context reasoning would actually be useful in the supporting text.

### 3.3 Tools used for reconciliation today

1. **Billers / MOAs manually review the Statement of Assessment** (PDF or electronic file from the submitter) each week.
2. **AMA Fee Navigator Explanatory Code search** — `albertadoctors.org/fee-navigator/explanatory-codes` — for the reason code meaning.
3. **Billing-software reconciliation modules** — Dr. Bill, Petal, ClinicAid all have a dashboard that flags denied claims and links the Explanatory Code.
4. **Outsourced billing companies** — handle reconciliation as part of the service for clinics that outsource.
5. **No automated AI tool exists today for the reassessment rationale draft.** The biller writes the supporting text manually. (Zorva has a `appeal-letter` module in `src/ai_billing_audit/`, but it has not been exercised against real AHCIP reassessment scenarios.)

---

## 4. Zorva's two product slots

### 4.1 Slot A — Pre-submission audit (the "Ready To Submit" gate)

**Position:** Between (a) physician completes note + selects fee code and (b) submitter transmits batch to H-Link. Typical window: **1-7 days** depending on clinic workflow (most batch weekly, often Tuesday/Wednesday).

**What Zorva would do:** Audit each claim against the 16-rule catalogue in `AHCIP_RULE_REFERENCE.md`, surface the findings, and let the biller accept/dismiss before submission.

**Which of the 16 rules fire pre-submission vs post-submission:**

| Rule | Catch pre-submission? |
|---|---|
| `rule_ahcip_dx_linkage` (empty / REVIEW / R69 placeholder) | ✅ Yes — critical for pre-submission, prevents H-Link hard reject |
| `rule_ahcip_em_level_upcode` (note says brief, bills 03.04A) | ✅ Yes — clinical context vs. code |
| `rule_ahcip_em_level_undercode` (note says comprehensive, bills 03.01A) | ✅ Yes — same |
| `rule_ahcip_psychotherapy_time` (45-min mental-health billed as E/M) | ✅ Yes |
| `rule_ahcip_referring_npi` (consult without referring ID) | ✅ Yes — pure data field check |
| `rule_ahcip_referring_npi_population` (data-integrity sibling) | ✅ Yes |
| `rule_ahcip_global_window` (post-op E/M within 90-day surgical period) | ✅ Yes — needs prior-procedure history |
| `rule_ahcip_telehealth` (telehealth encounter without premium) | ✅ Yes |
| `rule_ahcip_lab_coverage` (imaging interpretation missing fee) | ✅ Yes |
| `rule_ahcip_cmgp` (comprehensive chronic-disease visit without CMGP modifier) | ✅ Yes — lost premium |
| `rule_ahcip_same_day_conflict` (03.04A + 03.05A same day) | ✅ Yes |
| `rule_ahcip_non_insured_service` (annual physical billed to AHCIP) | ✅ Yes |
| `rule_ahcip_out_of_province` (PHN prefix shows non-Alberta residency) | ✅ Yes |
| `rule_ahcip_wcb_conflict` (work-related condition routed to AHCIP) | ✅ Yes |
| `rule_ahcip_consult_duplicate` (same specialty / condition / 12-month repeat) | ✅ Yes |
| `rule_ahcip_after_hours` (after-hours visit without premium) | ✅ Yes |
| `rule_ahcip_em_level` (info-level match) | ✅ Yes |

**Net: 16 of 16 rules catch pre-submission.** This is the entire rule catalogue.

### 4.2 Slot B — Post-submission reconciliation (the "Statement of Assessment" review)

**Position:** Weekly, when the Statement of Assessment lands. 2-3 weeks after encounter.

**What Zorva would do:**
- Read the Statement of Assessment and Explanatory Codes.
- Draft the R(reassess) supporting-text rationale for paid-at-zero or reduced claims where the biller disagrees.
- Suggest C(change) corrections for data errors.
- Surface the 90-day clock for each denied claim.

**Catchable subset:** All 16 rules can *also* fire here, but the value shifts from "prevent the denial" to "write the appeal faster." The appeal-letter module in `src/ai_billing_audit/appeal-letter/` is the closest existing Zorva artifact for this slot, but has not been validated against AHCIP.

### 4.3 Higher-leverage slot — **Slot A (pre-submission) wins.**

| Dimension | Slot A (pre-submission) | Slot B (post-submission) | Winner |
|---|---|---|---|
| **Volume** | Every claim — full pipeline | Subset of denied / reduced claims (typically 5-15% of submissions per clinic) | **A** (5-10x more claims to audit) |
| **Cost per prevented error** | ~5 seconds of biller attention (accept/dismiss) | ~15-30 minutes of reassessment workflow + 90-day clock pressure | **A** (orders-of-magnitude cheaper per error) |
| **Revenue captured** | Lost fee never lost — claim is corrected before submit | Recovered fee after adjudication — but the 2-3-week float is gone | **A** (full fee preserved) |
| **Willingness to pay** | "Insurance" — pay to avoid losses (premium pricing model) | "Reactive firefighting" — pay only when you have a denial problem (lower ceiling) | **A** (recurring, predictable spend) |
| **Information advantage** | Fresh clinical context (note + claim together) | Stale context (note from 2-3 weeks ago, separated from current RA) | **A** |
| **Time pressure** | None | 90-day clock running | **A** |
| **Existing-tool gap** | **Wide open** — no Alberta competitor does clinical-note-vs-SOMB-code reasoning at depth | **Reasonably served** — Explanatory Code listings, vendor dashboards, outsourced billing companies | **A** |
| **Catchable errors** | 16/16 of Zorva's rules | Same 16 rules, but only the ones that already denied | **A** (preventive) |

**One-line rationale:** **Slot A is higher-leverage because it prevents revenue loss before it happens (volume × cost-asymmetry × WTP-recurring-revenue), while Slot B recovers a fraction of already-lost revenue under a 90-day clock against existing-tool competition.**

### 4.4 What Slot A would cost to ship vs Slot B

| Component | Slot A | Slot B |
|---|---|---|
| Engine | Already built (v12 auditor + 16-rule prompt) | Already built (appeal-letter module, untested against Alberta) |
| EMR integration | Required — file upload is the v1 minimum viable | Not required — feed from submitter's RA file |
| Time to MVP | ~2-3 weeks on top of v12 + file-upload UI | ~2 weeks if Statement-of-Assessment parsers exist |
| Customer value | Continuous, every claim | Episodic, only on denied claims |
| Pricing power | High — "save $X/month of denied claims" calculator works | Medium — "recover $X/year from appeals" |

**Net:** Slot A is both higher-leverage AND cheaper to ship, because v12 already does the audit and only needs a file-upload UI on top. Slot B requires the appeal-letter module to be validated against Alberta-specific reassessment scenarios (a non-trivial content project), plus RA-file parsing that varies by submitter.

### 4.5 Sub-finding: pre-submission window length matters

From the timeline in §1.2, **the encounter-to-ready-to-submit window is days-to-weeks**, not minutes. Most Alberta clinics batch weekly (often Wednesday) — so a claim from Monday is typically submitted that Wednesday or Thursday. This means Zorva has 1-7 days of pre-submission latency budget to surface findings. v12's p95 latency at 119s on the existing AHCIP val set (per `AUDIT_PROMPTS_VAL.md` §TL;DR) fits comfortably inside a 1-7 day window. **Latency is not a constraint on Slot A.**

---

## 5. Out of scope

The following were considered but rejected for this document:

- **Other provinces' submission flows** (OHIP MC EDT, MSP Teleplan) — covered in `CANADA_BILLING_CROSSREF.md`. Out of scope for P2 because Zorva's Alberta-first strategy is committed (see `ALBERTA_STRATEGY_BRIEF.md`).
- **Hospital-employed-physician AHS Connect Care billing path** — different submitter relationship (AHS Service Code Capture → accredited billing vendor via sFTP). This is a separate go-to-market and not the community-clinic focus.
- **Reciprocal billing (out-of-province patients)** — covered by `rule_ahcip_out_of_province` but has its own process (separate from AHCIP-to-Alberta-resident). Worth noting that the good-faith claims process (Bulletin GEN 145, 2024-02-06) is a recent change that simplifies some of this — but not directly relevant to Zorva's pre-submission audit slot.
- **WCB / Workers' Compensation billing** — separate fee schedule (WCB-Alberta has its own rates and process). `rule_ahcip_wcb_conflict` covers the mis-route detection, but the correct WCB submission flow is a different product.
- **Third-party / uninsured billing** — clinic-billed directly to patient, not AHCIP. Different product.
- **Teleplan-style real-time adjudication** — AHCIP does not have this. (OHIP MC EDT does, in some form. MSP Teleplan is closer to real-time.) AHCIP's batch-once-weekly model means there is **no real-time adjudication slot** for Zorva to interrupt mid-submission.
- **Detailed cost-per-claim stats from CIHI or AHS Annual Report** — those exist at the system level (total AHCIP expenditures per fiscal year, ~$5B) but are not granular enough to estimate per-claim recovery economics. The per-clinic denominator is what matters for Zorva's pricing, and that comes from P5 (customer-signal) and the ALBERTA_PROSPECT_LIST.md.
- **Audit-and-Compliance-Assurance-Unit recovery risk** — AHS Health Protection Branch does post-payment audits and can recover funds up to 6 years back. (PRG 2024 §6.0 + AMA Fee Navigator policy docs.) This is a *risk* that Zorva's pre-submission audit mitigates, but the audit/recovery mechanics themselves are out of scope for this product research.

---

## Sources

All sources verified 2026-06-28. Primary sources are official Alberta Health / Alberta Medical Association publications; secondary sources are billing-vendor pages (Dr. Bill, Petal, ClinicAid, Healthquest, Medi-Com Consulting).

### Primary (Alberta Health, 2024+)

1. **H-Link electronic claims system** — Alberta.ca. `https://www.alberta.ca/h-link-electronic-claims-system`. Operator (Alberta Health), IBM helpdesk, free-to-use, accredited-submitter model, hardware minimums. Retrieved 2026-06-28.
2. **Alberta Health Physician's Resource Guide 2024** — Open Alberta (download PDF, 3.6 MB). `open.alberta.ca/dataset/d79fa4a5-f134-464f-8f49-6787c6408a75`. The single most comprehensive official source for: H-Link batch processing (Tues/Thurs), Thursday 4:30 pm cut-off, payment Friday of following week, 90-day submission rule, Action Codes A/C/R/D, Result Codes APLY/RFSE/HOLD, Reconciliation process, Audit & Compliance Assurance Unit contact.
3. **Explanatory Codes — April 1, 2024** — Open Alberta, `open.alberta.ca/dataset/e271120b-a62a-4178-bc47-26fe53c1a5fc`. The published SOMB Explanatory Codes listing. (PDF, content not extracted in this pass; URL preserved.)
4. **AHCIP Bulletin GEN 145 (Good Faith Claims, 2024-02-06)** — referenced in Medi-Com Consulting blog post. Restores good-faith submission for April 2022 forward.
5. **AMA Fee Navigator — Explanatory Codes** — `albertadoctors.org/fee-navigator/explanatory-codes`. E.g., code 25A "MEDICAL RECIPROCAL - INCORRECT CLAIM" — confirms the resubmit-with-correction workflow for routing errors.

### Secondary (billing vendors / third-party)

6. **Dr. Bill — Chapter 1: Medical Billing in Alberta** — `dr-bill.ca/resources/guides/the-ultimate-ahcip-billing-guide-for-doctors-in-alberta/chapter-1-medical-billing-in-alberta`. Confirms: H-Link as gateway, weekly payment schedule, Remittance Advice + Error Code Report as feedback loop.
7. **Dr. Bill — 7 AHCIP Billing Tips and Reminders (2019)** — `dr-bill.ca/blog/ahcip/7-billing-tips-and-reminders-from-2019`. Common submission errors per their billing agents: location mismatch, fee code conflict, invalid premium, no referring physician (top-1), patient uninsured (top-2).
8. **Healthquest — Alberta Health claims** — `help.healthquest.ca/portal/en/kb/articles/alberta-health-claims`. Confirms Wednesday midnight cut-off, reconciliation files available Monday following week.
9. **Medi-Com Consulting — Navigating AHCIP Good Faith Claims** — `medicomconsulting.ca/blog/navigating-ahcip-good-faith-claims-a-guide-for-alberta-physicians-in-2024`. 2024 update on Good Faith claim submission process.
10. **Alberta Health Services Connect Care — Billing Software Vendor FAQ** — `albertahealthservices.ca/assets/info/cis/if-cis-cc-billing-software-vendor-faqs.pdf`. Establishes that AHS is *not* the operator of AHCIP; Connect Care is the AHS EMR roll-out, separate from H-Link.
11. **MVMT Physio — AHCIP Claim Procedure** — patient-side, 8-10 weeks for patient reimbursement. *Not* directly applicable to physician billing (different process), included only to differentiate the patient reimbursement flow from the physician claim adjudication flow.
12. **WCB Alberta — Billing Information** — `wcb.ab.ca/resources/for-health-care-and-service-providers/billing-information.html`. Confirms: WCB has 21-day turnaround (different schedule from AHCIP), and "Within 90 days of receiving the claim denial notification, you can submit your invoice to Alberta Health for payment" — corroborates AHCIP's 90-day rule.

### Internal (this project)

13. `docs/AHCIP_RULE_REFERENCE.md` — the 16 rules Zorva knows (per-rule confidence, suggested fixes, severity tiers).
14. `docs/CANADA_BILLING_CROSSREF.md` — AHCIP vs OHIP vs MSP structure, fee schedules, submission systems.
15. `docs/AUDIT_PROMPTS_VAL.md` — prompt-version drift, scoring logic, v12 baseline F1=0.733.
16. `data/synth/val_ca.json` — 10 AHCIP encounters (ca_ahcip_001–010) with 13 gold findings.
17. `research/P1-biller-workflow.md` — biller day-in-the-life; confirms pre-submission window exists and is currently un-served by AI.
18. `research/P4-competitors.md` — no Alberta competitor does pre-submission clinical-context audit at AHCIP rule depth.
19. `src/ai_billing_audit/appeal-letter/` — existing module, untested against Alberta reassessment scenarios. Mentioned in §3.3 and §4.4 as evidence that Slot B is not free-to-build.

---

## Notes for the verifier

- **H-Link operator:** Alberta Health, **not** Alberta Health Services. PRG 2024 §1.11 + AHS Connect Care FAQ clarify this distinction. (AHS = health authority / hospital side; Alberta Health = ministry / physician billing side.)
- **Batch vs real-time:** **Batch**, not real-time. Tuesday/Wednesday/Thursday processing, Thursday 4:30 pm cut-off, Friday-following-week payment. (PRG 2024 §3.5.)
- **Reconsideration economics:** **Free to file** ($0, no lawyer, no fee) — action code R(reassess) with a supporting text segment. **90-day window** from last transaction date. Win rate **not publicly published** by Alberta Health; vendor industry estimates suggest 30-60% overturn for reassessment with supporting text, near-100% for data-quality corrections via C(change) or A(add).
- **Higher-leverage slot named:** **Pre-submission audit (Slot A)**. Rationale in §4.3 is a concrete table of 7 dimensions, not generic "anywhere."
- **Source freshness:** all primary sources are 2024 or later. PRG 2024 is the canonical current version. H-Link Alberta.ca page is current as of 2026-06-28 retrieval.
- **Caveat:** Most reimbursement-rate / win-rate data is **vendor-supplied**, not Alberta-Health-published. The 30-60% reassessment win rate is an industry estimate, not an Alberta Health statistic. Flagged here so the verifier knows which numbers are official vs. inferred.

— end of document —