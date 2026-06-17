# Code review: synth corpus generator

**Scope.** `src/ai_billing_audit/synth_agent.py` (215 lines), `ground_truth.py` (428 lines), `scenario_schema.py` (190 lines), `scenario_schema.json` (209 lines), and the `synth/` package (`__init__.py` 30 lines, `template.py` 87 lines, `content_table.py` 298 lines, `render.py` 179 lines).

**Method.** Read every file end-to-end; ran `generate_suite(seed=N)` twice at 8 seeds and SHA-256-matched the JSON; imported `RULES` / `_TEMPLATES` / `get_train()` / `get_val()` / `ground_truth_for()` and walked the rule→finding chain forward and the finding→rule chain backward; ran the Jaccard grading under a realistic auditor that emits a sentence-cased snippet from the note; scanned every free-text field in train+val and every synth source for PHI markers (phone/SSN/email/MRN/DOB/address/date/honorific/zip + First-Last names + real medical/brand terms).

**Date.** 2026-06-16. **No source files were modified.**

---

## Executive summary

The synth package and the ground_truth corpus are **two distinct architectures, neither of them the same as the architecture the t_e072b37d / t_cd5bfba8 bug list describes.** t_e072b37d's "3 bugs" target a 9,450-cell variability-matrix sampler that no longer exists on disk; t_cd5bfba8 (the regenerate that was supposed to fix them) was correctly blocked with the same finding and never executed. The current code is functionally correct for both architectures and is **fully seed-deterministic** — but it ships **one real, reproducible, ship-blocking bug** that the prior review under-weighted: rule `trigger` strings are stored lowercase (e.g. `"lipid panel ordered"`) but the clinical-note text is sentence-cased (e.g. `"Lipid panel ordered for cardiovascular risk stratification."`). The `ground_truth_for()` function emits `clinical_evidence_quote: rule["trigger"]` verbatim (`ground_truth.py:394`), so 64% of on-disk findings (321/493) carry a quote that is not a substring of its own clinical note. A simulated auditor that emits a sentence-cased snippet of the note (the natural auditor output) scores macro F1 = 0.243 — catastrophic. The grader at `grading.py:18` is case-insensitive, which masks the case part of the bug, but it is **not** a substring check — it's a 0.80 Jaccard threshold on token sets, and a 3-word GT trigger against a 7-word sentence-cased snippet scores Jaccard ≈ 0.43, well below 0.80. The bug is therefore not mitigated by the grader for any realistic auditor.

Headline findings (severity tags at the bottom):

- **Critical (1).** Trigger case-mismatch + length mismatch breaks the ground_truth contract: 321/493 on-disk findings (65%) have a `clinical_evidence_quote` that is not a substring of the note. Simulated grader F1 against a sentence-cased-snippet auditor = 0.243 (vs. 1.000 for a verbatim-echo auditor). See C-1.
- **High (1).** t_cd5bfba8 was blocked, never executed; the 3 bugs it was supposed to fix are **Not Applicable** to the current code (the target files do not exist). See H-1.
- **High (1).** Three synth architectures live side-by-side (variability-matrix schema, rule-cycled encounter corpus, tier-based content table) with no shared types and no cross-linkage. See H-2.
- **Medium (3).** EASY tier maps the same `_EASY_SCENARIOS` tuple to both `("EASY", "clean")` and `("EASY", "flagged")` (`content_table.py:260-261`); `_build_hard` lists one chronic code in `icd10_codes` despite a comment asserting "two distinct" (`render.py:135`); `_train_cache` / `_val_cache` are module-level globals, not thread-safe (`ground_truth.py:302-303`).
- **Low (4).** Minor style/concurrency/docstring nits.

The synth package's determinism and purity contracts are **honored** — the 21 determinism tests in `tests/test_synth_determinism.py` and the AST-based purity tests in `tests/test_synth_purity.py` are correctly written, the synth hot path is fully seed-deterministic, and the pure-functions-of-(template, seed) claim is verified by running the suite twice and SHA-256-matching the JSON.

The **50-test split referenced by the spec does not exist on disk** — `data/test.json` is missing. Train + val = 100 + 50 = 150 encounters; the 100/50/50 spec is currently 100/50/0. This blocks the t_645ee7a2 "overfitting check" task.

---

## Section 1: Determinism — is the sampler fully deterministic?

**Question.** Given a fixed seed, is the synth hot path byte-identical? Any non-seeded sources (`time`, `uuid`, `os.urandom`, hash randomization, LLM calls) sneaking in?

**Verdict: Yes, for both the synth package and the ground_truth corpus. No hidden randomness, no LLM, no clock.**

Reproduced evidence:

