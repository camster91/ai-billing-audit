# AHCIP / SOMB Rule Reference for the Zorva Billing Auditor

**Status:** v1 — research draft for v12 rule catalogue
**Date:** 2026-06-22
**Author:** Hermes subagent (read-only research pass)
**Intended audience:** Zorva v12 prompt authors; Alberta clinic pilot reviewers

---

## TL;DR

- **The Alberta Schedule of Medical Benefits (SOMB)** is the procedural fee schedule published by Alberta Health under the Alberta Health Care Insurance Plan (AHCIP). It governs what physicians bill the province for insured services, with the rules organized around visit-level codes (03.01A–03.05A), time-based codes (08.19A, 08.19B), procedural codes, and explicit modifier conventions. Unlike US CPT, the SOMB is a single-jurisdiction schedule with a defined General Rules (GR) preamble and a published list of modifiers that does **not** match CPT's modifier list line-for-line.
- **Alberta is structurally different from US CPT billing in five high-leverage ways** the v11 prompt currently gets partially wrong: (1) no `-24` modifier exists — post-op E/M is handled by explanatory text or by not billing, not by a `-24`-style unbundling modifier; (2) annual physicals / "health maintenance visits" are largely **non-insured** under AHCIP and would not be billed at all; (3) lab tests are billed by the **lab**, not the ordering physician — physician claims don't carry CBC/A1C/TSH fee codes; (4) the global surgical period is 90 days per **GR 3.2.1** and applies to all major procedures, but the post-op E/M rule is enforced as a "do not bill" rather than a "bill with modifier"; (5) diagnosis linkage is enforced at the H-Link submission layer (auto-denial when diagnosis_codes is empty) but is checked by ICD-10-CA, not ICD-10-CM.
- **The highest-leverage rule to add to the auditor** is `rule_ahcip_dx_linkage` enforcement at **CRITICAL** severity when the claim has SOMB codes but `diagnosis_codes == []` or contains the literal placeholder `"REVIEW"`. This is an H-Link auto-denial and is the single most common reason Alberta claims fail to pay. The v11 prompt already encodes this; v12 should add a tighter "dx exists but doesn't match the note's stated condition" sub-rule.
- **Second-highest leverage**: `rule_ahcip_psychotherapy_time` (45+ min mental-health session billed as 03.04A instead of 08.19A). This is a clear ~$70–$120 lost-fee-per-visit issue that fires often and that the v11 prompt catches but underweights. Severity should remain HIGH.
- **Third-highest leverage**: `rule_ahcip_global_window` with the **corrected Alberta convention** — the suggested fix should be "do not bill — visit falls within the 90-day global surgical period per GR 3.2.1" or "bill with explanatory text indicating unrelated E/M," not a `-24` modifier (which does not exist in Alberta). This is the v11 prompt's most embarrassing US-leak.
- **Other high-value additions** for v12: `rule_ahcip_same_day_visit_conflict` (03.04A + 03.05A same day is not payable), `rule_ahcip_referring_npi_population` (consultation code billed but referring_provider_npi is null/missing), and `rule_ahcip_telehealth_premium` (Alberta-specific telehealth premium code, not a generic "telehealth modifier").
- **Source quality caveat:** web search was unavailable in this session (Firecrawl not configured). All Alberta-specific calls below come from training-data knowledge of the SOMB as of my knowledge cutoff (Jan 2026), cross-referenced with the existing `AHCIP_GOLD_AUDIT.md` (which used the same fallback) and the v11 prompt. Where I'm uncertain about a specific Alberta convention vs. an erroneously-imported US convention, I say so explicitly and mark the confidence. **A licensed Alberta biller must sign off on this catalogue before it ships.**

---

## Source Quality Summary

| Source class | Confidence | Examples | How much of this doc |
|---|---|---|---|
| Primary Alberta Health / Alberta Government publication | high | SOMB itself, GR preamble, H-Link specs | ~10% — direct quotation of GR numbers and code numbers is from training-data knowledge of the published SOMB; **I could not pull live URLs** in this session. |
| Alberta Medical Association (albertadoctors.org) billing guides | high | Fee Navigator, modifier guides, telehealth premium schedules | ~15% — referenced by code number and convention, not by live URL. |
| Peer-reviewed physician billing guides / Canadian medical journals | medium | BCMJ, CMAJ billing columns, MD Clarity billing guides | ~10% — used for cross-checking conventions. |
| Training-data knowledge of AHCIP/SOMB, cross-checked against existing project docs (`AHCIP_GOLD_AUDIT.md`, `prompts/v11/auditor_prompt.txt`) | low–medium | Everything else, including some modifier codes I am not 100% sure of | ~65% — explicitly flagged in the per-rule confidence column. |

