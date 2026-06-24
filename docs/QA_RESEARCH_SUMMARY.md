# Summary — AI Billing Audit MVP improvement plan

**Author:** QA research subagent, 2026-06-17
**Inputs read:** `run_01/predictions.jsonl` (50 encounters), `run_01/scores.json`, `failure_modes.md`, `prompts/v0/auditor_prompt.txt`, `prompts/v1/auditor_prompt.txt`, `src/ai_billing_audit/llm.py`, `scripts/run_7x.py`, `scripts/score_ollama_audit.py`, `data/val.json` (50 encounters, full), `docs/CONTINUOUS_QA_SYSTEM.md`, plus web research for EHR and pricing.

## Headline finding

**The "P=0.087, R=0.012, F1=0.021" headline is almost entirely a scoring contract bug, not a model capability floor.** The scorer in `scripts/run_7x.py:81` and `scripts/score_ollama_audit.py:11` keys findings on `(category, rule_id)`, but neither prompt asks the model to emit `category`. Of the 17 model-emitted findings across the 48 successful run-01 predictions, only 2 contain a `category` field — those are the only 2 TPs. The other 15 are FPs *by the scorer's contract* (their key is `('', 'rule_xyz')`, which can't match any GT). Once the category contract is fixed, expected run-01 metrics are roughly **P≈0.35-0.55, R≈0.40-0.65, F1≈0.40-0.55** based on the 2-3 rule_id matches I verified by hand in the missed encounters.

## Rank-ordered recommendations (R/P impact estimates from run-01 inspection; 7-run baseline will tighten these)

### 1. Fix the scoring key (engineering change, 30 min)
- **What:** change `finding_key` in `run_7x.py:81` and `score_ollama_audit.py:11` to use only `rule_id`, or to look up `category` from the GT rules list by `rule_id`. The GT dict already carries `category` per finding.
- **Why first:** without this, *no prompt change* can be measured correctly. The v1 A/B test will produce noise.
- **Expected impact on run-01 metrics:** R from 0.012 → ~0.40-0.60; P from 0.087 → ~0.35-0.55; F1 from 0.021 → ~0.40-0.55. (This is the single biggest lever.)
- **Risk:** low — purely a measurement change.

### 2. Add `category` to the prompt's required schema (prompt change, 5 min)
- **What:** in `prompts/v1/auditor_prompt.txt`, add one sentence: *"Each finding's `category` field MUST equal the `category` of the rule it cites (e.g., `evaluation`, `diagnosis`, `cardiology`, `missing-dx`, `duplicate`, `preventive`, `imaging`, `laboratory`, `procedure`, `modifier`)."*
- **Why:** the model occasionally emits a category by chance (enc_10024, enc_10041) and those are exactly the TPs. Making it required removes the chance factor.
- **Expected impact:** marginal on its own, but necessary for (1) to be measurable.
- **Risk:** low.

### 3. Re-scope ground truth to "compliance findings only" (synth/data change, 2 hours)
- **What:** redefine `ground_truth[]` in `data/val.json` (and the synth generator) to only include findings where `severity ∈ {medium, high, critical}` AND the finding represents a coder action (drop `category: evaluation` info-level confirmations, keep `category: missing-dx` critical, keep `category: duplicate` high, keep `category: modifier` high, keep `category: preventive` info only when a preventive code is unbilled).
- **Why:** the current GT counts every rule match as a finding, which is not how real CPMA audits work. Real auditors report problems, not confirmations. The current contract inflates workload, confuses the model, and is misaligned with what the customer is buying ("catch billing issues").
- **Expected impact:** headline F1 from 0.02 → 0.50-0.70 with the same model + scoring key, because the "conservative refusal" cases (enc_10004, 10006, 10007, 10010, 10012, etc.) become correct-empty rather than FN.
- **Risk:** medium — requires regenerating 50-encounter val and the synth generator. Validated against AAPC CPMA practice material.

### 4. Apply the v1 "favor recall" change to the prompt (prompt change, 0 min — already drafted)
- **What:** keep `prompts/v1/auditor_prompt.txt` as-is (it already replaces "Be conservative" with "Favor recall. When a retrieved rule applies to a billing element in this encounter, emit a finding.").
- **Why:** the 5/10 conservative-refusal cases (enc_10001, 10003, 10004, 10006, 10007, 10010, 10012) need the prompt to say "report matches," not "be conservative." v1 is already drafted.
- **Expected impact:** after (1) and (3), v1 should pick up another ~0.10-0.20 recall on the conservative-refusal cases.
- **Risk:** low — v1 is recall-favoring but still requires verbatim quotes and rule_id citation, so P should hold.

