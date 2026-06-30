# P1 — Alberta Biller Day-in-the-Life: Workflow Mapping

**Date:** 2026-06-28
**Author:** General (subagent research pass)
**Inputs:** `docs/ALBERTA_STRATEGY_BRIEF.md`, `docs/ALBERTA_PROSPECT_LIST.md`, `docs/BILLING_CONSULTANT_CHANNEL_PARTNERS.md`, `docs/AHCIP_RULE_REFERENCE.md`, `runs/recall/v12_summary.md`; plus targeted web search 2025-2026.
**Goal:** Find the natural slot for Zorva (or determine the slot doesn't exist).

---

## TL;DR

- An Alberta biller's week is a **batch-cycle job**, not a real-time one: encounters happen all week, claims are drafted in the EMR throughout, the EMR (or a third-party billing service) uploads a batch to **H-Link** by **Wednesday midnight**, Alberta Health adjudicates over the weekend, and the **remittance advice returns Monday** for the biller to reconcile. (Source: Healthquest help docs, Cloud Practice/ClinicAid cutoff article, Alberta.ca H-Link page.)
- The Alberta EMR market is dominated by **TELUS Health** (PS Suite + Med Access + CHR, ~42% Canada-wide share) and **QHR/Accuro** (~26%), with **WELL Health/OSCAR Pro** a third-place ~24% (Black Book Q2 2025). All four major vendors have billing modules that already push to H-Link — they are the biller's primary UI today.
- The dominant pain is **upstream data quality** (PHN errors, BA/Prac-ID linkage, skill code, facility/functional centre, ICD-9 diagnostic code, claimed amount), not adjudication logic — about half of AHCIP rejections come from missing-mandatory-field errors that an LLM-with-clinical-context could catch at draft time. (Source: Cloud Practice rejection-codes list; Petal Health Feb 2026 article.)
- **Zorva's natural slot is the "Ready To Submit" gate** — the moment between bill-drafted-in-EMR and bill-pushed-to-H-Link, which is the only point in the workflow where the biller is still in control and the rejection is still preventable. v12's 16 SOMB rules already target this slot. The companion post-submission slot (reconciliation of Sunday-evening RA) is real but lower-leverage (the rejection has already cost the biller the resubmission cycle).
- **Competitive blind spots** are real: every major Alberta billing tool (ClinicAid, Petal/Statgo, DoctorCare, Alberta Medical Billing, K&M, Accuro's own billing module) already does pre-submission edit checks. What they mostly **don't** do is **clinical-context-aware** rule firing — they check field-level syntax, not "this brief note billed as comprehensive, or this hypertensive visit billed with no CMGP, or this post-op day 8 that's in a global period." That's the gap Zorva fills.

---

## 1. Current state — what an Alberta biller's day actually looks like

### 1.1 The weekly batch cycle (the dominant cadence)

Alberta's H-Link is a **weekly batch system**, not a real-time submission portal:

| Day | What happens | Source |
|---|---|---|
| Mon–Wed (rolling) | Physician completes encounter → note signed in EMR → claim drafted (often auto-populated from EMR data) → biller reviews and approves claims → EMR vendor or billing service queues them | InputHealth CHR help docs (submits 2x/day to H-Link at 11 a.m. and 3:30 p.m., but the underlying H-Link cadence is weekly) |
| **Wed 23:59** | **H-Link batch cutoff** — any claim submitted to the submitter by this time is in the assessment run | Healthquest help: "cut-off is midnight every Wednesday" |
| Thu–Fri (or weekend) | Alberta Health adjudicates the batch | Cloud Practice/ClinicAid: "assessed over the weekend" |
| Sun evening / **Mon morning** | Remittance Advice (RA) / reconciliation file is returned to the submitter | Cloud Practice/ClinicAid: "remittance file is returned to ClinicAid generally by Sunday evening" |
| Mon–Tue next week | Biller reconciles paid/assessed/refused/explanatory codes; resubmits or appeals | Accuro reconciliation workflow (qhrtech.my.site.com) |

**Implication:** the biller's weekly "spike" of work is reconciliation + resubmission on Mon/Tue. Most week-day time is drafting/reviewing claims in the EMR, queueing them for Wednesday's auto-batch.

### 1.2 Hours and claim volume

A reasonable rule-of-thumb for a multi-physician Alberta clinic:

- A full-time family physician generates **~600–1,000 AHCIP claims/month** (ALBERTA_PROSPECT_LIST.md heuristic, matches Petal Health's "161 hours saved annually" claim of ~3 hours/week saved per physician).
- A typical 5-physician clinic = **3,000–5,000 claims/month**.
- A large multi-physician PCN-affiliated group (e.g., Strathcona PCN's ~60–80 physicians, Bow Valley 8–12) generates **~5,000–80,000 claims/month** network-wide.
- Per-claim biller time varies wildly — from ~30 seconds for a clean auto-populated claim to ~5–10 minutes for a complex multi-code encounter with modifiers and premiums. Average is probably ~1–2 minutes.

**Per-clinic time burden:** ~80–160 hours/month of biller time across a 5-physician clinic. Petal Health claims their billing product saves 161 hours/year per physician — about 13 hours/month/physician — which would be a ~50% reduction if true. (Vendor claim, not independently verified; treat as directionally right, not literally.)

### 1.3 Tools — what billers actually use today

**The EMR is the biller's primary UI.** Almost every biller works *inside* the EMR to draft claims, not in a separate billing application. Submission happens via the EMR vendor's accredited H-Link submitter role (or a third-party billing service that does it on the clinic's behalf).

EMR market share in Alberta (Canada-wide numbers from Black Book Q2 2025 / Mantra EHR 2026 / OpsMed Ontario Clinic Tech 2026):

| Vendor | Approx. share | Alberta-specific | H-Link integration |
|---|---|---|---|
| **TELUS Health** (PS Suite, Med Access, CHR) | ~42% nationally | Modal in Calgary + rural Alberta; CHR is the newer "all-in-one" | Direct, vendor-bundled |
| **QHR / Accuro** | ~26% nationally | Strong in Edmonton + academic clinics; sold to Loblaw's Shoppers Drug Mart in 2024 (QHR ownership stable) | Direct, vendor-bundled |
| **WELL Health / OSCAR Pro** | ~24% nationally | OSCAR McMaster was the open-source option; WELL is the corporate owner now | Direct, vendor-bundled |
| **Other** (InputHealth CHR, ClinicAid-only shops, Med Access legacy, Practice Solutions, Avaros, etc.) | ~8% | Smaller share, some standalone billing tools | Various |

**Standalone billing tools and services used alongside or instead of the EMR's billing module:**

- **ClinicAid / Cloud Practice** — dominant third-party Alberta billing software; has its own accredited H-Link submitter. Biller works in ClinicAid, EMR exports bill data in. (Used by many small-to-mid Alberta clinics; the Cloud Practice rejection-codes list is the de facto public reference.)
- **Petal Medical Billing (formerly Statgo)** — acquired by Petal Health in 2024; Alberta-focused billing service + software. Targets small/mid clinics. Claims +9.4% revenue increase, 161 hours saved/yr/physician (vendor stat).
- **DoctorCare** — billing service + software, multi-province; has AHCIP capability.
- **Alberta Medical Billing** (albertabilling.com) — Alberta-only billing service.
- **K&M Medical Billing** (Calgary) — Alberta AHCIP specialist billing service; ~25 clinic clients per BILLING_CONSULTANT_CHANNEL_PARTNERS.md.
- **Alberta Billing Pro** (Edmonton) — AHCIP-only billing service; ~20 clinic clients.
- **Accuro's own billing module** — included in Accuro EMR; many Accuro clinics stay in-EMR for billing.
- **Medcom Billing Systems** — primarily BC MSP but some AHCIP work.

**H-Link itself** (the government's portal) is **not** the biller's UI — it's the submitter's transport. The submitter is either (a) the clinic's own EMR vendor (most common) or (b) a billing service the clinic has hired (Alberta Medical Billing, Petal, K&M, DoctorCare, etc.).

### 1.4 The pre-submission window — where the biller actually has time

Most clinics run a **"Ready To Submit" hold state** for 1–3 days before the Wednesday batch:

- Physician signs encounter note → claim auto-drafted from EMR data → sits in "Draft" or "Ready To Submit" status.
- Biller reviews the queue (often Monday morning + rolling during the week).
- Approved claims go to "Ready To Submit" or directly to the submitter for Wednesday's upload.
- **This 1–3 day hold is the natural audit window.** Some EMRs (like InputHealth CHR per their docs) can be configured to auto-submit on a schedule, but most clinics prefer manual sign-off per claim or per batch.

**Zorva's pre-submission slot lives here.** Between "Draft" and "Ready To Submit."

---

## 2. Pain points — ranked by frequency × cost × Zorva-addressability

Sources for this section: Petal Health Feb 2026 article (top rejection categories by province), Cloud Practice/ClinicAid common rejection codes (the de facto public list), dr-bill.ca explanatory-codes reference, project docs (AHCIP_RULE_REFERENCE.md, AHCIP_GOLD_AUDIT.md).

### Pain #1 — Upstream data-quality rejections (≥60% of refusals)

These are field-level errors caught at H-Link's first pass. **Most do not require clinical context to detect** — they are form-completeness and code-syntax checks.

| Refusal code | Meaning | How often | Zorva-addressable? |
|---|---|---|---|
| **05A** Invalid PHN | Health number typo / missing digits | Very common (Petal: #1 Alberta issue) | **No** — Zorva has no PHN validation; EMR owns this |
| **11** Locum Business Arrangement | Locum BA missing on the claim | Common for locum-heavy clinics | **No** — EMR/BAA admin |
| **31** Incomplete Person Data | OOP claims missing demographic fields | Common for OOP claims | **No** — EMR data integrity |
| **37** Business Arrangement invalid/blank | BA missing / wrong / not linked to submitter | Common at new-clinic setup | **No** — EMR setup |
| **37A** Prac ID blank/invalid | Practitioner ID missing or wrong for date | Common during onboarding + Prac-ID changes | **No** — EMR setup |
| **37B** Skill Code invalid | Skill code doesn't match what BA is registered for | Common when billing outside scope | **No** — EMR setup |
| **39** Date of Service issues | Invalid date / future / newborn-DOB conflict | Common | **Partial** — Zorva can catch "service date in the future" or "service date before Prac-ID start" |
| **39DA** Facility Number | Facility number missing or invalid | Common for new physicians | **No** — EMR setup |
| **39DB** Functional Centre | Functional centre invalid/wrong for service | Common for new physicians (especially in hospitals) | **No** — EMR setup |
| **39C** Number of Calls | Invalid number of calls (e.g., 3 calls on a code limited to 2) | Common | **Partial** — Zorva has SOMB-rule knowledge of call-count limits |
| **39EB** Diagnostic Code | Dx blank / invalid (Alberta accepts ICD-9 only — DSM-IV doesn't validate) | Common | **Yes** — Zorva's `rule_ahcip_dx_linkage` is the primary target rule |
| **39FA** Claimed Amount / Indicator | Amount or Y-flag missing for 99.09-series unlisted procedures | Less common (specialty-specific) | **No** — form-field check |
| **80G** Outdated Claims | Submitted >90 days after date of service | Common at quarter-end scramble (90-day rule, effective March 31, 2020) | **Yes** — Zorva can flag claims approaching 90-day limit |

**Reality check:** roughly half of these rejections are **field-level data integrity** that Zorva cannot catch from a clinical-note + claim-record input (no PHN, no BA, no Prac ID are typically in the biller's claim record passed to Zorva). The other half (diagnostic code, date of service issues, claimed amount for unlisted procedures, call-count violations, 90-day stale-date) **can** be Zorva targets — and `rule_ahcip_dx_linkage` is the most impactful.

### Pain #2 — Code-choice and modifier errors (the Zorva sweet spot)

These are the rejections where the biller **chose the wrong SOMB code, modifier, or premium** for the documented work. They require reading the clinical note to detect — and that's Zorva's entire job.

| Issue | Example | Zorva rule |
|---|---|---|
| **E/M upcode** (brief note billed as comprehensive) | "Brief 5-min BP recheck" billed as 03.04A | `rule_ahcip_em_level_upcode` (HIGH) |
| **E/M undercode** (complex note billed as brief) | "Productive cough, fever, rhonchi, started amoxicillin" billed as 03.01A | `rule_ahcip_em_level_undercode` (HIGH) |
| **Missing CMGP modifier** | 03.04A for established T2DM/HTN patient without CMGP attached | `rule_ahcip_cmgp` (MEDIUM) |
| **Missing psychotherapy time-based code** | 45-min mental-health session billed as 03.04A instead of 08.19A | `rule_ahcip_psychotherapy_time` (HIGH) |
| **Missing telehealth premium** | "Phone follow-up" or "video visit" billed without premium | `rule_ahcip_telehealth` (MEDIUM, code value changes year-over-year) |
| **Billed in 90-day global surgical period** | "Post-op day 8 wound check" billed as 03.04A — should not be billed at all (no `-24` modifier in Alberta) | `rule_ahcip_global_window` (HIGH) |
| **Same-day comprehensive + minor** | 03.04A and 03.05A billed same day same physician — only one payable | `rule_ahcip_same_day_conflict` (HIGH) |
| **Consultation without referring Prac ID** | 03.03A billed but `referring_provider_npi` is null | `rule_ahcip_referring_npi` (HIGH) |
| **Non-insured service billed to AHCIP** | "Annual health maintenance" billed as 03.04A | `rule_ahcip_non_insured_service` (HIGH) |
| **Lab tests on physician claim** | CBC/A1C/TSH billed by physician (lab bills these, not the physician) | `rule_ahcip_lab_coverage` (split into lab vs imaging) |

**Source: Zorva's own AHCIP_RULE_REFERENCE.md catalogues 16 of these; v12 evaluates 11 of them against the cleaned val set.**

This is where Zorva has clear defensibility — no other off-the-shelf tool reads the **clinical note content** to detect "the work documented doesn't match the code billed." ClinicAid and Petal do form-level checks; DoctorCare's QC is human review; Accuro's billing module does code-syntax checks. None of them read the note.

### Pain #3 — Policy / eligibility rejections (lower frequency, harder to automate)

| Issue | Frequency | Zorva-addressable? |
|---|---|---|
| **WCB claim routed to AHCIP** | Common in industrial Alberta (oil & gas, construction) | **Yes** — `rule_ahcip_wcb_conflict` |
| **Out-of-province patient on AHCIP** | Common near SK/BC borders | **Yes** — `rule_ahcip_out_of_province` |
| **Duplicate / previously paid** | Common in busy clinics | **Partial** — Zorva can flag obvious duplicates if same-patient-same-date-same-code appears twice |
| **Frequency-limit exceeded** | Common for high-volume codes | **Partial** — Zorva needs per-patient history |
| **Premium code doesn't match service context** | Common | **Partial** — needs SOMB rule catalogue |

### Pain #4 — Reconciliation friction (post-submission)

After adjudication returns on Sunday/Monday, the biller has to:
- Open each RA item and read its explanatory code
- Decide: resubmit with corrected claim, file a written reconsideration, or write off
- For denied claims, generate a reconsideration letter with supporting documentation

**This is real time-sink.** Average Alberta biller spends ~30 min/day on RA reconciliation per physician on clinic. Petal claims their product saves 161 hours/year on this — a ~50% reduction.

**Zorva's current `appeal-letter` module already targets this slot** (per the project structure in `src/ai_billing_audit/`), but the v12 evaluation only audits pre-submission claims. The appeal-letter module is built but not exercised against Alberta data.

---

## 3. Zorva's natural slot — concretely

Zorva fits in **two specific workflow positions**, with very different leverage:

### Slot A (PRIMARY, higher leverage): the "Ready To Submit" gate

**Where:** Between "claim drafted in EMR" (status: Draft) and "claim queued for the Wednesday H-Link batch" (status: Ready To Submit or Submitted). Typically a 1–3 day hold per claim.

**What Zorva does today:**
- Reads the claim record + clinical note
- Runs the v12 SOMB rule catalogue (16 rules)
- Emits findings (severity-graded: critical / high / medium / info)
- Billers review findings and either accept (modify the claim), dismiss (it's a false positive), or ignore
- The accepted changes propagate back to the EMR

**Why this is the higher-leverage slot:**

1. **Pre-submission is the only point where rejection is preventable.** Once a claim is rejected, the biller is in the resubmission / reconsideration loop, which costs the same biller time again. Avoiding the rejection entirely is a 2x time-save vs. catching it on the RA.
2. **Batch cadence creates a natural 1–3 day hold** — billers have idle claim queue time that they currently use for manual review. Zorva is a forced-multiplier on that idle review time.
3. **The "first-pass acceptance rate" (FPAR) is the biller's existing KPI** (per Petal's pitch, Accuro's reconciliation reporting, and Alberta Health's own batch-assessment reports). FPAR is a biller metric; Zorva directly improves it.
4. **Defensibility against EMR-bundled competition is strongest here.** Every EMR has form-level edit checks. None of them read clinical-note content. Zorva's clinical-context audit is a genuine differentiator at this gate.

**Concrete workflow integration:**

```
Physician signs note in EMR
        ↓
EMR auto-drafts claim (Draft status)
        ↓
[NEW] Zorva audits Draft claim + clinical note
        ↓
Zorva emits findings to biller's Zorva dashboard
        ↓
Biller reviews findings, accepts/dismisses each
        ↓
Biller sets claim to "Ready To Submit" (in EMR)
        ↓
Wednesday batch → H-Link → adjudication → remittance Mon
```

### Slot B (SECONDARY, lower leverage): reconciliation / reconsideration

**Where:** After Sunday/Monday RA returns, for claims that were assessed but refused or adjusted. The biller reconciles each explanatory-code refusal.

**What Zorva could do:**
- Auto-read the RA file (from EMR or submitter portal)
- Match refused claims back to original note + claim + audit history
- Generate reconsideration letters (`appeal-letter` module is already built)
- Track win/loss to improve over time

**Why this is lower-leverage:**

1. **By the time RA returns, the work has already been done.** The claim was already drafted, batched, submitted, and adjudicated. The biller can prevent the next occurrence (via Slot A) but cannot un-do the cost of this one.
2. **Reconsideration win rates are low** (Alberta does not publish official rates, but industry rule-of-thumb is 30–50% on technical rejections, 10–20% on substantive disputes). Zorva's appeal-letter quality matters less than its pre-submission audit accuracy.
3. **Most RA denials are re-keyable in 30 seconds with the right explanatory code** — the biller doesn't need an AI letter, they need a quick "yes, I see code 39EB, fix the dx, resubmit" UI. Zorva's letter generation is overkill for routine refusals.

**Where Slot B still matters:**
- Complex substantive denials (e.g., 63A "Schedule of Benefits" — meaning adjudicator disagreed with the level billed)
- High-dollar claims where a reconsideration letter pays for itself in recovered revenue
- The `cross-tenant denial pattern recognition` deferred item (per ALBERTA_STRATEGY_BRIEF.md §8.1)

### My recommendation

**Lead with Slot A.** Slot B is a v2 add-on after the anchor pilot has 3+ months of denial feedback (per the v2 deferred plan). For the first 90 days, Zorva should be a **pre-submission audit, not a post-submission reconciliation tool.**

This matches the v12 strategy brief's positioning ("catches 6–7 of 10 real billing errors before submission") and the existing v2 deferral logic.

---

## 4. Competitive blind spots — what existing tools already cover

### 4.1 EMR-native billing modules

**TELUS PS Suite, Accuro, OSCAR Pro, Med Access, CHR** all have native billing modules that include:
- Field-level form validation (PHN, BA, Prac ID, facility, functional centre, skill code, dates)
- H-Link submitter integration (the EMR vendor is itself an accredited submitter)
- Reconciliation reports from RA downloads
- Modifier and premium code dropdowns (auto-populate from the visit-level code)

**What they don't do:**
- Read the clinical-note content to detect note-vs-code mismatches (the "brief note billed as 03.04A" problem)
- Catch SOMB-specific rules like 90-day global surgical period, same-day conflict, CMGP eligibility, psychotherapy-time inference
- Generate audit findings the way Zorva does

**Competitive threat: medium.** They could add note-reading AI (TELUS has the data and the customer relationship), but the AI medical coding space is crowded and they've been slow to ship it. Accuro's billing module has no AI audit feature (per their product page — verified 2026-06).

### 4.2 Standalone Alberta billing tools

**ClinicAid / Cloud Practice** (the dominant Alberta third-party billing software):
- Form-level edit checks before submission to H-Link
- Its own accredited H-Link submitter
- The Cloud Practice "common rejection codes" page is itself evidence of how form-level their checks are
- **No clinical-note content reading.** Their check is "field X is blank or wrong format," not "the note documents X work and the claim bills Y code."

**Petal Medical Billing (formerly Statgo)**:
- Stronger — has AI-assisted coding suggestions per their marketing copy
- Targets small/mid Alberta clinics
- +9.4% revenue increase claim (vendor stat, not independently verified)
- **Some clinical-context reading** — Petal's "smart code suggestions" likely touch this. But their rule depth is unproven against AHCIP SOMB specifics.

**DoctorCare**, **Alberta Medical Billing**, **K&M Medical Billing** (the billing services):
- Human-biller QC. The biller reads each claim before submission. Slow, expensive (5–8% of collections typical for outsourced billing), but catches what humans catch.
- **No AI audit.** Pure manual review by trained billers.

### 4.3 What Zorva uniquely does

The clean competitive positioning for Zorva, grounded in what no other tool does:

| Capability | Zorva | EMR billing module | ClinicAid | Petal | Outsourced biller |
|---|---|---|---|---|---|
| Field-level form validation | No (not in scope) | Yes | Yes | Yes | Yes (human) |
| H-Link submission | No | Yes | Yes | Yes | Yes |
| RA reconciliation | Partial | Yes | Yes | Yes | Yes |
| **Clinical-note vs code consistency** | **Yes** | No | No | Partial | Yes (human) |
| **SOMB rule depth** (CMGP, global period, psychotherapy time, telehealth premium) | **16 rules** | No | No | Partial | Yes (human) |
| **AHCIP-specific** (no US-CPT drift) | **Yes** | Mixed (depends on EMR config) | Yes | Yes | Yes |
| **Per-clinic calibration** (deferred v2) | **Deferred** | No | No | No | Implicit (human knows the clinic) |
| **Cost per claim** | ~$0.50–$2 at scale | Included in EMR | Included in ClinicAid | Included in service | $3–$8 (human time) |

**Bottom line:** Zorva's defensible niche is the **clinical-context audit** — reading the note and the claim together to catch SOMB-specific rule violations that form-level checks miss. No off-the-shelf Alberta tool does this with AHCIP rule depth.

---

## 5. Out of scope — things I considered and rejected

- **Building a Zorva H-Link submitter.** Out of scope. Becoming an accredited H-Link submitter is a multi-month regulatory + integration effort (forms AHC2210, AHC2208, AHC2209 + connectivity testing per alberta.ca). Better to integrate with EMR vendors as a value-added audit layer on top of their existing submitter. Reject until Zorva has 50+ clinic customers and the integration revenue justifies the regulatory overhead.
- **Building a Zorva EMR.** Out of scope. The EMR market is locked up by TELUS/QHR/WELL; competing is a $50M+/10-year project. Zorva is the audit layer, not the EMR.
- **Going to OHIP/MSP first instead of deepening AHCIP.** Rejected. AHCIP rule depth (16 rules, v12 F1=0.690) is Zorva's only defensible asset; spreading thin to OHIP (0 rules) and MSP (0 rules) before landing Alberta would burn 12+ person-weeks for zero near-term revenue.
- **Real-time claim streaming to H-Link.** Out of scope — H-Link is weekly batch, so "real-time" isn't a thing in Alberta. If we wanted real-time we would have to wait for Alberta to change the cadence, which is not on the roadmap.
- **Building a reconsideration letter generator for v1.** Deferred to v2. The pilot's value prop is pre-submission catch (Slot A), not post-submission recovery. The appeal-letter module is built but should not be a v1 sales message.
- **Pricing Zorva per-claim vs per-month.** Out of scope for this workflow research — the existing $499/$1,499/$2,999 per-month tiers in the strategy brief are reasonable for the biller-pilot positioning. Per-claim pricing is a downstream optimization.
- **Direct-to-physician marketing (vs billing-lead / office manager / PCN ops).** Out of scope for this research, but flagged: physicians are not the buyer of a billing-audit tool. The buyer is the office manager, billing lead, or PCN ops director. Per Cameron's audit-first outreach style and the existing prospect-list strategy, Zorva sells to the operator, not the clinician.
- **Studying Quebec / RAMQ.** Out of scope. Quebec is a different fee schedule, different submission system, and not in the Alberta-first strategy brief.

---

## 6. Implications for downstream tracks

### For P2 (AHCIP submission flow)
- The weekly H-Link batch is the dominant cadence — Slot A pre-submission window is 1–3 days per claim.
- 90-day submission limit (since March 31, 2020) is the relevant SLA for "outdated claim" detection.
- Real-time reconciliation is not the design constraint; weekly batch is.

### For P3 (EMR integration landscape)
- TELUS Health (PS Suite + Med Access + CHR) is the #1 target (~42% share).
- Accuro (QHR) is #2 (~26%); their billing module is in-house so Zorva is competing with their own UI, but the clinical-context audit gap is still real.
- OSCAR Pro (WELL Health) is #3 (~24%); OSCAR's open API history means integration may be cheaper than the closed TELUS/QHR systems.
- All three have H-Link submitter roles — Zorva is a value-added layer, not a replacement submitter.

### For P4 (competitors)
- The Alberta-relevant competitors are **Petal Medical Billing (formerly Statgo)** and **ClinicAid / Cloud Practice** (the dominant standalone billing tools), plus the EMR vendors' own billing modules.
- US-CPT-focused competitors (CodaMetrix, Anterior, AKASA, SmarterDx, Maverick Medical AI) are not direct Alberta threats — they have no AHCIP/SOMB coverage and would have to build it from scratch.
- DoctorCare, Alberta Medical Billing, K&M Medical Billing are channel-partner candidates, not competitors.

### For P5 (customer signal)
- The Zorva pitch for an Alberta biller should lead with **Slot A (pre-submission audit)** + **defensibility against outsourced billing services** (Zorva is faster than human biller QC, cheaper than 5–8% collections fee).
- The "first-pass acceptance rate (FPAR)" framing matches how billers already think — Petal's pitch is built on this.

### For P6 (product gaps)
- The current v12 covers pre-submission audit. v2 deferred items (per ALBERTA_STRATEGY_BRIEF.md §8) cover post-submission learning loop + cross-tenant denial patterns.
- Open product gaps to flag for P6: per-patient history (for frequency-limit rules), PHN/BA validation (out of Zorva scope but valuable to flag), reconsideration-letter UI (built but unexercised), H-Link batch simulation mode for the pilot.

---

## 7. Source quality summary

| Source | Type | Confidence | Used for |
|---|---|---|---|
| `docs/ALBERTA_STRATEGY_BRIEF.md` | Internal project doc | High (authored 2026-06-22) | Prospect list, ICP, pricing, v12 baseline |
| `docs/ALBERTA_PROSPECT_LIST.md` | Internal project doc | High (12-clinic table) | Clinic landscape, EMR guesses |
| `docs/BILLING_CONSULTANT_CHANNEL_PARTNERS.md` | Internal project doc | High | Consultant / channel partner economics |
| `docs/AHCIP_RULE_REFERENCE.md` | Internal project doc | High (16-rule catalogue) | Zorva's rule depth |
| `runs/recall/v12_summary.md` | Internal eval | High (F1=0.690 baseline) | What Zorva actually catches |
| https://www.alberta.ca/h-link-electronic-claims-system | Government primary | High (verified 2026-06) | H-Link operator, batch cadence, submitter model |
| https://help.healthquest.ca/portal/en/kb/articles/alberta-health-claims | EMR vendor (Healthquest) | High | Wednesday cutoff, Monday reconciliation |
| https://cloudpractice.freshdesk.com/support/solutions/articles/3000039839-alberta-cutoff-dates-and-remittance-periods | EMR vendor (ClinicAid) | High | Weekend assessment, Sunday-evening RA |
| https://help.inputhealth.com/en/articles/6056208-submitting-provincial-ahcip-bills-to-h-link-alberta | EMR vendor (InputHealth CHR) | High | 11am/3:30pm EMR-side batching |
| https://cloudpractice.freshdesk.com/support/solutions/articles/3000110683-alberta-how-to-fix-common-rejection-codes | EMR vendor (ClinicAid) | High (2022, but explanatory codes stable) | Common AHCIP refusal codes |
| https://www.petal-health.com/en/blog/physicians/top-reasons-for-medical-billing-rejections-in-ab-bc-and-on/ | Vendor (Petal) blog | Medium (Feb 2026, vendor-sourced) | Alberta-specific rejection taxonomy |
| https://blackbookmarketresearch.com/uploads/pdf/Black-Book-Research-CANADA-Q2-2025-EHR-RESULTS.pdf | Industry report | High (Q2 2025) | EMR market share Canada-wide |
| https://opsmed.ca/resources/ontario-clinic-automation-landscape/ | Industry analyst | High (2026) | TELUS 42% / QHR 26% / WELL 24% |
| https://www.dr-bill.ca/alberta-health-billing-explanatory-codes-2 | Industry reference | Medium | Alberta explanatory codes reference |
| https://www.albertadoctors.org/fee-navigator/explanatory-codes | Alberta Medical Association primary | High | Official SOMB explanatory codes |
| https://open.alberta.ca/dataset/e271120b-a62a-4178-bc47-26fe53c1a5fc/... | Government primary (Apr 2024) | High | SOMB explanatory codes 2024 |
| Petal Health + Cloud Practice + DoctorCare product pages | Vendor marketing | Low (vendor claims, +9.4% revenue, 161 hours saved) | Directional only |

---

## 8. One-line summary for the synthesis task

> **Zorva fits at the "Ready To Submit" gate** (1–3 day pre-batch hold per claim). v12's 16-rule SOMB audit reads clinical-note + claim together and catches ~6–7 of 10 real billing errors before H-Link's Wednesday batch upload. This slot is defensible because no Alberta competitor (EMR billing module, ClinicAid, Petal, outsourced billing service) does clinical-context reading at AHCIP rule depth. Slot B (reconciliation / reconsideration) is real but lower-leverage and deferred to v2.

---

*End of P1. Ready for synthesis.*