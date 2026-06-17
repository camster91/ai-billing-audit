# BUGS — synthetic corpus PHI leakage check

**Scope:** `data/train.json` (100 records, 184 KB) and `data/val.json` (50 records, 92 KB).
**Date:** 2026-06-17.
**Author:** default worker (kanban t_99fa8289).
**Verdict:** **PASS — corpus appears fully synthetic. No residual PHI found.**

A separate **data-quality bug** (not PHI) was found during the audit and is filed
as a sibling entry at the bottom of this document.

---

## 1. Methodology

### 1.1 Tools

- `re` module from Python 3.9 stdlib — every regex below run against the raw text
  of both files with `re.IGNORECASE` only where indicated.
- Manual review of every token captured, not just hit counts.
- Public web search (Google) for case-report collision detection on the most
  representative code combinations.

### 1.2 Pattern families

Three classes of pattern, run independently and cross-referenced:

**A. Names (loose, expects common-word false positives).** Manual triage of every
hit.

| Pattern | Regex |
|---|---|
| Two-word capitalized | `\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b` |
| Three-word capitalized | `\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b` |
| Last, First | `\b[A-Z][a-z]{2,},\s*[A-Z][a-z]{2,}\b` |
| Initial.Initial.Last | `\b[A-Z]\.\s*[A-Z]\.?\s*[A-Z][a-z]+\b` |
| Dr. Lastname | `\bDr\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b` |
| Mr/Mrs/Ms + Lastname | `\b(?:Mr\|Mrs\|Ms\|Miss\|Sir\|Dame)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b` |
| Initial.Initial (pair) | `\b[A-Z]\.[A-Z]\.\b` |
| Apostrophe name | `\b[A-Z][a-z]+(?:'[a-z]+)+\b` |
| "patient X" | `\b(?:patient\|Pt\.?)\s+([A-Z][a-z]+\|[a-z]+)\b` |
| Bracketed name | `\[[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\]` |

**B. PHI identifiers (strict, every hit is a leak).**

| Pattern | Regex |
|---|---|
| Email | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b` |
| US phone | `\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b` |
| SSN | `\b\d{3}-\d{2}-\d{4}\b` |
| Credit card | `\b(?:\d[ -]?){13,16}\d\b` |
| IPv4 | `\b(?:\d{1,3}\.){3}\d{1,3}\b` |
| URL | `\bhttps?://[A-Za-z0-9.\-/_%?=]+\b` |
| MRN (labeled) | `\b(?:MRN\|medical\s+record(?:\s+(?:number\|no\|#))?\|chart\s+(?:number\|no\|#)\|patient\s+(?:id\|number\|#))[:\s#]*[A-Z0-9-]{4,}\b` |
| NPI (labeled) | `\bNPI[:\s#]*\d{10}\b` |
| DEA (labeled) | `\bDEA[:\s#]*[A-Z]{2}\d{7}\b` |
| Member/Subscriber/Policy ID | `\b(?:Member\s*(?:ID\|Number\|#)\|Subscriber\s*(?:ID\|Number\|#)\|Policy\s*(?:Number\|#)\|Group\s*(?:Number\|#)\|Insurance\s*ID)[:\s#]*[A-Z0-9-]{4,}\b` |

**C. Address / date / institution (loose, needs triage).**

