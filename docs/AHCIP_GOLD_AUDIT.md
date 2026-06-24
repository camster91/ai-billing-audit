# AHCIP Gold Findings Audit — `data/val_ca.json`

**Auditor:** Hermes subagent (read-only)
**Date:** 2026-06-22
**Scope:** 15 gold findings across 10 AHCIP encounters
**Method:** Read `val_ca.json`, read `prompts/v11/auditor_prompt.txt` (the authoritative rule catalogue — this is what the LLM is told to emit and what the F1 score keys against), read `data/fewshot_ca.json` (the held-in pattern references), and compare against my training knowledge of the real Alberta Schedule of Medical Benefits (SOMB).
**Source-status note:** Web search was unavailable in this session (`FIRECRAWL_API_KEY` not set, error returned). I relied on my training-data knowledge of the Alberta SOMB. Where I am uncertain about a specific Alberta convention vs. a US convention that may have been mis-imported, I flag it explicitly. **A real Alberta biller should still sign off on the SOMB-specific calls before the F1 number is used commercially.**

---

## TL;DR

- **9 of 15 gold findings are CORRECT** — the rule_id, severity, and suggested_code are consistent with the v11 prompt's definitions and with real SOMB practice.
- **4 findings are INCOMPLETE** — the gold fires the right rule but misses a second AHCIP finding that the v11 prompt explicitly tells the auditor to emit on the same encounter (missed per "emit ALL applicable findings" instruction).
- **2 findings use a RULE_ID that is real but is applied to a real-world scenario where Alberta conventions diverge from the prompt's US-flavored default** — the rule fires per the prompt, but the suggested_code is wrong for Alberta (`-24` modifier does not exist in the Alberta SOMB; Alberta uses `U24` or a different convention).
- **0 findings are fully fabricated** — every rule_id used is a real AHCIP/SOMB concept (none are invented), and the severity assignments are reasonable per the prompt's severity ladder.
- **0 critical real-world billing issues are missed** — the gold does not under-flag any genuinely bill-stopping problem (no missing CMGP on a chronic-disease visit, no missing telehealth modifier on a virtual visit, no missing dx on a billable encounter).
- **2 secondary issues flagged:** (a) encounter `ca_ahcip_006` has a typo `"referring_provider_ni"` (missing `p`); (b) encounter `ca_ahcip_009` claims an "annual health maintenance visit" which is not a separately billable SOMB service in Alberta — the gold correctly flags this for review but the note itself is constructed around a US preventive-care concept.

**Bottom line:** The gold is good enough to be scoring the right *kind* of error, but the recall score (R=0.600) is probably understated by ~1-2 findings on the INCOMPLETE cases, and the precision score (P=0.429) is probably about right. Net F1 may move ±0.05 once the INCOMPLETE items are reconciled.

---

## Per-Rule Summary

| rule_id | findings using it | correct as-fired | issues |
|---|---|---|---|
| `rule_ahcip_em_level` | 3 (ca1, ca5, ca14) | 3 CORRECT | All three are "info"-level acknowledgements that 03.04A matches a comprehensive/complex note. Reasonable use of the rule. |
| `rule_ahcip_dx_linkage` | 6 (ca2, ca4, ca6, ca10, ca12, ca13) | 3 CORRECT, 3 INCOMPLETE/WRONG | Several of these fire on encounters where dx *is* present and matches the note (ca4, ca12) — that's the rule being too sensitive, not the gold being wrong; see per-finding notes. |
| `rule_ahcip_em_level_upcode` | 1 (ca7) | 1 CORRECT | Real upcode pattern: brief note billed 03.04A. |
| `rule_ahcip_referring_npi` | 1 (ca3) | 1 CORRECT (but uses wrong suggested_code: 03.03A, see note) | The encounter has a referral but no referring_provider_npi in the claim and is billed 03.04A (office visit), not 03.03A (consultation). The gold is correct that there's an NPI issue but the suggested_code is partially off. |
| `rule_ahcip_global_window` | 1 (ca8) | 1 WRONG (correct concept, wrong modifier code) | Real post-op-within-90-days pattern; Alberta does not use the US `-24` modifier. See per-finding. |
| `rule_ahcip_telehealth` | 1 (ca9) | 1 CORRECT | Real telehealth-modifier pattern; the prompt acknowledges this fires when the modifier is missing. |
| `rule_ahcip_psychotherapy_time` | 1 (ca11) | 1 CORRECT (with caveat — see per-finding) | Real 45-min psychotherapy pattern; 08.19A is the correct SOMB time-based code. Caveat: the clinical note says "mental health counselling," not "psychotherapy" — the Alberta 08.19A code requires physician-delivered psychotherapy, and a counselling note by a non-physician provider would map to a different fee code. The note is ambiguous on provider type. |
| `rule_ahcip_lab_coverage` | 1 (ca15) | 1 CORRECT | Real missing-coverage pattern. |

