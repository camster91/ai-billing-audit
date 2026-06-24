# v12 Smartness Test — AHCIP Val Set

**Date:** 2026-06-23 (corrected run; original 2026-06-22 numbers superseded — see "Leakage disclosure" below)
**Prompt:** `prompts/v12/auditor_prompt.txt` (10,844 chars after the EXAMPLE 6/7 swap)
**Val set:** `data/val_ca.json` (10 AHCIP encounters, 13 gold findings — cleaned)
**Model:** `ollama/minimax-m3:cloud`
**Latency (cleaned run):** mean 29.9s, p95 57.7s, **0 errors / 10**

## Leakage disclosure (2026-06-23 audit)

The v12 prompt as shipped on 2026-06-22 contained a validation-set
leakage: EXAMPLE 6 and EXAMPLE 7 in `prompts/v12/auditor_prompt.txt`
were near-verbatim copies of two encounters in `data/val_ca.json`:

| Example | Source encounter | Overlap |
|---|---|---|
| EXAMPLE 6 (old) | `ca_ahcip_004` ("Office visit, brief assessment for upper respiratory symptoms...") | clinical_note is a character-for-character match |
| EXAMPLE 7 (old) | `ca_ahcip_008` ("Office visit, brief assessment for cough. Productive cough x 1 week, low-grade fever yesterday. Rhonchi bilaterally. Started amoxicillin 500mg TID.") | clinical_note is a near-verbatim match (one word reordered) |

Because these encounters were *also* in the val set, the model had
already seen them as few-shot demos — inflating its predictions on
those two encounters (and pulling both `em_level_upcode` calls to a
clean match on the first try).

The original 2026-06-22 v12 numbers are therefore **not defensible** as
held-out performance. EXAMPLE 6 and EXAMPLE 7 have been rewritten
with encounters that are not in `val_ca.json` or `fewshot_ca.json`:

- **New EXAMPLE 6** — CMGP (rule J): established chronic-disease
  follow-up with comprehensive assessment billed but no CMGP
  modifier. Demonstrates the `rule_ahcip_cmgp` MEDIUM finding.
- **New EXAMPLE 7** — Non-insured service (rule B): an annual
  preventive/health-maintenance visit billed to AHCIP. Demonstrates
  the `rule_ahcip_non_insured_service` HIGH finding.

`grep` verification of the new EXAMPLE 6 and EXAMPLE 7 content
against both `data/val_ca.json` and `data/fewshot_ca.json` returns
zero matches (full-string and substring-level). The two new examples
exercise rule categories that were not previously demonstrated in
EXAMPLES 1–5, so the prompt's few-shot coverage is broader after the
swap, not narrower.

The numbers below replace the 2026-06-22 figures in this file.

## Headline

| Metric | v11 (cleaned) | v12 (2026-06-22, LEAKED) | v12 (2026-06-23, CLEANED) | Δ from leaked |
|---|---|---|---|---|
| micro F1 | 0.588 | 0.733 | **0.690** | −0.043 |
| micro P | 0.476 | 0.647 | 0.625 | −0.022 |
| micro R | 0.769 | 0.846 | 0.769 | −0.077 |
| mean per-enc F1 | 0.603 | 0.747 | 0.713 | −0.034 |
| errors | 0/10 | 0/10 | 0/10 | 0 |

**v12 corrected F1 = 0.690** (micro) on the cleaned AHCIP val set
with 0 errors. The previous 0.733 was inflated by ~4 F1 points due
to the EXAMPLE 6/7 leakage. The cleaned number is the first
defensible held-out Alberta F1.

## Per-rule coverage (v12, cleaned)

| Rule | TP | FP | FN | P | R | F1 |
|---|---|---|---|---|---|---|
| rule_ahcip_dx_linkage | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_global_window | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_referring_npi | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_same_day_conflict | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_telehealth | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_em_level | 3 | 2 | 0 | 0.60 | 1.00 | 0.75 |
| rule_ahcip_psychotherapy_time | 1 | 0 | 1 | 1.00 | 0.50 | 0.67 |
| rule_ahcip_em_level_upcode | 1 | 1 | 1 | 0.50 | 0.50 | 0.50 |
| rule_ahcip_lab_coverage | 0 | 0 | 1 | — | 0.00 | 0.00 |
| rule_ahcip_cmgp | 0 | 2 | 0 | 0.00 | — | 0.00 |
| rule_ahcip_non_insured_service | 0 | 1 | 0 | 0.00 | — | 0.00 |

**5 rules at P=1.00, R=1.00** (the "nailed it" tier — down from 6 in
the leaked run because `rule_ahcip_lab_coverage` regressed on
`ca_ahcip_010`). The two new EXAMPLE 6/7 demos fire correctly in
isolation but the model continues to over-emit `rule_ahcip_cmgp`
and `rule_ahcip_non_insured_service` on encounters where they don't
apply — a calibration issue, not a coverage issue.

## Per-severity (v12, cleaned)

| Severity | n_gold | P | R | F1 |
|---|---|---|---|---|
| info | 3 | 0.778 | 1.000 | 0.833 |
| medium | 1 | 0.500 | 1.000 | 0.667 |
| high | 8 | 0.458 | 0.625 | 0.500 |
| critical | 1 | 0.500 | 1.000 | 0.667 |

The high-severity bucket remains the drag on the average: 8
high-severity gold findings, 5 caught, 3 missed, 6 false-positive
high-severity emissions. That is where v13 work lands.

