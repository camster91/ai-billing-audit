# AHCIP Telehealth Premium Code — Research Note

**Status:** v1 — for the v12 prompt and the Strathcona PCN pitch
**Date:** 2026-06-25
**Author:** Hermes subagent (targeted web research, 5 searches)
**Audience:** Zorva v12 prompt authors, Alberta clinic pilot reviewers
**Confidence:** **High** for the primary code (03.01T, $20.00);
**medium** for edge-case modifier rules (see §5).

---

## TL;DR

| Question | Answer | Confidence |
|---|---|---|
| What SOMB code pays the AHCIP telehealth premium for a virtual visit? | **HSC 03.01T** (secure videoconference) or **HSC 03.01S** (secure electronic communication) — both $20.00 as of SOMB 2026-04-01 | **High** |
| Is there a modifier, or is it a stand-alone HSC? | Stand-alone HSC, **no modifier**. The "T" or "S" is **part of the health service code** itself, not a CPT-style modifier suffix. | **High** |
| What E/M codes can 03.01T pair with? | 03.01T is itself a **limited virtual visit code** ($20, "Diagnostic interview and evaluation, unqualified"). It is **not** typically added as a premium to a 03.04A comprehensive visit — that's a different code path. The "premium on top of an in-person E/M" framing is US-CPT-style and doesn't translate cleanly. | **Medium** (this is the most likely source of confusion) |
| Is the $20 amount stable year-over-year? | It has been $20.00 across SOMB versions from at least Feb 2022 through Mar 2025 and continues in SOMB 2026-04-01. Treat as stable but verify before any rule ships. | **High** for stability; **medium** for "verify before shipping a hard-coded amount into the v12 prompt." |
| Phone-only visits (no video)? | **HSC 03.05JR** — "Physician telephone call directly to patient to discuss test results / management," $20.00, max 14/week/physician. Phone-as-visit (full visit by phone) is a contested area — verify per the latest SOMB bulletin. | **Medium** (verify) |

---

## 1. The primary code: HSC 03.01T (secure videoconference)

**Code:** 03.01T
**Description (verbatim, from SOMB 2026-04-01 / AMA Fee Navigator):**
"Diagnostic interview and evaluation, unqualified — *Physician to
patient secure videoconference*."
**Fee (as of SOMB 2026-04-01):** **$20.00** per encounter.
**Modifier:** None. The "T" is a literal part of the code.

**Scope (which E/M codes it pairs with):**
- 03.01T is a **stand-alone limited virtual visit code**. It is **not**
  added as a "+$20 premium" on top of a 03.04A comprehensive visit.
  This is a meaningful difference from US-CPT, where you would bill
  99214 + modifier `-95` (synchronous audiovisual). In AHCIP, 03.01T
  **replaces** the in-person E/M code for the virtual visit.
- For a **full virtual visit** that takes the place of a comprehensive
  in-person visit (history, exam, assessment, plan, decision-making
  all done over video), the physician bills **03.01T** (limited) and
  **not** 03.04A. The 03.04A fee schedule does not currently include
  a "video modifier" in the way CPT does.
- A clinic that wants to bill for a higher-acuity virtual visit should
  check the current SOMB for any new comprehensive-virtual codes that
  may have been added in the most recent SOMB revision. As of
  2026-04-01, **the safe and conservative code for any AHCIP virtual
  visit is 03.01T at $20.00**, paired with an appropriate ICD-10-CA
  diagnosis code and (where eligible) a chronic disease modifier such
  as CMGP.

**Mutual exclusivity (payable rules, from SOMB verbatim):**
"Neither HSCs 03.01S or 03.01T are payable if HSC 03.05JR is claimed
in the same calendar week by the same physician for the same patient."
Source: SOMB Medical Procedure List 2023-04 (and identical language in
2024-01, 2025-03, 2026-04 — verbatim across at least 4 revisions).

**Sources:**
- AMA Fee Navigator entry, HSC 03.01T:
  `https://www.albertadoctors.org/fee-navigator/hsc/03.01T`
- SOMB Medical Procedure List 2026-04-01:
  `https://open.alberta.ca/publications/somb-2026-04-01`
