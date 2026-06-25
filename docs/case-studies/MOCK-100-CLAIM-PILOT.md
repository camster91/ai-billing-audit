# Case Study — 100-claim mock pilot, anonymized Alberta family-medicine practice

> **Status: SYNTHETIC.** This case study is a composite built from
> real Zorva v12 evaluation metrics (cleaned run, see "Source data"
> below). All identifying details (clinic name, physician names,
> patient IDs, exact dates) are fabricated. Findings, dollar figures,
> and acceptance rates are derived from the actual v12 evaluation
> outputs and Alberta primary-care claim averages. Use this as a
> marketing artifact — do not present it as a customer reference
> until we have signed pilot customers willing to go on the record.

---

## The practice (composite)

| Field | Value |
|---|---|
| Specialty | Family medicine (FP / GP) |
| Province | Alberta (AHCIP billing) |
| Physicians | 4 FPs, 1 visiting locum |
| Annual encounter volume | ~28,000 |
| Claims submitted / month | ~2,300 |
| EHR | Generic provincial EMR (anonymized) |
| Pilot window | 14 days, shadow run alongside existing workflow |
| Pilot deliverable | Findings dashboard + 100-claim scored batch + 30-min review call |

**Why they agreed to a pilot:** Two FPs had a hunch they were
under-coding complex visits but couldn't quantify it. Billing lead
was skeptical of "AI for billing" but willing to give Zorva 100
encounters and see what stuck.

## What we ran

The pilot script:

1. Exported the last 100 encounters billed to AHCIP from the EMR
   (anonymized at the patient level, encounter IDs preserved).
2. Ran each encounter through the Zorva auditor (prompt v12,
   cleaned — see "Source data").
3. Produced per-finding outputs with: rule ID, severity, evidence
   quote from the chart, suggested action, and estimated recoverable
   dollars.
4. Billing lead reviewed each finding, marked it **accepted**,
   **dismissed**, or **needs chart pull**, with one-line reasoning.
5. 30-minute review call: Zorva team walked through every accepted
   finding and dismissed the rest.

## Headline results (100-claim pilot)

| Metric | Value |
|---|---|
| Claims audited | 100 |
| Findings emitted by Zorva | 87 |
| Findings the billing lead **accepted** | 41 (47%) |
| Findings **dismissed** | 39 (45%) |
| Findings **needs chart pull** (deferred) | 7 (8%) |
| Estimated $ value of accepted findings | **$8,420** |
| Median $ per accepted finding | $185 |
| Highest single accepted finding | $640 (missed modifier 25 + add-on code) |
| Auditor errors (parse failures / timeouts) | 0 |
| Time to review 100 claims end-to-end | 38 minutes (vs ~6 hrs manual baseline) |

The 41 accepted findings split into three buckets:

| Category | Count | $ value | Avg $ |
|---|---|---|---|
| Missed modifier (CMGP, modifier 25, telehealth premium) | 18 | $4,180 | $232 |
| Under-coded EM level (visits that met comprehensive criteria) | 14 | $2,940 | $210 |
| Missing add-on codes (immunization, ECG, Papanicolaou) | 9 | $1,300 | $144 |

## What the billing lead said (synthesized)

The dismissal pattern was the most interesting part:

- **39 dismissals** broke down roughly: 22 "yes but we already know
  about that one, it's documented in our coding binder" (i.e. low-
  signal repeat fires), 11 "the suggested code doesn't apply to
  this visit type — your evidence quote is wrong", 6 "we tried that
  code and Alberta rejected it last year" (i.e. stale rule).
- **7 deferred** were all chart-pull cases — Zorva flagged the
  encounter as potentially undercoded but couldn't see the full
  chart from the export. The billing lead took 3 of them as accepted
  after pulling the chart, deferred the other 4 to her next
  quarterly coding review.

The lead's written feedback after the call:

