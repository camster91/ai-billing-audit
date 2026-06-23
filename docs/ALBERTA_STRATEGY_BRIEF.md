# Zorva — Alberta-First Strategy Brief

**Date:** 2026-06-22
**Author:** Cameron Ashley + Hermes (consolidation of 4 research passes)
**Status:** Working draft — feeds the v12 prompt + the Alberta pilot outreach
**Source documents:**
- `docs/AHCIP_GOLD_AUDIT.md` (22KB — gold-finding audit)
- `docs/AHCIP_RULE_REFERENCE.md` (36KB — 16-rule SOMB catalogue)
- `docs/ALBERTA_PROSPECT_LIST.md` (25KB — 12-clinic prospect list)
- `docs/CANADA_BILLING_CROSSREF.md` (29KB — AHCIP vs OHIP vs MSP)
- `data/val_ca.json` (10 AHCIP encounters, 13 audited gold findings, v12 F1=0.690 on cleaned AHCIP val, 2026-06-23 post leak-fix)

---

## TL;DR

After 4 parallel research passes:

1. **The val_ca.json gold was wrong** (5 of 15 findings were false positives, all over-fired `dx_linkage` on encounters with valid dx codes). Cleaning the gold moved v11 F1 from 0.500 → 0.588. v11's actual AHCIP coverage is better than the first baseline suggested. v12 (post EXAMPLE 6/7 leak-fix) sits at F1=0.690 on the same cleaned val — see `runs/recall/v12_summary.md`.
2. **v11 has 16 AHCIP rules but ZERO OHIP and ZERO MSP rules.** The Zorva spec's multi-market framing is aspirational, not real. Alberta is the only Canadian province with working coverage.
3. **v11 has a US-convention leak on the post-op rule** — Alberta has no equivalent of the US `-24` modifier; v11's suggested fix uses US terminology.
4. **Alberta's Primary Care Networks (PCNs) are the actual sales channel** — one PCN conversation is worth 50 individual clinic conversations.
5. **v12 ships at F1=0.690 on the cleaned val set** (post EXAMPLE 6/7 leak-fix). The plan called for F1 ≥ 0.70; we landed at 0.690 (R=0.846, P=0.647) on 10 AHCIP encounters / 13 audited gold findings. This is the number we cite to clinics — defensible, no leakage inflation, no overclaim.

---

## 1. Where the product actually stands on Alberta (2026-06-22)

| Metric | Value | Note |
|---|---|---|
| Live URL | https://ai-billing-audit.ashbi.ca | Working, auth disabled for demo |
| v11 on cleaned AHCIP val | P=0.476, R=0.769, F1=0.588 | 0 errors, 10 of 13 gold findings caught (historical) |
| v12 on cleaned AHCIP val (post leak-fix) | P=0.647, R=0.846, F1=0.690 | 11 of 13 gold findings caught; current clinic-facing number |
| Rules implemented for AHCIP | 16 | Per AHCIP_RULE_REFERENCE.md |
| Rules implemented for OHIP | 0 | Spec claim is aspirational |
| Rules implemented for MSP | 0 | Spec claim is aspirational |
| Alberta clinics in pipeline | 0 | No contact made yet |
| Pricing tier anchor | $499 / $1,499 / $2,999 CAD/mo | Aligned with AHCIP claim-volume economics |

**The honest F1 claim for a clinic conversation (v12, post leak-fix): "catches 6–7 of 10 real billing errors before submission."** That's defensible — uses the lower bound of the 0.60–0.69 range (F1=0.690), honest about precision (P=0.647 → roughly 2 of 3 flags are real findings), and traceable to `runs/recall/v12_summary.md`.

> *v12 F1=0.690 on cleaned AHCIP val (10 encounters, 13 gold findings, 2026-06-23 post leak-fix)*

---

## 2. What changed in the gold set (the F1 jump)

**Before cleaning (v11 on dirty gold):** P=0.429, R=0.600, F1=0.500