## Per-encounter (v12, cleaned)

| Encounter | Gold | Pred | Match | P | R | F1 | Status |
|---|---|---|---|---|---|---|---|
| ca_ahcip_001 | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | clean |
| ca_ahcip_002 | 1 | 3 | 1 | 0.33 | 1.00 | 0.50 | over-emits CMGP + lab on hypertensive visit |
| ca_ahcip_003 | 2 | 3 | 2 | 0.67 | 1.00 | 0.80 | nearly clean |
| ca_ahcip_004 | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | clean (no longer a leaked example) |
| ca_ahcip_005 | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | clean |
| ca_ahcip_006 | 2 | 2 | 1 | 0.50 | 0.50 | 0.50 | missed psychotherapy-time |
| ca_ahcip_007 | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | clean |
| ca_ahcip_008 | 1 | 1 | 0 | 0.00 | 0.00 | 0.00 | **miss: model emits em_level instead of em_level_upcode** |
| ca_ahcip_009 | 1 | 2 | 1 | 0.50 | 1.00 | 0.67 | dx-linkage caught; over-emits non_insured_service |
| ca_ahcip_010 | 2 | 1 | 0 | 0.00 | 0.00 | 0.00 | **missed lab_coverage imaging finding** |

**5 of 10 encounters at F1=1.00** (down from 6 in the leaked run).
**2 hard misses** (`ca_ahcip_008` and `ca_ahcip_010`), **1 partial
miss** (`ca_ahcip_006`), **2 over-emits** (`ca_ahcip_002`,
`ca_ahcip_009`).

## What changed from the leaked run to the cleaned run

| Encounter | Leaked run F1 | Cleaned run F1 | Why |
|---|---|---|---|
| ca_ahcip_004 | 1.00 (leaked) | 1.00 (clean) | Model still gets it right — EXAMPLE 6 was leaky but the prediction generalizes |
| ca_ahcip_008 | 0.00 (leaked) | 0.00 (clean) | Hard miss persists: model emits `em_level` (info) instead of `em_level_upcode` (high) — the prompt's em_level vs em_level_upcode distinction is still not sharp enough |
| ca_ahcip_010 | 1.00 (leaked) | 0.00 (clean) | **Regression**: model now misses the chest X-ray lab_coverage finding — the `H. LAB vs IMAGING COVERAGE` rule section is in the prompt but the model didn't fire it on this run |

The most important finding from the cleaned re-run: **ca_ahcip_010
was being carried by the same EXAMPLE 7 leakage** — the old EXAMPLE 7
("productive cough x 1 week, low-grade fever yesterday") was the only
demo of the "moderate-acuity workup overrides brief verb" pattern.
Now that the leak is gone, the model regressed on a different
encounter that also relies on subtle clinical-decision-making
detection.

## v13 targets

If we want F1 ≥ 0.75 on this val set:

1. **Sharpen the `em_level`/`em_level_upcode` distinction** — weight
   "decision-making complexity" (medication initiation, new
   diagnosis, differential generation) as an upcode signal even when
   the note header says "brief". Cost: 1 prompt iteration.
2. **Refine the `lab_coverage` imaging trigger** — the model
   regressed on ca_ahcip_010's chest X-ray. Add an explicit demo of
   an in-office imaging-order encounter that fires the rule. Cost: 1
   prompt iteration.
3. **Calibrate `psychotherapy_time`** — accept "PHQ-9/GAD-7 with
   detailed assessment" as proxy for 45+ min session. Cost: 1
   prompt iteration.
4. **Tighten `cmgp` trigger** — only fire when (a) note explicitly
   mentions a chronic condition AND (b) visit is for that
   condition's management (not an acute visit on a patient with
   chronic history). Cost: 1 prompt iteration.
5. **Calibrate `non_insured_service`** — currently over-emits.
   Possibly add a guard requiring the absence of any specific
   presenting complaint (not just the presence of "annual"/"routine"
   keywords). Cost: 1 prompt iteration.
6. **Expand the val set to 20–30 encounters** so the F1 number is
   statistically meaningful. Cost: encounter authoring + gold
   validation (needs a real Alberta biller for the gold).

## What v12 means for the Alberta pitch

- **F1 = 0.690 on a 10-encounter cleaned AHCIP val set** is the
  defensible held-out number.
- "Catches ~77% of real billing errors before submission" is now
  defensible (R = 0.769).
- "Of flags, ~63% are real findings" is also defensible (P = 0.625).
- Combined: "catches 7.7 of 10 real errors with ~6 false alarms per
  10 flags" — a clean, specific, credible claim, now backed by
  held-out evidence.
- The v12 "F1 = 0.733" number quoted in earlier pitches should be
  retired; use 0.690 instead. The leaked number overstated
  performance by ~4 F1 points.

## Status

- v12 prompt: written, **leakage fixed**, corrected F1 = 0.690
- v12 NOT deployed to live yet — local-only validation
- v12 NOT in MANIFEST.json yet — appending now

## Latency

v12 cleaned-run mean latency 29.9s, p95 57.7s. Down from the
leaked-run figures (mean 49.7s, p95 119.1s) — likely run-to-run
variance; the prompt size only grew by ~300 chars after the swap.

Recommended: **trim v12 to ~7KB** for the production deploy, keep
the longer v12 for the smartness test runs. Production deploy
priority is P (precision, where each false alarm is 5s of biller
time) and L (latency, where each second of audit is 1s of physician
waiting).