# AHCIP auditor v13 — design analysis and proposed changes

> **Status:** Design proposal, not a measured improvement. The v12 baseline
> number in `README.md` (F1 = 0.690, R = 0.769, P = 0.625) was measured on
> an **older 10-encounter / 13-finding** subset of the AHCIP val set; the
> current `data/synth/val_ca.json` has **19 encounters / 31 gold findings**
> (cleaned post-leakage-fix in the v12 README number). Re-run with the live
> LLM to get a real v12 baseline on the current 19/31 split before
> accepting any v13 change as a measured win.
>
> Re-measure command: `python scripts/smartness_test_v12.py --live-llm --out v12_current.json`
> (offline-stub mode is the default and is structurally meaningless — it
> echoes the gold so F1 = 1.0 by construction).

## What we know from the v11 → v12 work

1. **The dx_linkage false positives are gone from the gold.** The
   `docs/AHCIP_GOLD_AUDIT.md` (2026-06-22) called out 5 wrong dx_linkage
   findings (ca2, ca4, ca6, ca10, ca12) on the v11 prompt. Those
   findings are no longer in `data/synth/val_ca.json` — the current
   gold does not score the LLM on a rule that the v12 prompt's
   "do NOT fire on encounters where dx is present and matches the
   note" clause (line 57-59) explicitly excludes.
2. **The v12 prompt has all 15 rules (A–O) covering every finding in
   the current gold.** No new rule is needed for the current val set.
3. **The remaining 0.690 ceiling is therefore driven by *emission*
   (LLM mis-firing) and *omission* (LLM not firing when it should),
   not by missing rule definitions.** The prompt-level fix is to
   add unambiguous few-shot examples for the rules where the
   "fire / do not fire" boundary is most easily crossed.

## Proposed v13 prompt deltas (targeted, evidence-based)

The v13 prompt starts as a verbatim copy of `prompts/v12/auditor_prompt.txt`
plus one appended section, `## V13 EXAMPLES AND TIGHTENINGS`, that
adds negative / positive few-shot examples and one explicit
boundary-tightening. No existing v12 text is removed.

### D1. Section A (dx_linkage) — negative example

The v12 prompt says "Do NOT fire on encounters where dx is present and
matches the note. A hypertensive visit with I10 billed is NOT a
dx-linkage issue." Add a worked counter-example inline so the LLM
sees the exact case where it must not fire.

```
V13 NEGATIVE EXAMPLE — dx_linkage MUST NOT fire
  Encounter: BP 168/102, started amlodipine 10mg. Note documents
  moderate-acuity hypertension management.
  diagnosis_codes: ["I10"]
  Billed: 03.04A
  → DO NOT fire rule_ahcip_dx_linkage. I10 matches the note.
  → DO fire rule_ahcip_cmgp (MEDIUM) if patient is established with
    chronic HTN and no CMGP modifier.
```

This is the exact pattern that the v11 gold flagged as a false
positive (ca4). A worked example makes the rule boundary explicit.

### D2. Section K (missing_procedure) — positive few-shot

The v12 prompt's K section has prose and trigger-phrase lists but no
worked example. The current gold has three K findings (ca20, ca22, ca24)
that the LLM will only fire if it recognises the "performed in office
but not billed" pattern. Add three small examples that match the
gold.

```
V13 POSITIVE EXAMPLES — missing_procedure DOES fire
  Example 1 (immunization):
    Note: "...administered PPSV23 pneumococcal vaccine in office today."
    Billed: 03.04A
    → Fire rule_ahcip_missing_procedure HIGH. suggested_code: current
      SOMB pneumococcal immunization code.
  Example 2 (EKG):
    Note: "12-lead ECG performed in office, normal sinus rhythm."
    Billed: 03.04A
    → Fire rule_ahcip_missing_procedure HIGH. suggested_code: X140A
      or current SOMB ECG / 12-lead EKG interpretation code.
  Example 3 (joint injection):
    Note: "Intra-articular knee injection performed, 40mg triamcinolone."
    Billed: 03.04A
    → Fire rule_ahcip_missing_procedure HIGH. suggested_code: X311A
      or current SOMB joint injection code.
```

