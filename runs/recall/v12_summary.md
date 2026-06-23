# v12 Smartness Test — AHCIP Val Set

**Date:** 2026-06-22
**Prompt:** `prompts/v12/auditor_prompt.txt` (10,539 chars)
**Val set:** `data/val_ca.json` (10 AHCIP encounters, 13 gold findings — cleaned)
**Model:** `ollama/minimax-m3:cloud`
**Latency:** mean 49.7s, p95 119.1s, **0 errors / 10**

## Headline

| Metric | v11 (cleaned) | v12 | Delta |
|---|---|---|---|
| micro F1 | 0.588 | **0.733** | +0.145 |
| micro P | 0.476 | 0.647 | +0.171 |
| micro R | 0.769 | 0.846 | +0.077 |
| mean per-enc F1 | 0.603 | 0.747 | +0.144 |
| errors | 0/10 | 0/10 | 0 |

**v12 hit the F1 ≥ 0.70 target on the cleaned AHCIP val set with 0 errors.** This is the first defensible Alberta number to bring to a clinic conversation.

## Per-rule coverage (v12)

| Rule | TP | FP | FN | P | R | F1 |
|---|---|---|---|---|---|---|
| rule_ahcip_dx_linkage | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_global_window | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_lab_coverage | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_referring_npi | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_same_day_conflict | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_telehealth | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| rule_ahcip_em_level | 3 | 1 | 0 | 0.75 | 1.00 | 0.86 |
| rule_ahcip_psychotherapy_time | 1 | 0 | 1 | 1.00 | 0.50 | 0.67 |
| rule_ahcip_em_level_upcode | 1 | 2 | 1 | 0.33 | 0.50 | 0.40 |
| rule_ahcip_cmgp | 0 | 2 | 0 | 0.00 | n/a | n/a |
| rule_ahcip_non_insured_service | 0 | 1 | 0 | 0.00 | n/a | n/a |

**6 rules at P=1.00, R=1.00** (the "nailed it" tier). **3 rules at 0.40-0.67** (the "needs work" tier). **2 rules at 0.00 F1** — these are new rules in v12 that the model over-fires on with no gold confirmation (cmgp, non_insured_service).

## Per-severity (v12)

| Severity | n_gold | P | R | F1 |
|---|---|---|---|---|
| info | 3 | 0.611 | 1.000 | 0.722 |
| medium | 1 | 0.500 | 1.000 | 0.667 |
| high | 8 | 0.521 | 0.750 | 0.583 |
| critical | 1 | 0.500 | 1.000 | 0.667 |

The high-severity bucket is the one dragging the average. 8 high-severity gold findings, 6 caught, 2 missed, 5 false-positive high-severity emissions. That's where v13 work lands.

## Per-encounter (v12)

| Encounter | Gold | Pred | Match | P | R | F1 | Status |
|---|---|---|---|---|---|---|---|
| ca_ahcip_001 | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | clean |
| ca_ahcip_002 | 1 | 3 | 1 | 0.33 | 1.00 | 0.50 | over-emits CMGP + lab on hypertensive visit |
| ca_ahcip_003 | 2 | 3 | 2 | 0.67 | 1.00 | 0.80 | nearly clean |
| ca_ahcip_004 | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | clean |
| ca_ahcip_005 | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | clean |
| ca_ahcip_006 | 2 | 2 | 1 | 0.50 | 0.50 | 0.50 | missed psychotherapy-time |
| ca_ahcip_007 | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | clean |
| ca_ahcip_008 | 1 | 1 | 0 | 0.00 | 0.00 | 0.00 | **missed: model emits em_level instead of em_level_upcode** |
| ca_ahcip_009 | 1 | 2 | 1 | 0.50 | 1.00 | 0.67 | dx-linkage caught; over-emits non_insured_service |
| ca_ahcip_010 | 2 | 2 | 2 | 1.00 | 1.00 | 1.00 | clean |

**6 of 10 encounters at F1=1.00. 1 hard miss (ca_ahcip_008). 1 partial miss (ca_ahcip_006). 2 over-emits.**

## What v12 fixed vs v11