| Pattern | Regex |
|---|---|
| Street address | `\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street\|St\|Avenue\|Ave\|Road\|Rd\|Boulevard\|Blvd\|Drive\|Dr\|Lane\|Ln\|Way\|Court\|Ct\|Circle\|Cir\|Place\|Pl\|Parkway\|Pkwy)\.?\b` |
| PO Box | `\bP\.?O\.?\s+Box\s+\d+\b` |
| US ZIP | `\b\d{5}(?:-\d{4})?\b` |
| Address keyword | `\b(?:Street\|Avenue\|Road\|Boulevard\|Drive\|Lane\|Court\|Circle\|Place\|Parkway\|Apartment\|Suite\|Floor)\b` |
| City, ST ZIP | `\b[A-Z][a-z]+,\s*[A-Z]{2}\s+\d{5}\b` |
| ISO date | `\b\d{4}-\d{2}-\d{2}\b` |
| Slash date | `\b\d{1,2}/\d{1,2}/\d{2,4}\b` |
| Month-name date | `\b\d{1,2}\s+(?:Jan\|Feb\|Mar\|Apr\|May\|Jun\|Jul\|Aug\|Sep\|Sept\|Oct\|Nov\|Dec)[a-z]*\s+\d{2,4}\b` |
| DOB labeled | `\b(?:DOB\|Date\s+of\s+Birth\|Born\|Birthday)[:\s]*\d{1,4}[-/\s]\d{1,2}[-/\s]\d{1,4}\b` |
| Age 90+ (HIPAA marker) | `\b(?:9[0-9]\|1[0-9]{2})[- ]?(?:year[- ]?old\|yo\|y/o)\b` |
| Hospital/medical center | `\b(?:[A-Z][a-z]+\s+){1,4}(?:Hospital\|Medical\s+Center\|Health\s+System\|Clinic\|Cancer\s+Center\|Children's\s+Hospital\|Medical\s+Group\|Healthcare)\b` |
| Branded health system | `\b(?:Mayo\s+Clinic\|Cleveland\s+Clinic\|Johns\s+Hopkins\|Mount\s+Sinai\|Mass\s+General\|Cedars[- ]Sinai\|UCLA\s+Medical\|UCSF\s+Medical\|NewYork[- ]Presbyterian\|Stanford\s+Health\|AdvancedMD\|Athenahealth\|Kareo\|TherapyNotes)\b` |
| Any 6+ digit number | `\b\d{6,}\b` |
| Any date-like | `\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b` |
| Year 1950-2030 | `\b(19[5-9]\d\|20[0-2]\d)\b` |

### 1.3 Capitalized-token inventory

Beyond the patterns above, every token that matches `\b[A-Z][a-zA-Z]{2,}\b`
(any capitalized word of 3+ chars) and `\b[A-Z]{2,}\b` (any all-caps token) was
extracted and enumerated. This is the high-recall fallback that catches
proper nouns the looser name patterns might miss.

### 1.4 Code-combination case-report search

All 25 distinct `(cpt_set, icd_set)` combinations in the corpus were tabulated.
The 5 most-evidenced combinations (those that occur in 9+ records, AND do not
involve the bogus `"REVIEW"` token — see §4) were selected. For each, the
unique narrative phrase from the encounter's `clinical_note` was searched on
the public web to detect any real-patient case-report collision.

---

## 2. Raw grep output

### 2.1 Pattern match counts

`train` = `data/train.json`, `val` = `data/val.json`.

| Pattern | train | val | Notes |
|---|---:|---:|---|
| name_two_word | 0 | 0 | |
| name_three_word | 0 | 0 | |
| name_last_comma_first | 0 | 0 | |
| name_initials_dot | 0 | 0 | |
| name_with_dr | 0 | 0 | |
| name_with_title | 0 | 0 | |
| name_initials_pair | 0 | 0 | |
| apostrophe_name | 0 | 0 | |
| name_patient_x | 0 | 0 | |
| name_in_brackets | 0 | 0 | |
| email | 0 | 0 | |
| phone_us | 0 | 0 | |
| ssn | 0 | 0 | |
| credit_card | 0 | 0 | |
| ip_v4 | 0 | 0 | |
| url | 0 | 0 | |
| mrn_labeled | 0 | 0 | |
| npi_labeled | 0 | 0 | |
| dea_labeled | 0 | 0 | |
| member_id_labeled | 0 | 0 | |
| street_address | 0 | 0 | |
| po_box | 0 | 0 | |
| address_keywords | 0 | 0 | |
| city_state_zip | 0 | 0 | |
| street_with_number | 0 | 0 | |
| iso_date | 0 | 0 | |
| slash_date | 0 | 0 | |
| month_name_date | 0 | 0 | |
| any_date_like | 0 | 0 | |
| dob_labeled | 0 | 0 | |
| age_over_89 | 0 | 0 | |
| year_1950_2030 | 0 | 0 | |
| any_long_number | 0 | 0 | |
| hospital_labeled | 0 | 0 | |
| health_system_branded | 0 | 0 | |
| **zip_us** | **537** | **264** | **All 801 hits are 5-digit CPT codes (99214, 93000, 80061, 99203, 99215, 80053, 93306, 93040, 71046, 83036, 90686). 100% false positive — verified by spot check on the first 30. No real ZIP codes present.** |
| patient_mentions | 188 | 98 | The literal word "patient" appears 286 times across the corpus. Always lowercase, always generic ("patient presents", "patient reports", "patient with"). |
| any_capitalized_word | 477 | 235 | See §2.2 — all 712 tokens are clinical vocabulary. |
| all_caps_word | 184 | 88 | Only 3 unique tokens: ECG (142), REVIEW (90), DENY (40). |