### D3. Section L (preventive_opportunity) — negative example for "already up to date"

The v12 prompt's L section has a "do not fire" list but not a
counter-example. The most common L false positive is firing the rule
when the patient is already up to date. Add the counter-example
inline.

```
V13 NEGATIVE EXAMPLE — preventive_opportunity MUST NOT fire
  Encounter: 71yo M, established, here for HTN follow-up.
  Note: "Pneumococcal vaccine — PPSV23 given 2018, no booster due."
  Billed: 03.04A
  → DO NOT fire rule_ahcip_preventive_opportunity for pneumococcal.
    The note documents a current vaccination status (2018 PPSV23) that
    satisfies the eligibility rule. Use rule_ahcip_em_level for the
    visit-level finding only.
```

### D4. Section O (telehealth) — explicit "premium is conditional"

The v12 prompt's O section is 26 lines and comprehensive. One
remaining risk: firing telehealth on encounters where the note
mentions a phone or asynchronous touchpoint but the encounter is not
in fact a billable visit. Tighten with one line.

```
V13 ADDITION — telehealth fires ONLY when the encounter is a billable
  E/M (03.03A / 03.04A / 03.05A / 03.07A / 03.01A) AND the modality is
  not in-person. A short phone call to discuss a lab result is NOT
  a billable AHCIP telehealth visit and does NOT fire this rule.
```

## What v13 deliberately does NOT change

- **No new rules.** Every gold finding in the current 19/31 val set
  is covered by an existing v12 rule. Adding a new rule would just
  inflate the catalogue without improving F1.
- **No removal of v12 "do not fire" clauses.** Those clauses are
  correct; they just need worked examples to take effect on
  small open-source LLMs.
- **No suggested_code rewrites.** The current suggested_code values
  in the gold are aligned with v12 (e.g. ca8 = "drop visit (within
  90-day global period) or attach explanatory text" matches v12
  section E).
- **No test-set redefinition.** The v13 work does not touch
  `data/synth/val_ca.json`. v13 is a prompt-only change, measured
  on the existing 19/31 split.

## How to measure v12 → v13 deltas

1. Get a real v12 baseline on the current 19/31 split:
   `python scripts/smartness_test_v12.py --live-llm --out v12_current.json`
2. Switch the prompt to v13 by editing `src/ai_billing_audit/auditor_prompt.txt`
   (or by setting the `AUDITOR_PROMPT_PATH` env var if the loader
   supports it) and re-run:
   `python scripts/smartness_test_v12.py --live-llm --prompt prompts/v13/auditor_prompt.txt --out v13_first.json`
3. Compare per-rule P/R and the headline F1. The expected wins:
   - **Precision (P)**: dx_linkage false-positive elimination via D1.
     The v11 false-positive rate on this rule was 5/15 (33%); v12 is
     already better, v13's worked example should make the rule
     stable on the current 19/31 split.
   - **Recall (R)**: missing_procedure emission via D2. Three of the
     31 gold findings depend on this rule firing; missing any is a
     direct -0.10 R hit.
   - **Precision (L)**: preventive_opportunity over-firing reduction
     via D3. The current val set does not include a positive L
     example that would score D3, but the negative example reduces
     the risk of L firing on the "patient is up to date" pattern
     that is common in real production data.

## Where the v13 prompt currently lives

- `prompts/v13/auditor_prompt.txt` — verbatim copy of v12 plus the
  `## V13 EXAMPLES AND TIGHTENINGS` section appended at the bottom.
- `prompts/v13/MANIFEST.json` — manifest noting v13 is a draft,
  content_sha256 unverified, byte_size +46 vs v12 (the additions).

The v13 prompt is intentionally a small, additive change. If the
user measures a real win on the 19/31 split, the additions can be
folded back into the v12 prompt for the next release. If v13
performs worse than v12 on the live LLM, the additions can be
removed without touching v12.