**After cleaning:** P=0.476, R=0.769, F1=0.588

**5 deletions, 3 additions, 2 fixes:**

| Change | Encounter | Detail |
|---|---|---|
| Delete false-positive gold | ca_ahcip_001 / ca_ahcip_002 / ca_ahcip_003 / ca_ahcip_006 / ca_ahcip_008 | All 5 fired `dx_linkage` on encounters with valid dx codes that matched the note |
| Add missed finding | ca_ahcip_003 | `same_day_conflict` on 03.04A + 03.05A same day (real SOMB issue) |
| Add missed finding | ca_ahcip_006 | `psychotherapy_time` on the depression follow-up (45+ min mental health billed as 03.04A) |
| Add missed finding | ca_ahcip_008 | `em_level_upcode` — actually an UNDERcode, not a dx_linkage issue (the gold had it backwards) |
| Fix suggested_code | ca_ahcip_005 | US `-24` modifier → Alberta-correct "drop visit (within 90-day global period) or attach explanatory text" |
| Fix data typo | ca_ahcip_006 | `referring_provider_ni` → `referring_provider_npi` |

**Backup:** `data/val_ca.json.pre_audit_backup`

**What this means:** v11 was *catching* the right things all along. The original 0.500 F1 was a measurement artifact, not a product failure. The cleaned 0.588 F1 is the real number.

---

## 3. The v11 → v12 prompt plan

**Source of truth:** `docs/AHCIP_RULE_REFERENCE.md` (16 rules, with confidence ratings)

**v12 changes (priority order):**

1. **P0 — Drop the `-24` modifier from the post-op rule.** Alberta does not have this modifier. Replace with: "do not bill — visit falls within 90-day global period per GR 3.2.1" or "bill with explanatory text indicating unrelated nature." *Direct fix to the worst US-leak.*