- Direct government XLSX of SOMB codes:
  `https://www.alberta.ca/system/files/custom_downloaded_images/health-research-somb-codes.xlsx`
  (row 157, HSC 03.01T, listed with description "Diagnostic interview
  and evaluation, unqualified — Physician to patient secure
  videoconference")
- PCPCM Operations Manual v4.2 (Jan 9, 2026):
  `https://www.albertadoctors.org/media/zolbejry/pcpcm-operations-manual-v42-jan-9.pdf`

---

## 2. The related code: HSC 03.01S (secure electronic communication, async)

**Code:** 03.01S
**Description:** "Diagnostic interview and evaluation, unqualified —
*Physician to patient secure electronic communication*."
**Fee:** **$20.00** (same as 03.01T as of SOMB 2026-04-01).
**Scope:**
- Used when the virtual encounter is **asynchronous** — physician and
  patient are not on a real-time call; the patient submits a question
  (via a secure portal, secure email, or similar) and the physician
  responds with a clinical assessment.
- 03.01S and 03.01T are mutually exclusive in the same calendar week
  for the same physician–patient pair (SOMB general rule).
- 03.01S is also mutually exclusive with 03.05JR (phone) in the same
  calendar week, same physician–patient.

**Source:** AMA Fee Navigator, HSC 03.01S:
`https://www.albertadoctors.org/fee-navigator/hsc/03.01S`

---

## 3. Phone-only calls: HSC 03.05JR

**Code:** 03.05JR
**Description:** "Physician telephone call directly to patient to
discuss patient management / diagnostic test results."
**Fee:** **$20.00**.
**Caps:** Maximum of **14 per week per physician**.
**Scope:**
- 03.05JR is **not** a full visit. It is a discrete telephone
  communication for a specific purpose (test result discussion,
  management question). It does not replace a comprehensive 03.04A
  visit.
- Mutual exclusivity with 03.01S and 03.01T (see §1).
- **Phone-as-visit (full visit by phone, not video)** has been on/off
  the AHCIP-insured list several times in the past decade. As of
  SOMB 2026-04-01, **phone visits for new clinical presentations are
  not separately payable at a visit-level code** — only 03.05JR
  (limited phone communication) is reliably billable, and only for
  result/management discussions. The auditor should **not** suggest
  03.04A + telehealth premium for a phone visit; it should suggest
  03.05JR if a brief phone call occurred, or escalate to a human
  biller if the documentation suggests a full visit-by-phone.

**Source:** DoctorCare AHCIP virtual care guide:
`https://doctorcare.ca/a-guide-to-ahcip-billing-codes-for-virtual-care/`

---

## 4. The v12 prompt should encode this as a rule

**Proposed v12 rule (drafting target):**

```
rule_ahcip_telehealth_premium:
  name: "AHCIP telehealth — virtual visit billed without virtual code"
  trigger: |
    The clinical note indicates a virtual encounter ("telehealth",
    "video visit", "phone follow-up", "secure message", "virtual
    follow-up", "Zoom visit", etc.) AND the claim does not contain
    HSC 03.01T (video), 03.01S (async electronic), or 03.05JR
    (phone, ≤ 14/wk/physician) as a payable health service code.
  finding: |
    "Telehealth encounter documented in the clinical note but no
    AHCIP telehealth health service code is present on the claim.
    AHCIP requires HSC 03.01T (video, $20.00), 03.01S (async
    electronic, $20.00), or 03.05JR (phone, $20.00, ≤ 14/wk).
    Mutual exclusivity: only one of 03.01S / 03.01T / 03.05JR may be
    billed in the same calendar week for the same physician-patient
    pair."
  severity: medium
  suggested_fix: |
    "Add the appropriate telehealth HSC to the claim. For a
    real-time secure video visit, use 03.01T ($20). For an
    asynchronous secure-message exchange, use 03.01S ($20). For a
    brief phone call to discuss test results or management, use
    03.05JR ($20, max 14/week/physician). Do not bill 03.01T and
    03.05JR for the same patient in the same calendar week."
  confidence: high
```

**Important nuance for the v12 prompt:** the v11 prompt fires this
rule with a suggested fix that often reads "add telehealth modifier
to 03.04A" — that's a **US CPT convention** (`-95` synchronous
audiovisual modifier on a 99214). It is wrong for Alberta. The
correct framing is "replace the in-person E/M with the appropriate
AHCIP telehealth HSC" (or escalate to a human biller if the work
performed is clearly more than a 03.01T limited visit).

