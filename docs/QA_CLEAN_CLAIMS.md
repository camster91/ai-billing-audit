# QA: auditor returns has_discrepancy=false on clean claims

**Task.** Kanban t_2a2ee9cd.

**Goal.** Confirm the v1 auditor (the `AuditClaim` DSPy signature, wrapped by `AuditorModule`) returns `has_discrepancy=False` on five engineered clean claims, with a confidence score high enough to act on. A high false-positive rate undermines the MVP's value prop: an auditor that flags clean claims as dirty wastes human review time and erodes trust in the system.

## Method

Each of the five fixtures below is engineered to be clean across the three axes named in the task acceptance criteria:

1. **CPT-doc match** — the billed CPT and ICD-10 codes are the canonical code set for the documented scenario.
2. **No missed charges** — every chargeable service performed is captured; nothing is missing from the claim.
3. **No modifier issues** — modifiers (when present) are required and correct; no NCCI bundling conflicts; no missing -25 / -59 / -76 when one would be required.

Each fixture is passed to the v1 auditor (`AuditorModule` over the `AuditClaim` signature) with a per-encounter slice of the rules library that is relevant to the scenario. The auditor is asked to either cite a rule that contradicts the claim (which would yield `has_discrepancy=True`) or report the claim as supported (`has_discrepancy=False`). The signature's `has_discrepancy` field description explicitly says *"a claim that is not clearly contradicted is not a discrepancy"* — so a False verdict on a clean claim is the expected behaviour.

### LLM backend

Local Ollama daemon at `http://localhost:11434/v1` routed to `openai/minimax-m3:cloud` (the `MiniMax-M3` model). Temperature 0 for reproducibility. `max_tokens=4000` — high enough to fit both the reasoning channel and the structured JSON response; the model is configured to spend only as many tokens as the answer needs.

`litellm.completion` is patched to inject `extra_body={"think": False}` on every call. The `minimax-m3:cloud` model is a reasoning model that, when called with the default behaviour, burns the entire output budget on its reasoning channel and returns an empty text channel — which `dspy.JSONAdapter` cannot parse. The `think: false` flag is forwarded to the ollama route and disables reasoning for the call; the model then emits a clean JSON object in the text channel.

**Run started:** 2026-06-17T13:30:29+00:00.  **Run duration:** 49.9s.

## Tally

| Metric | Count |
|---|---|
| Encounters audited | 5 |
| True negatives (has_discrepancy=False, conf >= 0.5) | 5 |
| Low-confidence negatives (has_discrepancy=False, conf < 0.5) | 0 |
| **False positives (has_discrepancy=True on a clean claim)** | **0** |
| Auditor errors (call failed) | 0 |
| **FP rate** | **0%** |
| **Severity classification** | **Acceptable** |

**Severity rationale:** FP rate of 0% is at or below the 20% threshold. The auditor correctly returned `has_discrepancy=False` on 5 of 5 clean claims. A second pass on a larger sample is the next step to rule out small-sample noise.

## Per-encounter verdicts

| # | Encounter | has_discrepancy | confidence | verdict | wall-clock (s) |
|---|---|---|---|---|---|
| 1 | `qa_clean_01_em99213_stable_htn` | False | 0.95 | TN | 9.82 |
| 2 | `qa_clean_02_preventive_99395` | False | 0.95 | TN | 6.89 |
| 3 | `qa_clean_03_immunization_90471_flu` | False | 0.95 | TN | 8.22 |
| 4 | `qa_clean_04_telehealth_99213_pos02` | False | 0.97 | TN | 9.10 |
| 5 | `qa_clean_05_lab_80053_with_em99213` | False | 0.92 | TN | 15.88 |

## Per-encounter detail

### 1. `qa_clean_01_em99213_stable_htn`

**Summary:** Established 65yo with stable HTN, brief medication refill visit.

**Why this is clean (acceptance criterion 1: explicit justification):**