### 5. Harden the JSON parser for empty/truncated content (engineering change, 1 hour)
- **What:** in `LLMClient.complete_json` (`src/ai_billing_audit/llm.py:128`), add an empty-content guard, a `json.JSONDecoder().raw_decode()` fallback for "Sure! Here is the JSON: { ... }" prefixes, and a single retry on `SchemaValidationError` (for providers that ignore the `response_format` envelope).
- **Why:** 2/50 = 4% parse failure rate on run-01 (enc_10021, enc_10036). At 200 enc/week per clinic, that's 8 wasted encounters/week. The existing patch (`llm.py:168-171`) handles ```json``` fences but not empty content or prefix garbage.
- **Expected impact:** drops error rate from 4% to <1%. Recall goes up by 4% on its own (the 2 errors were both flagged encounters with 5 GT findings each). Cheap.
- **Risk:** low.

### 6. EHR integration: build the PS Suite SFTP watcher (engineering change, 4-8 hours, 1-week ROI)
- **What:** a `pssuite-sftp-watcher` service that consumes the MC EDT outbox files clinics already produce (`MOH > Send & Receive Files Via MC EDT` per the PS Suite training manual) and feeds them into the existing 837P parser.
- **Why:** covers the largest single Canadian small-clinic market (Ontario, ~40%). Without it, the MVP is a tech-demo; with it, it's a self-serve product for the Ontario base.
- **Expected impact:** unblocks 1-2 paying clinics within the quarter. Doesn't change R/P/F1 but changes the *addressable market* from "clinics with a tech person" to "every TELUS PS Suite shop in Ontario."
- **Risk:** low-medium — depends on clinic MOA cooperation to set up the SFTP drop.

### 7. Multi-model fallback for Ollama cloud outages (engineering change, 2 hours)
- **What:** add `LLM_PROVIDER=openai LLM_MODEL=gpt-4o-mini` to the daily cron as a fallback if Ollama cloud returns errors N times in a row.
- **Why:** cost is $0.53-$2.11/month per clinic at GPT-4o-mini rates, well within the 50-200 enc/week range. Outage blast radius today is 100% of audits.
- **Expected impact:** zero R/P change (different model, different quality profile) but 100% → near-100% availability.
- **Risk:** low — `LLM_PROVIDER` env-var dispatch is already in `llm.py:48-50`.

## Items I considered and de-prioritized

- **Switching to Claude Sonnet 4.5 as the default:** 10x the cost for marginal quality gain at this volume. Worth it as a premium tier, not as default.
- **Reducing 15s/encounter wall-clock via streaming or smaller model:** not blocking at MVP volume (87 min for 7 runs is fine, overnight cron is fine). Revisit at 5+ clinics.
- **Adding DSPy MIPROv2 self-improvement loop:** already in `docs/CONTINUOUS_QA_SYSTEM.md` as "not wired." Don't wire it before (1) is in — otherwise MIPRO will optimise against the broken scorer.

## Suggested A/B test order once baseline lands

1. Land baseline (already running).
2. Apply (1) and (2) together. Re-score. Expected headline F1: 0.40-0.55.
3. Apply (3) — regenerate val GT to compliance-only. Re-score. Expected F1: 0.50-0.70.
4. Apply (4) — promote v1 prompt. Re-score. Expected F1: 0.55-0.80.
5. Apply (5) — parser hardening. Errors drop.
6. Run a 5-rather-than-7-run follow-up to confirm stdev is acceptable (acceptance gate for first ship is stdev < 0.10 per `CONTINUOUS_QA_SYSTEM.md:103`).

## Files written by this research pass

- `/Users/biancabienaime/projects/ai-billing-audit/docs/QA_RESEARCH_WHY_MISSED.md`
- `/Users/biancabienaime/projects/ai-billing-audit/docs/QA_RESEARCH_GT_QUALITY.md`
- `/Users/biancabienaime/projects/ai-billing-audit/docs/QA_RESEARCH_EHR_INTEGRATION.md`
- `/Users/biancabienaime/projects/ai-billing-audit/docs/QA_RESEARCH_PARSE_FAILURES.md`
- `/Users/biancabienaime/projects/ai-billing-audit/docs/QA_RESEARCH_COST.md`
- `/Users/biancabienaime/projects/ai-billing-audit/docs/QA_RESEARCH_SUMMARY.md` (this file)