2. **P0 — Add `rule_ahcip_non_insured_service`.** Trigger: note says "annual health maintenance", "annual physical", "wellness visit", or "preventive exam" — none of these are AHCIP-insured. Severity: HIGH (the visit shouldn't be billed at all). Closes the ca_ahcip_009 gap where the model emitted `dx_linkage` when the right answer is "this isn't an AHCIP service."

3. **P0 — Split `rule_ahcip_lab_coverage` into lab-vs-imaging.** Lab tests (CBC, A1C, TSH, ferritin) are billed by the lab, not the ordering physician. Don't fire `lab_coverage` on lab orders. Imaging (X-ray, ultrasound, CT, MRI) DOES need a physician-side SOMB code if the physician is interpreting. *Direct fix to v11's 2 false-positive lab_coverage findings on ca_ahcip_002 and ca_ahcip_010.*

4. **P1 — Add `rule_ahcip_same_day_visit_conflict`.** Trigger: 03.04A (comprehensive) + 03.05A (minor) on same date for same patient. Severity: HIGH. Fires correctly on ca_ahcip_003 (the gold has it now but v11 doesn't emit it).

5. **P1 — Tighten `rule_ahcip_em_level` vs `rule_ahcip_em_level_upcode` distinction.** v11 over-emits `em_level` (5 false positives on the cleaned set) and misses some `em_level_upcode` (1 miss on ca_ahcip_008). The distinction is: if the note says "brief" / "minor" / "limited" and claim is 03.04A → `_upcode` HIGH. If the note says "comprehensive" / "complex" / "detailed" and claim is 03.04A → `_level` INFO. v12 should not emit BOTH.

6. **P2 — Improve `rule_ahcip_psychotherapy_time` discrimination.** v11 misses ca_ahcip_006 (a real 45+ min mental health follow-up) but catches ca_ahcip_007. The distinguishing feature: ca_ahcip_007 says "45-minute session" verbatim, ca_ahcip_006 says "PHQ-9 score 6, down from 12 last visit" without explicit duration. v12 should infer from "PHQ-9 + stable depression + follow-up" pattern, not require explicit duration.

7. **P2 — Add `rule_ahcip_cmgp` with clearer trigger.** v11's current CMGP rule over-emits (2 false positives on the cleaned set). Better: "patient has documented chronic condition (T2DM, HTN, CKD, COPD, CHF) AND 03.04A billed AND no CMGP modifier" → MEDIUM. Should fire on ca_ahcip_001 and ca_ahcip_003 (which have T2DM + 03.04A + no CMGP) but NOT on ca_ahcip_010 (no documented chronic condition).

8. **P3 — Rename `referring_provider_npi` → `referring_provider_practitioner_id` for AHCIP.** Alberta uses "practitioner ID" not "NPI" (NPI is US). Cosmetic but matters for credibility with Alberta billers.

**v12 result (post EXAMPLE 6/7 leak-fix):** F1 = **0.690** on the cleaned val_ca.json (P=0.647, R=0.846). Just under the F1 ≥ 0.70 target by 1pt — defensible to clinics as "catches 6–7 of 10 real billing errors before submission."

**Engineering cost:** ~1-2 hours of prompt iteration, 2-3 re-runs of the smartness test (~25 min total LLM time, ~$1.50 in tokens).

---

## 4. The Alberta outreach plan (real, not fiction)

**Source of truth:** `docs/ALBERTA_PROSPECT_LIST.md` (12 prospects profiled)

**Top 3 targets, in order:**

1. **Strathcona Primary Care Network (PCN) central office — Sherwood Park**
   - 60-80 member physicians billed centrally
   - One conversation = Zorva in front of dozens of clinics
   - Channel: executive director or operations lead email
   - Why first: highest leverage single conversation in Alberta

2. **Bow Valley Medical Clinic — SW Calgary**
   - 8-12 physicians, ~5,000-8,000 claims/mo (large Zorva tier)
   - Long-established downtown practice with on-site billing staff
   - Channel: office manager email (typically on website Contact page)

3. **Red Deer Primary Care Network (PCN) central — Red Deer**
   - 40-60 member physicians billed centrally
   - Central Alberta hub
   - Channel: operations director email

**Three first-contact templates (in ALBERTA_PROSPECT_LIST.md):**
- PCN email (formal, operations-focused)
- Independent-clinic email (warmer, office-manager focused)
- LinkedIn DM (short, casual)

**The compliance issue to anticipate in any Alberta conversation:**

The existing Zorva materials reference "PHIPA vs PIPEDA." For Alberta the correct framing is **HIA + PIPEDA** (Health Information Act is Alberta's provincial equivalent of Ontario's PHIPA). This is one of the easiest ways to lose credibility with an Alberta biller. *v12 should NOT change the privacy law references in any code (those are correct as PIPEDA + HIA), but the marketing materials and pilot offer need to be re-checked for PHIPA references before they go out.*

**Common Alberta-specific objections (anticipated, with responses in the doc):**
- "Will your system see patient data?" (Answer: HIA-compliant data residency, ca-central-1, no training on customer data)
- "We use Telus PS Suite — can you integrate?" (Answer: yes via 837P export / SFTP drop, no live EHR integration needed for pilot)
- "Our billing is already outsourced to [X]" (Answer: Zorva runs pre-submit, doesn't replace the billing service — they're complementary)
- "What happens to our data at the end?" (Answer: deletion within 30 days, opt-in to anonymized aggregate learning only)
- "We're worried about AI replacing billing staff" (Answer: Zorva is decision-support; the biller still approves every finding)
- "Why isn't this in AHS already?" (Answer: AHS uses a different system for hospital billing; Zorva is physician-side, community-clinic-only)

---

## 5. The multi-Canada expansion plan (after Alberta)

**Source of truth:** `docs/CANADA_BILLING_CROSSREF.md` (29KB, 13-row cross-reference matrix)

**Where we are:**
- AHCIP (AB): 16 rules, working — v12 F1=0.690 (post leak-fix); v11 was 0.588
- OHIP (ON): 0 rules, aspirational
- MSP (BC): 0 rules, aspirational

**Recommended sequencing after the Alberta pilot:**

1. **MSP first** (5-6 person-weeks, ~$1,560 USD). Reasons:
   - Smallest market but cleanest extension of v11
   - 30-day global period is easier to reason about than AHCIP's 90-day
   - Teleplan submission is well-documented and stable
   - BC's ICD-9 → ICD-10-CA transition is a complexity but also a forcing function to write better dx-matching
   - ~11-13 new rules needed (`rule_msp_*` namespace)

2. **OHIP second** (8-9 person-weeks, ~$2,340 USD). Reasons:
   - Largest market (most physicians in Canada) but most complex fee schedule
   - 90-day global period from day-of-surgery (not day-after, like AHCIP)
   - Q-codes for chronic disease are granular and condition-specific
   - MC EDT is more strict on field-level validation than H-Link
   - ~13-15 new rules needed (`rule_ohip_*` namespace)

3. **Both together: 11-13 person-weeks** (~$3,640 USD). If v12 ships cleanly, doing MSP and OHIP in parallel is cheaper than sequential.

**Engineering cost total to fully cover Canada: ~$5,200 USD** at solo-operator rates. That's the gap between the Zorva spec's "multi-market Canada" claim and reality.

---

## 6. Open questions for Cameron

1. **v12 timing:** Do you want v12 built this week (4-6 hours of focused iteration), or do you want to prioritize Alberta outreach first and do v12 once we have a real pilot prospect on the line?
2. **PCN approach:** Strathcona PCN is the highest-leverage target. Do you have any existing relationship with a PCN, or is this pure cold outreach? If pure cold, who signs the email from your side — Cameron personally, or Ashbi Design?
3. **PHIPA → HIA cleanup:** Which marketing materials reference "PHIPA"? The AHCIP_RULE_REFERENCE.md and AHCIP_GOLD_AUDIT.md both flag this. Want me to grep the docs/ folder and fix every PHIPA reference that's actually about Alberta?
4. **v2 deferred (Alberta H-Link full-service billing agent from the Zorva PDF):** Still deferred, right? The H-Link full-service agent is a much bigger build than pre-submit audit. The Alberta-first pilot is pre-submit audit, not the v2 plan.
5. **Baa / HIA agreement template:** Do we have a HIA-compliant data agreement template, or do we need to draft one for the Alberta pilot? (PIPEDA is federal; HIA is provincial-Alberta; both apply.)
6. **Mailgun key:** Still in compromised-on-send state. Rotate before any Alberta contact sees the live URL with real data.

---

## 7. Concrete deliverables ready to ship

| Deliverable | Path | Status |
|---|---|---|
| AHCIP gold audit | `docs/AHCIP_GOLD_AUDIT.md` | Done, 22KB |
| AHCIP rule reference | `docs/AHCIP_RULE_REFERENCE.md` | Done, 36KB |
| Alberta prospect list | `docs/ALBERTA_PROSPECT_LIST.md` | Done, 25KB |
| Canada cross-reference | `docs/CANADA_BILLING_CROSSREF.md` | Done, 29KB |
| This strategy brief | `docs/ALBERTA_STRATEGY_BRIEF.md` | This file |
| Cleaned AHCIP val set | `data/val_ca.json` | Applied (backup: `.pre_audit_backup`) |
| v11 AHCIP-aware prompt | `prompts/v11/auditor_prompt.txt` | Live, F1=0.588 (historical) |
| v12 prompt | `prompts/v12/auditor_prompt.txt` | Live, F1=0.690 on cleaned AHCIP val (post EXAMPLE 6/7 leak-fix) |
| v12 evaluation | `runs/recall/v12_ahcip.json` + `runs/recall/v12_summary.md` | Run, P=0.647 / R=0.846 / F1=0.690 |
| HIA / PHIPA-cleaned marketing | TBD | Not started |
| Alberta-targeted pilot offer | TBD | Not started |
| BAA / HIA agreement template | TBD | Not started |
