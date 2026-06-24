# Zorva Prompt & Validation-Set Audit

**Date:** 2026-06-23
**Audit scope:** Read-only. Prompt catalogue (v0–v12), three val sets, scoring logic, prompt-version drift, LLM client/prompt construction, known issues.
**Project root:** `/Users/biancabienaime/projects/ai-billing-audit`
**Shipped baseline:** v12 (AHCIP-only, F1=0.733 on cleaned AHCIP val, 10539 chars, 23/50 → 0/50 timeouts after the 180s fix).

---

## TL;DR

- **The 12 prompt versions are real, but 10 of 12 are unmanaged.** `prompts/MANIFEST.json` only logs v0 and v12. v1–v11 are scattered on disk with no per-version R/P telemetry. The "history" is reconstructable from `artifacts/prompt_history.jsonl`, but every row's `prompt_version` is the literal string `"auditor_prompt"` — the **per-version F1 record is effectively wiped**. The only F1 number that survives is the one in v12's MANIFEST entry.
- **v12 EXAMPLE 6 in the few-shot section is the ca_ahcip_004 val encounter verbatim. EXAMPLE 7 is a close paraphrase of ca_ahcip_008.** This is direct val-set leakage into the prompt, not a holdout. The reported F1=0.733 is therefore optimistic.
- **The smartness-test scorer matches on `rule_id` overlap and ≥0.40 Jaccard quote overlap, severity is ignored.** Per-encounter mean is the headlined metric; micro-aggregate is also reported. Greedy one-to-one matching means the scorer handles multiplicity correctly (two `rule_em_001` gold findings can both match two distinct predictions) but cannot detect over-emission of the same rule_id twice when gold has it once.
- **v12 is functionally AHCIP-only, but v8 and v9–v11 still have multi-market framing on disk.** v11 still says "Alberta does NOT have a -24 modifier" in the modifier list section, then contradicts itself by listing `-24` in its "Modifiers" block. v10 explicitly says `drawn from a separate encounter set` for few-shot — but EXAMPLE 6 of v12 (which copied most of v10/v11's structure) does NOT honour that contract.
- **Schema enforcement is cosmetic.** `RESPONSE_JSON_SCHEMA` allows `additionalProperties: True` at both object levels, `quote` is no longer required (the validator synthesises one), and `rule_id` singular OR `rule_ids` plural are both accepted. The grader-style JSON-Schema round-trip is a *contract*, not a constraint.
- **The 180s timeout in `auditor.py:385` plus the 10539-char prompt are the proximate cause of p95 latency of 119s in the most recent smartness_test run.** v7's 23/50 timeout rate at 60s is now 0/10 timeouts at 180s, so the fix is on the right path; but the *prompt length doubled* (v11=5748 → v12=10539) without a corresponding model-version or context-window upgrade story documented anywhere.
- **Of the 791 pytest tests, zero exercise the prompt-iteration loop.** The closest is `test_v0_baseline::test_smoke_run_audit_on_first_val_encounter` which calls `run_audit` once with the v0 prompt. There is no test that runs v1–v12, no test that asserts the F1 reported by `smartness_test.py` is monotone over versions, and no test that detects val-set leakage into few-shot examples.

---

## 1. Prompt Catalogue

### 1.1 Per-version diff summary (v0 → v12)

Char/line counts (`wc -c` / `wc -l`):

| ver | chars | lines | style / era | status |
|-----|-------|-------|-------------|--------|
| v0  | 1373  | 25   | original baseline, US-only, no recall framing | **BASELINE** (pinned, in MANIFEST) |
| v1  | 1336  | 24   | adds "Favor recall" hint, drop duplicate (cat,rule_id) | dead (no R/P tracked) |
| v2  | 1560  | 27   | explicit RECALL IS THE PRIMARY METRIC + category rule | dead |
| v3  | 2239  | 41   | adds specific patterns: REVIEW placeholder, duplicate, MDM undercode, modifier required | dead |
| v4  | 5809  | 121  | big expansion: 12 rule families (rule_em_*, rule_modifier_25, rule_imaging, rule_lab, rule_injection, rule_ecg, rule_cardiology, rule_injection, rule_preventive, rule_overlap, rule_missing_dx_001, rule_modifier_25_001, "REVIEW" placeholder). | dead |
| v5  | 3978  | 105  | severe compaction; renames "Auditor" → "Zorva Auditor"; numeric rule IDs (rule_em_*, rule_lab_*); explicit JSON shape block | dead |
| v6  | 2331  | 61   | further compaction; very terse "rule firing rules" | dead |
| v7  | 5444  | 109  | re-expansion + 4 few-shot examples; "Few-shot examples (these are real gold findings from our val set)" | dead; **23/50 timeouts at 60s** |
| v8  | 5629  | 129  | multi-market framing (US + Canadian SOMB/OHIP/MSP); first AHCIP rules (rule_ahcip_em_level, etc.) | dead |
| v9  | 6663  | 145  | multi-market + 7 few-shot examples (6 AHCIP + 1 US) | dead |
| v10 | 4472  | 95   | trimmed multi-market; **few-shot disclaimer added**: "drawn from a separate encounter set; the val encounters you will be scored on are different from these" | dead |
| v11 | 5748  | 147  | AHCIP-aware rewrite; still claims `-24` modifier in modifiers block (US leak) | dead |
| v12 | 10539 | 237  | AHCIP-only; 7 few-shot examples; "Alberta does NOT have a -24 modifier"; splits lab vs imaging coverage; severity tier ladder | **SHIPPED** (in MANIFEST) |

### 1.2 MANIFEST documentation gap

`prompts/MANIFEST.json` has exactly **2 entries**:

- v0: `content_sha256: 285eab0898cd769c29efe1d9f3841970e4f8f010f8173fdbebe4925871051dcc`, train_R=0.842, val_R=0.813, val_P=0.187 (miprov2 reference run, gpt-4o-mini)
- v12: val_F1=0.733, val_n=10, val_set=`data/val_ca.json (cleaned, 13 gold findings)`, rationale with 8 specific `changes_from_v11`

**v1–v11 are not in MANIFEST.** The MANIFEST schema (lines 2–3) says "append-only log of prompt optimization runs" — implying one entry per optimization pass, not per prompt version. The 12 prompts on disk are far more than the 2 MANIFEST entries. This is a documentation/audit gap, not necessarily a bug — MANIFEST tracks optimization runs (e.g., the miprov2 pass) and the prompt versions on disk are the *drafts* evaluated within each run.

### 1.3 Where the per-version R/P actually lives

`artifacts/prompt_history.jsonl` is the closest thing to a per-version F1 log. **However, every row's `prompt_version` field is the literal string `"auditor_prompt"`, not `v3` / `v7` / `v12`.** See line 1 of every record:

```json
{"prompt_version": "auditor_prompt", "run_at": "2026-06-22T22:49:25.095713+00:00", ...}
```

Why? `smartness_test.py:529` reads `prompt_version = Path(args.prompt).stem`. But the 15 rows in `prompt_history.jsonl` all show `"prompt_version": "auditor_prompt"` — implying every run was invoked with `--prompt prompts/<ver>/auditor_prompt.txt` AND the basename extraction was overwritten somewhere, or the runs were all invoked without `--prompt` (in which case `prompt_version = "default"`, line 531). Either way, the per-version telemetry is **wiped from this artifact**.

The actual per-version F1 numbers are partially recoverable from `artifacts/smartness_*.json` (e.g., `smartness_ca_v7_chunk_0.json`, `smartness_ca_v10_full.json`) — these are out-of-band JSON dumps, not part of MANIFEST.

### 1.4 Live candidates vs dead

| ver | referenced anywhere as live? | evidence |
|-----|------------------------------|----------|
| v0  | YES (the **default** — `auditor.py:136` `load_prompt()`) | `src/ai_billing_audit/auditor_prompt.txt` is the bundled default; live URL & tests all use it |
| v1–v6 | NO | not referenced in any script's `--prompt` arg path; `git log` shows the commits (`feat(prompt-v4)`, `feat(prompt-v5-v6)`) but no later reference |
| v7  | partial | `scripts/run_v7b_full.sh:11` is the only remaining reference, with `LLM_PROVIDER=ollama` + `LLM_MODEL=ollama/minimax-m3:cloud` (the cloud backend) |
| v8  | NO | artifacts `smartness_ca_v8_chunk_0.json` exist but no script references v8 |
| v9  | NO | artifacts only |
| v10 | NO | artifacts only |
| v11 | NO | artifacts only |
| v12 | YES (the **shipped** baseline) | MANIFEST entry, deployed to live URL, `prompts/v12/auditor_prompt.txt` |

**Dead prompts still on disk:** v1–v6, v8–v11 (10 versions). The README says "v1+ optimizer is measured against" v0 but doesn't say v1–v11 are dead. A reader of the prompts/ directory will assume all 12 are live candidates.

### 1.5 Stale prompts and contradictions

- **v11 still has the US -24 modifier leak.** `prompts/v11/auditor_prompt.txt:32`: `-24: unrelated E/M in post-op period (GR 3.2.1, 90 days)`. This is the "US modifier bleed" that the v12 MANIFEST entry claims was "fixed in v12". The fix is in v12 only — v11 still ships with the leak.
- **v8 / v9 / v10 have multi-market framing for a project that pivoted to Canada-only.** `v8:25-50` includes US CPT codes (99201-99215), -25/-59 modifiers, and 4 different Canadian jurisdictions. The current shipped direction (Alberta AHCIP-only) is not represented.
- **v10's few-shot disclaimer is more honest than v12's.** v10:44 says "drawn from a separate encounter set; the val encounters you will be scored on are different from these". v12:151 says "AHCIP-encounter set; the val set is held out" — but **EXAMPLE 6 of v12 IS a val encounter, verbatim** (see §2.1 below).

### 1.6 Near-duplicates

- **v8 vs v9**: v9 = v8 + 7 few-shot examples + "the rule_id convention exactly so the scorer can match" tip. Otherwise identical structure.
- **v10 vs v11**: v11 = v10 + expanded AHCIP-specific guidance section + "pipeda+HIA" legal note + more pattern detail. Few-shot examples same.
- **v11 vs v12**: v12 = v11 + 2 more few-shot examples (EXAMPLES 6+7) + severity-tier ladder + new patterns (rule_ahcip_non_insured_service, rule_ahcip_same_day_conflict) + explicit "Alberta does NOT have a -24 modifier" framing + tightened em_level vs em_level_upcode distinction.

**Critical observation:** v11's MANIFEST entry claims "v12 prompt: AHCIP-only guidance with 7 AHCIP pattern sections". v11's prompt file already had 8 AHCIP pattern sections (A through H). v12 reorganised these but did not add net-new ones except `rule_ahcip_non_insured_service` and `rule_ahcip_same_day_conflict`. The MANIFEST rationale overstates the diff.

### 1.7 Few-shot leakage into v12

**v12 contains two val-set encounters in its few-shot section:**

- **EXAMPLE 6** (v12:198–204) clinical_note: `"Office visit, brief assessment for upper respiratory symptoms. Patient reports cough x 5 days, no fever. Lungs clear. Supportive care advised."` — this is **ca_ahcip_004 verbatim** (val_ca.json line 119, byte-for-byte match including the trailing period).
- **EXAMPLE 7** (v12:206–214) clinical_note: `"Office visit, brief assessment for cough. Productive cough x 1 week, low-grade fever yesterday. Rhonchi bilaterally. Started amoxicillin 500mg TID."` — this is **ca_ahcip_008 paraphrased** (val_ca.json line 257). The only edit is "Lungs show rhonchi bilaterally" → "Rhonchi bilaterally" (token reordering + the word "show" dropped). The model is trained on v12, so the paraphrase is irrelevant — the semantic content is identical.

Mechanically verified via Python string match:

```
EXAMPLE 6: EXACT MATCH to val_ca ca_ahcip_004
EXAMPLE 7: not byte-exact, but is ca_ahcip_008 with one rewording of "Lungs show rhonchi bilaterally"
```

The v12 prompt's claim at line 151 — `Few-shot examples (AHCIP-encounter set; the val set is held out)` — is **false**. Two of the seven examples are derived from val encounters.

v9 had the same problem at greater scale (EXAMPLES 1, 2, 3, 4, 5, 6 are paraphrases of ca_ahcip_001 through ca_ahcip_006 — verified by reading each example side-by-side with val_ca.json). v10 cleaned this up by switching to "drawn from a separate encounter set". v11 reverted (most of v11's examples match v9). **v12 inherited v11's examples and added two MORE (EXAMPLES 6+7) which are direct val-set encodings.**

---

## 2. Validation Set Integrity

### 2.1 Encounters and authorship

| file | encounters | gold findings | authored by | modification date |
|------|-----------|---------------|-------------|-------------------|
| `data/val.json` (US) | 50 | 164 | synthetic, generated by an LLM-driven ground_truth generator (`src/ai_billing_audit/ground_truth.py`); not hand-verified by a real biller | 2026-06-16 |
| `data/val_ca.json` (AHCIP) | 10 | 13 (cleaned) / 18 (pre-clean) | **Hermes** (cleaned 2026-06-22 by current session); **NOT by a real Alberta biller** | 2026-06-22 |
| `data/val_sample.jsonl` | 150 | varies per row (categories only, not full findings) | LLM-generated (`scripts/build_test_sample_manifest.py`) | 2026-06-16 |
| `data/fewshot_ca.json` | 5 | 7 (1-2 per encounter) | Hermes, held-in (separate from val) | 2026-06-22 |
| `data/train.json` | 100 | full | synthetic, generator | 2026-06-16 |

**Val_ca.json authorship:** The current session's `pre_audit_backup` (line 7) shows the file pre-dated this session at 18 gold findings (with the 5 false-positive `rule_ahcip_dx_linkage` findings on ca_ahcip_001/002/003/006/008). The cleaned file (current `val_ca.json`) has 13 gold findings across 10 encounters. The cleanup is documented in the v12 MANIFEST entry ("5 false-positive dx_linkage findings removed, 3 missed findings added, 1 US modifier leak fixed") — but no author signature, no SHA, no diff log. The "1 US modifier leak fixed" refers to ca_ahcip_005 (post-op cholecystectomy) where the pre-clean gold said `suggested_code: "modifier -24"` (v11's bleed) and the cleaned version says `suggested_code: "drop visit (within 90-day global period) or attach explanatory text"`.

**Val.json authorship:** Generated, not authored by a human biller. The README refers to "50 hand-verified encounters" — `scripts/smartness_test.py:3` repeats that claim — but the encounters are LLM-synthesised. The "hand-verified" framing is misleading. The test split's manifest (`data/val_manifest.json`) is a JSON manifest generated by `scripts/build_test_sample_manifest.py` from the synthetic data.

### 2.2 Train / val / test split

There is **no documented train/val/test split policy** in the repo. The closest is:
- `data/val_manifest.json` — 50 US encounters, with hashes per row
- `data/holdout_seed9999.json` — the synthetic holdout (90KB, far larger than the 50-encounter val)
- `data/test_sample.jsonl` — 150 encounters for cross-provider acceptance

No hash of any of these is referenced from MANIFEST (only v0's `val.json` is referenced from `prompts/v0/MANIFEST.json:23`). Train/val/test contamination is therefore *unverifiable* by inspection: the only way to check whether `train.json` encounters appear in `val.json` is to compare encounter_ids. Quick check: train.json has 100 encounters with `enc_NNNN` shape; val.json has 50 with the same shape. I did not exhaustively compare them.

### 2.3 Cross-contamination: US val vs AHCIP val

`grep -i "icd-10-ca\|SOMB\|AHCIP\|alberta\|canada\|ca_ahcip" data/val.json` → **0 matches**.
`grep -i "cpt\|9920\|9921\|icd-10-cm\|modifier-25" data/val_ca.json` → **0 matches**.

The two val sets are clean of each other's terminology at the string level. Good.

### 2.4 Synthetic demographics

US val encounters use sequential IDs (`enc_10000`, `enc_10001`, ...) and have PHI-free, but realistic-looking clinical notes (BP 152/94, HR 78, A1C 8.9 etc.).

AHCIP val encounters have **sequentially patterned Alberta PHNs** (`123456789`, `987654321`, `111222333`, `444555666`, ..., `321321321`) and dates that are all in Feb–May 2026. The PHN pattern is a dead-giveaway that this is synthetic — a real Alberta biller would not see PHNs in the 123456789/987654321 pattern (those are 9 digits but unlikely to be real assigned values). A model fine-tuned on real PHN distributions would not be confused, but **a model that sees the literal "123456789" might overfit on the test set** if the same pattern appears in production logs (which it will, because developers often use `123456789` as a placeholder). The risk is small but real.

### 2.5 Rule-id consistency between val_ca gold and prompt v12

Gold rule_ids in `val_ca.json` (13 findings):
- `rule_ahcip_em_level` (×3) — ca_ahcip_001, ca_ahcip_003, ca_ahcip_010
- `rule_ahcip_em_level_upcode` (×2) — ca_ahcip_004, ca_ahcip_008
- `rule_ahcip_referring_npi` (×1) — ca_ahcip_002
- `rule_ahcip_same_day_conflict` (×1) — ca_ahcip_003
- `rule_ahcip_global_window` (×1) — ca_ahcip_005
- `rule_ahcip_telehealth` (×1) — ca_ahcip_006
- `rule_ahcip_psychotherapy_time` (×2) — ca_ahcip_006, ca_ahcip_007
- `rule_ahcip_dx_linkage` (×1) — ca_ahcip_009
- `rule_ahcip_lab_coverage` (×1) — ca_ahcip_010

All 9 distinct rule_ids are explicitly enumerated in v12's AHCIP pattern section (lines 49, 64, 76, 82, 91, 102, 116, 125, 140, 147). **Naming is consistent** — no mismatches.

**However:** `rule_ahcip_cmgp` is in the v12 prompt (line 147) but **never appears in val_ca gold**. Similarly `rule_ahcip_non_insured_service` is in v12 (line 63) and fires on ca_ahcip_009 in practice (per the smartness_test run on 2026-06-22 23:00 — `smartness_ca_v12_full` micro-aggregate shows `rule_ahcip_non_insured_service: precision=0.0, recall=null`) but the gold says `dx_linkage critical`. The model fires `non_insured_service` (because the note says "Annual health maintenance visit") but the gold prefers `dx_linkage` (because the diagnosis_codes array is empty). These are **two valid findings for the same encounter** and the gold only has one — the model is correct to fire both, but the scorer only matches `dx_linkage` and counts `non_insured_service` as FP.

### 2.6 The 5 false-positive dx_linkage findings pre-cleanup

`val_ca.json.pre_audit_backup` shows:
- ca_ahcip_001: extra `rule_ahcip_dx_linkage` finding citing "labs: A1C 8.9" (severity=critical, suggested_code="E11.9,I10"). The encounter has dx codes E11.9 and I10 in the claim — so a dx_linkage finding is **incorrect** (dx is present).
- ca_ahcip_002: extra `rule_ahcip_dx_linkage` finding citing "BP 168/102" — claim has I10. **Incorrect, dx present.**
- ca_ahcip_003: extra `rule_ahcip_dx_linkage` finding citing "T2DM, HTN, dyslipidemia, osteoarthritis knees" — claim has E11.9, I10, E78.5, M17.9. **Incorrect, dx present.**
- ca_ahcip_006: extra `rule_ahcip_dx_linkage` finding citing "PHQ-9 score 6" — claim has F32.1. **Incorrect, dx present.**
- ca_ahcip_008: extra `rule_ahcip_dx_linkage` finding citing "rhonchi bilaterally" — claim has J18.9. **Incorrect, dx present.**

All 5 are the **same family**: dx_linkage over-firing on encounters where dx codes ARE present and ARE valid for the note's reported conditions. This matches v12's pattern A description (lines 49–56): "Do NOT fire on encounters where dx is present and matches the note." The pre-clean gold violated v12's own rule. The cleanup is consistent with the prompt's stated semantics.

### 2.7 The 3 added findings (cleaning pass)

The MANIFEST entry says "3 missed findings added" — comparing pre-clean to current:

1. **ca_ahcip_003 `rule_ahcip_same_day_conflict`**: claim has both 03.04A and 03.05A billed same day. v12 pattern I (line 137): "03.04A (comprehensive) + 03.05A (minor) on same date for same patient → rule_ahcip_same_day_conflict HIGH (SOMB does not allow comprehensive + minor on the same day; drop the 03.05A or downgrade the 03.04A)". **Real SOMB concept** — though SOMB allows multiple E/M on the same day under specific circumstances (separate unrelated problems), so the rule is a heuristic, not an absolute.
2. **ca_ahcip_006 `rule_ahcip_psychotherapy_time`**: claim bills 03.04A but the note documents PHQ-9 score 6 + sertraline continuation. v12 pattern F (line 100): "Note documents a 45+ minute mental-health / psychotherapy session AND claim bills standard E/M (03.04A) → rule_ahcip_psychotherapy_time HIGH (recoded to 08.19A)". **The gold claim is a stretch** — the note does not document "45-minute session" explicitly, only "PHQ-9 score 6, down from 12 last visit". v12's pattern F requires either an explicit time phrase OR an extended mental-health visit (>30 min based on content depth). The session duration is not in the note; this is borderline.
3. **ca_ahcip_008 `rule_ahcip_em_level_upcode`**: claim bills 03.01A but the note documents "productive cough x 1 week, low-grade fever, rhonchi bilaterally, started amoxicillin" — moderate-acuity visit. v12 pattern C: "Note documents 'comprehensive'/'complex' but claim bills 03.01A brief → rule_ahcip_em_level_upcode HIGH (under-coded, increase to 03.04A)". **Strong match** — the clinical content supports 03.04A not 03.01A.

All 3 added findings correspond to real SOMB concepts (the same_day_conflict and em_level_upcode rules are documented in the SOMB; psychotherapy_time maps to HSC 08.19A which is a real Alberta health service code).

### 2.8 The US -24 leak in pre-clean val_ca

`val_ca.json.pre_audit_backup` ca_ahcip_005 has `suggested_code: "modifier -24"` (line 187). Alberta SOMB does not have a -24 modifier (this is a US CPT modifier per `prompts/v12/auditor_prompt.txt:35-38`). The pre-clean gold was contaminated by v11's bleed; the cleanup correctly removed it.

---

## 3. Scoring Logic (`scripts/smartness_test.py`)

### 3.1 Matching criterion

`_findings_match()` (lines 78–134): a predicted finding matches a gold finding iff **all three**:

1. **`rule_id` set intersection is non-empty.** Predictions can have `rule_id` (string) or `rule_ids` (list); gold can have either. Intersection of the union sets must be non-empty. (`pred_rules & gold_rules`)
2. **`quote` overlap ≥ 0.40 Jaccard.** `_jaccard()` tokenises both quotes (whitespace + `[a-z0-9]+`), returns `len(a∩b) / len(a∪b)`. Default threshold 0.40.
3. **Severity match (optional, off by default).** `require_severity_match=False` → severity is ignored. If flipped on, predictions must be within 1 tier of gold (e.g., gold=high, pred=medium OK; gold=critical, pred=low not OK).

The `_findings_match()` function ignores `category` and `suggested_code`. Per-rule aggregation at lines 263–283 also uses only `rule_id` for matching.

### 3.2 Per-encounter vs micro-aggregation — both reported

The scorer reports **both** in `_aggregate()`:

- `mean_per_encounter`: mean of per-encounter P/R/F1 (lines 246–248). This is the **headlined metric** — see the comment at smartness_test.py:30-39: "A clinic sees ONE claim at a time. They don't care if the auditor has 90% recall across 50 claims; they care if THE CLAIM ON THEIR DESK is right."
- `micro_aggregate`: pooled TP / total_predicted / total_gold across all encounters (lines 249–254). This is the v12 MANIFEST entry's "val_F1 = 0.733" — micro-aggregate F1.

The two metrics diverge when encounter sizes are heterogeneous. For v12 on val_ca (10 encounters, 13 gold findings, 17 predicted, 11 TP): mean_per_encounter F1 = 0.747, micro F1 = 0.733. Close but not equal.

### 3.3 Severity penalty — explicitly disabled

`_findings_match` (lines 87–99) explicitly does **not** penalise severity mismatches by default:

> "Setting `require_severity_match=False` was the single biggest improvement to the smartness test after we added few-shot examples in v7 — the examples biased the model toward medium severity, and gold findings use info/low for the same rule_ids. Penalizing that mismatch hid genuine improvements in finding emission."

Per-severity P/R/F1 is still reported (lines 286–312) so the breakdown is observable; the *match* decision ignores it.

### 3.4 Quote match detail

`_jaccard` (lines 71–75) — token-set Jaccard on `[a-z0-9]+` regex tokens. Threshold 0.40 (line 82). Substring / Levenshtein are NOT used.

This is **lenient** — it allows the model to quote a phrase like "chest pain on exertion" even if the exact phrase in the note is "Patient reports chest pain on exertion for 3 weeks" — both tokenise to overlapping sets.

But this is also **lenient in the wrong direction**: a model that emits `"chest pain"` as the quote (just those 2 words) gets Jaccard ≈ 0.5 against gold `"chest pain on exertion"` (3 words), which **passes** the 0.40 threshold with a quote that doesn't include "on exertion". A model that fabricates a quote with the right rule_id and the right 2 of 3 tokens passes — the F1 doesn't distinguish "strong evidence" from "weak evidence".

### 3.5 What happens when the prompt emits an FP

For each unmatched prediction: `per_rule[rule_id]["fp"] += 1` (line 283). F1 denominator includes `n_pred` → adding FPs lowers precision but not recall. The matcher's `_score_encounter` line 217:

```python
p = n_matched / n_pred if n_pred > 0 else (1.0 if n_gold == 0 else 0.0)
```

So if a clean encounter (gold empty) gets one false-positive prediction, P=0.0 (matches the prior). If a dirty encounter gets 5 predictions but only 1 matches gold: P=1/5=0.2, R=1/2=0.5, F1=0.286.

The smartness_test fails *gracefully* on FPs (it logs them, lowers P), it does not crash.

### 3.6 Multiplicity (gold has rule_x twice)

The matcher is greedy one-to-one (`matched_preds` and `matched_gold` are sets; line 207–212):

```python
for gi, g in enumerate(gold):
    for pi, p in enumerate(preds):
        if pi in matched_preds: continue
        if _findings_match(p, g):
            matched_preds.add(pi)
            matched_gold.add(gi)
            break
```

Two gold findings with the same rule_id can match two different predictions — multiplicity works. **But** a single prediction that "should" have matched two gold findings (same rule_id, different quotes) can only match one of them — the second gold is counted as FN.

This is a **known limitation**: the scorer cannot represent "one prediction covering two distinct issues". For the rule_ids the prompts actually emit (`rule_ahcip_em_level`, `rule_ahcip_em_level_upcode`), this rarely happens in val_ca — but for the more generic US rules (e.g., two missing-dx findings on the same encounter with different suggested_codes), it's a real issue.

### 3.7 Calibration phase

There is **no smoke test or known-answer check** at the start of a smartness_test run. `main()` (line 434) reads val_paths, loads encounters, and goes straight to `_score_encounter()`. There is no fixed-input sanity check, no warm-up LLM call, no contract assertion that the LLM is producing parseable JSON.

The closest is `scripts/calibration_report.py` and `scripts/verify_grader_reproducibility.py` — these test the **grader** (judge model), not the **auditor**. The auditor has no pre-flight check.

This means a silent LLM config change (e.g., model swap, API key expiry, schema-version mismatch) only surfaces as `n_errors` going up in the latency field. The smartness_test will happily report F1=0.0 if the LLM is returning empty payloads.

### 3.8 Has the scorer changed between versions?

Indirectly, yes. The 2026-06-17 change from `category+rule_id` matching to `rule_id`-only matching (mentioned in the task context: "10x F1 improvement") is documented in the `prompt_history.py` docstring as a known correction. The current `_findings_match` is the post-fix version.

For the F1 numbers to be **comparable across versions**:
- The matcher logic is constant across v0–v12 (the scorer file hasn't changed).
- The val set content HAS changed — `val.json` (50 US) was the baseline, `val_ca.json` (10 AHCIP) is the current scoring target. F1 on `val.json` is not comparable to F1 on `val_ca.json`.
- The `prompt_history.jsonl` rows from 2026-06-22 22:49 → 23:10 all show the US rule_ids (`rule_ecg_001`, `rule_em_001..003`, `rule_icd_001..004`, etc.). The rows from 2026-06-22 23:41 onwards show the AHCIP rule_ids. **The two regimes are interleaved in the history log without a regime tag.** Anyone aggregating across them will get nonsense.

---

## 4. Prompt-Version Drift

### 4.1 Functionally-identical pairs

- **v0 ≠ v1** (v0 has 25 lines, v1 has 24; v1 drops the explicit findings shape and adds "Favor recall")
- **v0 ≠ v12** (different content)
- **v8 ≈ v9**: v9 = v8 + 7 few-shot examples + minor "match the rule_id convention" tip. Otherwise identical.
- **v10 ≈ v11**: v11 = v10 + AHCIP-specific guidance section + "pipeda+HIA" + few-shot example 6+7. v10 had only 5 examples; v11 had 7.
- **v11 ≈ v12**: v12 = v11 + 2 more few-shot examples + severity-tier ladder + 2 new rules + explicit "-24 doesn't exist" framing + tightened em_level distinction. v11 already had `08.19A 30-min` mentioned; v12 makes it explicit `08.19B`.

No two prompt files have identical byte content. They are *related* but not duplicate.

### 4.2 Default in `auditor.py`

`src/ai_billing_audit/auditor.py:60-158` — `load_prompt(path=None)` resolves to `src/ai_billing_audit/auditor_prompt.txt` (the bundled v0 prompt). Verified: `diff` of `src/ai_billing_audit/auditor_prompt.txt` vs `prompts/v0/auditor_prompt.txt` shows 3 lines of difference (v0 has additional explanation text about the findings shape). The bundled default is **NOT byte-identical to prompts/v0/**.

`prompts/v0/MANIFEST.json:8` claims `content_sha256: 285eab08...` and `byte_size: 1200`. The actual `prompts/v0/auditor_prompt.txt` is 1373 chars (per `wc -c`). **Mismatch** — MANIFEST says 1200 bytes, file is 1373 chars. Likely the MANIFEST was generated against an earlier revision and never updated. (Or it's a typo.)

### 4.3 Scripts referencing prompts

- `scripts/run_v7b_full.sh:11` — `--prompt prompts/v7/auditor_prompt.txt` (v7)
- `scripts/eval_holdout.py:44` — `V0_PROMPT_PATH = PROJECT_ROOT / "prompts" / "v0" / "auditor_prompt.txt"` (v0)
- `scripts/eval_final_test.py:44` — `V0_PROMPT_PATH = ...` (v0)
- `scripts/smartness_test.py:448` — `--prompt` arg, default None (uses bundled default = v0-equivalent)

No script references v1–v6, v8–v12 directly. The v12 deployment is presumably handled by a Docker build arg or environment override that I haven't traced here.

### 4.4 Different AI authorship

Reading the 12 prompts stylistically:

- v0–v6: prose is denser, sentence-fragment-heavy. "Be conservative. A claim that is not clearly contradicted by the retrieved rules is not a finding." (v0)
- v7 onward: more structured ("The downstream product cares about RECALL MORE THAN PRECISION. A missed billing error costs the clinic revenue; a false positive costs the biller 5 seconds of dismissing it."). This framing is repeated **verbatim** in v4, v7, v8, v9, v10, v11, v12 — strongly suggesting these were written by the **same LLM session / human author**.
- v3 is the odd one out: it has specific code-level patterns (CMS MDM table, -25/-59/-24/-79 modifiers) that are US-CPT-specific. This was likely written by a US-context LLM, separate from the Alberta-context v4+ author.

The Alberta-specific framing in v4+ suggests one consistent author (Hermes itself or a US-context LLM prompted to switch contexts). The v3 US specificity reads like an earlier generation.

---

## 5. LLM Client & Prompt Construction

### 5.1 How the prompt is composed into messages

`build_messages()` (`auditor.py:193-202`):

```python
return [
    {"role": "system", "content": prompt},
    {"role": "user", "content": _encounter_context(encounter)},
]
```

The prompt is **always** in the system message. Few-shot examples are embedded in the prompt string itself (the "Few-shot examples" section of v12 is lines 151–214). There is no separate user-message-based few-shot. `_encounter_context()` (lines 166-190) renders the encounter as plain text:

```
encounter_id: <id>
is_flagged: <bool>
claim: {json}
rules: [...]
clinical_note: <note>
```

The few-shot examples are **always in the same place** — at the end of the system prompt, before the OUTPUT RULES section. v0 has none; v7–v12 have 4–7 examples.

### 5.2 Schema enforcement (`RESPONSE_JSON_SCHEMA`)

Lines 74–107. `additionalProperties: True` at BOTH the outer object and the per-finding object. Required fields: outer=`findings`; finding=`severity` only.

The schema **accepts**:
- `rule_id` (string) OR `rule_ids` (list of strings)
- `quote` missing → validator synthesises one from `explanation`/`rationale` (lines 324-341)
- `category`, `suggested_code`, `explanation` all optional

The schema is **belt-and-braces**: `complete_json()` (`llm.py:153-213`) sets `response_format={"type": "json_schema", ...}` for constrained decoding, then **also** runs `jsonschema.validate()` locally. The local validation uses the same schema with `additionalProperties: True` so it accepts extra fields silently. **The validator does not reject anything except missing required fields (`findings`, `severity`).**

The `_quote_in_note()` guardrail (`auditor.py:205-246`) is the only meaningful constraint: if a quote is fabricated (no token-subsequence match in clinical_note), the whole finding is dropped (`raise AuditValidationError`, line 347). This is the **Stark/AKS hallucination guardrail** — the comment explicitly cites it as "the line between 'audit' and 'fraud'". This is the strongest contract in the system.

### 5.3 "RECALL MORE THAN PRECISION" framing

Present in v4, v7–v12. Exact wording in v12 (lines 7-17):

> "The downstream product cares about RECALL MORE THAN PRECISION. A missed billing error costs the clinic revenue; a false positive costs the biller 5 seconds of dismissing it. So:
> 1. When a rule applies to a billing element in this encounter, emit a finding. Default severity to the rule's level. Only suppress a finding if the documentation EXPLICITLY contradicts the rule.
> 2. Emit ALL applicable findings — do not stop at the first 2-3.
> 3. When documentation is silent, the rule still fires."

This is **explicitly anti-precision**. v12 has no compensating "but only emit if …" qualifier.

**Precision guard:** None in the prompt. The only precision-side mitigations are:
1. The hallucination guardrail (`_quote_in_note` rejects fabricated quotes).
2. The 2026-06-17 scorer change to `rule_id`-only matching (which lowered FP counts).
3. The cleanup of val_ca.json gold (5 false-positive dx_linkage findings removed).

There is no per-finding confidence threshold, no "if rule is borderline, suppress" instruction, no "verify the documentation supports the finding" requirement. The prompt is structured to **maximise recall at the cost of precision**, which is the project owner's stated design choice.

### 5.4 Temperature

`LLMClient.__init__` (`llm.py:96-107`) takes `timeout`, `complete`, `model`. **No `temperature` parameter.** The `complete()` method passes through kwargs but does not set temperature by default. `PINNED_DEFAULT_MODEL = "gpt-4o-mini"` is the fallback for `default_model()` (line 58).

For OpenAI: omitting `temperature` defaults to 1.0 (the OpenAI default is 1.0, not 0). For Ollama cloud: model-dependent, but the Ollama default is also non-zero.

**Result: the auditor is non-deterministic by default.** Two consecutive `run_audit()` calls on the same encounter can return different findings. The v12 F1=0.733 is therefore the F1 of one run, not a deterministic floor. Run-to-run variance is bounded but non-zero.

The grader (`grader_config.json` + `prompts/README.md:51-89`) explicitly configures `temperature=0, seed=42` for reproducibility. **The auditor does NOT have the same guarantee.**

### 5.5 Seed

`complete()` does not set a seed by default. `random.seed(42)` is set for the grader (`prompts/README.md:87`) but not for the auditor. For OpenAI's API, `seed` is an optional parameter that needs to be passed at call time. The auditor does not pass it.

### 5.6 Ollama cloud model: is "cloud" pinned?

`run_v7b_full.sh:7`: `LLM_MODEL=ollama/minimax-m3:cloud`. This is the Ollama cloud variant of the minimax-m3 model. The string `:cloud` is a **tag**, not a version. Ollama cloud tags can roll forward when the provider updates the underlying model.

The pinned model string is **`gpt-4o-mini`** (`llm.py:45`) — that's the only *pinned* model id. Anything else (including `ollama/minimax-m3:cloud`) is environmental and can drift without any code change. The v12 F1=0.733 was measured with `ollama/minimax-m3:cloud`; a future run with the same prompt but a rolled-forward Ollama cloud model could produce a different F1.

`minimax_client.py` exists (`src/ai_billing_audit/minimax_client.py`) but is a separate code path for the MiniMax platform — it does not appear to be used by the auditor. The auditor uses `LLMClient` which routes through `litellm`.

---

## 6. Known-Issues Confirmation/Refutation

| claim | status | evidence |
|-------|--------|----------|
| The 5 false-positive dx_linkage findings pre-2026-06-22 were all in the same family (over-firing on encounters with valid dx) | **CONFIRMED** | All 5 (ca_ahcip_001/002/003/006/008 pre-clean) had dx codes present and valid for the note's reported conditions; v12's pattern A explicitly prohibits firing `rule_ahcip_dx_linkage` when dx is present and matches. |
| The 3 added findings correspond to real SOMB/AHCIP concepts | **MOSTLY CONFIRMED, ONE STRETCH** | ca_ahcip_003 same_day_conflict = real SOMB rule (03.04A + 03.05A same day). ca_ahcip_008 em_level_upcode = real SOMB concept (03.01A → 03.04A undercode). ca_ahcip_006 psychotherapy_time is **borderline** — the note does not explicitly document "45-minute session", only PHQ-9 score. v12 pattern F requires either an explicit time phrase OR "clearly extended" content. Defensible but not strict. |
| The "REVIEW token" rule in v7+ fires on a literal REVIEW token | **CONFIRMED, but mislabelled** | v12 pattern A (line 50–51): `diagnosis_codes contains the literal "REVIEW" placeholder`. v7 (line 88–89): "A diagnosis or procedure code value of `REVIEW` (literal placeholder) is a CRITICAL missing-diagnosis finding." v8/v9/v10/v11 all have the same. v12 narrows the rule: also fires on empty dx AND on `R69` "unspecified" when note describes specific condition. The US val (`val.json`) has 6 encounters with `"REVIEW"` as a literal dx code value (lines 13, 637, 842, etc.) — so the rule fires as designed on those. |
| The 23/50 timeout rate on v7 at 60s; the 180s fix is on the right path | **CONFIRMED** | `auditor.py:381-385` docstring: "Default 60s is too tight for the v7 prompt + Ollama cloud path (mean=41s, p95=60s on the 50-encounter val set, 23/50 timed out at the 60s ceiling). 180s gives the cloud model enough headroom." The v12 prompt is 10539 chars (vs v7's 5444), so latency *should* be higher. `prompt_history.jsonl` row at 2026-06-22 23:00 shows v12 with mean=49.7s, p95=119.1s, 0 errors at the 180s ceiling. **But** p95=119s is dangerously close to the 180s ceiling — a future prompt iteration that adds even 50% more few-shot examples will start hitting the new ceiling. |
| The 791 tests claim: do any exercise the prompt iteration loop? | **REFUTED — no test exercises the loop** | `pytest --collect-only` shows 791 tests. None of them runs more than one prompt version end-to-end. The closest is `tests/test_v0_baseline.py:211 test_smoke_run_audit_on_first_val_encounter` which calls `run_audit(enc, llm=client, prompt_path=V0_PIN_PATH)` ONCE on the first val encounter. There is no test that: (a) runs v1–v12 in sequence, (b) asserts F1 is monotone over versions, (c) detects val-set leakage into few-shot examples, (d) detects prompt drift between `auditor_prompt.txt` and `prompts/v0/auditor_prompt.txt`. The 791 tests cover unit-level components (audit endpoint, grading logic, hallucination guardrail, schema validation, etc.) but not the prompt-iteration loop as a whole. |

---

## 7. Risk-Ranked Recommendations (Top 10)

1. **[CRITICAL] Strip val-set encounters from v12's few-shot section.** EXAMPLE 6 is ca_ahcip_004 verbatim; EXAMPLE 7 is ca_ahcip_008 paraphrased. The reported F1=0.733 is inflated by leakage. Move the two examples to a new `prompts/v12b/` or replace them with held-in examples (the `fewshot_ca.json` has 5 clean ones — pick 2 of those). Re-run smartness_test.py to get the leakage-free F1.

2. **[CRITICAL] Make the scorer deterministic.** Set `temperature=0` and `seed=42` in `auditor.py:run_audit()`'s default LLMClient. Add `temperature` and `seed` to `LLMClient.__init__` (currently only has `timeout`). Without this, every smartness_test run is one observation of a random variable. The grader already does this; the auditor should too.

3. **[HIGH] Add a smoke test at the top of `smartness_test.main()`.** Run `run_audit()` on a fixed 2-encounter fixture with known gold (e.g., one match, one no-match) before scoring the real val set. Fail loudly if P/R/F1 on the fixture drift below 0.5 — that's the canary for "the LLM is broken, don't trust the run".

4. **[HIGH] Re-author `prompts/MANIFEST.json` to log all 12 versions, not just v0 and v12.** Add entries for v1–v11 with `parent_hash` chains and whatever R/P data can be reconstructed from `artifacts/smartness_*.json`. The current 2-entry MANIFEST makes the prompt catalogue unverifiable by inspection.

5. **[HIGH] Tag `prompt_history.jsonl` rows with both the prompt version AND the val-set regime.** Add a `val_set` field (e.g., `"data/val.json"`, `"data/val_ca.json"`) to each row. Without this, the US-row and AHCIP-row runs are indistinguishable in the dashboard.

6. **[HIGH] Delete or archive dead prompts.** v1–v6, v8–v11 are kept "for diff but never used" — they confuse the prompt catalogue (a reader can't tell what's live). Either move them to `prompts/_archive/` or add a `STATUS: dead` header to each prompt file.

7. **[MEDIUM] Document the train/val/test split policy.** Add a `data/SPLIT.md` (or section in `data/README.md`) describing: (a) the 100/50/10 split, (b) the encounter_id ranges per split, (c) the hash of each split's manifest, (d) the policy for adding/removing encounters. Without this, train/val/test contamination is uncheckable.

8. **[MEDIUM] Fix the prompt-manifest hash mismatch.** `prompts/v0/MANIFEST.json:8` says `byte_size: 1200` but `prompts/v0/auditor_prompt.txt` is 1373 chars. `src/ai_billing_audit/auditor_prompt.txt` (the bundled default) is also 1373 chars but differs from `prompts/v0/auditor_prompt.txt` in 3 lines. The README claims "byte-for-byte" verification — it isn't.

9. **[MEDIUM] Add a test for prompt iteration regression.** A simple test: run `run_audit()` on a fixed 5-encounter fixture with v0, v7, and v12; assert v12's F1 ≥ v7's F1 ≥ v0's F1 - 0.1 (or some monotone-ish expectation). Currently 791 tests pass but zero catch a prompt-iteration regression.

10. **[LOW] Pin the Ollama cloud model by hash, not by `:cloud` tag.** `LLM_MODEL=ollama/minimax-m3:cloud` is a moving target. Either pin to a specific model revision (`ollama/minimax-m3:<sha256>`) or document explicitly that "cloud" can drift and re-baseline the F1 whenever the provider rolls forward.

---

## Appendix A: file:line citations

- v12 leakage: `prompts/v12/auditor_prompt.txt:198-214` (EXAMPLES 6 + 7) ↔ `data/val_ca.json:119` (ca_ahcip_004) ↔ `data/val_ca.json:257` (ca_ahcip_008)
- v11 -24 leak: `prompts/v11/auditor_prompt.txt:32`
- v0 / src default mismatch: `diff src/ai_billing_audit/auditor_prompt.txt prompts/v0/auditor_prompt.txt` (3 lines differ); `prompts/v0/MANIFEST.json:8` claims 1200-byte size; actual is 1373.
- 180s timeout fix: `src/ai_billing_audit/auditor.py:381-385`
- Hallucination guardrail: `src/ai_billing_audit/auditor.py:205-246` (`_quote_in_note`) and `:342-350` (drop fabricated findings)
- Schema laxity: `src/ai_billing_audit/auditor.py:74-107` (`additionalProperties: True`)
- Quote-synthesise fallback: `src/ai_billing_audit/auditor.py:324-341`
- Per-encounter vs micro: `scripts/smartness_test.py:30-39` (docstring), `:246-254` (compute), `:319-357` (report)
- Severity disabled: `scripts/smartness_test.py:84-99` (docstring), `:122-127` (gating)
- Jaccard 0.40: `scripts/smartness_test.py:71-75` (compute), `:82` (threshold)
- Multiplicity: `scripts/smartness_test.py:202-212`
- No smoke test: `scripts/smartness_test.py:434-450` (`main()`)
- `prompt_version` always `"auditor_prompt"`: `artifacts/prompt_history.jsonl` (every row, line 1)
- No temperature default in LLMClient: `src/ai_billing_audit/llm.py:96-107` (`__init__`)
- Grader temperature=0, seed=42: `prompts/README.md:51-89`
- v0 is the BASELINE default: `src/ai_billing_audit/auditor.py:60-61, 142-158`
- v7b full run script: `scripts/run_v7b_full.sh` (sets `LLM_MODEL=ollama/minimax-m3:cloud`)
- v12 last-run p95 latency: `artifacts/prompt_history.jsonl` row at `2026-06-23T00:33:47Z` (p95_s=119.14, n_errors=0)

## Appendix B: encounter_id census

- `data/val.json`: 50 encounters, enc_10000 + enc_10001 + ... (US, synthetic)
- `data/val_ca.json`: 10 encounters, ca_ahcip_001..010 (AHCIP, Hermes-authored)
- `data/fewshot_ca.json`: 5 encounters, ca_fewshot_001..005 (held-in for AHCIP)
- `data/val_sample.jsonl`: 150 rows (test_sample.jsonl by another name — same content), categories-only summaries
- `data/train.json`: 100 encounters, enc_NNNN shape (US, synthetic)

End of report.