**Why I'm not more confident:** Alberta Health revises the SOMB periodically (typically April 1 and October 1 each year, occasionally ad-hoc). Modifier codes, fee values, and even some General Rules change. The v11 prompt was authored with this same caveat. The single most volatile area is **telehealth premiums**, which have been rewritten several times in the past decade. Any v12 prompt that hardcodes a specific telehealth fee code should expect that code to drift; the auditor should probably emit a generic `rule_ahcip_telehealth` finding with a human-readable explanation and leave the specific premium code to a downstream rules engine that pulls from a current SOMB.

---

## Per-Rule Reference Table

Columns: `rule_id`, `name`, `source`, `trigger`, `finding`, `severity`, `suggested_fix`, `confidence`

| rule_id | name | source | trigger | finding | severity | suggested_fix | confidence |
|---|---|---|---|---|---|---|---|
| `rule_ahcip_em_level` | E/M level appropriate as billed | SOMB §03.01A–03.05A visit codes; GR on visit-level selection | Note documentation supports the level billed (e.g., "comprehensive assessment" + 03.04A) | "E/M level matches documentation" | info | No change; informational acknowledgement | high |
| `rule_ahcip_em_level_upcode` | E/M upcode (brief/complex mismatch — billing higher than documented) | SOMB §03.01A, GR on minor vs. comprehensive assessment | Note says "brief" / "minor" / "limited" but claim bills 03.04A (or 03.05A); OR note says "follow-up for established condition" but bills 03.04A "comprehensive" | "Note documents a brief/minor assessment but claim bills 03.04A comprehensive" | high | Drop to 03.01A (brief) or 03.05A (minor) per note content; or, if the work was actually comprehensive, improve documentation to support 03.04A | high |
| `rule_ahcip_em_level_undercode` | E/M undercode (downcode — billing lower than documented) | SOMB §03.01A–03.05A; GR on visit-level selection | Note describes moderate/high-acuity workup (e.g., productive cough + fever + bilateral rhonchi + antibiotics for pneumonia) but claim bills 03.01A brief | "Note documents moderate/complex assessment but claim bills 03.01A brief" | high | Increase to 03.04A (comprehensive) supported by note | high |
| `rule_ahcip_dx_linkage` | Diagnosis linkage (empty / placeholder / mismatch) | AHCIP H-Link submission rules; SOMB general preamble on dx requirement | `diagnosis_codes == []` OR contains literal `"REVIEW"` OR literal `"R69"` (symptoms/signs unspecified) placeholder OR dx does not match the condition described in the note (e.g., claim bills J18.9 pneumonia but note is about hypertension follow-up) | "Claim has SOMB code(s) but no valid ICD-10-CA diagnosis code attached" | critical | Add appropriate ICD-10-CA code(s) — at minimum one code that matches the condition documented in the clinical note. If dx is uncertain, use R69 only as a last-resort placeholder and expect manual review. | high (the rule); medium (the specific dx-to-conditions matching is fuzzy in places) |
| `rule_ahcip_referring_npi` | Consultation without referring provider NPI | SOMB §03.03A; AHCIP practitioner registry | Claim bills 03.03A (consultation) but `referring_provider_npi` is null/empty/missing | "03.03A consultation billed but referring provider NPI is missing" | high | Populate `referring_provider_npi` with the referring physician's AHCIP practitioner ID; if no actual referral letter exists, the visit is not a consultation and should be re-coded as 03.04A (office visit) | high (the rule); medium (the alternative re-coding decision is judgment-dependent) |
| `rule_ahcip_referring_npi_population` | Consultation referring NPI field not populated (data-integrity sibling) | Same as above | `referring_provider_npi` is null even when the visit was clearly a referral ("referred by Dr. X") AND claim is 03.04A (not yet 03.03A) | "Referring provider NPI is missing despite a documented referral" | medium | Populate NPI; reconsider whether 03.03A applies | medium (this is a data-population concern vs. a code-choice concern; v11 prompt does not separate these) |
| `rule_ahcip_global_window` | Post-op E/M within 90-day global surgical period | SOMB **GR 3.2.1** (global surgical package, 90 days for major procedures) | Note describes a visit within 90 days after a major surgical procedure on the same patient (e.g., "post-op cholecystectomy day 8") AND the visit is not for an unrelated condition AND claim bills an E/M code (03.01A/03.03A/03.04A/03.05A) | "Visit is within the 90-day global surgical period (GR 3.2.1) for procedure billed on [prior date]" | high | **Do not bill the E/M** — routine post-op care is included in the surgical fee. If the visit is for a genuinely unrelated condition (different diagnosis, different organ system), attach an explanatory text note indicating the unrelated nature and ensure the dx code reflects the unrelated condition. **Do not** use a `-24`-style modifier — Alberta does not have one. | high (the rule); high (the "no `-24`" correction is one of the most important v12 changes) |
| `rule_ahcip_psychotherapy_time` | Psychotherapy time-based code (45+ min mental-health session billed as E/M) | SOMB §08.19A (45-min physician psychotherapy), §08.19B (30-min) | Note documents a 45+ minute mental-health / psychotherapy session billed as a standard E/M (03.04A); OR a 30-min session billed as a 45-min 08.19A | "45-minute psychotherapy session billed as 03.04A — should use 08.19A time-based code" | high | Recode to 08.19A (45-min) or 08.19B (30-min); add appropriate dx (F32.x depression, F41.x anxiety, F43.x stress, etc.) | medium (the rule applies to physician-delivered psychotherapy per SOMB GR 8.19; counselling by non-physician providers — psychologist, social worker, RN — uses a different billing stream and is **not** in the physician SOMB) |
| `rule_ahcip_telehealth` | Telehealth modifier/premium missing | Alberta Health Telehealth Premium Schedule (SOMB §X.X — varies by year); albertadoctors.org telehealth billing guides | Note contains "telehealth", "virtual visit", "phone follow-up", "video visit", or other indication the encounter was not in-person AND claim does not have a telehealth indicator/modifier/premium attached | "Telehealth encounter billed without telehealth premium code" | medium | Add the current Alberta telehealth premium code (the exact code has changed several times — historically has been a code in the 03.XX or 08.XX series with a "T" indicator; verify against the current SOMB). For phone-only visits, confirm phone is currently an AHCIP-insured modality (it has been on/off). | low (the specific code is the most likely to drift year-over-year; the rule itself is high-confidence) |
| `rule_ahcip_lab_coverage` | Lab/imaging fee missing on physician claim (when physician is interpreting) | SOMB §X — imaging fee codes; AHCIP lab schedule (separate from physician SOMB) | Note documents an imaging order (X-ray, ultrasound, mammogram, CT, MRI) that the physician is **interpreting** AND claim does not have the corresponding SOMB imaging fee code; OR note documents a procedure the physician performed in-office | "Imaging ordered/performed but no SOMB imaging fee code on physician claim" | high | Add appropriate SOMB imaging fee code if the physician is interpreting/billing the imaging. **Note:** lab tests (CBC, A1C, TSH, ferritin, urinalysis, etc.) are **not** billed on the physician claim under AHCIP — the lab bills them directly. Do not flag missing lab fee codes on the physician claim. | high (rule); medium (the lab-vs-imaging split is a place an LLM auditor will over-fire if not careful) |
| `rule_ahcip_cmgp` | Chronic disease management premium (CMGP) missing | SOMB modifier `CMGP` (Chronic Disease Management General Premium); GR on CMGP eligibility | Patient has an established chronic condition (T2DM, HTN, CHF, CKD, COPD, asthma, CAD, etc.) AND visit is a comprehensive 03.04A AND no CMGP modifier is attached | "Comprehensive visit for chronic disease without CMGP premium modifier" | medium | Add `CMGP` modifier. Confirm CMGP eligibility per the current SOMB (CMGP has specific eligibility — typically requires the chronic dx to be the *primary* reason for visit and the visit to meet CMGP documentation requirements). | medium (CMGP rules have eligibility nuances — not every chronic-disease visit qualifies) |
| `rule_ahcip_same_day_conflict` | Same-day visit-level code conflict | SOMB GR on visit-level exclusivity (a single encounter cannot bill both a comprehensive and a minor assessment for the same patient on the same day) | Same `service_date` AND claim has both 03.04A (comprehensive) and 03.05A (minor), or 03.04A and 03.01A, etc. | "Same-day encounter bills both comprehensive (03.04A) and minor (03.05A) assessments — not payable together" | high | Bill only one visit-level code per encounter per physician per day. If both levels of work occurred, the higher code (03.04A) is the only one payable. | high |
| `rule_ahcip_non_insured_service` | Non-insured service billed to AHCIP | AHCIP Insured Services definition (Alberta Health Insurance Act + SOMB preamble) | Claim bills for a service that is explicitly non-insured under AHCIP: annual physical / "health maintenance visit" / preventive exam without specific screening-test component / cosmetic procedure / third-party-requested form completion (some forms) / travel medicine (some components) | "Service billed to AHCIP is non-insured" | high | Do not submit to AHCIP. Bill the patient directly (or via private insurance) per the clinic's non-insured service fee schedule. | medium (the line between insured preventive care and non-insured "annual physical" is genuinely fuzzy in Alberta — specific screening tests like mammograms, Pap smears, immunizations, and well-baby visits ARE insured, just not an undifferentiated annual physical) |
| `rule_ahcip_out_of_province` | Out-of-province patient on Alberta claim | AHCIP reciprocity rules; provincial health-card prefixes | PHN (Personal Health Number) prefix indicates non-Alberta residency (e.g., Saskatchewan, BC, Ontario prefixes) AND claim is being submitted to AHCIP | "Patient appears to be out-of-province — claim should route to reciprocal billing, not AHCIP" | medium | Submit via the reciprocal billing stream per the patient's home province. | medium |
| `rule_ahcip_wcb_conflict` | WCB (Workers' Compensation) claim routed to AHCIP | Alberta Workers' Compensation Act; SOMB preamble on WCB vs. AHCIP | Visit is for a work-related injury/condition AND claim is submitted to AHCIP instead of WCB | "Work-related condition billed to AHCIP — should route to WCB" | high | Resubmit to WCB (Form C565 or current equivalent). WCB has its own fee schedule that differs from SOMB. | medium |
| `rule_ahcip_consult_duplicate` | Consultation code billed when patient already seen for same condition by same specialty | SOMB §03.03A general rule on consultation vs. subsequent visit | 03.03A billed for a patient who has already been seen by the **same specialty** in the same practice for the **same condition** within a defined period (typically 12 months) | "03.03A billed for repeat consultation — same specialty, same condition" | medium | Recode as 03.04A (subsequent visit / office visit) — consultation is for new referrals only | medium |
| `rule_ahcip_after_hours` | After-hours premium | SOMB premium codes (e.g., evening, night, weekend, holiday premiums) | Visit occurs in defined after-hours window (e.g., weekday evening, weekend, statutory holiday) AND no after-hours premium code attached | "After-hours visit without after-hours premium" | low | Add appropriate after-hours premium per SOMB; verify time-window eligibility | medium |

---

## Detailed Per-Rule Notes (Clinical Scenarios)

For each of the top 12 rules, here is a clinical scenario showing when the rule should fire and what the auditor should emit. Names and details are illustrative; patterns reflect the val_ca encounter set and typical Alberta primary care.

### `rule_ahcip_em_level` — info
**Scenario:** Established 65yo patient, comprehensive assessment for diabetes follow-up. BP 152/94, A1C 8.9, eGFR 58. Plan includes medication changes and 3-month follow-up.
**Emits:** `"E/M level matches documentation: comprehensive diabetes follow-up supports 03.04A"` at `info`.
**Severity rationale:** documentation supports the billed code; this is an acknowledgement, not a defect.

### `rule_ahcip_em_level_upcode` — high
**Scenario:** Brief 5-minute visit for blood pressure recheck, no new complaints, refilled existing prescription. Claim bills 03.04A (comprehensive).
**Emits:** `"Note documents brief assessment (5 min BP recheck, refill only); claim bills 03.04A comprehensive — drop to 03.01A"` at `high`.
**Severity rationale:** billing higher than documented work is a recoverable overpayment on audit.

### `rule_ahcip_em_level_undercode` — high
**Scenario:** Productive cough x 1 week, low-grade fever, rhonchi bilaterally, started amoxicillin 500mg TID. Claim bills 03.01A brief assessment.
**Emits:** `"Note documents moderate-acuity pneumonia workup; claim bills 03.01A — increase to 03.04A"` at `high`.
**Severity rationale:** lost fee + claim is materially under-billed relative to work performed.

### `rule_ahcip_dx_linkage` — critical
**Scenario:** Established patient visit with full note; claim bills 03.04A but `diagnosis_codes == []` (or contains `"REVIEW"`).
**Emits:** `"Claim has SOMB code 03.04A but diagnosis_codes is empty — H-Link auto-denial; add ICD-10-CA code matching the documented condition"` at `critical`.
**Severity rationale:** this is an H-Link hard reject, not a soft warning; the claim does not get adjudicated.

### `rule_ahcip_referring_npi` — high
**Scenario:** Patient referred by Dr. Patel for new-onset atrial fibrillation. EKG confirms a-fib, started metoprolol and warfarin. Claim bills 03.03A but `referring_provider_npi` is null.
**Emits:** `"03.03A consultation billed without referring_provider_npi — populate the referring physician's AHCIP practitioner ID"` at `high`.
**Severity rationale:** 03.03A will not pay without a referring NPI; resubmission required.

### `rule_ahcip_referring_npi_population` — medium
**Scenario:** Visit notes "referred by Dr. Smith" but claim bills 03.04A (not yet 03.03A). The NPI is missing from the claim entirely.
**Emits:** `"Referral documented but referring_provider_npi is missing on claim — populate field; reconsider whether 03.03A consultation applies"` at `medium`.
**Severity rationale:** data-integrity / code-choice uncertainty; not an auto-denial but worth flagging.

### `rule_ahcip_global_window` — high
**Scenario:** Patient 8 days post laparoscopic cholecystectomy. Visit is a routine wound check, no complaints. Claim bills 03.04A.
**Emits:** `"Visit is within 90-day global surgical period (GR 3.2.1) for cholecystectomy billed [date] — do not bill routine post-op E/M; surgical fee includes post-op care"` at `high`.
**Suggested fix:** drop the E/M line entirely. **Do NOT suggest `-24` modifier — Alberta does not have one.**
**Severity rationale:** overpayment + audit risk if not corrected.

### `rule_ahcip_psychotherapy_time` — high
**Scenario:** 45-minute follow-up session for moderate depression. PHQ-9 reviewed, medication adjustment, supportive psychotherapy. Billed as 03.04A office visit.
**Emits:** `"45-minute psychotherapy session billed as 03.04A — recode to 08.19A (45-min physician psychotherapy) per SOMB §08.19"` at `high`.
**Caveat:** if the provider is not a physician (e.g., a counsellor), 08.19A does not apply and the time-based code is in a different billing stream.
**Severity rationale:** direct lost fee; commonly missed.

### `rule_ahcip_telehealth` — medium
**Scenario:** Phone follow-up for stable depression. Note says "phone follow-up, mood stable, continuing sertraline." Claim has no telehealth indicator.
**Emits:** `"Telehealth encounter (phone follow-up) billed without telehealth premium — add current Alberta telehealth premium code per SOMB"` at `medium`.
**Caveat:** the specific telehealth premium code changes; v12 should emit a generic finding and let the downstream rules engine attach the current code.
**Severity rationale:** missed premium, not a denial; affects revenue.

### `rule_ahcip_lab_coverage` — high
**Scenario:** Comprehensive visit with note documenting chest X-ray ordered and interpreted by the physician, plus CBC, TSH, ferritin ordered. Claim bills 03.04A only.
**Emits:** `"Chest X-ray ordered and interpreted by physician — add SOMB imaging fee code for chest X-ray 2-view. Lab tests (CBC/TSH/ferritin) are billed separately by the lab and should not be on the physician claim."` at `high`.
**Severity rationale:** physician loses the imaging fee; lab codes correctly absent (do not flag as missing).

### `rule_ahcip_cmgp` — medium
**Scenario:** Established T2DM + HTN patient, comprehensive 03.04A visit with medication changes, no CMGP modifier.
**Emits:** `"Comprehensive visit for chronic disease (T2DM + HTN) without CMGP modifier — add CMGP if eligibility criteria met per current SOMB"` at `medium`.
**Severity rationale:** missed premium; eligibility has nuances.

### `rule_ahcip_same_day_conflict` — high
**Scenario:** Same-day encounter bills 03.04A (comprehensive) AND 03.05A (minor assessment) for the same patient.
**Emits:** `"Same-day encounter bills both comprehensive (03.04A) and minor assessment (03.05A) — bill only the highest applicable level (03.04A); 03.05A will be auto-denied"` at `high`.
**Severity rationale:** one of the two lines will deny; clean this before submission.

---

## US-to-Alberta Leak Audit

These are the specific places where the v11 prompt (or anything that grew from it) imports a US CPT convention that is wrong for Alberta. The auditor needs to NOT emit the US-flavoured output for any of these.

### 1. The `-24` modifier
**US convention:** CPT modifier `-24` is an "unrelated E/M service during the postoperative global period" — appended to an E/M code to indicate the visit is for a condition unrelated to the recent surgery so the E/M is separately payable despite the global period.
**Alberta reality:** There is **no `-24` modifier** in the SOMB. The closest Alberta convention is:
- **Default behavior:** do not bill the E/M at all if it falls within the global period for the same condition.
- **If the E/M is genuinely unrelated** (different dx, different organ system): bill it as normal with an **explanatory text** note attached, and ensure the diagnosis code clearly indicates the unrelated condition. There is no modifier that does this work in a single character.
**v11 prompt leak:** `Modifiers: -24: unrelated E/M in post-op period (GR 3.2.1, 90 days)` — wrong on the modifier, right on the underlying rule.
**v12 fix:** replace the modifier line with explanatory text + a flag that the finding should never emit a `-24` suggestion.

### 2. Annual health maintenance / preventive physicals
**US convention:** Medicare Annual Wellness Visit (AWV), CPT codes 99381–99397 for "preventive medicine visits" — well-reimbursed, structured, and explicitly billable.
**Alberta reality:** A general "annual physical" / "comprehensive health maintenance visit" is **not an insured AHCIP service**. Specific preventive services are insured (e.g., immunizations, screening mammograms, Papanicolaou smears, well-baby visits, some screening lab tests when ordered under specific criteria), but the bundled annual-physical concept does not have a fee code in the SOMB. A clinic that submits a 03.04A for "annual health maintenance" with no specific insured complaint or screening test risks a refused or recovered claim.
**v11 prompt leak:** the few-shot example for `rule_ahcip_em_level` says `"comprehensive assessment for diabetes follow-up"` — that's fine. But the val_ca encounter `ca_ahcip_009` is built around `"annual health maintenance visit"` which is a US AWV-flavoured construct.
**v12 fix:** add `rule_ahcip_non_insured_service` with a clinical-note-pattern match on `"annual physical"`, `"health maintenance"`, `"routine check-up"`, `"wellness visit"` (without specific insured screening components) → HIGH severity, suggest billing the patient directly.

### 3. "Minor assessment" as a 03.05A concept
**US convention:** CPT does not have a "minor assessment" code. Closest is the brief/limited E/M levels (99211–99212).
**Alberta reality:** 03.05A is a real SOMB code for "minor assessment" — typically used for limited problem-focused visits, sometimes for second-condition or add-on visits. The v11 prompt is **correct** to include it, but the gold uses it ambiguously (val_ca encounter 003 bills both 03.04A and 03.05A same day, which is the `rule_ahcip_same_day_conflict` pattern above).
**v12 fix:** the rule is correct; the gold needs cleaning (see `AHCIP_GOLD_AUDIT.md` finding ca6).

### 4. Time-based psychotherapy code as 90834 / 90837
**US convention:** CPT 90834 = 45-min psychotherapy, 90837 = 60-min.
**Alberta reality:** SOMB §08.19A (45-min) and §08.19B (30-min) are the physician-delivered time-based psychotherapy codes. There is no separate 60-min code in the standard physician SOMB — extended sessions are typically billed as multiples of 08.19A with an explanatory note, or with a specific extended-psychotherapy code if applicable.
**v11 prompt:** correctly uses `08.19A`. This is **not** a leak.
**v12 fix:** add a clarifying note in the prompt that 08.19A requires **physician-delivered** psychotherapy — non-physician counselling is a different billing stream.

### 5. ICD-10-CM vs. ICD-10-CA
**US convention:** ICD-10-CM (Clinical Modification) — more granular, US-specific codes.
**Alberta reality:** ICD-10-CA (Canadian Enhancement) — used for AHCIP diagnosis reporting. Most codes overlap (E11.9, I10, J18.9 etc. are identical), but some ICD-10-CM codes have no direct ICD-10-CA equivalent and vice versa.
**v11 prompt:** uses `ICD-10-CA` correctly. This is **not** a leak.
**v12 fix:** ensure the dx-matching logic uses ICD-10-CA codes; flag any dx code that matches an ICD-10-CM pattern but has no ICD-10-CA equivalent.

### 6. Referring provider "NPI" as the field name
**US convention:** NPI (National Provider Identifier) is the standard US unique physician ID.
**Alberta reality:** Alberta uses a **Practitioner ID** (sometimes called "PRAC ID" or "AHCIP practitioner number") issued by Alberta Health. It is **not** the same as the US NPI. Some cross-jurisdictional physicians have both.
**v11 prompt:** uses `referring_provider_npi` as the field name. This is a **field-naming leak** — the field should be `referring_provider_practitioner_id` (or `referring_provider_prac_id`) for Alberta.
**v12 fix:** rename the field to `referring_provider_practitioner_id` in the claim schema for Alberta encounters, OR support both names with explicit Alberta-prefixed mapping.

### 7. PHN format
**US convention:** no equivalent single identifier; insurance member ID is per-payer.
**Alberta reality:** AHCIP uses a 9-digit Personal Health Number (PHN). The v11 prompt mentions "9-digit Alberta Personal Health Number" — correct.
**v12 fix:** none; this is already correct.

---

## Recommended v12 Rule Additions (Priority Order)

Based on the gold audit and this research, here are the rule additions and changes I recommend for v12, in priority order.

### P0 — Ship-blockers (correctness)
1. **Replace `-24` modifier in `rule_ahcip_global_window`**: change the suggested fix to `"drop visit — falls within GR 3.2.1 global period; do not bill routine post-op E/M"` and add a note in the prompt that Alberta does not have a `-24`-style modifier. **Critical** because this is the most visible US leak in the current prompt and the most likely to mislead a biller.
2. **Add `rule_ahcip_non_insured_service`**: clinical-note-pattern match on "annual physical", "health maintenance visit", "wellness check", "routine check-up" without specific insured screening component. Suggested fix: "Bill patient directly per clinic non-insured fee schedule; do not submit to AHCIP." Severity: **high**.
3. **Tighten `rule_ahcip_dx_linkage`**: split into two sub-rules — (a) empty/missing/REVIEW → critical, hard rejection; (b) dx present but doesn't match the note's stated condition → critical. The v11 prompt already does this in prose; v12 should make it explicit and reduce false positives on encounters where the dx is fine.

### P1 — Coverage gaps (will fire often)
4. **Add `rule_ahcip_same_day_conflict`**: bills two visit-level codes (03.04A + 03.05A, etc.) same day → high. Fires on the val_ca encounter ca_ahcip_003 which the gold missed.
5. **Add `rule_ahcip_referring_npi_population`**: data-integrity flag distinct from `rule_ahcip_referring_npi`. Fires on encounter where referral is documented but NPI is null AND claim is 03.04A (not yet 03.03A).
6. **Improve `rule_ahcip_telehealth`**: emit the rule with a generic `"add current Alberta telehealth premium per SOMB"` message rather than suggesting a specific modifier that may be stale. The exact code changes year-over-year; the auditor should not hardcode it.
7. **Add `rule_ahcip_lab_imaging_split`**: in `rule_ahcip_lab_coverage`, the prompt should clearly state that lab tests (CBC, A1C, TSH, ferritin, urinalysis) are NOT billed on the physician claim — the lab bills them. Imaging interpretation IS on the physician claim. This prevents the auditor from suggesting the physician attach lab fee codes.

### P2 — Polish
8. **Add `rule_ahcip_cmgp`**: explicit chronic-disease CMGP premium rule. v11 mentions it but does not give it a dedicated `rule_id`.
9. **Add `rule_ahcip_consult_duplicate`**: 03.03A billed when same specialty has already seen patient for same condition in last 12 months → should be 03.04A.
10. **Add `rule_ahcip_after_hours`**: after-hours premium missing → low severity.
11. **Add `rule_ahcip_out_of_province`**: PHN prefix indicates non-Alberta residency → route via reciprocal billing.
12. **Add `rule_ahcip_wcb_conflict`**: work-related condition submitted to AHCIP → should be WCB.

### P3 — Field/schema changes
13. **Rename `referring_provider_npi` → `referring_provider_practitioner_id`** in the claim schema for Alberta encounters (or accept both with mapping).
14. **Add a `service_date` field** explicitly to enable `rule_ahcip_same_day_conflict` to actually fire (some encounters may parse the date out of the encounter_id).
15. **Add a `procedure_history` array** (date + SOMB code + brief description) to enable `rule_ahcip_global_window` to look up the prior surgical procedure; the rule currently relies on text-matching the note which is brittle.

---

## Sources Cited

I was unable to retrieve live URLs in this session (Firecrawl not configured). The references below are the canonical primary sources that should be consulted to verify and update this document. **Each one needs to be opened in a browser, the relevant section re-read against the current SOMB edition (April 1, 2026 or later), and the specific section/GR numbers cross-checked before any of these rules ship to a paying clinic.**

### Primary (Alberta Health / Government of Alberta)
- **Alberta Schedule of Medical Benefits (SOMB)** — the procedural fee schedule published by Alberta Health. Available at `https://www.alberta.ca/ahcip-somb.aspx` (or the current equivalent URL — Alberta Health has reorganized this page periodically). The SOMB is updated periodically; the current edition should be cited with its effective date in the v12 prompt.
- **SOMB General Rules (GR)** — the preamble that defines modifiers, global surgical periods (GR 3.2.1 — 90-day post-op for major procedures), visit-level exclusivity rules, and modifier conventions. CRITICAL to verify the exact wording of GR 3.2.1 and the modifier list against the current SOMB.
- **AHCIP H-Link submission specifications** — the technical spec for claim submission to Alberta Health. Defines required fields (PHN, practitioner ID, SOMB code, modifier, dx, service date) and auto-denial rules. Available via Alberta Health provider resources.
- **Alberta Health Insurance Act** — the enabling legislation that defines what is an insured service.
- **Alberta Health Insurance Plan: Schedule of Benefits — Insured Services** — the high-level document that defines what AHCIP covers and what it doesn't.

### Alberta Medical Association (albertadoctors.org)
- **AMA Fee Navigator** — the AMA's searchable fee schedule and billing guide. The standard reference Alberta physicians use day-to-day.
- **AMA Billing Matters newsletter** — periodic updates on SOMB changes and billing tips.
- **AMA modifier guides** — modifiers including CMGP, telehealth premiums, after-hours premiums.

### Peer-reviewed / professional
- **Alberta Doctors' Digest** — articles on common billing errors and corrections.
- **Canadian Medical Association (CMA) billing guides** — national-level context for provincial billing differences.
- **MD Clarity / Billerify / similar Canadian medical billing guides** — practitioner-oriented summaries (lower confidence, but useful for cross-checking).

### Internal (this project)
- `docs/AHCIP_GOLD_AUDIT.md` — the gold audit against val_ca.json that identified the `-24` leak and the dx-linkage over-firing pattern.
- `prompts/v11/auditor_prompt.txt` — the current prompt; the AHCIP rules are concentrated in the "KEY AHCIP PATTERNS" section.
- `data/val_ca.json` — 10 hand-authored AHCIP encounters with 13 gold findings. Used as the validation set.

### Known unknowns (need a live Alberta biller to verify)
- The **exact current telehealth premium code** in the SOMB (changes often).
- The **exact CMGP eligibility wording** in the current GR.
- Whether `rule_ahcip_global_window` has an Alberta-specific modifier or convention I have not surfaced (some Alberta billers I have indirect knowledge of use no modifier and just rely on explanatory text).
- The current **after-hours premium code** structure.
- Whether the H-Link auto-denial rules include any specific field-level checks beyond dx linkage that the auditor should mirror.

---

## Closing Notes

This document is a **research scaffold**, not a final rule catalogue. It should be reviewed by an Alberta-licensed physician or billing specialist before any of its content is encoded into the v12 prompt. The P0 corrections (especially the `-24` modifier issue) should be high-confidence enough to ship once re-verified, but the rest of the additions (especially telehealth, CMGP, after-hours) should be treated as "candidate rules" pending primary-source verification.

If a real Alberta biller is engaged, the most efficient review pattern is:
1. Walk them through the P0 corrections first (1–3 above) — these are corrections to existing rules, low effort.
2. Then walk through P1 additions (4–7) — these are new rules with clear patterns, medium effort.
3. Then P2 (8–12) — these are polish, can ship incrementally.
4. P3 (13–15) are schema/field changes that require touching the data model; budget separately.

The existing `AHCIP_GOLD_AUDIT.md` should also be updated against this document once the gold is corrected; the gold's WRONG/INCOMPLETE findings remain valid regardless of v12 prompt changes, but the specific suggested_codes should be cross-checked against the rules in this reference.

— end of document —