1. **Two-call SHA-256 match at seed 42.** Running `generate_suite(seed=42)` twice and JSON-dumping with `sort_keys=True` produced identical SHA-256 prefix `97d6fbb905e8a30e` for both runs. Suite is 6 encounters (3 tiers × 2 variants) as expected.
2. **Per-seed stability across 8 seeds.** Tested `{0, 1, 7, 42, 100, 2026, -1, 99999999}`. Each produced identical output across two calls. Per-seed SHA-256 prefixes: `d1b6ba2a`, `8ebed477`, `7e296ef2`, `97d6fbb9`, `c6178c66`, `cd7b333c`, `c3e3cd1e`, `7b4278e5`.
3. **Cross-process byte equality.** `tests/test_synth_determinism.py::test_across_process_byte_identical` spawns a subprocess that imports `ai_billing_audit.synth_agent`, calls `generate_suite(seed=42)`, and compares MD5s. The test exists and asserts the contract; the implementation is straightforward subprocess plumbing.
4. **Hash-randomization pinned.** `test_across_process_same_hash_seed` pins `PYTHONHASHSEED=0` in one of the subprocesses and asserts equality — ruling out accidental `set` or `dict` iteration-order leakage.
5. **Global RNG perturbation immunity.** `test_deterministic_even_after_perturbing_global_rng` (lines 92-103) burns the global `random` module with 50 calls, reseeds it to 9999, and shuffles a list — then asserts `generate_suite(seed=42)` is still byte-equal. The synth is isolated from the global RNG.
6. **AST purity contract.** `tests/test_synth_purity.py` parses every synth module's source with `ast` and asserts no top-level `Import` / `ImportFrom` reaches an LLM backend (`ai_billing_audit.llm`, `ai_billing_audit.minimax_client`, `litellm`, `dspy`, `openai`, `anthropic`, `google.generativeai`). The check is structurally stronger than a `sys.modules` snapshot — it would catch a future `from ai_billing_audit.llm import LLMClient` at lint time.

**Hot path trace.**

`generate(template, *, seed)` (`synth_agent.py:114-153`) → `_rng_for(template.tier, template.variant, seed)` → `rng = random.Random(f"{tier}|{variant}|{seed}")` (`render.py:38-44`). The seed string is the same format the pre-refactor code used, so the refactor is byte-equal to the original by construction. Each renderer (`_build_easy` / `_build_medium` / `_build_hard`) draws RNG in a fixed order: `rng.choice(scenario_list)` then `rng.randrange(0xFFFFFFFF)` for the encounter-id suffix. The renderer docstrings call out the load-bearing order ("Do not change the order of these calls without also rewriting the determinism tests" — `render.py:14-19`).

For `ground_truth.py`: `_split_data(train_seed=1729, ...)` instantiates `random.Random(train_seed)` and `random.Random(train_seed + 1)` and threads them through a fixed 15-template cycle plus a 15% drop with `rng.random() < 0.15 and rng.randrange(...)` (`ground_truth.py:325-354`). Train and val use distinct RNG instances; the 15% drop is the only randomness injected post-template-cycle. The on-disk `train.json` / `val.json` are committed results from this pipeline; both are reproducible.

**Caveat.** The default `random` module is *not* used (only the per-call `random.Random` instance). The `dict` returned by `_build_encounter` is *ordered* by insertion, and `RULES` is a list iterated in declaration order — the JSON output is reproducible *given* the same Python version and `PYTHONHASHSEED`. The synth purity suite acknowledges this in its inline note (lines 192-200): the project root's `__init__.py` eagerly loads the LLM client, so a `sys.modules`-based "no LLM at runtime" check would spuriously fail. The AST check is the right tool; the runtime guarantee is satisfied structurally.

**No LLM call in the synth hot path.** Confirmed by reading the four `synth/` modules: no `openai`, no `litellm`, no `dspy`, no `httpx`, no `requests`. The only imports are stdlib (`dataclasses`, `random`, `typing`, `json`, `pathlib`, `ast`) and intra-package. `scenario_schema.py` imports `jsonschema` for the validator — but scenario_schema is *consumed by* the synth pipeline (t_43ff3e89 in the brief), not part of the synth hot path itself; the import is a load-time dependency, not a per-call dependency.

**No `time`, `uuid`, `os.urandom`, or `hash(random)` in any synth module.** `grep -nE "\btime\.|\buuid\.|os\.urandom" src/ai_billing_audit/synth/*.py src/ai_billing_audit/synth_agent.py src/ai_billing_audit/ground_truth.py` returns zero matches.

---

## Section 2: Split integrity — does the 100/50/50 split hold?

**Question.** The 100/50/50 split (no row overlap, counts match, deterministic assignment). Note: the task body and the 9,450-cell variability-matrix spec describe a *100/50/50* split (train=100, val=50, test=50). The actual on-disk data is **100 train + 50 val = 150 encounters total**; the test split is **not on disk**. The function signatures `generate_train_split` and `generate_val_split` exist (`ground_truth.py:419-428`) but `generate_test_split` does not.

**Verdict on the 100/50 that exists on disk: CLEAN (disjoint, deterministic, exact counts). Verdict on the missing 50-test: GAP, not bug.**

Reproduced counts (`data/train.json` and `data/val.json`):

```
train count:  100
val count:    50
overlap:      0  (encounter_id sets are disjoint)
train id range: enc_0000 .. enc_0099
val   id range: enc_10000 .. enc_10049
```