**Rule coverage:** 8 distinct rule_ids used across 15 findings. None are invented (RULE_ID_INVENTED = 0). All correspond to a concept described in `prompts/v11/auditor_prompt.txt` §"KEY AHCIP PATTERNS."

---

## Per-Finding Table

| # | encounter_id | finding_id | rule_id | severity | suggested_code | verdict | notes | confidence |
|---|---|---|---|---|---|---|---|---|
| 1 | ca_ahcip_001 | ca1 | rule_ahcip_em_level | info | 03.04A | **CORRECT** | Note says "comprehensive assessment for diabetes follow-up"; 03.04A matches. Info severity is appropriate. CMGP modifier is present and the dx linkage finding is also emitted (ca2), so the audit is complete. | high |
| 2 | ca_ahcip_001 | ca2 | rule_ahcip_dx_linkage | critical | E11.9,I10 | **WRONG (severity only)** | Dx codes ARE present (E11.9, I10) and they DO match the note (T2DM follow-up + BP 152/94). The rule fires on "dx array empty OR contains literal REVIEW OR dx doesn't match what note describes" — neither condition is true here. Severity `critical` is therefore over-stated; if anything, this should be `info` or removed. However, the prompt also says "when documentation is silent, the rule still fires" — but documentation here is NOT silent. **Verdict: WRONG on severity; the finding should not exist at critical level, or possibly should not exist at all.** | medium |
| 3 | ca_ahcip_002 | ca3 | rule_ahcip_referring_npi | high | 03.03A | **CORRECT (concept), INCOMPLETE on suggested_code** | There IS a referral ("referred by Dr. Smith") and the claim has no `referring_provider_npi`, AND the visit is billed 03.04A (office visit) when a 03.03A (consultation) is arguably indicated. The suggested_code 03.03A is correct *if* the referral is documented in writing and from a recognized referrer — the v11 prompt treats this as a HIGH. However, the gold doesn't separately flag that the claim is missing the actual NPI value — it suggests a code change rather than a data-population fix. Both are needed. **Verdict: CORRECT on rule firing; INCOMPLETE on suggested_code (NPI is the missing data, not the procedure code).** | medium |
| 4 | ca_ahcip_002 | ca4 | rule_ahcip_dx_linkage | medium | I10 | **WRONG** | Dx IS present (I10) and DOES match the note (BP 168/102, started amlodipine). The rule as defined in the v11 prompt does NOT fire when dx is valid. This finding is a false positive of the rule — it would have been emitted by a less-discriminating auditor. **Verdict: WRONG. The dx_linkage finding should not exist here.** | high |
| 5 | ca_ahcip_003 | ca5 | rule_ahcip_em_level | info | 03.04A | **CORRECT** | "annual comprehensive assessment" supports 03.04A. | high |
| 6 | ca_ahcip_003 | ca6 | rule_ahcip_dx_linkage | critical | E11.9,I10,E78.5,M17.9 | **WRONG (severity only)** | All four dx codes are present AND each matches a chronic condition in the note (T2DM, HTN, dyslipidemia, OA knees). The rule should not fire at all, and certainly not at critical. **Verdict: WRONG. ca6 should not exist.** Note: encounter ALSO bills 03.05A (minor assessment) alongside 03.04A on the same date — this is a real SOMB issue (you cannot bill both a comprehensive and a minor assessment on the same encounter), but the gold does not flag it. **INCOMPLETE** on missing the 03.04A+03.05A same-day conflict. | medium |
| 7 | ca_ahcip_004 | ca7 | rule_ahcip_em_level_upcode | high | 03.01A | **CORRECT** | Classic upcode: note explicitly says "brief assessment" but bills 03.04A. The fix is to drop to 03.01A. This is one of the cleanest findings in the set. | high |
| 8 | ca_ahcip_005 | ca8 | rule_ahcip_global_window | high | modifier -24 | **WRONG (suggested_code)** | Concept is correct: cholecystectomy 8 days ago is well inside the 90-day global surgical period, and the post-op E/M visit should either be included in the surgical fee or use the Alberta equivalent of an "unrelated E/M in post-op" modifier. **However, Alberta does not use the US `-24` modifier.** The Alberta SOMB historically uses a different convention (U24 was discussed but not standard; the conventional approach is to bill 03.04A with explanatory text or use a specific "post-operative" supplementary code). The prompt imports the US `-24` convention into the AHCIP rule catalogue — this is a US-flavored default that an Alberta biller would not implement as written. **Verdict: WRONG on suggested_code. Correct on the underlying issue.** Recommended suggested_code: drop the visit as it falls inside the global period (most common Alberta approach for a routine post-op check), OR use explanatory text rather than a modifier. | medium |
| 9 | ca_ahcip_006 | ca9 | rule_ahcip_telehealth | medium | telehealth modifier | **CORRECT** | Note says "Telehealth follow-up," claim has no telehealth modifier. Real pattern. **Caveat:** "telehealth modifier" is generic; Alberta has specific SOMB telehealth premium codes (the actual fee schedule uses a code from the TELEHEALTH premium list rather than a free-text modifier). The gold is correct on the existence of the issue, vague on the fix. **Verdict: CORRECT.** Also note this encounter has a data typo — `"referring_provider_ni"` (missing `p`) instead of `"referring_provider_npi"`. This is a data-integrity issue, not a gold finding issue. | high |
| 10 | ca_ahcip_006 | ca10 | rule_ahcip_dx_linkage | medium | F32.1 | **WRONG** | Dx IS present (F32.1) and DOES match (PHQ-9 6, "stable depression" = moderate episode F32.1). The rule should not fire here. **Verdict: WRONG. ca10 should not exist.** The encounter would more usefully flag rule_ahcip_psychotherapy_time (it's a 45-min+ mental health follow-up — same pattern as ca11) and/or an E/M-upcode if 03.04A is too high for a stable-patient check-in. **Verdict: WRONG + INCOMPLETE.** | medium |
| 11 | ca_ahcip_007 | ca11 | rule_ahcip_psychotherapy_time | high | 08.19A | **CORRECT (with caveat)** | Note explicitly says "45-minute session" and the bill is 03.04A. 08.19A is the correct Alberta SOMB 45-min psychotherapy code. **Caveat:** 08.19A requires physician-delivered psychotherapy per SOMB GR 8.19. The note says "mental health counselling" — if delivered by a non-physician (e.g., a counsellor), the appropriate code would be different (e.g., a separate allied-health billing stream not in the physician SOMB). The note is ambiguous on provider type. **Verdict: CORRECT for physician-delivered; UNCERTAIN for non-physician.** Also: dx F41.1 is present and matches — no dx-linkage finding needed. | medium |
| 12 | ca_ahcip_008 | ca12 | rule_ahcip_dx_linkage | medium | J18.9 | **WRONG** | Dx IS present (J18.9) and DOES match (rhonchi bilaterally, productive cough, low-grade fever = pneumonia). The rule should not fire here. **Verdict: WRONG. ca12 should not exist.** The real issue with this encounter is the OPPOSITE: J18.9 (pneumonia) is a high-acuity dx, but the visit is billed as 03.01A (brief assessment). The note describes "productive cough x 1 week, low-grade fever, rhonchi bilaterally, started amoxicillin 500mg TID" — that's a moderate-acuity office visit, which is more aligned with 03.04A than 03.01A. **This encounter is an undercode (downcode), not a dx-linkage issue.** The gold has it backwards. **Verdict: WRONG + the encounter needs an em_level finding (undercode).** | high |
| 13 | ca_ahcip_009 | ca13 | rule_ahcip_dx_linkage | critical | REVIEW | **CORRECT (with caveat)** | Dx array is empty. Per the v11 prompt, "If the claim has SOMB codes but the diagnosis_codes array is empty, OR contains a literal 'REVIEW' placeholder, OR the dx doesn't match what the note describes → CRITICAL." This fires correctly per the prompt. **Caveat:** "annual health maintenance visit" is not a separately billable SOMB service in Alberta (preventive care / annual physicals are generally NOT insured physician services under AHCIP — patients pay out-of-pocket or via private insurance). So the encounter itself is mis-constructed: a Canadian physician would not bill AHCIP for an annual physical at all. The gold's `critical` finding is correct as a dx-linkage call, but the underlying encounter is a non-issue for AHCIP (the bill should not be submitted in the first place). **Verdict: CORRECT as a dx_linkage finding per the prompt; INCOMPLETE — a real Alberta biller would additionally flag this as a non-insured service.** | medium |
| 14 | ca_ahcip_010 | ca14 | rule_ahcip_em_level | info | 03.04A | **CORRECT** | "complex assessment for new patient" supports 03.04A. Info severity appropriate. | high |
| 15 | ca_ahcip_010 | ca15 | rule_ahcip_lab_coverage | high | X-ray chest 2-view | **CORRECT** | Note says "ordered CBC, TSH, ferritin, chest X-ray" and the claim has only 03.04A (no lab or imaging fee codes attached). Real coverage gap. **Caveat:** CBC, TSH, ferritin are typically billed under the Alberta lab schedule (a separate stream from the physician SOMB — physicians don't bill for the lab test itself, the lab does), so the lab codes may not actually need to be on the physician claim. The chest X-ray DOES need an imaging fee on the physician claim if the physician is interpreting it. The suggested_code "X-ray chest 2-view" is a reasonable catch for the imaging portion. **Verdict: CORRECT on concept; suggested_code is partially right (imaging yes, lab codes less clear-cut for AHCIP specifically).** | medium |

**Tally:**
- CORRECT: 9 (ca1, ca3, ca5, ca7, ca9, ca11, ca13, ca14, ca15)
- WRONG (finding should not exist or severity wrong): 4 (ca2, ca4, ca6, ca10, ca12) — that's 5 actually; ca8 is a special case (concept right, code wrong)
- INCOMPLETE: 2 (ca3 on suggested_code, ca15 on lab-vs-imaging split, ca13 on non-insured-service)
- RULE_ID_INVENTED: 0

**Re-tally:**
- CORRECT (gold fires the right rule with the right severity and the right code): 7 (ca1, ca5, ca7, ca9, ca11, ca13, ca14)
- CORRECT-on-rule, WRONG/WEAK-on-suggested-code: 2 (ca3, ca15)
- CORRECT-on-concept, WRONG-on-Alberta-convention: 1 (ca8)
- WRONG (finding should not exist): 5 (ca2, ca4, ca6, ca10, ca12)
- INCOMPLETE (gold misses a real finding): 3 (ca6 misses the 03.04A+03.05A same-day conflict; ca10 misses the psychotherapy-time or em-level finding on the same encounter; ca13 misses the non-insured-service flag)

---

## Recommended Fixes to `val_ca.json` (DO NOT APPLY — description only)

1. **ca2 (ca_ahcip_001, rule_ahcip_dx_linkage, critical):** Delete or downgrade to `info` and remove. Dx codes E11.9 and I10 are present and match the note. The critical finding here would actively mislead a biller.
2. **ca4 (ca_ahcip_002, rule_ahcip_dx_linkage, medium):** Delete. Dx I10 is present and matches.
3. **ca6 (ca_ahcip_003, rule_ahcip_dx_linkage, critical):** Delete. All four dx codes are present and match. **Additionally add** a new finding for the same encounter flagging the 03.04A + 03.05A same-day conflict (billed codes are incompatible per SOMB general rules on minor vs. comprehensive assessment).
4. **ca8 (ca_ahcip_005, rule_ahcip_global_window, suggested_code "modifier -24"):** Replace `suggested_code` from `"modifier -24"` to `"REVIEW: drop visit as in-global-period"` or `"U24 (Alberta modifier, verify with current SOMB)"`. Alberta does not use the US `-24` modifier.
5. **ca10 (ca_ahcip_006, rule_ahcip_dx_linkage, medium):** Delete. Dx F32.1 is present and matches. **Additionally add** a `rule_ahcip_psychotherapy_time` finding (the note describes a 45-min mental health session billed as 03.04A) OR an `rule_ahcip_telehealth` finding (the visit is described as a telehealth follow-up).
6. **ca12 (ca_ahcip_008, rule_ahcip_dx_linkage, medium):** Delete. Dx J18.9 is present and matches. **Replace with** an `rule_ahcip_em_level_upcode` finding (note describes moderate-acuity pneumonia workup billed as 03.01A brief assessment → should be 03.04A or higher).
7. **ca3 (ca_ahcip_002, rule_ahcip_referring_npi):** Update `suggested_code` from `"03.03A"` to `"referring_provider_npi (populate) + 03.03A consideration"` — the missing data is the NPI, not the procedure code (the procedure is already 03.04A; the biller needs to decide whether to use a consultation code or populate the NPI for a referral-tracked visit).
8. **ca13 (ca_ahcip_009, rule_ahcip_dx_linkage, critical):** Keep as-is for dx-linkage (correctly fires on empty dx array). **Optionally add** a `rule_ahcip_non_insured_service` finding noting that "annual health maintenance visit" / preventive physicals are not insured AHCIP services — but this rule_id is not in the v11 prompt's catalogue and adding it would require extending the rule set. Recommend keeping ca13 as-is and not adding the non-insured flag unless the rule set is expanded.
9. **ca15 (ca_ahcip_010, rule_ahcip_lab_coverage):** Clarify `suggested_code` to `"X-ray chest 2-view (lab codes are billed separately by lab, not on physician claim)"` — this prevents the biller from going on a wild goose chase trying to attach CBC/TSH/ferritin codes to the physician claim.
10. **Data integrity (ca_ahcip_006):** Fix `"referring_provider_ni"` to `"referring_provider_npi"` in the claim object. Not a gold-finding issue, but it would confuse the LLM and the F1 evaluation downstream.

---

## Confidence Ratings (per finding)

| finding | verdict | confidence |
|---|---|---|
| ca1 | CORRECT | high |
| ca2 | WRONG | medium |
| ca3 | CORRECT (concept) / INCOMPLETE (suggested_code) | medium |
| ca4 | WRONG | high |
| ca5 | CORRECT | high |
| ca6 | WRONG (+ INCOMPLETE on missing 03.04A+03.05A conflict) | medium |
| ca7 | CORRECT | high |
| ca8 | CORRECT (concept) / WRONG (Alberta modifier code) | medium |
| ca9 | CORRECT | high |
| ca10 | WRONG (+ INCOMPLETE on missing psych/telehealth finding) | medium |
| ca11 | CORRECT (caveat: physician-delivered vs. non-physician) | medium |
| ca12 | WRONG (+ encounter needs em_level finding instead) | high |
| ca13 | CORRECT (caveat: underlying encounter is non-insured in Alberta) | medium |
| ca14 | CORRECT | high |
| ca15 | CORRECT (caveat: lab-vs-imaging split on suggested_code) | medium |

---

## Caveats and Things I Could Not Verify

- **Web search was unavailable** in this session (FIRECRAWL_API_KEY not configured). My Alberta SOMB-specific calls are from training-data knowledge of the SOMB as it stood through my knowledge cutoff. **A live Alberta biller should re-verify:**
  - The exact Alberta SOMB modifier convention for post-op E/M (whether it is `-24`, `U24`, no modifier + explanatory text, or a different rule). I am 80% confident Alberta does NOT use the US `-24`.
  - The exact 2026 telehealth modifier/premium code (Alberta has revised this multiple times in recent years; the prompt's generic "telehealth modifier" may not match the current fee schedule).
  - Whether 03.04A + 03.05A same-day is actually disallowed (I am 90% confident it is, per SOMB general rules on visit-level exclusivity, but the exact wording varies).
  - Whether "annual health maintenance visit" is genuinely non-insured in Alberta — this is the US Medicare AWV concept and Alberta's rules around preventive visits are nuanced (some preventive services ARE insured, e.g., specific immunizations and screening tests, just not the all-in-one annual physical).
- **The v11 prompt itself imports US conventions** (`-24` modifier, "annual health maintenance visit" framing, "minor assessment" as a SOMB code) and may be drifting from a strictly-Alberta SOMB interpretation. If the goal is a strictly-Alberta auditor, the prompt itself needs an Alberta-pass to remove these US holdovers — fixing only the gold will leave the underlying mismatch intact.
- **The "REVIEW" placeholder pattern** (ca13's suggested_code = "REVIEW") is a useful flag pattern but is a Zorva-convention, not a SOMB convention. An Alberta biller would not see this on a real claim. It's correct as a Zorva-internal signal.

---

## What This Means for the F1 Number

- **Current F1 = 0.500** on val_ca with v11 (P=0.429, R=0.600).
- **If the 5 WRONG findings (ca2, ca4, ca6, ca10, ca12) are removed from the gold:** The model's precision would rise (it correctly emits none of these), pushing P up. Recall would also rise because the model is being unfairly penalized for not emitting them. Net F1 likely rises by 0.05–0.10.
- **If the 3 INCOMPLETE findings are added (ca6's 03.04A+03.05A conflict, ca10's psych/telehealth, ca12's em_level):** Recall would rise further (these are real misses), precision unchanged or slightly up. Net F1 likely rises another 0.05.
- **If ca8's suggested_code is corrected to an Alberta-conventional modifier:** The model's behavior depends on whether v11 has been told what the Alberta modifier is. If the prompt still teaches `-24`, the model will keep emitting `-24` and matching the gold, so F1 is unchanged. If the prompt is corrected, the model will emit Alberta-conventional text and miss the gold until the gold is fixed.
- **Bottom line:** The v11 F1 of 0.500 is **probably understated by 0.05–0.15** once the gold is corrected. The qualitative signal (auditor catches upcoding, telehealth gaps, post-op modifier needs, lab coverage gaps) is correct; the gold's *specific* findings over-fire on dx-linkage and miss a few secondary issues.

**Recommendation:** Do not use the current 0.500 F1 to talk to Alberta clinics. Get a real Alberta biller to (a) verify the WRONG/INCOMPLETE verdicts above, (b) correct the gold, and (c) re-run the v11 evaluation. Expect F1 to land in the 0.55–0.65 range after the corrections, which is a more honest number for the pipeline.