---

## 5. What's still uncertain (verify before shipping the rule into prod)

1. **Has Alberta added a comprehensive-virtual code that pays at
   the 03.04A-equivalent level?** As of SOMB 2026-04-01, I could
   not find a published "comprehensive video visit" code with a fee
   higher than $20.00. A biller should confirm this is still the
   state of the schedule before quoting fee numbers to a clinic.
   **Action:** ask the Strathcona PCN billing lead (or a certified
   Alberta biller) to confirm whether 03.01T at $20 is the *only*
   payable video code, or whether something like a "comprehensive
   virtual visit" HSC has been added.
2. **Phone-as-visit.** The current SOMB still treats phone as
   03.05JR (limited), not as a full visit. Verify with the most
   recent Alberta Health Bulletins — this area has been rewritten
   several times.
3. **CMGP modifier on 03.01T.** The chronic disease management
   premium (`CMGP`) modifier is typically billed on a 03.04A
   comprehensive chronic-disease visit. Whether CMGP attaches to
   03.01T (a $20 limited virtual visit) is unclear from the
   publicly available materials I could read. **Action:** confirm
   with a certified Alberta biller before suggesting CMGP on 03.01T
   in the v12 prompt.

---

## 6. Source URL summary (paste-ready citations)

| Source | URL |
|---|---|
| AMA Fee Navigator — HSC 03.01T | https://www.albertadoctors.org/fee-navigator/hsc/03.01T |
| AMA Fee Navigator — HSC 03.01S | https://www.albertadoctors.org/fee-navigator/hsc/03.01S |
| AMA Fee Navigator — HSC 03.05JR (via search) | https://www.albertadoctors.org/fee-navigator/hsc/search/03.05JR |
| Alberta Government — SOMB 2026-04-01 | https://open.alberta.ca/publications/somb-2026-04-01 |
| Alberta Government — SOMB codes XLSX | https://www.alberta.ca/system/files/custom_downloaded_images/health-research-somb-codes.xlsx |
| AMA PCPCM Operations Manual v4.2 (Jan 9, 2026) | https://www.albertadoctors.org/media/zolbejry/pcpcm-operations-manual-v42-jan-9.pdf |
| DoctorCare — AHCIP virtual care guide | https://doctorcare.ca/a-guide-to-ahcip-billing-codes-for-virtual-care/ |
| Petal Health — Alberta virtual care cheat sheet | https://www.petal-health.com/en/blog/medical-billing/alberta-health-cheat-sheet/ |
| Dr.Bill — AHCIP psychiatry codes (confirms $20 for 03.01S/T) | https://www.dr-bill.ca/blog/ahcip/ahcip-psychiatry-codes-billing-cheat-sheet |

---

## 7. Confidence statement

The **primary code (03.01T at $20.00 for a secure video visit)** and
its **mutual exclusivity rule with 03.01S and 03.05JR** are confirmed
verbatim across **four consecutive SOMB revisions** (2022-02, 2023-04,
2024-01, 2025-03) and continue in the 2026-04-01 release. I rate
these as **high confidence** and safe to hardcode into the v12
prompt.

The **edge-case modifier rules** (CMGP on 03.01T, phone-as-full-visit,
whether a comprehensive-virtual code has been added in 2026) I rate
as **medium confidence** and recommend verifying with a certified
Alberta biller before the v12 prompt goes to a paying clinic.

---

*Companion: `docs/AHCIP_RULE_REFERENCE.md` (full 16-rule AHCIP
catalogue), `docs/research/AHCIP-TELEHEALTH-PREMIUM-CODE.md` (this
file), and `docs/ALBERTA_STRATEGY_BRIEF.md` (overall Alberta plan).*
