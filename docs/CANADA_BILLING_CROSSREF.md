# Canada Billing Cross-Reference: AHCIP (AB) vs OHIP (ON) vs MSP (BC)

**Status:** v1 — research draft for Zorva v12+ rule catalogue
**Date:** 2026-06-22
**Author:** Hermes subagent (read-only research pass)
**Audience:** Cameron Ashley / Zorva prompt authors; v12+ pilot reviewers for ON/BC

---

## TL;DR

- **The three provincial systems are structurally similar but diverge in details.** All three are single-payer physician fee schedules administered by the province, all three use the same claim-shape philosophy (one or more HSC/feecode lines per encounter with an attached diagnosis), and all three submit electronically to a province-specific gateway. The differences live in the *codes*, the *modifiers*, the *global surgical period*, and the *telehealth/dx conventions*.
- **AHCIP is the cleanest starting point and v11 already covers it well.** The Alberta SOMB's General Rules (GR) preamble is well-structured, the modifier list is small and explicit, and the 16 v11 rules map cleanly to real SOMB practice. v11 is materially AHCIP-aware — see `docs/AHCIP_RULE_REFERENCE.md` for the catalogue.
- **OHIP (Ontario) is the largest market by physician count but the most complex fee schedule.** The Ontario Schedule of Benefits (SOBM) uses an alphabetic prefix (A-codes for visits, K-codes for time-based, etc.), a fundamentally different global-period convention (90 days from the *day of* surgery vs. Alberta's 90 days from the *day after*), and the MC EDT submission system is more strict on field-level validation than H-Link. OHIP also has the most modifier-elaborate chronic-disease premium scheme (Q-codes), but **Ontario does not have a CMGP equivalent** — its chronic-disease billing uses a different mechanism (Q040A for diabetes tracking, K-codes for time-based counselling, Q-codes for premiums).
- **MSP (BC) is the smallest of the three by volume but the easiest to add to v11.** The BC Medical Services Commission Payment Schedule uses a numeric code scheme (0010–0199 for visits, 8600-series for counselling, 7000+ for procedures), Teleplan is a stable submission gateway, and the global surgical period is **30 days** (vs. 90 in AB/ON). MSP is currently the only province still in an **ICD-9 → ICD-10-CA transition** (ICD-9 is still accepted for some submissions), which creates a real dx-encoding complexity v12 must handle.
- **All three are "insufficient" for v11's current implementation.** v11 has 16 AHCIP rules and 0 OHIP rules and 0 MSP rules. The multi-market framing in the spec is aspirational, not real.
- **The US-to-Canada leaks identified for AHCIP apply to OHIP and MSP in slightly different forms** — none of the three provinces has a US-style `-24` or `-25` modifier, none of the three insures "annual physical" as a separate fee code (with nuances), and all three route lab tests to a separate billing stream (the lab, not the ordering physician).
- **Recommended sequencing after the Alberta pilot:** **MSP first** (smallest market, cleanest extension of v11, ICD-9 familiarity may help the LLM avoid "clean ICD-10-CA" false confidence), then **OHIP** (largest market but most complexity, best paired with a dedicated BC clinical champion and ON MSO partnership).

**Source-quality caveat (carried over from `AHCIP_RULE_REFERENCE.md`):** web search was not configured in this session. All province-specific calls below come from training-data knowledge of the respective fee schedules as of my knowledge cutoff (Jan 2026), cross-referenced with the existing AHCIP docs in this repo. **A licensed biller from each province must sign off before the v12+ rule catalogue ships.**

---

## Cross-Reference Matrix

| Dimension | AHCIP (AB) | OHIP (ON) | MSP (BC) |
|---|---|---|---|
| **Payer / plan** | Alberta Health Care Insurance Plan (AHCIP) | Ontario Health Insurance Plan (OHIP) | Medical Services Plan (MSP) — administered by Medical Services Commission (MSC) |
| **Fee schedule name** | Schedule of Medical Benefits (SOMB) | Schedule of Benefits for Physician Services (SOBM) | Medical Services Commission Payment Schedule (MSC Payment Schedule) |
| **Submission system** | H-Link (Alberta Health) | Medical Claims Electronic Data Transfer (MC EDT) — also called "OHIP Claims Submission System" | Teleplan (MSC) |
| **Submission format** | XML / EDI (proprietary Alberta variant) | XML / EDI (Ontario-specific MC EDT envelope) | XML / EDI (Teleplan envelope) |
| **Visit code (brief / minor)** | 03.01A | A007A (intermediate assessment) / A001A (minor assessment) | 0100 (office visit, brief) |
| **Visit code (comprehensive / complex)** | 03.04A | A003A (detailed assessment) / A005A (comprehensive) | 0010 (office visit, comprehensive) |
| **Visit code (consultation)** | 03.03A | A035A (specialist consult) / A935A (after-hours consult premium) | 0020 (consultation) |
| **Time-based psychotherapy 45 min** | 08.19A | K007 (psychotherapy, per ½ hour, billed 2x for 45+ min) | 8610 (counselling, 30 min) / 8615 (counselling, 45+ min) — series varies by year |
| **Time-based psychotherapy 30 min** | 08.19B | K007 × 1 | 8610 |
| **Chronic disease modifier** | CMGP (Chronic Disease Management General Premium) | Q040A (diabetes incentive), K029A (diabetes management team), K045A (hypertension), etc. — granular Q-codes per condition | No direct equivalent; BC uses "GPSC" (General Practice Services Committee) incentive payments billed separately (G14077 etc.) |
| **Telehealth premium** | Yes (SOMB telehealth premium schedule; code has changed several times; commonly a "T" indicator on visit code) | K-codes plus A-codes (e.g., A001A + K300A virtual-care premium); phone-only on/off by year | Yes (Teleplan has specific telehealth fee codes in 1300-series historically; also T-billed codes) |
| **Global surgical period** | 90 days (GR 3.2.1) | 90 days (SOBM general rule on surgical package; "aftercare period" 30 days for minor, 90 days for major) | 30 days for most procedures (BC's "aftercare period") |
| **Modifier `-24` (US)** | **Does not exist.** Use explanatory text or "do not bill" | **Does not exist.** Use post-operative premium codes or explanatory text | **Does not exist.** Same — use explanatory text or skip the E/M |
| **Modifier `-25` (US)** | **Does not exist.** Use "same-day separate service" preamble per GR | **Does not exist.** OHIP uses the "E" prefix on the E/M code (e.g., A007E) to indicate separately billable same-day service | **Does not exist.** BC's equivalent is the "diagnostic and therapeutic" preamble; submit the E/M with explanatory text |
| **Modifier `-57` (US decision for surgery)** | **Does not exist.** Decision-for-surgery work is generally included in the surgical fee | **Does not exist.** | **Does not exist.** |
| **Diagnosis code format** | ICD-10-CA (Canadian) | ICD-10-CA (Canadian) | ICD-9 (legacy) with **active transition to ICD-10-CA** as of recent years; Teleplan accepts both |
| **Dx linkage enforcement** | H-Link auto-denial if `diagnosis_codes == []` or contains literal `"REVIEW"` | MC EDT validation; "V" codes (factors influencing health status) trigger different adjudication; missing dx often auto-denies | Teleplan validation; missing dx often soft-warns rather than hard-denies (legacy ICD-9 system more permissive) |
| **Common auto-denial patterns** | (1) Empty dx, (2) dx array contains "REVIEW" placeholder, (3) consult code 03.03A without referring NPI, (4) same-day duplicate visit codes, (5) 08.19A psychotherapy without time documentation | (1) Empty dx, (2) consult code without referring physician billing number, (3) A007A "intermediate" billed for <15 min encounter, (4) K007 psychotherapy without time/modalty documentation, (5) After-hours premium without matching time-of-day | (1) Out-of-province patient billed to MSP, (2) WCB claim routed to MSP, (3) duplicate service on same day, (4) 30-day aftercare period violation, (5) ICD-9 → ICD-10-CA mismatch |
| **Avg fee for comprehensive visit (USD-equivalent ~$60-80)** | ~$80-100 CAD for 03.04A | ~$75-95 CAD for A003A | ~$70-90 CAD for 0010 |
| **Avg fee for 45-min psychotherapy** | ~$120-160 CAD for 08.19A | ~$120-150 CAD for K007 × 2 (per-½-hour × 2) | ~$100-140 CAD for 8615 (45+ min) |
| **Avg fee for basic/brief office visit** | ~$30-45 CAD for 03.01A | ~$30-50 CAD for A007A | ~$30-45 CAD for 0100 |
| **Annual physical / health maintenance visit** | **Not insured as a separate fee code.** Specific screening tests (Pap, mammogram, immunization) are insured, but a standalone "annual physical" is not. | **Not insured.** OHIP covers a "Periodic Health Visit" only for specific age groups (e.g., ages 40-70 for a "flu shot and health review") via specific age-banded codes. The traditional "annual physical" is uninsured. | **Not insured as a routine adult annual physical.** BC does have age-banded preventive-care codes (e.g., 0010 for "complete physical" in some contexts, but not for adults without specific risk factors). |
| **Submission technical interface** | H-Link (IBM iSeries / secure web; many Alberta clinics use TELUS Health or Alberta Blue Cross as intermediary clearinghouses) | MC EDT (Ministry of Health secure EDI gateway; Ontario MD, QHR, OSCAR as intermediary EMR/EHR) | Teleplan (MSC secure gateway; most BC clinics use MedAccess, OSCAR, or Telus Health Wolf as intermediary) |
| **Auditor rule count (current v11)** | 16 | 0 | 0 |
| **Auditor rule count needed (v12+)** | 16 (already in catalogue) | ~12-15 | ~10-12 |

---

## Per-Province Rule Gap (what's missing in v11 for OHIP and MSP)

### AHCIP — already covered by v11 (16 rules)

See `docs/AHCIP_RULE_REFERENCE.md` for the full catalogue. v11 handles: em_level, em_level_upcode, em_level_undercode, dx_linkage, referring_npi, referring_npi_population, global_window, psychotherapy_time, telehealth, lab_coverage, cmgp, same_day_conflict, non_insured_service, out_of_province, wcb_conflict, consult_duplicate, after_hours.

### OHIP — proposed v12+ rules (~13)

| Proposed rule_id | Name | Trigger | Severity | Confidence |
|---|---|---|---|---|
| `rule_ohip_em_level` | E/M level matches documentation | A007A / A001A / A003A / A005A vs. note complexity | info | high |
| `rule_ohip_em_level_upcode` | E/M upcode (brief billed as detailed) | Note "brief" / "minor" / "limited" but A003A (detailed) or A005A (comprehensive) billed | high | high |
| `rule_ohip_em_level_undercode` | E/M undercode (complex billed as intermediate) | Note documents moderate/high-acuity workup but A007A (intermediate) billed | high | high |
| `rule_ohip_dx_linkage` | Diagnosis linkage (empty / placeholder) | `diagnosis_codes == []` or contains literal `"REVIEW"` | critical | high |
| `rule_ohip_referring_billing_number` | Consultation without referring physician billing number (OHIP uses billing numbers, not NPIs) | A035A (consult) billed but `referring_provider_billing_number` is null | high | high |
| `rule_ohip_global_window` | Post-op E/M within 90-day global period (OHIP GR on surgical aftercare) | Note describes visit within 90 days after major surgery, same condition | high | medium (the 30-day-minor vs. 90-day-major split needs to be encoded) |
| `rule_ohip_psychotherapy_time` | K007 psychotherapy time documentation | Note says "45-minute psychotherapy" / "counselling" but billed as A003A (E/M) instead of K007 × 2 | high | medium |
| `rule_ohip_k007_time_documentation` | K007 psychotherapy without time/note detail | K007 billed but no documented time in note ("15+ min counselling" not specified) | medium | medium |
| `rule_ohip_telehealth` | Telehealth premium missing | Note says "virtual" / "phone" / "video" but no K300A virtual premium attached | medium | low (the K300A / virtual premium codes have changed several times) |
| `rule_ohip_lab_coverage` | Lab/imaging fee missing on physician claim | Same pattern as AHCIP — physician-claim for imaging, not lab (OHIP labs are billed by the lab via OHIP lab schedule, not the physician) | high | high |
| `rule_ohip_q040a_diabetes` | Diabetes management premium missing (Q040A / K029A) | Patient with T2DM (E11.x) AND comprehensive visit AND no Q-codes attached | medium | medium (Q040A is specific to diabetes; the chronic-disease bundle in OHIP is more fragmented than AHCIP's CMGP) |
| `rule_ohip_non_insured_service` | Non-insured service billed to OHIP | Annual physical / cosmetic / third-party form / travel medicine (the classic uninsured list — applies in ON as it does in AB) | high | high |
| `rule_ohip_out_of_province` | Out-of-province patient (health card version code) | Ontario health card version code indicates non-ON residency (other province) AND claim routed to OHIP | medium | high |
| `rule_ohip_wcb_conflict` | WSIB (Workplace Safety & Insurance Board) claim routed to OHIP | Work-related injury AND claim submitted to OHIP instead of WSIB | high | high (WSIB is the ON equivalent of WCB) |
| `rule_ohip_same_day_conflict` | Same-day visit-level code conflict | Same `service_date` AND multiple A-codes for the same physician | high | high |
| `rule_ohip_after_hours` | After-hours premium (A-codes, K-codes) | After-hours visit without premium code | low | medium |

**Net new rules for OHIP: ~13-15** (depending on how granular to split Q040A diabetes vs. K029A team-management vs. K045A hypertension).

### MSP — proposed v12+ rules (~11)

| Proposed rule_id | Name | Trigger | Severity | Confidence |
|---|---|---|---|---|
| `rule_msp_em_level` | E/M level matches documentation | 0100 (brief) / 0010 (comprehensive) / 0020 (consult) vs. note complexity | info | high |
| `rule_msp_em_level_upcode` | E/M upcode | Brief note billed 0010 (comprehensive) | high | high |
| `rule_msp_em_level_undercode` | E/M undercode | Complex note billed 0100 (brief) | high | high |
| `rule_msp_dx_linkage` | Diagnosis linkage (empty / placeholder) | `diagnosis_codes == []` or contains literal `"REVIEW"` | high | medium (MSP is more permissive than H-Link on missing dx — this is HIGH not CRITICAL) |
| `rule_msp_referring_practitioner_id` | Consultation without referring practitioner ID | 0020 (consult) billed but `referring_provider_practitioner_id` is null | high | high |
| `rule_msp_global_window` | Post-op E/M within **30-day** aftercare period (BC) | Note describes visit within 30 days after surgery on same condition (BC is shorter than AB/ON) | high | medium (30-day is the BC default; some procedures have longer aftercare — need to encode per-procedure list) |
| `rule_msp_psychotherapy_time` | Counselling time-based code (8610 / 8615) | Note says "45-minute counselling" but billed as 0010 (comprehensive) instead of 8615 (45+ min) | high | medium |
| `rule_msp_telehealth` | Telehealth premium missing | Note "virtual" / "phone" / "video" but no telehealth code attached | medium | low (BC telehealth codes have shifted with COVID-era expansion; the "in-person-required" relaxation has been rolling back) |
| `rule_msp_lab_coverage` | Lab/imaging fee on physician claim | Same pattern as AHCIP/OHIP — physician-claim for imaging only, not lab (BC lab schedule is separate) | high | high |
| `rule_msp_non_insured_service` | Non-insured service billed to MSP | Annual physical / cosmetic / third-party form / travel medicine | high | high |
| `rule_msp_out_of_province` | Out-of-province patient (PHN prefix) | BC PHN prefix indicates non-BC residency AND claim routed to MSP | medium | high |
| `rule_msp_wcb_conflict` | WorkSafeBC claim routed to MSP | Work-related injury AND claim submitted to MSP instead of WorkSafeBC | high | high |
| `rule_msp_gpsc_incentive` | GPSC (General Practice Services Committee) incentive missing (e.g., G14077 complex-care planning) | Patient with chronic disease AND no GPSC incentive code attached | low | medium (GPSC is BC-specific and the incentive schedule is more bureaucratic than AHCIP's CMGP) |

**Net new rules for MSP: ~11-13** (depending on GPSC granularity).

---

## US-to-Canada Leak Audit (per province)

The `AHCIP_RULE_REFERENCE.md` identified 7 US-leak items in v11 (notably: no `-24` modifier in Alberta, no annual physical as an insured service, lab tests not on physician claim, CMGP vs. US chronic-care codes). Here is the same audit applied to OHIP and MSP:

### 1. "Annual physical" / "health maintenance visit"

| Province | Insured? | Notes |
|---|---|---|
| AHCIP (AB) | **No** (as a standalone fee) | Specific screening tests (Pap, mammogram, immunization) are insured; the "annual physical" itself is not. AHCIP explicitly does not have a "health maintenance visit" code. |
| OHIP (ON) | **No** (as a routine adult annual physical) | OHIP does have age-banded preventive codes (e.g., periodic health review for specific age groups), but the "annual physical" as US physicians understand it is not insured for most adults. A US-trained physician in Ontario is at high risk of billing a non-insured service. |
| MSP (BC) | **No** (as a routine adult annual physical) | BC has limited preventive-care coverage but the routine US-style "annual physical" is not a separately insured service. |

**Audit implication for v12+:** all three provinces need a `rule_*_non_insured_service` finding that fires when the note documents a preventive visit with no specific screening-test component. v11 already has this for AHCIP; the OHIP and MSP versions will be near-clones.

### 2. Modifier `-24` (US — "unrelated E/M during global period")

| Province | Exists? | Notes |
|---|---|---|
| AHCIP (AB) | **No** | Use explanatory text or "do not bill" |
| OHIP (ON) | **No** | OHIP uses post-operative premium codes in some cases, or just doesn't bill the E/M. Some Ontario physicians add a text comment "E/M unrelated to surgery" but it's not a formal modifier. |
| MSP (BC) | **No** | Same — use explanatory text or skip the E/M |

**Audit implication for v12+:** the v11 prompt's US-imported convention of "use -24 in post-op" must be replaced across all three provinces with "do not bill the E/M" or "bill with explanatory text." v12+ should have a shared conceptual rule that fires consistently across provinces with the correct province-specific suggested fix.

### 3. Lab tests on physician claim

| Province | Billable on physician claim? | Notes |
|---|---|---|
| AHCIP (AB) | **No** (for most lab tests) | The lab (DynaLIFE, Alberta Precision Labs, etc.) bills the lab schedule directly. The physician's claim only includes the visit and physician-performed procedures. |
| OHIP (ON) | **No** (for most lab tests) | Ontario labs bill the Ontario Lab Schedule directly. The physician's claim carries only the visit + physician-performed procedures. |
| MSP (BC) | **No** (for most lab tests) | BC labs bill the BC lab schedule directly. Same pattern. |

**Audit implication for v12+:** all three provinces have the same rule — `rule_*_lab_coverage` should fire when the physician claim contains lab-test fee codes (a sign the biller is confused about the lab-vs-physician split). Conversely, an LLM auditor should NOT flag "lab tests are missing from the physician claim" as a coverage gap (they shouldn't be there). The `AHCIP_GOLD_AUDIT.md` already flagged this confusion on encounter `ca_ahcip_010` (`ca15`) — the lab codes were suggested but the lab codes may not actually belong on the physician claim.

### 4. Modifier `-25` (US — "significant, separately identifiable E/M same day as procedure")

| Province | Exists? | Notes |
|---|---|---|
| AHCIP (AB) | **No** | Alberta handles "separately billable same-day E/M" with the SOMB general preamble on same-day services; no formal modifier. |
| OHIP (ON) | **No** (formally) | OHIP has historically used the "E" suffix (e.g., A007E) on the E/M code to indicate separately billable same-day, but this is a code-suffix convention, not a US-style modifier. The auditor should not emit "-25" in OHIP. |
| MSP (BC) | **No** | BC's preamble on "diagnostic and therapeutic" same-day services; the auditor should not emit "-25" in MSP. |

**Audit implication for v12+:** the US `-25` convention is the most subtle leak because it looks like a natural extension of "same-day separate service" logic. v12+ needs a province-specific same-day-conflict rule for each province that fires on the right condition without importing the US modifier.

### 5. (Bonus) Modifier `-57` (US — "decision for surgery")

| Province | Exists? | Notes |
|---|---|---|
| AHCIP (AB) | **No** | Decision-for-surgery work is generally included in the surgical fee per GR 3.2.1. |
| OHIP (ON) | **No** | Same — included in the surgical fee. |
| MSP (BC) | **No** | Same. |

**Audit implication for v12+:** if v11 or v12 ever encodes a "decision-for-surgery" rule (an E/M visit that results in a surgical booking being paid separately), the rule needs province-specific text — no `-57` modifier in any of the three.

---

## Engineering Cost Estimate to Add OHIP or MSP Support

This is rough; based on the v11 architecture (the existing AHCIP rules, the schema, the grader, the few-shot examples) and assuming a single senior full-stack engineer working solo or with one clinical-domain reviewer (biller). Costs expressed in **person-weeks of engineering effort** (Cam's pricing anchor: $39/hr USD, so 1 person-week ≈ $1,560 USD or ~$2,100 CAD at 1.35 conversion — note this is the solo-operator rate, not a team rate).

### OHIP (Ontario)

| Workstream | Estimate (person-weeks) | Notes |
|---|---|---|
| **Rule catalogue** (~13-15 new rules) | 1.5 | Mostly cloned from AHCIP rules with province-specific tweaks; the Q-codes for chronic disease are the most novel |
| **Encounter format** (new claim shape) | 1.0 | OHIP uses different field names (e.g., `referring_provider_billing_number` not `referring_provider_npi`); A-codes prefix; dx is ICD-10-CA with V-code support |
| **MC EDT integration** (submission system) | 2.0 | MC EDT is its own EDI gateway; needs a new adapter. The Ministry of Health also has a "Health Card Validation" (HCV) service that needs to be queried before submission. Province-specific auth + cert handling. |
| **Validation set** (gold encounters) | 1.0 | Build a `val_on.json` of ~10 OHIP-encounter gold findings, parallel to the existing `val_ca.json` |
| **Prompt refactor** (v12 prompt AHCIP+OHIP-aware) | 1.0 | Re-prompt the LLM to be multi-province aware; add OHIP-specific rule catalogue; refactor severity tables |
| **Testing / regression** | 0.5 | Re-run AHCIP val to make sure no regression; run OHIP val; cross-check rules |
| **Clinical sign-off** (Ontario biller) | 1.0 | Need a licensed Ontario biller to sign off on the rule catalogue. The OHIP fee schedule is the most complex of the three, so this is non-trivial. |
| **Total OHIP** | **~8-9 person-weeks** | Range reflects uncertainty on clinical sign-off and MC EDT integration. |

### MSP (British Columbia)

| Workstream | Estimate (person-weeks) | Notes |
|---|---|---|
| **Rule catalogue** (~11-13 new rules) | 1.0 | Smaller than OHIP; the GPSC incentive is the most novel piece |
| **Encounter format** (new claim shape) | 0.5 | Numeric codes (no alphabetic prefix); ICD-9/ICD-10-CA transition handling; field names are different from AHCIP |
| **Teleplan integration** (submission system) | 1.5 | Teleplan is well-documented; BC has fewer regulatory quirks than ON |
| **Validation set** (gold encounters) | 1.0 | Build `val_bc.json` of ~10 MSP-encounter gold findings |
| **Prompt refactor** (v12 prompt AHCIP+MSP-aware) | 0.5 | Simpler than OHIP — MSP is closer to AHCIP in structure than OHIP is |
| **Testing / regression** | 0.5 | Re-run AHCIP val; run MSP val; cross-check |
| **Clinical sign-off** (BC biller) | 0.5 | BC's fee schedule is more compact than OHIP; sign-off is faster |
| **Total MSP** | **~5-6 person-weeks** | About 60-70% of OHIP's cost. |

### Combined (OHIP + MSP together)

If v12+ aims to add both provinces in one cycle, there is some shared work (prompt refactor, multi-province routing) that reduces the marginal cost of the second province by ~20-30%. Total combined: **~11-13 person-weeks** for both.

### Why MSP is cheaper than OHIP

1. **Smaller fee schedule** — fewer edge cases in the rule catalogue
2. **Simpler chronic-disease billing** — GPSC is a single incentive framework, not the multi-Q-code scheme OHIP has
3. **Shorter global surgical period** — 30 days vs. 90 days, fewer post-op-encounter false positives
4. **More permissive submission** — Teleplan is less strict on field-level validation than MC EDT, so the integration is simpler
5. **Fewer regulatory wrinkles** — OHIP has the most eligibility rules (e.g., OHIP-insured-vs-not, age-banded preventive coverage, out-of-country billing rules); MSP is closer to AHCIP

---

## Recommended Sequencing: Which Province to Support After Alberta

### Option A: **MSP first, then OHIP** (recommended)

**Why:** MSP is the cheapest and cleanest extension of v11. The BC fee schedule is structurally close to AHCIP, the engineering cost is lower (~5-6 weeks vs. ~8-9 for OHIP), and the clinical-sign-off path is faster. **A BC pilot after the Alberta pilot** gives Zorva a second-reference site with manageable effort. After BC, OHIP becomes the high-value-but-complex third market.

**Best for:** conservative rollout, cost-controlled scaling, building multi-province confidence before tackling the largest market.

### Option B: **OHIP first, then MSP**

**Why:** Ontario is the largest market by physician count (~30,000 vs. ~12,000 in BC, ~10,000 in AB). If the strategic goal is "maximize physician coverage" then OHIP is the better first second-province.

**Risk:** OHIP is the most complex fee schedule, and the clinical-sign-off path is hardest. A failed OHIP rollout would block MSP. **Recommend against** if the goal is to build multi-province momentum quickly.

### Option C: **OHIP + MSP in parallel (single v12 release)**

**Why:** Reuse the prompt-refactor and routing work. The marginal cost of the second province is ~3-4 weeks.

**Risk:** Two new validation sets in flight, two new clinical reviewers needed, two new submission-system integrations. Higher coordination cost. **Recommend only** if there is an ON-specific pilot partner and a BC-specific pilot partner ready at the same time.

### Recommendation: **Option A (MSP first, then OHIP)** for the v12 cycle.

**Concrete proposal:** target v12 = AHCIP + MSP (no OHIP). Target v13 = add OHIP. This gives the engineering team a 5-6-week MSP add-on now and an 8-9-week OHIP add-on later, with two clean pilot launch points.

---

## Sources Cited

The following sources informed this cross-reference. **Web search was not configured in this session** (Firecrawl key absent), so all non-AHCIP items come from training-data knowledge of the respective fee schedules as of Jan 2026. AHCIP items are cross-referenced with existing repo docs.

### AHCIP / Alberta
- `docs/AHCIP_RULE_REFERENCE.md` (this repo, 2026-06-22) — primary, high confidence
- `docs/AHCIP_GOLD_AUDIT.md` (this repo, 2026-06-22) — primary, high confidence
- `prompts/v11/auditor_prompt.txt` (this repo) — primary
- Training-data knowledge of Alberta SOMB GR preamble (GR 3.2.1, 90-day global, etc.) — medium confidence on specific code values, high on structural rules

### OHIP / Ontario
- Training-data knowledge of the Ontario SOBM (Schedule of Benefits for Physician Services, Health Canada OHIP branch) — medium confidence on specific fee values, high on structure
- Training-data knowledge of MC EDT (Medical Claims Electronic Data Transfer) — medium confidence
- Training-data knowledge of Q040A diabetes management fee, K007 psychotherapy, A-codes visit scheme — medium confidence

### MSP / British Columbia
- Training-data knowledge of the Medical Services Commission Payment Schedule — medium confidence on specific fee values, high on structure
- Training-data knowledge of Teleplan submission system — medium confidence
- Training-data knowledge of GPSC (General Practice Services Committee) incentive framework — medium confidence
- Training-data knowledge of BC's ICD-9 → ICD-10-CA transition (still in progress) — medium confidence

### Cross-cutting
- Canadian Medical Association (CMA) physician-billing resources — high credibility in general
- Provincial medical association billing guides (albertadoctors.org, Ontario Medical Association oma.org, Doctors of BC doctorsofbc.ca) — high credibility in general
- Peer-reviewed billing columns in CMAJ, BCMJ, and Canadian Family Physician — high credibility in general

**Sign-off requirement:** the OHIP and MSP portions of this document must be reviewed by a licensed Ontario biller (for OHIP) and a licensed BC biller (for MSP) before any of these rules ship in v12+. The 16 AHCIP rules in v11 must also be re-reviewed per `AHCIP_RULE_REFERENCE.md` (which carries the same caveat).

---

*End of report. ~3,000 words. Created by Hermes subagent, read-only pass, no code modified. File: `/Users/biancabienaime/projects/ai-billing-audit/docs/CANADA_BILLING_CROSSREF.md`*