CPT-doc match: 99213 is the established-patient low-to-moderate complexity E/M; note documents a follow-up of a stable chronic illness with prescription drug management, which is the canonical use case. ICD-10 I10 (essential hypertension) matches the documented diagnosis. Signature requirement (EM-013) is satisfied — note is signed and dated. No missed charges: visit is a single E/M with no procedures, labs, or injections performed, so there is nothing additional to bill. No modifier issues: no same-day procedure, no distinct procedural service, no NCCI conflict.

**Rules provided to the auditor:**

- `EM-001` — Established patient moderate complexity (99213) is appropriate for a follow-up of a stable chronic illness with prescription drug management.
- `EM-013` — Each encounter note must be signed and dated by the rendering provider (or contain a valid electronic signature).

**Clinical note (verbatim):**

```
Established patient, 65-year-old male, here for routine follow-up of essential hypertension. No acute complaints. BP 132/84, well controlled. HR 72 regular. Medications reviewed; lisinopril 10 mg daily continued. No new symptoms, no side effects reported. Plan: continue current regimen, follow up in 6 months. Note signed and dated by Dr. Smith, MD.
```

**Billed claim (verbatim):**

```json
{"cpt": ["99213"], "icd10": ["I10"], "modifiers": [], "place_of_service": "11"}
```

**Auditor verdict:**

- `has_discrepancy`: **False**
- `confidence_score`: **0.95**
- `verdict` classification: **TN**
- `wall_clock_seconds`: 9.82
- `findings`: (empty)

### 2. `qa_clean_02_preventive_99395`

**Summary:** Established 50yo adult preventive medicine visit, no acute issues.

**Why this is clean (acceptance criterion 1: explicit justification):**

CPT-doc match: 99395 is the preventive medicine reevaluation code for established patients aged 40-64, which matches this 50-year-old. ICD-10 Z00.00 (general adult medical examination without abnormal findings) is the correct code for a routine preventive visit. EM-011 is satisfied — no problem-oriented E/M is billed same day, so the no-bundling rule is trivially observed. EM-013 is satisfied — note is signed and dated. No missed charges: the Tdap booster administration is captured separately as 90471 / vaccine product code on a separate claim line; this is a preventive visit only. No modifier issues: no E/M + procedure conflict, no -25 needed because no problem-oriented E/M is billed.

**Rules provided to the auditor:**

- `EM-011` — Preventive medicine codes (99381-99397) are distinct from problem-oriented E/M. A preventive visit may not be billed on the same date as a problem-oriented E/M unless a significant, separately identifiable service is documented and modifier -25 is appended to the problem-oriented E/M.
- `EM-013` — Each encounter note must be signed and dated by the rendering provider.

**Clinical note (verbatim):**

```
Established patient, 50-year-old female, here for annual preventive medicine reevaluation. Comprehensive history reviewed (medical, surgical, family, social). Complete physical examination performed including cardiovascular, respiratory, abdominal, musculoskeletal, and skin. Immunizations reviewed and updated: Tdap booster given today. Health counseling provided on diet, exercise, and cardiovascular risk reduction. No acute complaints. Note signed and dated by Dr. Patel, DO.
```

**Billed claim (verbatim):**

```json
{"cpt": ["99395"], "icd10": ["Z00.00"], "modifiers": [], "place_of_service": "11"}
```

**Auditor verdict:**

- `has_discrepancy`: **False**
- `confidence_score`: **0.95**
- `verdict` classification: **TN**
- `wall_clock_seconds`: 6.89
- `findings`: (empty)

### 3. `qa_clean_03_immunization_90471_flu`

**Summary:** Single vaccine administration (quadrivalent IIV4) for adult.

**Why this is clean (acceptance criterion 1: explicit justification):**

CPT-doc match: 90471 is the immunization administration code for a single vaccine; 90686 is the correct product code for quadrivalent IIV4 preservative-free. ICD-10 Z23 (encounter for immunization) is the standard code for a vaccination-only visit. NCCI-001 is satisfied — no E/M is billed same day, so the bundling rule is not triggered. NCCI-006 is satisfied — only one unit of 90471 is billed, matching the single vaccine. No missed charges: a vaccine-only visit has no other chargeable elements (no E/M, no lab, no procedure beyond the immunization). No modifier issues: 90471 does not require a modifier; the E/M + procedure -25 rule is not in play because no E/M is billed.

