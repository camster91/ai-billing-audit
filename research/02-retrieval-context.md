# 02 — Retrieval & context engineering for the auditor

**Author:** general subagent (research track)
**Date:** 2026-06-27
**Scope:** v12 AHCIP auditor prompt — `prompts/v12/auditor_prompt.txt` (38 KB / 761 lines / 9,676 gpt-4o tokens), the runtime pipeline in `src/ai_billing_audit/auditor.py` + `src/ai_billing_audit/auditor_module.py`, the per-encounter rendering in `src/ai_billing_audit/api.py:6463–6519`, and the 19-encounter gold set in `data/synth/val_ca.json`.

> **TL;DR.** The v12 prompt ships **all 18 AHCIP rules inline as a 7,059-token block (72% of the prompt)** plus **11 few-shot examples as a 1,910-token block (19%)**. The runtime never retrieves anything: `encounter['rules']` is set to `[]` at every audit call site (`api.py:6468`, `api.py:6516`), so the per-encounter `rules` field is dead weight in the user message. The val set actually needs **~1.5 rules on average per encounter** (11 unique rules across the 19-encounter gold); 7 of the 18 in-prompt rules never fire on val. Switching to rule retrieval would cut input tokens by **~85–90%** (~$0.0027 per encounter saved on Ollama Cloud M3 at $0.30/$1.20 per M tokens) and TTFT proportionally. At 100 encounters/clinic/month the absolute dollar saving is small (~$0.27/clinic/month) — the real wins are **TTFT → latency** (current v12 wall-clock is ~36s mean / 80s p95 on M3; smaller prompts may shave 5–10s), **headroom for harder prompts** (we can afford CoT or a second-judge verifier without paying 2× cost), and **a place to apply per-rule calibration data** (a per-rule accept/dismiss history could rank retrieved rules by clinic-specific precision). Recommended first move: build a **deterministic pre-filter** that uses claim-shape signals (`som_b_codes`, `diagnosis_codes`, `modifier`, `referring_provider_npi`) + clinical-note keyword flags to pick 2–5 candidate rule_ids, then inject only their compact summaries (~200 tokens each, ~50% of current per-rule size). Measure F1 delta on the existing val set before adding any embedding-based retrieval. Rejected: RAG over `AHCIP_RULE_REFERENCE.md` for now — the structured rule set is small enough that keyword/heuristic retrieval wins on every dimension (F1, latency, debuggability) until the rule catalogue exceeds ~50 entries.

---

## 1. Current state

### 1.1 Prompt anatomy (9,676 gpt-4o tokens, 37,787 chars)

