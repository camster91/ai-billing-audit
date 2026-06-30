# 00 — Prioritized 4-week improvement roadmap

**Author:** general (synthesize-roadmap, Mavis plan `plan_0bbfa512`)
**Date:** 2026-06-27
**Scope:** synthesize `research/01-prompt-optimization.md`, `02-retrieval-context.md`, `03-eval-methodology.md`, `04-llm-backends.md`, `05-rule-calibration.md` into a single executable plan.

> **Audience:** Cameron Ashley, solo operator. This document is meant to be startable Monday morning without further research.

---

## TL;DR — the 5 highest-leverage moves, in order

1. **Wire the missing `CalibrationSignal` write hook (30 min).** [#05 §3.1] The dashboard shipped today in c33b88c will render empty for every tenant in production until this lands. Pure bug fix; no design choice. Ship-blocker.
2. **Pin `temperature=0` + `seed=42` on the auditor + add a 2-encounter smoke fixture + re-run the 7× baseline (~2 h wall-clock).** [#01 Rank 1+2+4, #03 §3.3] Every other experiment is unmeasurable today because model stochasticity dominates the F1 stdev (estimated ±0.05–0.08 on the current 19-encounter val set). Once landed, a <0.05 F1 delta is noise; ≥0.05 is signal.
3. **Rotate the compromised Ollama Cloud API key + fix the 3-way `LLM_BASE_URL` host discrepancy (~30 min).** [#04 §2 P1, §4.2 D+0/D+1] P0 security, has been sitting open since 2026-06-17. Mechanical, but every day it stays open is another day PHI-bearing traffic flows under a key an unknown party has read.
4. **Build a deterministic pre-filter rule retriever (R1) and ship it env-gated behind `RULE_FILTER_ENABLED=1` (~2–3 days).** [#02 §4.1] Cuts system-prompt tokens 81% (9,676 → ~1,800), saves ~$0.27/clinic/month at MVP volume, cuts wall-clock ~5–10s by shrinking prompt-eval, and creates the surface where per-clinic calibration data can later rank retrieved rules. Deterministic + unit-testable rule-by-rule.
5. **Run MIPROv2 against the real `MiniMax-M3-2026-06-23` backend with a real AHCIP train split (~2 h wall-clock, ~$4 cost).** [#01 Rank 5, #04 cost ceiling §4] The DummyLM path in `scripts/optimize.py` is hermetic but useless on the AHCIP split (US-shaped canned responses — `optimize.py:1011-1142`). Real-backend MIPROv2 has never been done for v12. Realistic F1 lift: +0.03 to +0.08.

**Net direction (best case, all five land):** F1 0.690 → 0.72–0.80 (with a ±0.17 CI we won't fully close in 4 weeks), per-audit cost $0.002 → $0.0005, wall-clock 30s mean → 20–25s mean. **The CI dominates everything** — by the end of Week 4 we will have *moved the mean* but we will not have *narrowed the CI* materially.

---

## 1. Sequenced plan — 4 weeks

### Week 1 — Three quick wins (independent, each ≤2 days)

These three ship in parallel. None of them depend on the others.

#### W1.1 — Security + config hygiene (Mon, ~30 min)  ⭐ DO THIS FIRST
**Source:** `04-llm-backends.md` §2 P1, §4.2 D+0/D+1
**Owner:** Cameron (mechanical)
**Output:** Compromised Ollama key replaced; the three-way host discrepancy (api.minimax.io / api.minimax.chat / ollama.com) collapsed to one source of truth.

| Step | Action | Files | Time |
|---|---|---|---|
| 1 | Generate new key in Ollama dashboard. Replace `~/.config/ai-billing/ollama-key` on the Mac. | local + remote | 5 min |
| 2 | `ssh coolify 'cat /root/ai-billing-audit-secrets/llm_api_key'` to verify deploy picked up the new key. | ssh | 5 min |
| 3 | Run `./deploy-to-vps.sh`; smoke `/healthz`. Confirm `/healthz` reports the new key's first 8 chars. | deploy | 5 min |
| 4 | **Three-way `LLM_BASE_URL` fix:** delete the `MINIMAX_BASE_URL` env from `docker-compose.yml:61,94` (so the deploy-script value wins); add `LLM_BASE_URL=${LLM_BASE_URL}` explicit pass-through to the api/worker env blocks. | `docker-compose.yml`, `deploy-to-vps.sh` | 15 min |
| 5 | Verify with `grep -rn LLM_BASE_URL deploy-to-vps.sh docker-compose.yml scripts/run_7x.py` — should now show exactly two values, one each for prod (`api.minimax.io/v1`) and research (`ollama.com/v1`). | shell | 5 min |

**Acceptance:** `/healthz` reports new key prefix; `grep` shows two `LLM_BASE_URL` values, one for prod, one for the research script.

#### W1.2 — CalibrationSignal write hook (Mon-Tue, ~30 min + 30 min backfill)  ⭐ SHIP-BLOCKER BUG
**Source:** `05-rule-calibration.md` §1.2, §3.1
**Owner:** Cameron
**Output:** Every biller accept/dismiss click populates a `CalibrationSignal` row. Dashboard goes from empty-for-everyone to live.

| Step | Action | Files | Time |
|---|---|---|---|
| 1 | Add `upsertCalibrationSignal(tx, tenantId, ruleId, action)` helper to `apps/portal/src/lib/calibration.ts`. ~10 lines. Schema already exists (Prisma migration `20260627110000_add_calibration_scaffold`). | `calibration.ts` | 15 min |
| 2 | Call from `writeAuditEntry()` in `apps/portal/src/lib/audit-write.ts` for single-finding accept/dismiss routes. Call from `writeAuditBatch()` for bulk accept/dismiss. Inside the existing Prisma transaction so failure rolls back atomically. | `audit-write.ts` | 15 min |
| 3 | Write `scripts/backfill_calibration_signals.ts` — walks `AuditTrailEntry` grouped by `(tenantId, finding.ruleId, action)`, upserts counts. Idempotent (upsert key is `@@unique([tenantId, ruleId])`). | new file | 20 min |
| 4 | Run backfill on staging data. Verify a few tenants render non-empty dashboard cards. | manual | 10 min |
| 5 | Re-run existing 7 calibration-card unit tests + add one test for `upsertCalibrationSignal` (accept increments acceptCount, dismiss increments dismissCount, idempotent re-run produces same result). | test | 10 min |

**Acceptance:** Dashboard renders live `calibrated` / `reviewing` / `overcalled` / `uncalibrated` labels for tenants with ≥5 decisions; backfill is idempotent on re-run.

**Why this is Week 1 and not Week 0:** it's the highest single-leverage change but takes <1 hr, so it batches naturally with W1.1 and W1.3. **Do W1.1 first** because it touches secrets and W1.2 doesn't.

#### W1.3 — Determinism + smoke test + re-baseline (Tue-Thu, ~1 day code + ~2 h compute)  ⭐ UNBLOCKS EVERYTHING
**Source:** `01-prompt-optimization.md` §3 Ranks 1, 2, 4 + §5 "Recommended first move"; `03-eval-methodology.md` §3.3, §3.4, §4.
**Owner:** Cameron
**Output:** Audit's F1 is reproducible; v12 baseline is re-measured against the *current* 19-encounter val_ca (not the stale 10-encounter MANIFEST pin); backend drift trips the smoke test before it ships.

| Step | Action | Files | Time |
|---|---|---|---|
| 1 | Add `temperature` and `seed` kwargs to `LLMClient.__init__` (`src/ai_billing_audit/llm.py:96-107`). Default to `temperature=0.0, seed=42`. Pass through `complete()` and `complete_json()` via the litellm kwargs dict. | `llm.py` | 30 min |
| 2 | Update `scripts/run_7x.py:105` to instantiate `LLMClient` with the new defaults explicitly. | `run_7x.py` | 15 min |
| 3 | Add a 2-encounter smoke fixture at the top of `run_7x.py:171` — one known-match (FP/FN expected), one known-no-match (no findings expected). Assert F1 ≥ 0.5 and `n_errors=0`; fail loudly otherwise. Mirror the grader's existing `scripts/verify_grader_reproducibility.py` pattern. | `run_7x.py`, `tests/fixtures/eval_smoke.json` (new) | 2 h |
| 4 | Update `CHANGELOG.md` with the determinism note. | `CHANGELOG.md` | 5 min |
| 5 | Run: `python scripts/run_7x.py --split val_ca --prompt v12 --n-runs 7`. Wall-clock: ~10 min on `MiniMax-M3-2026-06-23`, ~70 min on Ollama Cloud (production = minimax via api.minimax.io per `deploy-to-vps.sh:97` — use the prod backend, not Ollama, since this is the canonical baseline). | shell | 2 h |
| 6 | Update `prompts/MANIFEST.json` `val_per_bucket` to include the 9 distinct rule_ids now in the gold set (adds `rule_ahcip_missing_procedure` × 3 + `rule_ahcip_preventive_opportunity` × 3 — current val_ca is 19/31 vs the MANIFEST pin of 10/13). | `MANIFEST.json` | 30 min |
| 7 | Verify determinism: two consecutive runs with seed=42 should produce F1 within ±0.005. If not, the backend ignores `seed` — fall back to N=3 mean for the protocol. | shell | 30 min |

**Acceptance:** Smoke test passes on every run; F1 stdev across N=7 drops from current ~0.06 (extrapolated from v0/US) to ≤ 0.02; MANIFEST entry reflects the 19-encounter reality.

**Expected F1:** Probably **lower than 0.690** because the 19-encounter set has more hard cases (missing_procedure, preventive_opportunity) and the current v12 prompt has bias from §2.1 (the cmgp/non_insured_service over-fires). Conservative estimate: **0.55–0.65**. **This is the truth** — call it out in CHANGELOG so the team doesn't think we lost 5 F1 points.

---

### Week 2 — One medium item (3-5 days, depends on Week 1)

Two candidate Week-2 items — pick **R1 (deterministic pre-filter)** because it has the highest $/F1/leverage ratio and unblocks the calibration flywheel in Week 3-4.

#### W2.1 — Deterministic rule-retrieval pre-filter (Mon-Fri, ~3 days)
**Source:** `02-retrieval-context.md` §4.1 (R1), §5 "Recommended first move"
**Owner:** Cameron
**Depends on:** W1.3 (need the deterministic baseline to measure against)
**Output:** A `pick_relevant_rules(encounter)` step that ships env-gated; when on, system prompt shrinks from 9,676 → ~1,800 tokens (81% reduction); system stays on the 9,676-token prompt until F1 is verified equivalent.

| Step | Action | Files | Time |
|---|---|---|---|
| 1 | Write `src/ai_billing_audit/rule_filter.py` with `pick_relevant_rules(encounter, *, top_k: int = 3) -> list[str]`. Use claim-shape signals (`som_b_codes`, `diagnosis_codes`, `modifier`, `referring_provider_npi`) + 12-15 clinical-note keyword regexes mapped to the 18 `rule_ahcip_*` IDs. ~150 lines. | new file | 4 h |
| 2 | Split val_ca into 2 folds: encounters 1-10 (build/inspect), encounters 11-19 (held-out). For each fold-1 encounter, verify top-3 precision ≥ 0.95 and top-5 recall = 1.0 against gold. Fix over-/under-fires. | unit tests + manual | 3 h |
| 3 | Add `RULE_FILTER_ENABLED=1` env var to `build_messages` in `src/ai_billing_audit/auditor.py:166-202`. When set, inject only retrieved rules + their compact summaries (~200 tokens each, 50% trim of current definitions) instead of the 18-rule block. Default off. | `auditor.py` | 2 h |
| 4 | Re-run 7× multi-run on val_ca with `RULE_FILTER_ENABLED=1`. **Accept the change if F1 does not drop by more than 0.03** on held-out encounters 11-19 AND no per-rule recall regresses. | shell | 2 h |
| 5 | Wire into `deploy-to-vps.sh` with the env var defaulting to OFF (a regression is reversible by redeploy). Update CHANGELOG. | `deploy-to-vps.sh`, `CHANGELOG.md` | 30 min |

**Acceptance:** Top-3 precision ≥ 0.95, top-5 recall = 1.0 on fold-1; F1 delta on held-out ≤ -0.03 vs Week-1-3 baseline; per-rule recall does not regress on any rule.

**Expected F1 delta:** **Neutral to slightly positive (+0.00 to +0.03).** Reasoning: current model already over-fires `cmgp` (4 FP/13) and `non_insured_service` (1 FP) *with* their full definitions in context; removing those definitions should make those FPs *less* likely, not more. The retrieval pre-filter is deterministic — unit-testable rule-by-rule against val_ca.

**Expected cost/latency:** Per-audit cost drops from $0.003 to ~$0.001 (~$0.27/clinic/month saved at MVP volume, ~$2/clinic/month at 800 enc/mo); wall-clock drops 5-10s from prompt-eval phase shrinkage.

**Companion sub-task (parallel, ~half day):** Apply research/05 §3.2 — render sample size (`n=X`) next to every bucket label on the calibration dashboard card. Pure UI change in `calibration-card.tsx`. **1 hour.** Wire while W2.1 is in flight.

---

### Weeks 3-4 — Strategic item (depends on Weeks 1-2)

**Pick: MIPROv2 against the real `MiniMax-M3-2026-06-23` backend.** Highest theoretical F1 gain. Runs sequentially over Weeks 3-4 because the loop needs W1.3's deterministic baseline for measurement and W2.1's smaller prompt for cost-effective iteration.

#### W3-4.1 — Real-backend MIPROv2 run (~2 h wall-clock + ~2 days prep)
**Source:** `01-prompt-optimization.md` §3 Rank 5, §4 "Cost ceiling"; `03-eval-methodology.md` §1.5 (per-clinic F1 caveat)
**Owner:** Cameron
**Depends on:** W1.3 (deterministic F1 measurement); W2.1 (smaller prompt → cheaper MIPROv2 trials)
**Output:** A `v13` prompt variant (or better) on disk that scores ≥ 0.05 F1 above the W1.3 re-baseline. **OR** a documented "no improvement found, MIPROv2 returned to baseline" outcome — also valuable.

| Step | Action | Files | Time |
|---|---|---|---|
| 1 | **Verify train/val isolation.** Confirm `data/fewshot_ca.json` exists (currently missing per `01-prompt-optimization.md` §6.3) OR author it from encounters outside val_ca (`ca_ahcip_001-019`). If encounters overlap with val, **refuse to run MIPROv2** — train/val contamination makes the result meaningless. | `data/fewshot_ca.json` (new) | 4 h |
| 2 | Replace the canned US-shaped DummyLM responses in `scripts/optimize.py:1011-1142` with shape-aware real-model responses for the AHCIP rule set. OR add a `--provider minimax --split val_ca --train data/fewshot_ca.json` flag that bypasses DummyLM entirely. | `optimize.py` | 1 day |
| 3 | Run MIPROv2 `auto=light` first (~350 calls, ~20 min on MiniMax, ~$1) — confirms the loop works end-to-end. Promote only to `auto=medium` (~1,400 calls, ~2 h, ~$4) once `auto=light` produces a saved artifact. | shell | 1 day (with run + analysis) |
| 4 | Compare MIPROv2-best F1 vs the W1.3 baseline. Accept if F1 delta ≥ +0.05 (above the noise floor). If < 0.05, document why (overfit to val? few-shot set too small?) and revert. | `runs/acceptance/miprov2-*/summary.json` | 1 day |
| 5 | If accepted, promote to `prompts/v13/MANIFEST.json` and `prompts/v13/auditor_prompt.txt`. Update `deploy-to-vps.sh:224` model pin to use v13. Re-run W1.3's smoke + 7× baseline against v13 to confirm the lift reproduces on the held-out 9-encounter fold. | `MANIFEST.json`, `deploy-to-vps.sh` | 1 day |

**Acceptance:** A `v13` prompt with reproducible F1 ≥ baseline + 0.05 on val_ca, OR a documented "no improvement" finding with the MIPROv2 artifact archived for reference.

**Expected F1 delta:** **+0.03 to +0.08** (literature: DSPy MIPROv2 medium on small val sets gets +0.05 to +0.15 on hand-written baselines, but AHCIP + 19-enc val + few-shot author-time limit the upside).

**Cost ceiling:** ~$4 per `auto=medium` run, ~2 h wall-clock on MiniMax. Run once; iterate only if first run finds a candidate worth probing.

**Risk mitigation:** Run MIPROv2 *against the held-out 9-encounter fold* (encounters 11-19), NOT the full val set, when selecting the best program. Best-program selection on full val is a classic overfit footgun.

**Parallel Week 3-4 work (doesn't block MIPROv2):**
- **HIA lawyer engagement** (research/04 §4.2 D+2 to D+5). Send `docs/BAA_TEMPLATE_HIA.md` + `docs/HIA_LAWYER_HANDOFF.md` to Alberta counsel. **$1,500-$4,000 CAD, 4-8 hours of lawyer time.** Not blocking engineering; blocks real Alberta clinic pilots. Schedule this now so it's in flight by the time we want to ship a pilot.
- **Per-clinic F1 dashboard tile** (research/05 §3.3). ~half-day Prisma migration + helper + card expansion. Closes the loop from biller click to the F1 number the tuner uses. Can ship while MIPROv2 is grinding.

---

## 2. Dependencies — explicit graph

```
                ┌──────────────────────┐
                │ W1.1 Ollama key +    │     [Mon, 30 min, INDEPENDENT]
                │ LLM_BASE_URL hygiene │
                └──────────┬───────────┘
                           │ (security, must precede any production deploy)
                           ▼
                ┌──────────────────────┐
                │ W1.2 CalibrationSignal│    [Mon-Tue, ~1 hr, INDEPENDENT]
                │ write hook + backfill │
                └──────────┬───────────┘
                           │ (unblocks per-clinic F1 dashboard in W2-W4)
                           ▼
                ┌──────────────────────┐
                │ W1.3 Determinism +   │    [Tue-Thu, ~1 day code + 2h run]
                │ smoke + re-baseline  │
                └──────────┬───────────┘
                           │ (F1 measurement now reproducible)
                           ├──────────────────────────────┐
                           ▼                              ▼
                ┌──────────────────────┐    ┌──────────────────────────┐
                │ W2.1 Deterministic   │    │ W2.2 Sample-size UI      │
                │ rule-retrieval (R1)  │    │ (companion, parallel)    │
                │ ~3 days              │    │ ~1 hr                    │
                └──────────┬───────────┘    └──────────────────────────┘
                           │ (prompt shrinks 81%; per-rule precision hopefully up)
                           ▼
                ┌──────────────────────┐
                │ W3-4.1 MIPROv2       │    [Week 3-4, ~2 days prep + 2h run]
                │ real-backend run     │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ HIA lawyer review    │    [PARALLEL — must start W2 to land W4]
                │ (HIA-IMA sign-off)   │    Blocks real Alberta clinic pilots
                └──────────────────────┘

PARALLEL (independent, can run any week):
  • HIA lawyer engagement (send docs by end of W2, want memo by end of W4)
  • Per-clinic F1 dashboard tile (W2.5/W3.1)
  • Staleness tiers on calibration card (W3, ~1 hr)
```

**Critical path:** W1.1 → W1.3 → W2.1 → W3-4.1. **Total wall-clock on the critical path: ~8-9 working days across 4 weeks** (assuming the deterministic baseline + retrieval + MIPROv2 all hit their expected timelines; add 30% buffer = ~11-12 days). Leaves ~1 week of slack in the 4-week budget.

**What blocks what explicitly:**
- W2.1 **depends on** W1.3 (needs deterministic F1 to measure the F1 delta).
- W3-4.1 **depends on** W1.3 (same) AND W2.1 (smaller prompt → cheaper MIPROv2 trials → faster iteration).
- HIA lawyer review **does not block** engineering work; **blocks** real clinic pilots.
- Per-clinic F1 dashboard tile **depends on** W1.2 (needs live CalibrationSignal rows).
- The 3-way host fix (W1.1 step 4) **depends on nothing** but should land same-day as key rotation to keep deploys deterministic.

---

## 3. Expected cumulative impact

Best-case if every item lands. **Numbers are estimates, not promises** — the 95% CI on F1 at N=19 is ±0.17-0.20 (per `03-eval-methodology.md` Appendix A), so any reported "delta" smaller than ~0.10 is within noise.

| Metric | Today (start of Week 1) | End of Week 1 (after W1.1+W1.2+W1.3) | End of Week 2 (after W2.1) | End of Week 4 (after W3-4.1) |
|---|---|---|---|---|
| **F1 (val_ca, 19 enc)** | 0.690 (10-enc number, stale) | 0.55-0.65 (truth on 19 enc; CI ±0.17) | 0.55-0.68 (R1 neutral-to-+0.03) | 0.58-0.76 (MIPROv2 +0.03-0.08) |
| **F1 stdev across 7 runs** | unknown (~0.05-0.08 est.) | ≤ 0.02 (seed=42 pin) | ≤ 0.02 | ≤ 0.02 |
| **Per-audit cost** | ~$0.003 | ~$0.003 | ~$0.001 (R1 cuts prompt 81%) | ~$0.001 |
| **Per-audit wall-clock (mean)** | ~30s | ~30s | ~20-25s (R1 saves 5-10s prompt eval) | ~20-25s |
| **Per-audit wall-clock (p95)** | ~58s | ~58s | ~50s | ~50s |
| **Per-clinic monthly cost (866 audits)** | ~$2.51 | ~$2.51 | ~$0.87 | ~$0.87 |
| **CalibrationSignal rows in prod** | 0 (read-only scaffold) | Live for new clicks + backfilled | Live | Live |
| **Smoke-test backend drift detection** | none | catching in <2 encounters | catching | catching |
| **F1 confidence in any "improvement"** | noise ±0.17 = 1/3 of number | noise ±0.02; delta ≥0.05 = signal | same | same |

**Honest framing for stakeholders:** By end of Week 4 we will have *moved the mean* by an estimated +0.05 to +0.10 F1 and we will have *narrowed the variance* from ±0.17 to ±0.02 — meaning any further improvement is now detectable as signal, not noise. The CI itself won't move (we'd need 200+ encounters of held-out gold for that, which is out of scope this quarter).

**What we will NOT get in 4 weeks:**
- A real per-clinic F1 number (needs ≥5 feedback events per clinic; no clinics have ≥5 today)
- A held-out human-labelled 30-encounter gold (2-4 weeks lead time, $3-6k, scheduled for next quarter)
- A drop in 30s → 3s wall-clock (that's a backend swap to Haiku/Flash, explicitly deferred)

---

## 4. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R1** | **Ollama key still compromised (W1.1 incomplete).** The key has been exposed since 2026-06-17; any day of delay is another day PHI-bearing traffic flows under a known-leaked credential. | LOW (after W1.1 lands); HIGH until then | HIGH (PHI exfiltration; HIA breach; clinic trust destroyed) | **W1.1 is day 1, hour 1 of Week 1.** Verification step: `/healthz` returns new key prefix. Add monthly key-rotation cron (`scripts/rotate_ollama_key.sh` + crontab entry) so this doesn't recur. Track in `deploy-to-vps.sh` so future deploys don't silently overwrite with the old key. |
| **R2** | **Optimize against val_ca then ship and underperform in prod.** The val set is 19 encounters / 31 gold (Hermes-authored, single annotator, known dx_linkage over-fire bias per `03-eval-methodology.md` §1.3). MIPROv2 overfits to val if we select the best program on val. | HIGH (default MIPROv2 behaviour) | HIGH (silent F1 regression in prod) | **(a) Split val_ca into 2 folds: encounters 1-10 (build/inspect), encounters 11-19 (held-out for MIPROv2 selection).** MIPROv2 selects best program on the held-out fold, not on val. (b) Re-score on `(rule_id, severity-tier)` — 3-tier coarsening from `03-eval-methodology.md` §3.2 — to surface severity miscalibration as a separate signal. (c) Smoke test (W1.3 step 3) catches backend drift before it ships. (d) Production monitoring: per-week accept-rate per `(clinic, rule_id)` from `CalibrationSignal` (W1.2) — if a clinic's accept rate drops ≥0.15 vs the W1.3 baseline, alert. (e) Author held-out human-labelled gold in next quarter to close this risk fully. |
| **R3** | **MIPROv2 overfits on a 19-encounter val set.** | MEDIUM | MEDIUM | Combine with R2 mitigations (held-out fold). Add `--min-train-size 10` gate to `optimize.py` — refuse to run if train set is too small. Cap MIPROv2 `auto=medium` budget at $5; bail out and document "no improvement" if best program delta < 0.05. |
| **R4** | **Rule retrieval (W2.1) under-recalls on a real-world rule.** Val gold uses 11/18 rules; the other 7 are silently un-tested. If production encounters fire those 7 rules, retrieval misses them and F1 drops. | MEDIUM | MEDIUM | Pre-filter is **over-recall by construction** (returns `[definitely-relevant] + [maybe-relevant]` not `[just-the-relevant]`). Aim for **top-3 precision ≥ 0.95 and top-5 recall = 1.0** against val gold. Add a fallback: if the pre-filter returns < 2 rules for any encounter, fall back to the full 18-rule prompt. Monitor per-rule F1 weekly via CalibrationSignal — any rule that drops by > 0.10 vs baseline flags for prompt-rule investigation. |
| **R5** | **CalibrationSignal backfill produces wrong counts.** Existing `AuditTrailEntry` data may have inconsistent `ruleId` (null on old rows, or a different enum mapping). | LOW-MEDIUM | MEDIUM (false calibration signals) | Idempotent backfill is safe to re-run. Add an explicit pre-backfill assertion: `count(AuditTrailEntry WHERE ruleId IS NULL) == 0` — if not, log + halt, manual reconciliation needed. Spot-check 5 tenants post-backfill by comparing to manual ground-truth counts. |

**Risks NOT in scope this quarter** (mentioned for awareness only): HIA lawyer review blocking real clinic pilots (mitigated by parallel scheduling, not engineering); new model version drift on `MiniMax-M3-2026-06-23` (date-pinned snapshot; deploy fails loudly if the alias is retired).

---

## 5. Out of scope this quarter

Things the research surfaced that we are explicitly NOT doing in the next 4 weeks, with one-line rationale each:

| # | Item | Source | Why out of scope |
|---|---|---|---|
| OOS.1 | **30-encounter held-out human-labelled gold** (2-4 wk, $3-6k) | `03-eval-methodology.md` §3.1 | Lead time exceeds 4-week budget; needs Cameron to engage 2 Alberta billers / AAPC CPMA contractors. Schedule for next quarter. |
| OOS.2 | **Per-clinic MIPROv2 tuning** | `05-rule-calibration.md` §3.4-3.5; `01-prompt-optimization.md` §6.7 | Per-clinic data gate (`SPECIALTY_TUNING.md:47-60`, ≥200 labeled feedback per specialty) not met. Solo operator with no production feedback yet. Defer until ≥5 clinics active. |
| OOS.3 | **Switch primary inference to Claude Haiku / GPT-5-mini / Gemini Flash** | `04-llm-backends.md` §4.1 | Latency is a product UX issue, not compliance; HIA lawyer review is the binding constraint regardless of vendor; current M3 has the only known AHCIP F1 = 0.690. Re-evaluate after D+10-14 multi-provider eval AND lawyer sign-off. |
| OOS.4 | **Self-host Llama 3.3 70B on Hostinger VPS** | `04-llm-backends.md` §3.1 #8 | VPS is CPU-only (no GPU); inference would be 5-10× slower than Ollama M3 + capex is $2.5k-4k. Not worth it for pilot volume. |
| OOS.5 | **Embedding-based RAG over `docs/AHCIP_RULE_REFERENCE.md`** | `02-retrieval-context.md` §6 | Rule catalogue is 18 entries; embedding retrieval is overkill at this scale. Revisit when catalogue exceeds ~50 entries (multi-jurisdiction expansion). |
| OOS.6 | **Chain-of-thought before JSON output** | `01-prompt-optimization.md` §6.2 | Schema rejects text-before-JSON prose (`scripts/optimize.py:515-525` chose `dspy.Predict` deliberately). CoT would require a schema change. Belongs in a separate "schema refactor" track. |
| OOS.7 | **Macro-F1 over per-rule buckets** | `03-eval-methodology.md` §5.2 | Weights rare rules equally with common ones; `cmgp` (2 FP in val) would dominate. Micro-F1 is the right aggregate; per-rule breakdowns already in MANIFEST. |
| OOS.8 | **LLM-as-judge for ground truth validation** | `03-eval-methodology.md` §5.4 | Circular — we don't trust the LLM enough to author gold, so we don't trust it to validate gold. Human biller only. |
| OOS.9 | **Cross-tenant rule calibration sharing** | `05-rule-calibration.md` §5.4 | Different payer mix / modifier frequency / staff training per clinic. Pooling destroys the per-clinic signal. Per-specialty fallback already covers the natural shared axis. |
| OOS.10 | **Re-train model weights on feedback data** | `05-rule-calibration.md` §5.3 | `SPECIALTY_TUNING.md §7` explicitly rules this out. CalibrationSignal is for MIPROv2 (prompt optimization) only — never `.bin` weights. |
| OOS.11 | **Streaming CalibrationSignal updates via websocket** | `05-rule-calibration.md` §5.5 | Dashboard already renders on page load; staleness window is 7-30 days. Websocket infra on Next.js + Prisma + SQLite is not free. Re-render on load is the right cadence. |
| OOS.12 | **Add 50+ encounter production-corpus held-out set** | `03-eval-methodology.md` Appendix A | Needs 200-300 encounters to close CI to ±0.05. Solo operator, no production clinic volume. Defer to "first paying clinic" milestone. |
| OOS.13 | **Lowering the 5-action minimum to 3** | `05-rule-calibration.md` §5.7 | F1 helper needs ≥3 for binomial variance tolerance; bucket label needs ≥5 for stability. Different questions, different thresholds. |
| OOS.14 | **Multi-cloud failover (run 3 providers simultaneously)** | `04-llm-backends.md` §5 | 3× the operational surface for secret rotation + per-provider quirks. Defer until HIA lawyer clarifies whether Ollama Cloud is acceptable. |

---

## 6. Execution checklist (Monday morning)

```
[ ] W1.1 — Ollama key rotation + 3-way URL fix (~30 min)         [DO FIRST]
[ ] W1.2 — CalibrationSignal write hook + backfill (~1 hr)
[ ] W1.3 — Determinism + smoke + re-baseline (~1 day)
[ ] Send BAA_TEMPLATE_HIA + HIA_LAWYER_HANDOFF to counsel (start W1, parallel)
[ ] W2.1 — Deterministic rule-retrieval R1 (~3 days)
[ ] W2.2 — Sample-size UI on calibration card (~1 hr, parallel)
[ ] Per-clinic F1 dashboard tile (~half day, parallel in W3)
[ ] W3-4.1 — Real-backend MIPROv2 (~2 days prep + 2 h run + 1 day analysis)
[ ] Final CHANGELOG + re-run W1.3's smoke + 7× baseline against v13 if accepted
```

**Definition of done for the 4-week plan:**
1. All items above checked.
2. `prompts/MANIFEST.json` reflects the new v13 (or current v12) state with current val_ca counts.
3. `/healthz` reports the new (rotated) Ollama key prefix.
4. CalibrationSignal rows populate for every new tenant click + backfill complete.
5. HIA lawyer engagement is in flight (memo expected by end of plan or scheduled).
6. Final stakeholder report: current F1 + CI + cost + latency + per-clinic dashboard status.

---

*End of roadmap. ~2,800 words. Review with Cameron before kickoff; if the W2-W4 sequencing or the strategic choice (MIPROv2 vs HIA-priority) needs to flip, the dependency graph in §2 is the only thing that has to change — the Week 1 quick wins are independent and should land regardless.*