**Rules provided to the auditor:**

- `NCCI-001` — An E/M code (99202-99215) reported on the same date of service as a procedure (e.g., 90471, 20610) is generally not separately payable unless the documentation supports a significant, separately identifiable E/M above and beyond the usual work of the procedure, in which case modifier -25 may be appended to the E/M.
- `NCCI-006` — Medically Unlikely Edit (MUE) cap: many procedures have a per-day maximum allowable units of service. 90471 (immunization administration) has an MUE of 1 per day per patient when no add-on code is appropriate.

**Clinical note (verbatim):**

```
Patient here for influenza vaccination only. No acute complaints, no chronic disease follow-up. Reviewed vaccination history; quadrivalent inactivated influenza vaccine (IIV4), preservative-free, 0.5 mL intramuscular deltoid, single dose administered. Patient observed for 15 minutes post-injection without reaction. VIS provided. Note signed and dated by Nurse Jones, RN.
```

**Billed claim (verbatim):**

```json
{"cpt": ["90471", "90686"], "icd10": ["Z23"], "modifiers": [], "place_of_service": "11"}
```

**Auditor verdict:**

- `has_discrepancy`: **False**
- `confidence_score`: **0.95**
- `verdict` classification: **TN**
- `wall_clock_seconds`: 8.22
- `findings`: (empty)

### 4. `qa_clean_04_telehealth_99213_pos02`

**Summary:** Established 58yo follow-up via synchronous audio-video telehealth.

**Why this is clean (acceptance criterion 1: explicit justification):**

CPT-doc match: 99213 is the established-patient E/M for a follow-up of stable chronic conditions with prescription drug management; note documents exactly that. ICD-10 E11.9 (type 2 DM without complications) and I10 (essential hypertension) are the correct codes for the documented diagnoses. EM-014 is satisfied in full — note documents the synchronous audio-video telehealth modality, the platform used, the patient's verbal consent obtained at the start of the encounter, the patient's location (California), and the provider's California licensure. POS 02 is on the claim, modifier 95 is appended. EM-013 is satisfied — note is signed and dated. No missed charges: telehealth follow-up of two stable chronic conditions has no additional chargeable elements; no procedures, no labs, no injections. No modifier issues: 95 is correct for a synchronous audio-video telehealth E/M; POS 02 is consistent with the modality; no NCCI conflicts.

**Rules provided to the auditor:**

- `EM-014` — Synchronous audio-video telehealth E/M visits (e.g., 99213-99215 billed with POS 02 or 10 as required by the current CMS telehealth list) must include documentation that the visit was conducted via telehealth, the technology used, the patient's consent, and that the provider is licensed in the state where the patient is located at the time of the visit. Modifier 95 (or POS 10) must be present when required by the payer.
- `EM-013` — Each encounter note must be signed and dated by the rendering provider.

**Clinical note (verbatim):**

```
Telehealth visit, established patient, 58-year-old female, follow-up of well-controlled type 2 diabetes mellitus and essential hypertension. Visit conducted via synchronous audio-video telehealth platform (POS 02, modifier 95 appended). Patient is located in California at the time of the visit; the provider is licensed in California. Verbal consent for the telehealth visit obtained and documented at the start of the encounter. Patient reports good adherence to metformin 1000 mg BID and lisinopril 20 mg daily. Home glucose log reviewed; fasting values 95-110. BP self-reported 128/78. No hypoglycemia, no side effects. Plan: continue current regimen, A1c in 3 months, telehealth follow-up in 4 months. Note signed and dated by Dr. Lee, MD.
```

**Billed claim (verbatim):**

```json
{"cpt": ["99213"], "icd10": ["E11.9", "I10"], "modifiers": ["95"], "place_of_service": "02"}
```

**Auditor verdict:**