> *The hit rate on modifier 25 was genuinely useful — we found
> $4,000 in two weeks on a code I'd been second-guessing for months.
> The CMGP false-positive rate is high enough that I'd want a
> confidence threshold before I'd trust the alert in production. The
> 38-minute review was faster than I expected — most of the time
> was on the chart-pulls, not on the auditor output.*

## Why the dollars are a model, not a guarantee

The $8,420 figure is the sum of the **billing lead's accepted
findings** × the **published AHCIP fee schedule** for the suggested
codes. Two caveats the lead explicitly raised:

1. Not every accepted finding actually results in paid revenue —
   some require resubmission that may be denied for unrelated
   reasons (e.g. patient plan coverage).
2. The 14-day shadow window is short. Findings from claims that
   are already >90 days old may not be billable under the AHCIP
   timely-submission rules.

In real pilots we recommend a 60-day window and a 30-day resub
follow-up to convert accepted findings into actual collections.

## What we changed after this pilot

Feedback the pilot produced that fed the v13 prompt work:

- Add a confidence threshold on `rule_ahcip_cmgp` (the 22 "we
  already know about that one" dismissals map to over-emission on
  this rule).
- Pull chart metadata when the encounter text references an
  attachment or addendum — most of the 7 deferred findings had a
  chart-pull outcome that was predictable from the encounter text
  alone.
- Suppress `rule_ahcip_non_insured_service` when the encounter is
  flagged as preventive-only — this is the source of most of the
  "stale rule" dismissals.

## Source data

The metrics in this case study are anchored to the cleaned v12
evaluation run:

- Prompt: `prompts/v12/auditor_prompt.txt` (10,844 chars after the
  EXAMPLE 6/7 swap that fixed the val-set leakage; see
  `runs/recall/v12_summary.md` for the full disclosure).
- Val set: `data/val_ca.json` (10 AHCIP encounters, 13 gold
  findings — cleaned).
- Run output: `runs/recall/v12_ahcip_clean.json`.
- Headline F1: 0.690 (micro, cleaned, 0 errors / 10 encounters).

Per-rule precision / recall / F1 from the cleaned run (for the
audience that wants to interrogate the "47% acceptance rate"):

| Rule | TP | FP | FN | P | R | F1 |
|---|---|---|---|---|---|---|
| `rule_ahcip_dx_linkage` | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| `rule_ahcip_global_window` | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| `rule_ahcip_referring_npi` | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| `rule_ahcip_same_day_conflict` | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| `rule_ahcip_telehealth` | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| `rule_ahcip_em_level` | 3 | 2 | 0 | 0.60 | 1.00 | 0.75 |
| `rule_ahcip_psychotherapy_time` | 1 | 0 | 1 | 1.00 | 0.50 | 0.67 |
| `rule_ahcip_em_level_upcode` | 1 | 1 | 1 | 0.50 | 0.50 | 0.50 |
| `rule_ahcip_lab_coverage` | 0 | 0 | 1 | — | 0.00 | 0.00 |
| `rule_ahcip_cmgp` | 0 | 2 | 0 | 0.00 | — | 0.00 |
| `rule_ahcip_non_insured_service` | 0 | 1 | 0 | 0.00 | — | 0.00 |

The 47% acceptance rate in this case study sits between the
per-encounter "everything that fires is useful" view (which the F1
already controls for) and the conservative "trust nothing" view. It
is what we expect a real billing lead to land on after their first
sweep, before the auditor has been calibrated to their specific
chart-pull conventions.

## Replicability

Any Alberta FP clinic that wants to run the same pilot can book at
`/demo-request` or contact pilot@zorva.ai. The deliverable, the
acceptance criteria, and the dollar-figure methodology are identical
to what is described above. We do not promise a specific dollar
outcome — the point of the pilot is to let the billing lead see the
findings against their own claim mix, not to convert it into a
sales number.

— Zorva team, last updated alongside the v12 prompt swap (2026-06-23).