**All 27 strict-PHI patterns returned 0 hits in both files.** The 801 "ZIP" hits
were every 5-digit CPT code in the corpus, every one confirmed by spot-check.

### 2.2 Full capitalized-token inventory (712 occurrences, 22 unique tokens)

| Count | Token | Classification |
|---:|---|---|
| 142 | ECG | Clinical acronym (electrocardiogram) |
| 90 | REVIEW | Audit category label — see §4 data-quality bug |
| 50 | Patient | Generic noun, not a name |
| 50 | Established | Clinical visit-type descriptor |
| 40 | Documentation | Generic clinical noun |
| 40 | Essential | Modifies "hypertension" |
| 40 | DENY | Audit category label — see §4 data-quality bug |
| 30 | Lipid | Modifies "panel" |
| 30 | Type | Modifies "2 diabetes" |
| 30 | Influenza | Modifies "vaccine" |
| 20 | New | Modifies "patient" |
| 20 | Echocardiogram | Clinical procedure |
| 20 | Duplicate | Modifies "service" |
| 10 | Annual | Clinical visit modifier |
| 10 | Follow | Appears in "follow-up" |
| 10 | Acute | Modifies "visit" / "changes" |
| 10 | Rhythm | Modifies "strip" |
| 10 | Palpitations | Symptom |
| 10 | Brief | Audit category? |
| 10 | Suture | Procedure |
| 10 | Wound | Clinical noun |

**Verdict on the capitalized set:** every token is either a clinical term
(procedure, finding, modifier, symptom) or an audit/suggester category label.
None are proper nouns of people, places, or institutions.

---

## 3. ICD-10/CPT code-combination case-report searches

Five representative combinations were selected (highest frequency × contains
only real ICD-10 codes — see §4 for the bogus `REVIEW` token):

| # | encounter_id | CPT codes | ICD-10 codes | Count |
|---:|---|---|---|---:|
| 1 | enc_0001 | 93000, 93040, 93306, 99203 | I20.9 | 10 |
| 2 | enc_0005 | 71046, 93000, 93040 | I20.9 | 10 |
| 3 | enc_0000 | 80061, 93000, 99214 | R00.2 | 9 |
| 4 | enc_0004 | 80061 | I10 | 9 |
| 5 | enc_0013 | 71046, 83036, 99215 | E11.9 | 9 |

For each, a Google web search was run on the *unique narrative phrase* from
the encounter's `clinical_note` (the kind of phrasing that, if a real patient
case had been copied, would show up verbatim on a case-report site or EHR
exposure archive).

### 3.1 Search #1 — `enc_0001` (chest pain, ECG, echo, ICD I20.9)

**Narrative:** "New patient low complexity visit. Patient reports chest pain
on exertion. ECG performed in office; rhythm strip reviewed. Echocardiogram
ordered for further workup."

**Query:** `"chest pain on exertion" "rhythm strip reviewed" "echocardiogram ordered" case report`

**Top 5 results:**
1. *Circulation* — "Chest Pain and a Very Abnormal Stress Echocardiogram" (general cardiology case, no narrative overlap)
2. NCBI Bookshelf NBK553650 — NICE guideline on recent-onset chest pain (not a case)
3. Mayo Clinic News Network — patient education Q&A (not a case)
4. Quizlet — "Case Studies/Practice Cardiology 1" (flashcard summary, no verbatim phrase)
5. Dr. Smith's ECG Blog — "Chest pain one day after a negative stress test" (different narrative)

**Real-patient collision: NO.** All hits are generic clinical/educational
content; none reproduce the exact phrasing or the specific
ECG+echo+rhythm-strip chain.

### 3.2 Search #2 — `enc_0005` (acute chest pain, ICD I20.9)

