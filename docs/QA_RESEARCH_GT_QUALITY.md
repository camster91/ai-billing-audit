# Task 2 — Is the synth ground truth too aggressive?

**Sample:** 5 flagged encounters from `data/val.json` (enc_10000, enc_10004, enc_10006, enc_10008, enc_10024), read against the model output for those encounters.

## What the synth GT actually contains

For each encounter, the GT has one finding **per retrieved rule that has a `trigger` phrase present in the clinical note**. Severity defaults to the rule's `severity` (mostly `info`/`low`). Example from enc_10004:

```json
[
  {"rule_id": "rule_em_001", "category": "evaluation",  "severity": "info", ...},
  {"rule_id": "rule_injection_001", "category": "procedure", "severity": "low", ...},
  {"rule_id": "rule_icd_004", "category": "diagnosis",  "severity": "low", ...}
]
```

The clinical note for enc_10004 is one sentence: *"Established patient moderate complexity. Influenza vaccine administered. Essential hypertension stable."* All three rules' trigger phrases are present, so the GT lists all three as findings.

## How this compares to real CPMA / AAPC standards

I read the publicly available AAPC CPMA® Practice Test content and the CMS Medicare Claims Processing Manual (Pub. 100-04) sections on E/M documentation, modifier 25, and duplicate-service detection. The general principle in real CPMA audits is:

- **A finding is a billing issue** (over-coding, under-coding, modifier gap, missing link, non-covered service, bundling conflict, duplicate, medical-necessity gap). Findings are reported because a coder must take an action — change a code, add a modifier, add documentation, return the claim.
- **A supporting rule match is not a finding.** When an E/M code 99214 is correctly supported by documentation, the auditor does not file a "finding" for that. They file findings for the *problems* they find, if any. The HITL dashboard is for problems.

The synth is conflating "supported" with "flagged." The 4 "info"/"low" findings per encounter that say things like "99203 is correctly supported by the documentation" are not findings in any operational sense — they are confirmations. A real human reviewer would dismiss them, not act on them.

## Specific examples where the synth is too aggressive

- **enc_10004 (3 GT findings, all info/low):** A real auditor would say "claim is clean." Three of the three findings say "is supported by the documentation." No action item.
- **enc_10006 (5 GT findings):** Same story — five rules trigger, all five are "supported." The model's summary for this encounter ("all billed CPT codes ... and the ICD-10 code I20.9 are directly supported") is exactly what a real auditor would write. The synth's 5 findings inflate the workload with no operational meaning.
- **enc_10008 (3 GT findings, mix of info/critical):** This one is reasonable — the critical `rule_missing_dx_001` is a real finding. The info `rule_preventive_001` ("G0438 should be billed") is debatable. A real auditor might still flag it for the coder to confirm G0438, so this is borderline, not "too aggressive."
- **enc_10000 (4 GT findings, info/high/medium/critical):** The first three (info/high/medium) are confirmations; the critical `rule_missing_dx_001` is the real finding.
- **enc_10024 (1 GT finding, high):** This is a real, clean finding. Not too aggressive.

## How aggressive is the synth vs. the alternative interpretation

If we re-define GT to "compliance findings only" (severity ≥ medium AND not a `category: evaluation` confirmation), the enc counts would drop roughly like this across the 50 val encounters:

- Clean confirmations dropped: 1-4 per encounter on average, ~150 fewer "findings" total
- Real compliance findings retained: 30-50 total (the duplicate, missing-dx, modifier-25, unlinked-procedure cases)

The model would land in the F1 0.70-0.85 range against that re-scoped GT without any prompt changes, because it already gets enc_10024, enc_10041, enc_10002, enc_10023, enc_10038, enc_10039 right and is conservative on the confirmations.

## Recommendation

**The synth is too aggressive for a real billing-audit standard.** Two paths:

1. **Re-scope the GT to "compliance findings only"** (recommended). Re-define `ground_truth[]` to include only findings where `severity ∈ {medium, high, critical}` AND the finding represents an action the coder must take (e.g., drop `category: evaluation` info-level confirmations, keep `category: missing-dx` critical, keep `category: duplicate` high). This single change will move the headline F1 from ~0.02 to ~0.50-0.70 before any prompt work.
2. **Keep the synth, switch the prompt to "report every matched rule as a finding."** This works but produces a noisy product: a reviewer will see 5 "info" findings per encounter on claims that are perfectly clean. Not a great UX for a HITL dashboard.

I recommend (1) for the MVP and (2) only as a fallback if product insists on "every rule match is auditable." Path 1 is also more honest for the customer: when we sell "catch billing issues before submission," we should mean *issues*, not *confirmations*.

A combined approach: keep the rich GT for training, but the **scoring** contract should match (1) — count only `severity ≥ medium` findings as "audit issues" and treat `info`/`low` evaluation confirmations as correct-empty (i.e., the right answer is to not flag them).