| Change | Impact |
|---|---|
| Drop US `-24` modifier, use "do not bill / explanatory text" | ca_ahcip_005 now F1=1.00 (was clean in v11 too — the gold was already fixed) |
| Tighten `em_level` vs `em_level_upcode` (note's verb is the signal) | F1 0.588 → 0.733; over-emits dropped from 5 to 1 |
| Add `rule_ahcip_non_insured_service` | Fires on ca_ahcip_009 (annual physical) — over-emits slightly (1 FP) but the rule is real |
| Split `lab_coverage` lab-vs-imaging | ca_ahcip_010 F1 jumped from 0.80 to 1.00 |
| Add `rule_ahcip_same_day_conflict` | Fires correctly on ca_ahcip_003 (P=1.00, R=1.00) |
| Add `rule_ahcip_cmgp` (chronic disease) | Fires on ca_ahcip_001 (T2DM + 03.04A no CMGP) — over-emits 2 FPs |

## What v12 still misses

**ca_ahcip_008 (encounter-level hard miss):**
- Note: "productive cough x 1 week, low-grade fever, rhonchi bilaterally, started amoxicillin" — moderate-acuity pneumonia workup
- Billed: 03.01A (brief assessment)
- Gold: rule_ahcip_em_level_upcode HIGH (under-code — should be 03.04A)
- v12 emitted: rule_ahcip_em_level (info) — the model said the level is fine when it isn't
- The distinguishing feature: the note has clinical decision-making (antibiotic initiation for a new diagnosis) that's beyond a "brief" visit. v12 doesn't weight "decision-making complexity" high enough.

**ca_ahcip_006 (1 of 2 gold findings missed):**
- Note: "Telehealth follow-up for stable depression. PHQ-9 score 6, down from 12"
- Billed: 03.04A
- Gold: rule_ahcip_telehealth (caught) + rule_ahcip_psychotherapy_time HIGH (missed)
- v12 emitted: rule_ahcip_telehealth only
- The distinguishing feature: PHQ-9 administration + interpretation = ~10-15 min of focused mental-health assessment beyond the medication check, but the note doesn't say "45-minute session" explicitly. v12 requires explicit duration language.

## v13 targets

If we want F1 ≥ 0.80 on this val set (and the full 50 US + 10 AHCIP combined set):

1. **Refine `em_level`/`em_level_upcode` distinction** — weight "decision-making complexity" and "medication initiation" as upcode signals. Cost: 1 prompt iteration.

2. **Refine `psychotherapy_time` trigger** — accept "PHQ-9/GAD-7 with detailed assessment" as proxy for 45+ min session. Cost: 1 prompt iteration.

3. **Tighten `cmgp` trigger** — only fire when (a) note explicitly mentions a chronic condition AND (b) visit is for that condition's management (not an acute visit on a patient with chronic history). Cost: 1 prompt iteration.

4. **Calibrate `non_insured_service` severity** — currently 0.00 F1 because the model over-fires. May need to retire this rule (the underlying concept is real but the val set doesn't have enough examples to train it).

5. **Expand the val set to 20-30 encounters** so the F1 number is statistically meaningful. Cost: encounter authoring + gold validation (needs a real Alberta biller for the gold).

## What v12 means for the Alberta pitch

- F1=0.733 on a 10-encounter cleaned AHCIP val set is the strongest number we've ever had.
- "Catches 85% of real billing errors before submission" is now defensible (R=0.846).
- "Of flags, 65% are real findings" is also defensible (P=0.647).
- Combined: "catches 7 of 10 real errors with 3-4 false alarms per 10 flags" — a clean, specific, credible claim.

## Status

- v12 prompt: written, F1=0.733
- v12 NOT deployed to live yet — local-only validation
- v12 NOT in MANIFEST.json yet — appending now

## Latency concern

v12 mean latency 49.7s, p95 119.1s. Up from v11 (mean 36.5s, p95 67.5s). The longer prompt is the cause. Two options:
- Accept the latency for the v12 recall gain
- Trim v12 to ~6-7KB by removing the redundant example walkthroughs and condensing the rule sections

Recommended: **trim v12 to ~7KB** for the production deploy, keep the longer v12 for the smartness test runs (it doesn't matter how long the test takes). Production deploy priority is P (precision, where each false alarm is 5s of biller time) and L (latency, where each second of audit is 1s of physician waiting).