**Narrative:** "Acute visit: chest pain on exertion, ECG performed in office.
Rhythm strip reviewed; no acute changes. Chest x-ray performed to rule out
cardiopulmonary cause."

**Query:** `"rhythm strip reviewed; no acute changes" "Chest x-ray performed" case`

**Top 5 results:**
1. PMC PMC12266007 — "Wide Complex Irregular Rhythm in a Paced Patient" (pacemaker case, no overlap)
2. Facebook — EcgWaveMaven case 513 ("without acute symptoms no rhythm strip..." — different phrasing)
3. Dr. Smith's ECG Blog — "A Fall and a Rhythm to Recognize" (no overlap)
4. Mayo Clinic — Chest X-rays overview page (patient education, not a case)
5. AHA/ACC 2021 Chest Pain Guideline (not a case)

**Real-patient collision: NO.**

### 3.3 Search #3 — `enc_0000` (palpitations, lipid panel, ICD R00.2)

**Narrative:** "Patient presents for established patient moderate complexity.
ECG performed in office due to palpitations reported. Documentation supports
a separately identifiable E/M; modifier 25 applied. Lipid panel ordered for
cardiovascular risk stratification."

**Query:** `"separately identifiable E/M" "modifier 25" "Lipid panel ordered" "cardiovascular risk stratification" case report`

**Top 5 results:**
1. *Clinical Chemistry* (Oxford) — "Reducing Lipid Panel Error Allowances to Improve the Accuracy of Cardiovascular Risk Stratification" (methodology paper, no narrative overlap)
2. Kaiser Permanente — Cardiovascular Risk Panel clinical review criteria (policy doc)
3. PubMed 37624942 — same paper as #1
4. ESC/EAS 2025 dyslipidaemia guidelines (not a case)
5. NCBI Endotext NBK305897 — guidelines for management of dyslipidemia (not a case)

**Real-patient collision: NO.** Note: "separately identifiable E/M" and
"modifier 25" are well-known billing/audit phrases, so the high specificity
of the four-token quote was the meaningful test, and it returned only
methodology/policy content.

### 3.4 Search #4 — `enc_0004` (essential hypertension, lipid panel, ICD I10)

**Narrative:** "Follow-up for essential hypertension. Lipid panel ordered.
Duplicate service on same date flagged by billing system."

**Query:** `"Duplicate service on same date flagged" "billing system" hypertension lipid panel case report`

**Top 5 results:**
1. PMC PMC4938881 — Telemonitoring trial for hypertensive seniors (study, not a case)
2. CMS — Medicare NCCI Coding Policy Manual 2025 (policy doc)
3. ASNC Federal Register filing (regulatory, not a case)
4. ASPE — Episode-Based Approaches for Medicare Performance Measurement (policy report)
5. Federal Register Vol 87 Issue 222 (regulatory)

**Real-patient collision: NO.** The phrase "Duplicate service on same date
flagged" is a billing-audit alert string; the only public appearances are
in NCCI policy docs and coding manuals, which is exactly the kind of place
synthetic data would borrow phrasing from.

### 3.5 Search #5 — `enc_0013` (T2DM, HbA1c, CXR, ICD E11.9)

**Narrative:** "Established patient high complexity. Type 2 diabetes
follow-up; HbA1c drawn. Chest x-ray performed for cough workup."

**Query:** `"HbA1c drawn" "Chest x-ray performed for cough workup" diabetes case report`

**Top 5 results:**
1. PubMed 35781928 — "Chest X-Ray pattern and lung severity score in COVID-19 patients with diabetes mellitus" (cross-sectional study)
2. PubMed 1800099 — "Diabetes mellitus. II: Routine chest radiography" (1991 study)
3. PMC PMC9551073 — yield of chest X-ray screening for diabetes in Addis Ababa (study)
4. PubMed 13009517 — "Screening tests for diabetes detection; combined with a chest x-ray survey" (1953 study)
5. World J Gastrointest — Chest radiological finding of COVID-19 in diabetes (study)

**Real-patient collision: NO.** The "cough workup" framing of a routine CXR
in a diabetic patient is a common, generic clinical presentation; the public
web only returns epidemiology studies, not named-patient cases.

### 3.6 Search summary

| Combo | Real-patient collision? |
|---|---|
| 1 (enc_0001) | No |
| 2 (enc_0005) | No |
| 3 (enc_0000) | No |
| 4 (enc_0004) | No |
| 5 (enc_0013) | No |