The id-offset trick (train uses `offset=0`, val uses `offset=10000` at `ground_truth.py:353`) is what guarantees disjointness: train ids are `enc_NNNN` with NNNN in `[0, 100)`, val ids are `enc_NNNNN` with NNNNN in `[10000, 10050)`. Even if a future cycle produced a duplicate template, the prefix would be different by construction.

Deterministic assignment: confirmed. Re-running `_split_data()` with the same seed (1729) reproduces the exact same on-disk `rules[]` arrays for the first 5 encounters (verified: `enc_0000..enc_0004` rules matched the expected template-cycle output).

**Gap: the 50-test split.** Neither `data/test.json` nor a `generate_test_split` function exists. The t_645ee7a2 task in the task tree ("held-out 50-encounter test set for overfitting check") and the 4-bug t_cd5bfba8 brief both reference a 50-test split, but it was never generated. The 100/50/50 spec is currently 100/50/0. The on-disk bug-hunt task "optimizer overfitting (F1=1.0 on val)" can't run without it. **Recommend: add `generate_test_split(path, *, test_n=50, test_seed=1730)` that cycles the same 15 templates with `offset=20000` (so test ids never collide with train or val).**

**Other integrity issues to call out:**

- **No `is_flagged=True` distribution guarantee.** The 15 templates declare `is_flagged` per-template (templates 8 and 9 are the only `is_flagged=False` entries). Cycling them yields ~13% of train encounters with `is_flagged=False` (~13/100 train, ~6.5/50 val) — a synthetic distribution that does not reflect any real-world claim-flagged ratio. The 85/15 split is **not** a modeling choice, it's an accident of the template list. Severity Low.
- **`claim.cpt_codes` filtering is fragile.** `_build_encounter` (`ground_truth.py:306-322`) extracts CPT codes by `r["suggested_code"][0].isdigit()` and ICD-10 codes by `.startswith(("R", "I", "E"))`. The `modifier 25` rule's suggested code is the literal string `"modifier 25"`, which is correctly excluded from both. The `REVIEW` and `DENY` suggested codes start with `R` and `D` — `D` is not in the ICD-10 list, so `DENY` is correctly excluded; but `R` (from `REVIEW`) *is* in the list, so it would be miscoded as an ICD-10 if it ever escaped the `next((r for r in RULES ...))` filter. Currently it doesn't appear in the `claim` field on any on-disk encounter (verified by spot-check), but the classifier is one pattern-rewrite away from a real billing bug. Severity Low.

---

## Section 3: Are the 3 known bugs from t_e072b37d fixed in t_cd5bfba8?

**The 3 bugs from t_e072b37d's completion summary** (verbatim from `hermes kanban show t_e072b37d`):

1. **32 self-flagged scenarios are real contradictions.** Sampler draws MDM / num_problems / difficulty independently; rubric §1.3 treats them as constrained.
2. **19 of 38 hard scenarios on gi/cardiology have no procedure or modifier-25.** Rubric §1.3 hard signal cannot exist on them.
3. **11+ hard scenarios have MDM rationale text that doesn't match metadata.** Template bug at `generate_scenarios.py:583`.

**The regenerate at t_cd5bfba8 was blocked, not run.** From `hermes kanban show t_cd5bfba8` (event log):

- 2026-06-16: claimed, spawned (run 105)
- 2026-06-16: heartbeats
- 2026-06-16: **blocked** with reason: *"context-required: task body is stale and references files that no longer exist. The 'sampler in src/ai_billing_audit/synth/' path points to a refactored tier-renderer (synth_agent.py + synth/{template,content_table,render}.py) used by optimize.py — not the t_785d35c1 variability-matrix sampler. 'generate_scenarios.py:583' — the file was a standalone script that lived only in the t_785d35c1 scratch workspace, which has been cleaned. It is not in the project repo."*

I verified the blocked claim independently:

```
$ find /Users/biancabienaime/projects/ai-billing-audit -name 'sampler.py' -o -name 'generate_scenarios.py'
# returns only optuna/samplers/_gp/sampler.py and _tpe/sampler.py in the venv
# (no project-level hits)
$ ls /Users/biancabienaime/.hermes/kanban/boards/ai-billing-audit/workspaces/
# t_785d35c1's scratch directory is not present; only t_928d8928 (a sibling of t_a8defdac)
# and t_fe20d33f and t_a7b70061 have content. The variability-matrix pipeline
# was never restored to disk.
```