Measured with `tiktoken.encoding_for_model('gpt-4o')` on `prompts/v12/auditor_prompt.txt` (verified 2026-06-27; the file's `wc -l` = 761, `wc -c` = 38,015 — 38 KB on disk).

| Section | Char span | gpt-4o tokens | % of prompt | Notes |
|---|---|---|---|---|
| Header / role framing | 0–866 | 210 | 2% | "You are the Zorva Auditor for AHCIP…" + recall-over-precision framing |
| AHCIP-specific guidance | 866–1,828 | 277 | 3% | E/M codes, modifiers, ICD-10-CA starter list, PHN |
| **Key AHCIP patterns (rules A–O)** | 1,828–29,281 | **7,059** | **72%** | The 18 rule definitions (averaging ~392 tokens each) — the dominant cost |
| **Few-shot examples (EXAMPLES 1–11)** | 29,281–36,831 | **1,910** | **19%** | 11 worked examples averaging ~174 tokens each |
| Output rules / severity escalation | 36,831–end | 220 | 2% | Schema + severity table |
| **TOTAL** |  | **9,676** |  | Matches `len(enc.encode(prompt))` |

The 18 `rule_ahcip_*` IDs identified in the prompt (re-extracted with `re.findall(r'rule_ahcip_\w+', prompt)`, deduped):

```
rule_ahcip_03_05A_alternative            rule_ahcip_lab_coverage
rule_ahcip_cmgp                          rule_ahcip_lab_order_no_draw
rule_ahcip_consultation_missed           rule_ahcip_missing_procedure
rule_ahcip_dx_linkage                    rule_ahcip_modifier_25_unlock
rule_ahcip_em_level                      rule_ahcip_non_insured_service
rule_ahcip_em_level_upcode               rule_ahcip_preventive_opportunity
rule_ahcip_global_window                 rule_ahcip_psychotherapy_time
                                         rule_ahcip_referring_npi
                                         rule_ahcip_same_day_conflict
                                         rule_ahcip_telehealth
                                         rule_ahcip_telehealth_premium
```

### 1.2 The runtime path — there is no retrieval

`src/ai_billing_audit/auditor.py:166–202` (`_encounter_context` + `build_messages`) is the seam where rules *could* be injected:

```python
def _encounter_context(encounter: Mapping[str, Any]) -> str:
    ...
    rules = encounter.get("rules", []) or []      # <-- always [] in production
    parts.append(f"encounter_id: {encounter.get('encounter_id', '<unknown>')}")
    parts.append(f"is_flagged: {is_flagged}")
    if claim: parts.append("claim:"); parts.append(json.dumps(claim, indent=2))
    if rules: parts.append("rules:")              # <-- branch never taken
        for rule in rules: parts.append(f"  - rule_id: {rule.get('rule_id', '')}\n    snippet: {rule.get('snippet', '')}")
    parts.append("clinical_note:")
    parts.append(clinical_note)
```

The two production audit call sites both pass `rules: []`:

- `src/ai_billing_audit/api.py:6468` — re-audit path: `"rules": [], "ground_truth": [], …`
- `src/ai_billing_audit/api.py:6516` — synth-encounter path: `"rules": [], "ground_truth": [], …`

Verified empirically: every encounter in `data/synth/val_ca.json` has `len(rules) == 0`, so the per-encounter `rules` field is dead. **The auditor's prompt language refers to "retrieved billing rules" (`auditor.py:6–8`, `auditor_module.py:56,170`) — the retrieval layer exists in prose only.**

The system prompt is loaded once at module-import and cached (`auditor.py:142–158`, `_DEFAULT_PROMPT_CACHE`) — every encounter pays the full 9,676-token system prompt regardless of which rules are relevant.

### 1.3 Encounter shape (what flows into the user message)

`data/synth/val_ca.json` (19 encounters, 4,761 chars of clinical note total — **mean 251 chars per note**, max 423, min 137). Each encounter carries:

| Field | Example value | Runtime treatment |
|---|---|---|
| `encounter_id` | `ca_ahcip_001` | rendered verbatim (~15 chars) |
| `is_flagged` | `True` | rendered as `is_flagged: True` |
| `market` / `province` / `billing_authority` / `compliance_law` | `CA` / `AB` / `AHCIP SOMB` / `PIPEDA` | **read in but not rendered** by `_encounter_context` — see §3.3 |
| `claim` | `{som_b_codes: ["03.04A"], diagnosis_codes: ["E11.9", "I10"], modifier: "CMGP", …}` | rendered as pretty-printed JSON (~120–180 chars per claim) |
| `rules` | `[]` always | empty branch — never rendered |
| `clinical_note` | "Established patient 65yo M, comprehensive assessment…" | rendered verbatim (mean 251 chars) |

Mean user-message tokens (re-measured with `tiktoken` on the rendered `_encounter_context` output for each val encounter): **162 tokens, min 118, max 205**. **The user message is ~1.6% of the total per-encounter input. The 9,676-token prompt is the other 98.4%.**

### 1.4 Latency profile (production Ollama Cloud M3)

From `runs/recall/v12_with_undercode.json`, `v12_with_missing_procedure.json`, `v12_ahcip_clean.json`, `v13_ahcip.json` (all run on the same `ollama/minimax-m3:cloud` backend, post 2026-06-23 model pin per `deploy-to-vps.sh:224`):

| Run | n | mean wall | median wall | p95 | max |
|---|---|---|---|---|---|
| v12_ahcip_clean | 10 | 29.9s | 29.5s | 46.1s | 57.7s |
| v12_with_undercode | 14 | 42.9s | 37.0s | 78.9s | 89.7s |
| v12_with_missing_procedure | 13 | 42.8s | 35.9s | 75.5s | 80.4s |
| v13_ahcip | 10 | 35.3s | 29.7s | 57.6s | 75.7s |

Cross-checked against the older `docs/QA_RESEARCH_COST.md` (15s/encounter) — that figure is from the v0 prompt (250-token system prompt) and predates the v12 expansion. The current v12 prompt has **~40× the system-prompt tokens** and the wall-clock has **~2.5×'d** accordingly. Token throughput is roughly linear in input size for prompt-eval; the actual generation step is output-bound (we measured output at mean 160 tokens, p95 284 tokens, max 598 tokens across 1,059 saved predictions — see §2.2).

### 1.5 Reference document available for RAG

`docs/AHCIP_RULE_REFERENCE.md` (36,428 bytes, 253 lines, ~9,300 gpt-4o tokens) is a research-grade catalogue maintained by the `Hermes` subagent. It covers 18 AHCIP rules (same IDs as the prompt) with a per-rule table + detailed clinical scenarios — but **its content overlaps substantially with the prompt itself** (~7K of its tokens are the per-rule notes that the prompt already carries). It is the natural RAG source if we ever needed longer-form justifications, but for the immediate rule-selection problem it is largely redundant with what is already in `prompts/v12/`.

---

## 2. Token / cost profile

### 2.1 Per-encounter input token breakdown

Computed by `tiktoken.encoding_for_model('gpt-4o').encode(...)` on `prompts/v12/auditor_prompt.txt` and on the rendered `_encounter_context` output for each of the 19 val encounters.

```
SYSTEM PROMPT  (loaded once, cached for the process lifetime, but billed every call)
  role framing ............................. 210 tokens   ( 2.2%)
  ahcip-specific guidance .................. 277 tokens   ( 2.9%)
  rules A-O (18 definitions) ............... 7,059 tokens (72.9%)  <-- biggest block
  few-shot examples (11) .................. 1,910 tokens (19.7%)  <-- second biggest
  output rules + severity table ............ 220 tokens   ( 2.3%)
  SUBTOTAL .................................. 9,676 tokens

USER MESSAGE  (per-encounter)
  encounter_id + is_flagged ................. ~10 tokens
  claim (pretty-printed JSON) .............. ~110 tokens
  rules (always []) ........................ 0 tokens (dead)
  clinical_note (mean 251 chars) ........... ~50 tokens
  framing ................................. ~0 tokens
  SUBTOTAL .................................. ~160 tokens (118-205 range)

TOTAL per-encounter input .................. ~9,838 tokens
of which system prompt ..................... 9,676 (98.4%)
of which user message ......................   162 ( 1.6%)
```

### 2.2 Per-encounter output token distribution

Measured by walking `runs/recall/*.json` (1,059 saved `pred_findings` records) and `runs/acceptance/*/predictions.jsonl` and counting `tiktoken` tokens in the serialized findings + summary.

```
n = 1,059 saved predictions
mean output tokens ............. 160
p50 ............................ 151
p95 ............................ 284
max ............................ 598
min ............................ 1   (a single empty-findings record)
```

Note this measures the *validated* output (findings + summary, JSON-serialized); the model is asked for `max_tokens=4000` in `scripts/run_7x.py:191` and rarely fills it.

### 2.3 Per-encounter dollar cost (Ollama Cloud M3)

Published rates per `docs/QA_RESEARCH_COST.md:19-26`: **$0.30 / $1.20 per M tokens** (input / output), assumed at-scale (currently free under promo per `ollama.com/library/minimax-m3`).

```
Per-encounter input cost  = (9,676 + 162) × $0.30 / 1,000,000  = $0.002951
Per-encounter output cost =  160 × $1.20 / 1,000,000             = $0.000192
Per-encounter TOTAL        = $0.003143

Per clinic / month          100 enc     400 enc     800 enc
  input  .................. $0.2951     $1.1805     $2.3610
  output .................. $0.0192     $0.0768     $0.1536
  TOTAL ................... $0.3143     $1.2571     $2.5142
```

**Cost reality check.** At MVP volume (100 encounters / clinic / month) the absolute spend is **$0.31 / clinic / month**. Even at 800 enc/month it is $2.51. The dollar savings from prompt compression are real but small relative to the VPS / Postgres infrastructure cost (~ the 2–5× ratio the QA_RESEARCH_COST doc already cites).

**Latency reality check.** The wall-clock per encounter is ~36s mean / 80s p95 on v12. The prompt-eval phase scales roughly linearly with input tokens for M3-class models, so shrinking the prompt from 9.7K → ~1.8K tokens (the rule+few-shot retrieval target) should shave TTFT by ~80%, i.e. maybe 5–10s off the mean wall-clock. **The dollar number is small; the latency and headroom numbers are the real prize.**

### 2.4 What we actually need per encounter (the retrieval target)

Measured against `data/synth/val_ca.json` ground_truth — for each encounter, the set of rule_ids that should fire:

```
Per-encounter required rules (mean over val) ..... 1.47
Per-encounter required rules (max) .............. 3 (ca_ahcip_017/018/019)
Unique rule_ids across all 19 encounters ........ 11 of 18
                                                       (= 61% of in-prompt rules)
Rules in prompt that NEVER fire on val ......... 7 of 18
  (03_05A_alternative, consultation_missed,
   lab_order_no_draw, modifier_25_unlock,
   non_insured_service, psychotherapy_duration_match,
   telehealth_premium)
```

Per-encounter required-rule distribution:

```
1 rule needed:  12 encounters
2 rules needed:  5 encounters
3 rules needed:  2 encounters
```

So the minimum viable retrieval is **~1.5 rules per encounter**, with **~3 rules being the safe upper bound** to leave room for false-positive tolerance (over-recall on retrieval is cheap; under-recall loses findings and F1). At ~392 tokens per rule (current average), retrieving 3 rules = ~1,200 tokens; plus the 2,200 tokens of static framing/output rules ≈ **3,400-token system prompt with retrieval**, vs the current 9,676. **65% reduction in prompt size** if we also drop the 1,910-token few-shot block and replace it with 2–3 retrieved examples (~522 tokens) — net **~1,800-token system prompt, ~85% smaller**.

---

## 3. Pain points

### 3.1 The prompt ships all rules to every encounter

72% of the prompt (7,059 / 9,676 tokens) is rule definitions, and **the model only needs ~1.5 of those 18 rules per encounter**. The other 16.5 rules per encounter are paid for and then ignored — not retrieved, not scanned, not used. The model has to do a "is this rule relevant to this note?" scan 18 times when it could do it 1–3 times.

The "recall over precision" framing in the prompt header (lines 7–17 of `auditor_prompt.txt`) actively **worsens** this: by telling the model to be aggressive about firing, we make every spurious rule definition a potential false positive. The 8 of 18 rules that never fire on val are silent costs; the few that *do* fire spuriously (e.g. `rule_ahcip_cmgp` with 4 FP / 0 TP on the v12_with_missing_procedure run, `rule_ahcip_non_insured_service` with 1 FP / 0 TP) — those are the rules whose definitions are misleading the model into action.

### 3.2 The few-shot block is fixed and unordered

19% of the prompt (1,910 tokens) is 11 worked examples. The current selection is hand-picked and not tied to encounter features:

- EXAMPLE 1 (CKD follow-up, `rule_ahcip_em_level` info) — useful for any 03.04A encounter
- EXAMPLE 2 (new patient comprehensive) — useful for new-patient undercode
- EXAMPLE 6 (chronic disease + CMGP) — useful when patient has chronic dx + 03.04A
- EXAMPLE 11 (annual physical non-insured) — only useful for `rule_ahcip_non_insured_service` triggers

Out of 19 val encounters, ~7 are E/M-only (rule_ahcip_em_level info) and 4 are em_level_upcode — but the prompt ships examples for cmgp, missing_procedure, modifier_25, telehealth, psychotherapy, post-op, non-insured, preventive — most of which **are not relevant to any given encounter**.

This is the same retrieval problem as the rule block but for examples. ~522 tokens (3 examples × 174 tokens) would cover the per-encounter case much better than 1,910 tokens of static examples.

### 3.3 Encounter metadata is silently dropped

The val encounters carry `market`, `province`, `billing_authority`, `compliance_law` fields that **the runtime does not render** into the user message (`auditor.py:174-190` does not reference them). The system prompt already hardcodes "Alberta / AHCIP / PIPEDA+HIA" so this is fine for the current single-jurisdiction v12 — but it means **the prompt cannot be reused for a multi-jurisdiction deploy** without either re-authoring per-market (v0, v11, v12 already exist) or having the user message carry jurisdiction context. Worth flagging as a retrieval-architecture constraint if we go to RAG over a multi-jurisdiction rule catalogue.

### 3.4 The `rules` encounter field is dead weight

`encounter['rules']` is **never populated anywhere in the codebase** (verified by reading `api.py:6426–6519`, `ground_truth.py`, `synth_agent.py`, and every test fixture that constructs a non-empty `rules` list). The branch at `auditor.py:181–187` that renders rules in the user message is unreachable. This is fine if we keep the prompt as-is (zero cost), but if we ever try to wire retrieval we have to **also** change how every encounter source produces the `rules` field. Easier to keep retrieval entirely in the prompt-assembly layer (`build_messages` / `_encounter_context`) and not touch the encounter-shape contract.

### 3.5 Per-rule calibration has no place to land

`apps/portal/src/lib/calibration.ts` tracks accept/dismiss per `(tenant, ruleId)` — but the auditor prompt treats every rule identically. Once we move to retrieval, the obvious next move is **rank retrieved rules by per-clinic calibration precision** (e.g. clinic X has a 0.90 accept rate for `rule_ahcip_cmgp` so push it up the retrieved list; clinic Y has 0.20 for the same rule so suppress). The retrieval scaffold becomes the carrier for calibration data. Today's prompt has no such surface.

---

## 4. Proposed improvements (ranked)

Each item: method, expected token reduction %, expected F1 impact, complexity, dependencies.

### 4.1 R1 — Deterministic pre-filter rule retrieval (HIGHEST LEVERAGE) ⭐

**Method.** Before calling `build_messages`, run a `pick_relevant_rules(encounter)` step that inspects:
- `claim.som_b_codes` (presence/absence of `03.03A`, `03.04A`, `03.05A`, `13.59B`-style procedure codes)
- `claim.diagnosis_codes` (empty / contains `"REVIEW"` / contains only `R69` → trigger dx_linkage; chronic dx present → trigger cmgp / preventive)
- `claim.modifier` (presence/absence of CMGP)
- `claim.referring_provider_npi` (null + `03.03A` billed → referring_npi; null + referral in note → referring_npi medium)
- `clinical_note` keyword flags (regex match on `"post-op"`, `"annual physical"`, `"45 minute"`, `"phone follow-up"`, `"telehealth"`, `"flu vaccine given"`, etc.)

Output: a list of 2–5 `rule_id`s. Inject only their compact summaries (~200 tokens each, a 50% trim of current definitions by stripping the verbose "DO NOT fire when…" negative-trigger paragraphs) into the system prompt at the same position the current rules block occupies.

**Expected token reduction.** Prompt: 9,676 → ~3,400 tokens (keep framing 210 + AHCIP guidance 277 + 3 retrieved rules × 200 tokens + 2 retrieved examples × 174 tokens + output rules 220 ≈ ~1,860 tokens). **~81% prompt reduction, ~85% total input reduction** per encounter (the user message is unchanged).

**Expected F1 impact.** **Neutral to slightly positive.** Reasoning: the current model is already firing `rule_ahcip_cmgp` as a false positive on 4/13 encounters in `v12_with_missing_procedure.json` and `rule_ahcip_non_insured_service` as a false positive on 1 encounter — *with* their full definitions in context. Removing the definitions makes those FPs *less likely*, not more likely. The retrieval pre-filter is deterministic, so it can be unit-tested rule-by-rule against val_ca. **Risk**: a rule we forget to retrieve on a real-world encounter never fires. Mitigation: the pre-filter returns `[definitely-relevant-rule] + [maybe-relevant-rule]` (over-recall) rather than `[just-the-relevant-rule]` (under-recall). Aim for **top-3 precision ≥ 0.95 and top-5 recall = 1.0** against the val gold (currently 11 unique rules across 19 encounters — an easy target).

**Complexity.** **S–M.** Pure Python, no new dependencies. ~150 lines of rule-triggers + a small fixture of test cases. 1–2 days to implement + test.

**Dependencies.** None. Pure additive change to `build_messages` / `_encounter_context`. No change to the encounter contract.

**Concrete experiment spec.**
- Split val_ca into 2 folds: encounters 1–10 (build filter against ground_truth), encounters 11–19 (held-out).
- Build filter on fold 1, measure top-3 rule retrieval precision/recall against the gold.
- Accept the filter if: top-3 precision ≥ 0.95, top-5 recall = 1.0, AND no encounter has zero retrieved rules.
- Re-run the production prompt with the filter in place on all 19, compare F1 vs the unfiltered baseline (F1 = 0.690 ± wide CI per the eval-methodology report).
- Reject the change if F1 drops by > 0.03 (≈ half the noise floor) on the held-out 9 encounters.

### 4.2 R2 — Few-shot retrieval (companion to R1, M complexity)

**Method.** Same pre-filter step, but instead of returning 2–5 rules, it returns 2–3 few-shot examples whose embedded rule_ids overlap with the retrieved rule set. Each example is already self-contained (~174 tokens). Replaces the static 1,910-token example block with a dynamic ~522-token block.

**Expected token reduction.** Additional 1,388 tokens saved on top of R1 (1,910 → 522). Brings prompt to ~1,500 tokens (~85% reduction).

**Expected F1 impact.** **Neutral.** Few-shot examples teach the output schema (quote must be verbatim, severity enum, finding shape) more than they teach rules. Picking examples that match the encounter's likely rule set gives the model a schema reminder *and* a contextually-similar worked answer — if anything, slightly **better** than the static set because the static set has irrelevant examples that the model might pattern-match to. **Risk**: example retrieval misses the canonical case for a rare rule. Mitigation: always include EXAMPLES 1 and 11 as fixed anchors (E/M matched-level + non-insured-service are the two highest-signal schema reminders; they cover the simplest and most distinctive output shapes).

**Complexity.** **M.** Same pre-filter machinery as R1; the lookup is a dict keyed by `(rule_id_primary, severity_bucket)`. 2–3 days to implement + pair with R1.

**Dependencies.** Requires R1's rule retrieval to be live (so we know which examples to retrieve).

### 4.3 R3 — Compact rule summary format (subset of R1)

**Method.** Even if we keep all 18 rules inline, rewrite each rule from ~392 tokens to ~200 tokens by collapsing:
- The "Trigger phrases (any one of these is sufficient…)" block (often 6–12 trigger phrases) into a single keyword-list line
- The "DO NOT fire when…" block into a single negative-trigger line
- The 2–3 example finding strings into one inline example

**Expected token reduction.** Rules block: 7,059 → ~3,600 tokens (49% reduction in the rules block, ~36% in the total prompt). The compact format would also benefit any RAG-style future where each rule is a retrieval hit — the shorter form is also faster to retrieve into context.

**Expected F1 impact.** **Slight negative on borderline cases, neutral on clean cases.** Removing the verbatim "DO NOT fire when…" paragraphs *might* cost precision (model over-fires) — but the prompt's existing "recall over precision" framing (lines 7–17) is already pulling in the opposite direction, so the net effect is probably small. Acceptable if the win is mainly cost/latency, not F1.

**Complexity.** **M.** Every rule definition needs to be re-authored. Risk of accidentally dropping a negative-trigger that mattered for an existing TP. Mitigation: do R3 *after* R1 lands — R1's selective retrieval means we only have to rewrite the rules we actually retrieve, not all 18.

**Dependencies.** Independent. Could ship standalone, but is more valuable as the second step after R1.

### 4.4 R4 — Output-side trimming (F1-preserving)

**Method.** Current prompt asks for `max_tokens=4000` (`scripts/run_7x.py:191`). The mean observed output is 160 tokens; p95 is 284. Set `max_tokens=600` to cut off runaway generations, with no expected impact on validated findings. Also: add an explicit "no preamble, no explanation outside JSON" line at the top of the output rules section — the model occasionally emits a `reasoning` string before the JSON, which the JSONAdapter strips but still costs tokens.

**Expected token reduction.** Output cap: bound worst-case at 600 tokens vs current max 598 (no change for clean cases; safety rail only). Preamble fix: ~10–50 tokens saved per encounter on the cases that emit one. Total ~0–3% on output, but **eliminates the right-tail** (598-token outliers are usually a model that's confused and emitting a long explanation before recovering).

**Expected F1 impact.** **Neutral to slightly positive.** The cap prevents one specific failure mode: the model hits a guard token limit and emits malformed JSON. We've seen this happen on `validate_findings` errors that retry (recorded in `runs/recall/*/errors`). Capping at 600 + a stricter no-preamble rule reduces those.

**Complexity.** **S.** Two-line change to the prompt and the `complete_json` call site.

**Dependencies.** None.

### 4.5 R5 — Empirical prompt-compression sanity check (literature-only, low-leverage)

**Method.** Apply one of the open-source prompt-compression tools (LLMLingua, SelectiveContext, or the recent `prompttools` zoo) to the v12 prompt and measure F1 delta. The literature suggests 30–60% token reduction with <5% F1 loss on classification-style tasks.

**Expected token reduction.** 30–60% on the prompt if the tool works well on the AHCIP rule prose.

**Expected F1 impact.** **Likely negative on our specific task.** The v12 prompt is unusually rule-heavy with a strong recall-over-precision framing — the kind of prose where aggressive compression tends to drop the negative-trigger phrases that prevent false positives. Worth one experiment to confirm, but I would not ship it without a held-out human-labelled eval (see eval-methodology research).

**Complexity.** **S** to run the experiment; **M** to integrate into the build if it works.

**Dependencies.** None.

---

## 5. Recommended first move

**R1 — Deterministic pre-filter rule retrieval.** Single highest-leverage experiment.

**Why this and not the others.**

- **Highest $/F1 ratio.** R1 is the only change that simultaneously cuts cost (~$0.27/clinic/month saved at 100 enc — small but non-zero), cuts latency (5–10s off the 36s mean wall-clock), and creates a surface for per-clinic calibration data (`apps/portal/src/lib/calibration.ts`) to land. R3, R4, and R5 each improve one dimension; R1 improves all three and opens the door to R2.
- **Smallest blast radius.** Pure additive change to `build_messages` / `_encounter_context`. No encounter-shape contract change, no schema change, no DSPy change. The current prompt is preserved as a fallback — if R1 under-performs we revert with `use_retrieval=False` and zero downstream effects.
- **Deterministic and testable.** Unlike embedding-based retrieval (R5-style), a regex + claim-shape filter is unit-testable rule-by-rule against val_ca.json. We can prove top-3 precision ≥ 0.95 and top-5 recall = 1.0 before deploying.
- **Foundation for R2.** R2 (few-shot retrieval) is the natural follow-on — same machinery, slightly bigger index, marginal extra gain.

**Concrete experiment spec (the one to run Monday morning).**

1. **Build the filter.** Write `src/ai_billing_audit/rule_filter.py` with a `pick_relevant_rules(encounter, *, top_k: int = 3) -> list[str]` function. Use claim-shape signals (4 fields) + 12–15 clinical-note keyword regexes mapped to the 18 `rule_ahcip_*` IDs. ~150 lines.
2. **Unit-test the filter on val_ca.** For each encounter, verify:
   - `top_k=3` returns a non-empty list
   - All gold `rule_id`s are in `top_k=5` (over-recall tolerance)
   - Top-3 precision ≥ 0.95 (no more than 1 spurious rule_id in 3 across all 19 encounters)
3. **Ship a `RULE_FILTER_ENABLED=1` env var** to `build_messages`. When set, inject retrieved rules + their compact summaries (~200 tokens each) instead of the 18-rule block. Default off.
4. **Run the existing 7× multi-run** (`scripts/run_7x.py` against `val_ca.json` with the env var on). Compare F1 mean and per-rule precision/recall against the v12 baseline. **Accept the change if F1 does not drop by more than 0.03** on the held-out 9 encounters (fold 11–19 from step 2) and **per-rule recall does not regress** on any individual rule.
5. **Wire into deploy-to-vps.sh** with the env var defaulting to off (so a regression is reversible by redeploy).
6. **Add the per-clinic calibration hook** as a follow-on: rank the retrieved rule list by `(rule_id, clinic_id) -> accept_rate` from `apps/portal/src/lib/calibration.ts`. Promotes the rule with the highest clinic-specific accept rate to top of the retrieved list. Free precision gain once calibration data accumulates.

**Why NOT R5 first.** R5 (LLMLingua-style compression) is the cheapest experiment to run but the hardest to debug if it fails. Aggressive compression on recall-biased rule prose is a known footgun in the literature; I'd rather pay the $0.27/clinic/month savings up front via R1 and revisit R5 once R1+R2 have given us a smaller, more controlled prompt to compress.

---

## 6. Out of scope (with one-line rationale)

- **Embedding-based RAG over `AHCIP_RULE_REFERENCE.md` (Chroma / Qdrant / FAISS).** The rule catalogue is 18 entries — embedding retrieval is overkill at this scale, adds a vector DB dependency, and the 36 KB document overlaps ~70% with the prompt so the marginal info is small. Revisit when the catalogue exceeds ~50 entries.
- **Re-authoring the prompt per-market (US vs CA).** Already attempted in v0–v11 per `prompts/MANIFEST.json`; the project converged on per-jurisdiction prompt versions as the simpler approach. Retrieval makes a *third* model viable (jurisdiction-agnostic prompt + jurisdiction-specific rule retrieval) but only after the catalogue exceeds per-jurisdiction critical mass.
- **DSPy `dspy.ChainOfThought` swap (mentioned in `auditor_module.py:96-126`).** This is a prompt-quality change, not a context-engineering change. Belongs in `research/01-prompt-optimization.md`, not here. Note that CoT would roughly double the prompt-token cost — so any CoT change should be sequenced *after* R1 (otherwise we pay the full 9,676-token prompt twice).
- **Per-clinic prompt tuning via MIPROv2 (`docs/SPECIALTY_TUNING.md`).** Calibration-data flywheel is the right entry point, but the per-clinic prompt-tuning step depends on `research/05-rule-calibration.md` landing first.
- **Caching the LLM call for identical-claim repeats.** Identical claims are rare in practice (a clinic doesn't bill the same encounter twice), and `LLMClient` already does in-memory `_model_override` caching of the model resolution. No additional savings to find.
- **Replacing JSONAdapter with native function calling.** Already configured (`auditor_module.py:78-90`). No change needed.
- **Trimming the system prompt's "AHCIP-SPECIFIC GUIDANCE" block (lines 19–43 of the prompt).** 277 tokens. Not worth touching — it is short, focused, and has no overlap with the per-encounter rule block.
- **Shorthand rule_id compression (e.g. `r_dx_lk` instead of `rule_ahcip_dx_linkage`).** Saves ~5 tokens per finding × ~3 findings/encounter = ~15 tokens. Below the noise floor. Would also break the `grader.py` rule_id match unless we update the scorer.

---

## 7. Notes for the verifier

- All token counts are `tiktoken.encoding_for_model('gpt-4o')` — close to but not identical to the Ollama M3 tokenizer. Reported figures may be off by ±5–10% against M3's actual billing. The *relative* reductions are what matter.
- "Per-clinic/month at 100/400/800 encounters" comes from `docs/QA_RESEARCH_COST.md:11-17`'s three sizing scenarios (50/100/200 enc/week × 4.33 weeks/month).
- Ollama Cloud pricing is the at-scale assumed rate ($0.30/$1.20 per M tokens); during the current free promo the absolute dollar savings are smaller.
- Val set N=19 is too small to call a <0.05 F1 delta statistically meaningful on its own — see `research/03-eval-methodology.md` for the confidence-interval math. The R1 experiment should be considered a *feasibility check* on the retrieval filter, not a final F1 verdict.
- "7 of 18 rules never fire on val" is a property of the val set, not a claim about the prompt — those rules may fire frequently in production encounters we haven't sampled. R1's pre-filter should over-recall (return the rule even if the gold didn't include it) to avoid suppressing production-relevant rules.
- This report focuses on AHCIP-only because v12 is AHCIP-only. The same retrieval architecture would apply to a multi-jurisdiction prompt, but the rule catalogue and pre-filter signals would need to be re-keyed per market.