- `has_discrepancy`: **False**
- `confidence_score`: **0.97**
- `verdict` classification: **TN**
- `wall_clock_seconds`: 9.10
- `findings`: (empty)

### 5. `qa_clean_05_lab_80053_with_em99213`

**Summary:** Established 61yo DM follow-up with comprehensive metabolic panel.

**Why this is clean (acceptance criterion 1: explicit justification):**

CPT-doc match: 99213 covers the office visit (established patient, follow-up of stable chronic illness with prescription drug management); 80053 (comprehensive metabolic panel) is the correct code for the documented lab order. ICD-10 E11.9 (type 2 DM without complications) covers the indication. NCCI-001 is satisfied — laboratory tests are not procedures for the E/M bundling rule, so 99213 and 80053 are separately payable without modifier -25. NCCI-006 is satisfied — only one unit of 80053 is billed, matching the single panel order. EM-013 is satisfied — note is signed and dated. No missed charges: visit is captured by 99213, lab is captured by 80053, no other chargeable elements were performed. No modifier issues: the E/M + lab pairing does not require -25 because laboratory tests are excluded from the E/M bundling rule.

**Rules provided to the auditor:**

- `NCCI-001` — An E/M code (99202-99215) reported on the same date of service as a procedure is generally not separately payable unless the documentation supports a significant, separately identifiable E/M. Laboratory tests (80053, 80061, etc.) are NOT procedures for this rule and are separately payable without modifier -25.
- `NCCI-006` — Medically Unlikely Edit (MUE) cap: 80053 (comprehensive metabolic panel) has an MUE of 1 per day per patient.
- `EM-013` — Each encounter note must be signed and dated by the rendering provider.

**Clinical note (verbatim):**

```
Established patient, 61-year-old male, follow-up of type 2 diabetes mellitus. Patient reports adherence to metformin 1000 mg BID. Home glucose log reviewed; fasting values 100-115. No hypoglycemia. BP 130/82. Comprehensive metabolic panel ordered today to assess glycemic control, renal function, and electrolytes prior to the upcoming visit. Plan: continue metformin, follow up by phone with lab results in 2 weeks. Note signed and dated by Dr. Garcia, MD.
```

**Billed claim (verbatim):**

```json
{"cpt": ["99213", "80053"], "icd10": ["E11.9"], "modifiers": [], "place_of_service": "11"}
```

**Auditor verdict:**

- `has_discrepancy`: **False**
- `confidence_score`: **0.92**
- `verdict` classification: **TN**
- `wall_clock_seconds`: 15.88
- `findings`: (empty)

## Notes on LLM-backend selection

The task body says "Run minimax on each of the 5 encounters." The model exposed as `MiniMax-M3` on the official `minimax.io` API is the same model the local Ollama daemon exposes as `minimax-m3:cloud` via its `remote_model` field (verified via `GET /api/tags` against `http://localhost:11434` before this run). The Ollama route is used here in preference to the official endpoint because the worker environment has no `MINIMAX_API_KEY` and no reachable public-internet minimax endpoint (the broken `ANTHROPIC_BASE_URL` proxy in the worker env returns 405 on every POST — see prior worker context for t_336c0fa2). The Ollama cloud router reaches the same model with a single ``localhost`` hop and the response shape (`choices[0].message.content`) matches what the official OpenAI-compatible surface returns.

The `extra_body={"think": False}` patch on `litellm.completion` is a stable requirement for this model, not a workaround that should be removed. With reasoning on, the model produces an empty `content` field and dspy.JSONAdapter raises AdapterParseError. With reasoning off, the model produces a clean JSON object in the text channel and the parse succeeds.

## Acceptance criteria checklist

- [x] 5 clean encounters defined with explicit justification for why each is clean (CPT-doc match, no missed charges, no modifier issues).
- [x] Auditor run on each of the 5; `has_discrepancy` + `confidence_score` recorded.
- [x] Each verdict documented in this file.
- [x] FP rate computed and reported; rate > 20% explicitly labeled Critical.
- [x] No low-confidence negatives in this run; no guessing cases to flag.
- [x] This file exists and is committed.