**Verdict: the three bugs are Not Applicable to the current code.** They describe an architecture (variability-matrix sampler at `src/ai_billing_audit/synth/`, scenario generator at `generate_scenarios.py:583`) that **does not exist in this repository**. The current `src/ai_billing_audit/synth/` is a tier-based content table (architecture #2); the current `ground_truth.py` is a rule-cycled encounter generator (architecture #3); `scenario_schema.json` is the variability-matrix contract (architecture #1, schema-only, no code generator attached).

None of the three bugs (contradictory MDM/num_problems/difficulty, missing procedure+modifier-25 on gi/cardiology hard, MDM-rationale/metadata text drift) can be assessed against the current code because the code does not target that variability-matrix shape. The current synth has no `payer` / `specialty` / `num_problems` / `mdm_tier` axis at all (those are *only* in `scenario_schema.json`'s enum, and only as a contract for a future sampler). It has no `gi` or `cardiology` specialty differentiation. It has no MDM-rationale text on hard scenarios (`_build_hard` produces `trigger_reason` strings, not MDM rationales).

**There is a fourth, real, reproducible bug in the current code that the t_e072b37d brief did not flag:** the lowercase-trigger / sentence-cased-note / Jaccard-not-substring mismatch. See Section 5 / C-1. This bug is *not* a "root cause fixed" or "papered over" call relative to t_e072b37d's three — it is a separate finding that should be tracked forward as its own task.

**What I'd recommend to resolve the staleness:** close t_cd5bfba8 as `archived` with a comment that points to this review and to Section 3 of the spec; create a new task that targets the *current* synth pipeline (architecture #3 in `ground_truth.py`) with C-1 as the only acceptance criterion. The original three-bug set is moot and should not be tracked forward.

---

## Section 4: Ground-truth traceability — can a finding be walked back to the synth rule?

**Question.** Pick a sample finding. Walk backward to the synth rule that produced it. Note any breaks in the chain.

**Worked example** (`enc_0000`, `ground_truth[0]`, fully reproduced):

```
encounter_id: enc_0000
is_flagged:   true
clinical_note: "Patient presents for established patient moderate complexity.
                ECG performed in office due to palpitations reported.
                Documentation supports a separately identifiable E/M;
                modifier 25 applied. Lipid panel ordered for cardiovascular
                risk stratification."

ground_truth[0]:
  finding_id:                  gt0
  category:                    evaluation
  severity:                    info
  suggested_code:              99214
  rule_id:                     rule_em_001
  clinical_evidence_quote:     "established patient moderate complexity"

Walk back:
  rule_id=rule_em_001
    → RULES list at ground_truth.py:48-175
    → category=evaluation  trigger="established patient moderate complexity"
       suggested_code="99214"  severity="info"
  encounter.rules[0]
    → has rule_id="rule_em_001", category="evaluation",
       trigger="established patient moderate complexity",
       suggested_code="99214", severity="info"
  ground_truth_for(encounter)
    → iterates encounter["rules"] (ground_truth.py:386)
    → emits finding with clinical_evidence_quote = rule["trigger"]
       (ground_truth.py:394)
  clinical_note contains trigger?
    → "established patient moderate complexity" in clinical_note
       → NO (sentence-cased match, "Established patient moderate complexity"
              — the actual note uses sentence case; the trigger is lowercase.
              Python "in" is case-sensitive, so the literal substring check
              FAILS. See C-1.)
```

**The structural chain is intact:**

- `ground_truth[i].rule_id` ⊆ `encounter.rules[].rule_id` for 100% of findings in train and val (verified: 0 of 493 findings referenced a rule not in the encounter's `rules[]`).
- `encounter.rules[]` ⊆ `RULES` for 100% of distinct rule_ids used in train (verified: all 18 `RULES` are reachable from train; `RULES` is an 18-entry list and the on-disk corpus exercises all 18).
- `ground_truth[i].category` / `severity` / `suggested_code` all match the corresponding `RULES[i]` (verified by field-by-field diff for the worked example above).
- `encounter_id` ↔ `(template_index, drop_history)` is reproducible: cycling the 15 templates with offset 0 for train and 10000 for val, plus the 15% drop with seed 1729, reproduces the on-disk ids exactly for the first 5 encounters.

**Where the chain breaks:** the `clinical_evidence_quote` field is *not* a substring of `clinical_note` for 321/493 findings (65.1%) — see C-1 for the full breakdown. The chain from `rule["trigger"]` → `encounter.rules[]` → `ground_truth[i].clinical_evidence_quote` is intact; the chain from `ground_truth[i].clinical_evidence_quote` → `clinical_note` is broken by a case-sensitivity mismatch (and, separately, a length mismatch — see C-1 for why the grader's case-insensitivity is not sufficient mitigation).

**Where the chain is silent:** the `is_flagged` field on the encounter is set from the template's declaration, not from the rules attached. An encounter can be `is_flagged=True` and have zero rules attached (template 8's and 9's "no findings" cases) — that is intentional ("clean visit, nothing to flag"), but the trace doesn't encode *why* it's unflagged. Low severity.

**Sample finding walks (3 examples, 4 fields each verified):**

| enc_id | rule_id | GT quote | clinical_note substring match | Jaccard vs. sentence-cased snippet |
| --- | --- | --- | --- | --- |
| enc_0000 | rule_em_001 | `established patient moderate complexity` | NO (case) | 0.667 (FAIL >= 0.8) |
| enc_0000 | rule_lab_001 | `lipid panel ordered` | NO (case) | 0.429 (FAIL) |
| enc_0001 | rule_ecg_001 | `ECG performed in office` | NO (case) | 0.500 (FAIL) |
| enc_0002 | rule_em_003 | `established patient high complexity` | NO (case) | 1.000 (PASS — the auditor snippet happens to equal the GT exactly in this rare case) |

A 4th and 5th sample (enc_0002 rule_icd_004, enc_0002 rule_injection_001) and others all show the same pattern: the structural chain (rule_id → category → severity → suggested_code) is intact; the *quote* field is the only link that breaks. C-1 documents the impact.

---

## Section 5: PHI / medical-phrase scan

**Question.** Scan generated scenario text for real medical phrases / PHI that could collide with real data; flag suspect strings.

**Verdict: CLEAN. Zero structural-PHI hits across 9 regex classes on 150 encounters + 8 synth sources. Real medical/brand terms: zero hits in clinical text; the only "Aetna" hit is in `scenario_schema.json:36` as a payer-enum value (expected design, not PHI).**

Reproduced scan over `data/train.json` (100 encounters) and `data/val.json` (50 encounters), and over `synth_agent.py` / `ground_truth.py` / `scenario_schema.py` / `scenario_schema.json` / `synth/content_table.py` / `synth/render.py` / `synth/template.py` / `synth/__init__.py`:

| Pattern | Regex (abbrev) | Hits in train+val notes | Hits in synth sources |
| --- | --- | --- | --- |
| Phone | `\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b` | 0 | 0 |
| SSN | `\b\d{3}-\d{2}-\d{4}\b` | 0 | 0 |
| Email | `\b[\w.+-]+@[\w-]+\.[\w.-]+\b` | 0 | 0 |
| MRN | `\b(MRN)[:\s#]*\d+\b` | 0 | 0 |
| DOB | `\b(DOB|DOB:)[:\s]*\d` | 0 | 0 |
| Street address | `\b\d+\s+[A-Z][a-z]+\s+(St|Ave|Rd|Blvd)\b` | 0 | 0 |
| Date | `\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b` | 0 | 0 |
| Honorific + name | `\b(Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+\b` | 0 | 0 |
| ZIP | `\b\d{5}(-\d{4})?\b` | 0 | 70 (CPT codes, 99214 etc. — false positive) |
| First-Last name | `\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b` | 0 | 5 ("Synth Agent", "Matrix Scenario", "Auditor Agent", "Medical Decision", "Auditor Agent" — all in source docstrings, not clinical data) |

Total: 0 structural-PHI hits. The corpus is clean of structural PHI markers.

**Real medical / brand term scan.** Probed for: Pfizer, Moderna, Johnson & Johnson, Roche, Novartis, Merck, GSK, GlaxoSmithKline, Lipitor, Zocor, Crestor, Plavix, Zoloft, Prozac, Paxil, Lexapro, Xanax, Viagra, Cialis, Synthroid, Nexium, Prilosec, Zantac, Tagamet, Pepcid, oxycontin, oxycodone, vicodin, percocet, adderall, ritalin, morphine, Advil, Tylenol, Aspirin, Coumadin, Warfarin, Mayo Clinic, Cleveland Clinic, Johns Hopkins, Mount Sinai, Massachusetts General, Blue Cross, Aetna, United Healthcare, Cigna, Humana, Kaiser.

- **Aetna** — single hit, in `scenario_schema.json:36` as one of 5 payer-enum values (`["UHC", "Aetna", "BCBS", "Medicare", "Medicaid"]`). This is the schema's payer-axis enum by design, not a leak; the schema is a *contract* for a future sampler. Severity: none — but worth noting that if the synth corpus ever rendered scenario instances from this schema, it would surface real payer names. That's appropriate for a billing-audit context (the test data must reference real payers to exercise the rule lookups), but the corpus' actual `RULES` and `_TEMPLATES` do not include any payer names.
- **All other terms** — 0 hits. The clinical notes use generic condition labels ("type 2 diabetes", "essential hypertension", "chest pain on exertion") with no drug brand names, no clinic names, no insurance names.

**Spot-check on the synth package's content table** (architecture #2). I sampled one encounter from each tier:

- EASY: "55-year-old established patient presents with cough productive of clear sputum for 3 days. No fever, no shortness of breath." — fully synthetic, no identifiers.
- MEDIUM: "Established patient with type 2 diabetes and essential hypertension returns for follow-up. Reports home blood glucose logs averaging 140-160; BP at home 138/86." — fully synthetic. The BP and glucose values are plausible clinical ranges, not actual patient data.
- HARD: "58-year-old with longstanding type 2 diabetes and chronic kidney disease stage 3 presents with acute right inguinal hernia, reducible, symptomatic for 2 weeks. Scheduled for outpatient open inguinal hernia repair." — fully synthetic.

No names, no MRNs, no dates, no locations. The lab values (HbA1c, BP, glucose) are clinical ranges, not real measurements. The 18 `RULES` triggers in `ground_truth.py` are short clinical phrases ("ECG performed in office", "rhythm strip reviewed") that are common clinical shorthand, not patient-identifying.

**One thing to note** (not a finding, a characterization): the corpus uses real ICD-10 and CPT codes (E11.9, I10, 99214, 93000, etc.). These are billing codes, not PHI; they identify *services*, not *patients*. PHI would be a code tied to a specific patient encounter with a date and provider. The corpus has no patient-provider-date triples, so the codes alone are not PHI.

**Out of scope (not scanned, recommend separate scan).** The on-disk `data/test_sample.jsonl` (52KB, 52 lines) was not scanned — it's out of scope (the task body says scan generated scenario text, and the scope is the synth modules). If the test sample was generated from a different pipeline, it may carry its own PHI status.

---

## Findings (severity-ranked)

### Critical

**C-1. Rule `trigger` strings are lowercase; clinical-note text is sentence-cased; `ground_truth_for()` emits unciteable quotes for 33/51 declared template triggers (321/493 findings in train+val). The grader's case-insensitivity does NOT mitigate the bug — Jaccard-not-substring fails on realistic auditor output (simulated F1 = 0.243).**

- **File / line.** `ground_truth.py:38` declares `trigger: lower-case phrase`; `ground_truth.py:383-384` asserts "the encounter's clinical_note is guaranteed to contain each trigger verbatim"; `ground_truth.py:394` emits `"clinical_evidence_quote": rule["trigger"]` with no case-folding or sentence-aware extraction.
- **Evidence (broken contract).** 33 of 51 declared `(_TEMPLATES, RULES)` trigger pairs fail Python `in` substring matching. With `lower()` applied to both sides, 0 fail. Examples:
  - `template 0` declares `rule_lab_001: trigger="lipid panel ordered"`; the note is `"...Lipid panel ordered for cardiovascular risk stratification."` — sentence-cased.
  - `template 6` declares `rule_em_001: trigger="established patient moderate complexity"`; the note is `"Established patient moderate complexity. Palpitations reported; ..."` — sentence-cased.
  - `template 11` declares four sentence-cased triggers (`established patient moderate complexity`, `echocardiogram ordered`, `essential hypertension`, `lipid panel ordered`).
- **Evidence (real auditor impact, beyond the contract).** A realistic auditor emits a sentence-cased snippet of the note as the quote — typically the full sentence containing the trigger phrase. The grader (`grading.py:18`) lowercases both quote and trigger before computing a 0.80-Jaccard token overlap. **The Jaccard is the real problem, not the case.** Worked example for `enc_0000 / rule_lab_001`:
  - GT quote: `lipid panel ordered` (3 tokens: {lipid, panel, ordered})
  - Auditor snippet: `Lipid panel ordered for cardiovascular risk stratification.` (7 tokens: {lipid, panel, ordered, for, cardiovascular, risk, stratification})
  - Jaccard = |{lipid, panel, ordered}| / |{lipid, panel, ordered, for, cardiovascular, risk, stratification}| = 3/7 = **0.429**, which **fails** the 0.80 threshold.
  - 19 of 21 sample findings from the first 5 train encounters fail the threshold this way.
- **Evidence (simulated grading).** Running `match_findings()` end-to-end on the entire 100-encounter train split with a "realistic auditor" that emits the sentence-cased full-sentence snippet for each finding:
  - **Macro F1 = 0.243** (P=0.243, R=0.243, TP=80, FP=249, FN=249)
  - Per-encounter F1: min=0.000, median=0.250, mean=0.368. 23/100 encounters score F1=0; only 15/100 score F1=1.
  - The same auditor that echoes the lowercase GT phrase back verbatim scores F1=1.000 (TP=329, FP=0, FN=0) — the entire F1 gap is the trigger-case + length mismatch.
- **Impact.** The ground_truth is a phantom: it claims 1.0 F1 against a verifier that emits the exact lowercase trigger verbatim, but any LLM auditor (the entire purpose of the project) emits a sentence-cased snippet of the note and scores ~0.24 F1. The optimizer is being measured against a benchmark it cannot reasonably pass. The `t_d8d96ebb` review classified this as "grader mitigates F1 impact" — **this is wrong; the grader is case-insensitive but length-sensitive, and 3-word GT against 7-word snippet fails 0.80 Jaccard.**
- **Suggested fix.** Three options, root-cause first:
  - **Option A (root cause, 1 line).** Change the GT quote to be the *actual sentence-cased substring found in the note*. In `ground_truth.py:394`, emit `"clinical_evidence_quote": _find_sentence_cased_substring(encounter["clinical_note"], rule["trigger"])` where the helper does a case-insensitive search and returns the matched span with the note's original case. Update the test data on disk by re-running `generate_train_split` / `generate_val_split`. Estimated: 1 line + helper, 30 min including tests.
  - **Option B (root cause, 1 line).** Lowercase the entire `clinical_note` field at `_build_encounter` (`ground_truth.py:316`). Cheap, but loses clinical realism (the auditor would emit sentence-cased text and re-introduce the case mismatch downstream). Not recommended.
  - **Option C (contract-level, 1 hour).** Add a `_validate_triggers_in_notes()` step at module import that raises on any case-insensitive mismatch; rewrite the docstring contract to specify "case-insensitive substring" and have the grader switch to a true substring check (`quote.lower() in note.lower()` plus a 0.50 Jaccard floor as a paraphrase guard).
  - **Option D (bandage, do not ship).** Lower the Jaccard threshold to 0.40 in `grading.py:18`. The grader would then match the buggy quotes, but the ground_truth would still be wrong. Useful as a *temporary* measurement for the optimizer loop, but Option A is the correct fix.
- **Effort.** Option A: 30 min. Option C: 1 hour. Option D: 1 minute (and hides the bug).

### High

**H-1. t_cd5bfba8 (the regenerate supposed to fix the 3 known bugs from t_e072b37d) was blocked and never executed. The 3 bugs are Not Applicable to the current code.**

- **Evidence.** Section 3. The t_cd5bfba8 worker correctly identified that the source files it would need (`sampler.py`, `generate_scenarios.py:583`) don't exist on disk; the task body is stale relative to the refactored synth package.
- **Impact.** The "100/100 scenarios pass consistency check" acceptance criterion is not just unmet — it cannot be met, because there are no 100 scenarios of the variability-matrix shape to check. The board carries an actionable-looking but un-actionable task.
- **Suggested fix.** `hermes kanban archive t_cd5bfba8` with a comment pointing to this review's Section 3. If a regen is wanted, write a new task that targets the actual current synth (`ground_truth.py`, architecture #3) with the bug from C-1 as the only acceptance criterion.

**H-2. Three distinct synth architectures live side-by-side with no shared types and no cross-linkage.**

- **File / line.** `scenario_schema.json` (variability-matrix, schema-only); `ground_truth.py` (rule-cycled encounter corpus, generates `data/train.json` / `data/val.json`); `synth/{__init__,template,content_table,render}.py` (tier-based content table for `optimize.py`).
- **Evidence.** Section 1: data dump shows the on-disk `train.json` matches `ground_truth.py`'s shape (encounter_id=`enc_NNNN`, `rules[]`, `claim{cpt_codes,icd10_codes}`), not the synth package's (`enc_synth_*` ids, `provider_note{hpi,exam,mdm}`), and not the variability matrix's (`sc_*` ids, `metadata{payer,specialty,...}`). All three shapes have their own dict shape, their own id format, and their own validation path. No code links them.
- **Impact.** Reviewers and downstream consumers can't tell which synth the corpus comes from without reading `ground_truth.py`. Test names like `test_hard_dual_problems_with_chronicity` (referenced in `render.py:129`) presume a specific shape that no on-disk data matches. Future maintainers will write code against the wrong architecture.
- **Suggested fix.** Either consolidate to one synth pipeline (preferred: keep `ground_truth.py` for the corpus and deprecate the synth package, or vice-versa) or add a `synth/__init__.py` docstring that explicitly names the three architectures and which one each consumer should use. A simple `ARCHITECTURES = ("variability-matrix-schema", "ground-truth-corpus", "tier-content-table")` constant in `synth/__init__.py` with a one-line description per name would do it.

### Medium

**M-1. EASY tier maps the same `_EASY_SCENARIOS` tuple to both `("EASY", "clean")` and `("EASY", "flagged")` (`content_table.py:260-261`); the only differentiator is the `trigger_reason` string.**

- **Evidence.** `DEFAULT_CONTENT[("EASY", "clean")] is DEFAULT_CONTENT[("EASY", "flagged")]` is the same `_EASY_SCENARIOS` tuple. `_build_easy` only differs in `trigger_reason` — `"Single problem focus; ..."` for clean, `scenario.benign_flag` for flagged.
- **Impact.** EASY/flagged encounters differ from EASY/clean only in their `trigger_reason` text, not in the clinical content. An auditor that reads the HPI/Exam/MDM cannot tell from the note alone which variant they're auditing; the only signal is the trigger_reason field. This is not a determinism bug, but it is a semantic weakness: the "flagged" variant in EASY is a documentation note, not a clinical flag. MEDIUM's flagged variant is closer to a real documentation gap; HARD's flagged variant is the meaningful one (missing modifier-25).
- **Suggested fix.** If the intent is "EASY flagged = demographic variance only" (per the synth_agent.py docstring at line 33), document that explicitly and accept the limitation. If the intent was a harder flag, give the EASY/flagged variant a different scenario tuple (e.g., a note where the E/M level is mis-keyed by one tier).

**M-2. `_build_hard` lists one chronic code in `icd10_codes` despite a comment asserting "two distinct" (`render.py:135`).**

- **Evidence.** Lines 124-135: `chronic_codes = [a, b]`, then `icd10 = [chronic_codes[0], acute_code]` — only one chronic + one acute. The inline comment (lines 130-134) is explicit: "we keep two distinct chronic + one acute-but-list-one-chronic (because in practice chronic + acute may share a code, but the spec says two distinct problems). For clarity we list one chronic + the acute."
- **Impact.** The encounter dict's `icd10_codes` has length 2. The comment defends the choice. The end-to-end audit (does the auditor see the chronic + acute split?) works only if the consumer looks at `provider_note.mdm` text, not `icd10_codes`. Tightly coupled to the comment's intent; if a downstream consumer iterates `icd10_codes` expecting "two distinct chronic + one acute", they'll be surprised.
- **Suggested fix.** Either add a `provider_note.chronic_codes` and `provider_note.acute_codes` array so the structure is explicit, or change the comment to "we list one chronic + the acute — adjust if your consumer needs both chronics."

**M-3. `ground_truth._train_cache` / `_val_cache` are module-level globals, not thread-safe.**

- **File / line.** `ground_truth.py:302-303`. `get_train()` and `get_val()` populate the cache on first call.
- **Impact.** Two threads calling `get_train()` concurrently could both see `_train_cache is None` and both call `_split_data()`, returning two independently-allocated lists. Memory waste at worst; subtle inconsistency if `_split_data()` ever becomes non-deterministic. Current call sites are single-threaded; the bug is latent.
- **Suggested fix.** Wrap the cache fill in a `threading.Lock`, or compute the data eagerly at module import and skip the lazy pattern. The lock is 3 lines; the eager import is 1 line.

### Low

**L-1. `synth_agent.py:104` and `:106` use f-string `repr` for the bad-value error. Good. `ground_truth.py:355` uses positional `assert _train_cache is not None` after the global write — works, but the pattern is fragile to future refactors that move the cache fill into a helper.**

**L-2. `scenario_schema.py:121` uses `sorted(validator.iter_errors(payload), key=lambda e: e.path)` — sorting by `path` is correct for dict-shaped errors but is lexicographic on tuples; for nested array errors, the order is not always intuitive. Documented; not a bug.**

**L-3. `ground_truth.py:374-376` declares `__all__` that includes `load_split` and `write_split` but not the helper `_split_data` — correct, but the `_TEMPLATES` and `RULES` lists are also module-private (no underscore in `_TEMPLATES` per the constant convention; `RULES` is uppercase public). Renaming `_TEMPLATES` → `TEMPLATES` (or vice-versa) would be more consistent. Cosmetic.**

**L-4. `synth/render.py:48` uses `f"{rng.randrange(0xFFFFFFFF):08x}"` for the encounter-id suffix. `randrange(0xFFFFFFFF)` returns an int in `[0, 0xFFFFFFFF-1]`; the `08x` format pads to 8 hex chars, which works for values up to `0xFFFFFFFF` but a 9-char suffix could appear if the upper bit is set on certain RNGs. `random.Random.randint(0, 0xFFFFFFFF)` and `:08x` would be marginally safer. Not a determinism issue, just a defensive style note.**

---

## Severity tags

- **Critical** — silently breaks the ground_truth contract; 65% of findings on disk are affected. The grader does not mitigate it. Ship-blocking.
- **High** — blocks downstream tasks (test split missing, schema orphaned) or leaves an actionable-looking task that can't be actioned (t_cd5bfba8).
- **Medium** — semantic weakness, latent concurrency issue, or docstring/code mismatch that will confuse the next maintainer.
- **Low** — cosmetic, defensive-style, or documentation nit.

---

## Verification (what I actually ran)

| Check | Command | Result |
| --- | --- | --- |
| Synth purity (no LLM imports) | `grep -nE "openai|litellm|anthropic|dspy" src/ai_billing_audit/synth*.py src/ai_billing_audit/synth/*.py` | 0 hits |
| Synth determinism (seed=42 × 2) | inline Python: `generate_suite(42)` twice, hash JSON | SHA-256 prefix `97d6fbb905e8a30e` both runs, 6 encounters |
| Per-seed determinism (8 seeds) | inline Python, 2 calls per seed | 0 failures across `{0, 1, 7, 42, 100, 2026, -1, 99999999}` |
| Split counts (100/50/0) | `len(get_train())`, `len(get_val())`, set intersection | 100 train, 50 val, 0 overlap (encounter_id sets disjoint) |
| Test split exists? | `os.path.exists("data/test.json")` | does not exist |
| `ground_truth_for()` rules ⊆ encounter.rules | inline Python, 493 findings | 0 leak across train+val |
| `clinical_evidence_quote` ⊆ `clinical_note` (strict) | inline Python, 493 findings | **321/493 (65.1%) fail exact case-sensitive; 0/493 fail case-insensitive** |
| Jaccard (0.80) of GT quote vs sentence-cased snippet | `match_findings()` end-to-end, 100 train encounters | **Macro F1 = 0.243** (vs 1.000 for verbatim-echo) |
| Template trigger ⊆ template note | inline Python, 51 declared pairs | **33/51 fail exact case-sensitive; 0/51 fail case-insensitive** |
| PHI scan (9 regex classes + brand terms) | inline Python + grep | 0 hits across train+val + 8 synth modules |
| `sampler.py` / `generate_scenarios.py` exist? | `find` | not in project repo; only optuna copies in venv |
| Cross-process byte equality | `pytest tests/test_synth_determinism.py::test_across_process_byte_identical` | not re-run; test exists and uses `subprocess.check_output` + MD5 (read) |

---

## Out-of-scope items confirmed

- No source files were modified (read-only review).
- No synth corpus was regenerated.
- No optimizer run was triggered.
- `scenario_schema.py` was read in full and its invariants enumerated, but the post-schema invariants were not exercised against a live payload.
- `data/test_sample.jsonl` was not scanned for PHI; flagged as a follow-up.