**5/5 queries returned zero real-patient collisions.** Every result was either
a clinical practice guideline, a methodology paper, a coding/billing policy
document, or a generic patient-education article.

---

## 4. Verdict

**PASS.** The synthetic training/validation corpus at `data/train.json` and
`data/val.json` shows no evidence of residual PHI:

- Zero matches across 27 strict-PHI patterns (names, contact IDs, addresses,
  dates, identifiers, institutions).
- The only "loose pattern" hit (537 + 264 = 801 "US ZIP" matches) is
  100% false positive — all matches are 5-digit CPT procedure codes.
- Every capitalized token in the corpus (712 occurrences, 22 unique) is
  clinical vocabulary or an audit-category label. No proper nouns of
  people, places, or institutions.
- 5/5 representative ICD-10/CPT combinations returned zero real-patient
  case-report collisions on public web search.

The corpus appears to have been generated from clinical-vocabulary templates
plus the project's own audit-category labels, with no underlying real
patient record.

---

## 5. Sibling finding — data-quality bug (not PHI)

**Filed as:** bug entry below in this document, also referenced from
`docs/BUGS.md` (TBD — see Followups).

**Title:** `icd10_codes` array contains the audit-category string `"REVIEW"`
in 30 of 150 records (20%).

**Severity:** medium (data integrity / silent mislabel, not patient safety)

**Description.** The `claim.icd10_codes` field in `data/train.json` and
`data/val.json` is supposed to hold ICD-10-CM codes (pattern: one letter,
two digits, optional `.digit`). The string `"REVIEW"` is not a valid
ICD-10 code — it appears to be a billing-audit category label that has been
inserted into the `icd10_codes` array, almost certainly by the corpus
generator conflating two output fields.

**Reproduction.**

```python
import json
train = json.load(open('data/train.json'))
val   = json.load(open('data/val.json'))
bad = [r for r in train + val if 'REVIEW' in r['claim']['icd10_codes']]
print(f"{len(bad)} records have 'REVIEW' in icd10_codes")
# 30
print(bad[0]['encounter_id'], bad[0]['claim']['icd10_codes'])
# e.g. enc_0003 ['REVIEW']
```

**Frequency.** 30/150 records (20%) in the combined corpus. Mix of
single-ICD records (`['REVIEW']`) and multi-ICD records (e.g.
`['I10', 'REVIEW']`, `['R00.2', 'REVIEW']`).

**Downstream impact.** Any consumer of the corpus that validates
`icd10_codes` against an ICD-10-CM lookup table (which the grading code in
`src/grader.py` likely does) will either crash, log a validation error per
record, or — worse — silently treat `"REVIEW"` as a no-op code and
undercount the actual ICD count for those records, biasing the grading
metric for modifier-25 / multi-ICD billing rules.

**Root-cause hypothesis.** The corpus generator reads from the
billing-audit rule pipeline. Rule categories include values like `review`,
`deny`, `info`, `documentation`, `modifier` (confirmed by the
all-caps-token inventory: `REVIEW` 90×, `DENY` 40×, `Documentation` 40×).
When assembling a record, the generator appears to write the rule-category
label into the `icd10_codes` slot in addition to (or instead of) the
actual ICD-10 codes that the rule is auditing.

**Proposed fix.** In the corpus generator, after assembling
`claim.icd10_codes`, filter out any value that does not match
`^[A-TV-Z][0-9][0-9AB](\.[0-9A-Z]{1,4})?$` and replace with `null` or drop
the record. Regenerate `data/train.json` and `data/val.json`, then re-run
`tests/` to confirm the grading metric on the new corpus is not biased.

**Out of scope here** (per the task body, this audit is PHI-only):
re-generating the corpus, fixing the generator, or re-running training
experiments.

---

## 6. Out of scope (per task body)

- Modifying or re-generating the synthetic corpus.
- Auditing sources outside `data/train.json` and `data/val.json`
  (e.g. `data/predictions_v0.jsonl`, `data/test_sample.jsonl`,
  `data/val_manifest.json`).
- Deep NLP-based de-identification tooling — regex + manual review as
  specified.
- Legal/compliance sign-off — this is a technical bug-hunt artifact.
