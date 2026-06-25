# Prompt Iteration Playbook — v12 → v13 → v14

> **Audience:** the next engineer (or future me) who runs the DSPy
> MIPROv2 loop and needs to decide whether to ship the result, iterate
> again, or roll back. This document is the **decision procedure** —
> not the iteration script. The script is `scripts/optimize.py` and the
> math is `docs/research/ROI-FORMULA.md` §3.
>
> **Read this before touching `prompts/v12/auditor_prompt.txt`.** The
> prompt is the production artefact; a "small tweak" can cost a clinic
> real money.

---

## 1. The contract you're protecting

Zorva's prompt is the only thing that decides whether a claim gets
flagged. The current shipped contract (v12) is:

| Metric                 | Value | Where it lives                                          |
|------------------------|-------|---------------------------------------------------------|
| Micro P                | 0.625 | `runs/recall/v12_ahcip_clean.json` (after EXAMPLE 6/7 leak fix) |
| Micro R                | 0.769 | same                                                    |
| **Micro F1 (global)**  | **0.690** | `docs/research/ROI-FORMULA.md` §3 anchor               |
| Eval set               | 10 encounters, 13 gold findings, 0 errors | `data/val_ca.json` |
| Provider               | minimax (`LLM_BASE_URL=https://api.minimax.io/v1`) | `deploy-to-vps.sh` |
| Model                  | `minimax/minimax-m2` (set in `src/ai_billing_audit/llm.py`) | runtime |

Any v13 candidate that ships **must not regress global F1 by more than
±0.02** unless it is also shipping a corresponding **+0.05** improvement
on at least one named bucket (see §3). The 0.02 / 0.05 thresholds are
the "noise floor" and "meaningful improvement" empirical values
measured on the v0–v12 history (see `docs/ITERATION_LOG.md`).

---

## 2. Before you touch the prompt

Run this checklist. If any item fails, **stop**:

```bash
# 1. Working tree clean?
git status --porcelain   # must be empty

# 2. On main, in sync with origin?
git rev-parse --abbrev-ref HEAD   # must be main
git fetch origin && git status    # "Your branch is up to date"

# 3. Are val_ca.json, v12 prompt, Dockerfile, deploy-to-vps.sh untouched?
git diff HEAD -- data/val_ca.json prompts/v12/ Dockerfile deploy-to-vps.sh
# (must be empty — these are pinned, do not modify)

# 4. Environment ready?
ls .venv/bin/python || python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 5. Baseline run works?
python scripts/optimize.py   # hermetic smoke check (ShapeAwareDummyLM)
ls -la artifacts/miprov2_best*.json
```

---

## 3. Reading a per-bucket breakdown

The aggregate metrics file (`runs/recall/<ver>_ahcip_clean.json`) gives
you one number per rule family. Below is what each value actually
means and the **decision rule** it triggers.

| Per-bucket pattern                              | Diagnosis                                | Action                                                |
|-------------------------------------------------|------------------------------------------|-------------------------------------------------------|
| High P (≥0.9), low R (<0.5)                     | **Under-recall.** Model is too cautious.  | Add an *example* (few-shot) showing the missed rule.   |
| Low P (<0.5), high R (≥0.9)                     | **Over-flagging.** Model hallucinates.   | Add a *negative constraint* ("do not flag X when…").   |
| Both low                                        | **Confused on this rule family.**        | Rewrite the rule's prose; usually the trigger phrase. |
| High P, high R, but bucket is small (<3 gold)   | Lucky / not statistically meaningful.    | Add 2-3 more val encounters that exercise the rule.   |
| F1 dropped vs v12 on a *previously green* bucket | **Regression.**                          | **DO NOT SHIP.** Either fix or split the change.      |

Concrete threshold policy (anchored to `data/val_ca.json` size = 10):

- **Single-bucket improvement:** needs ΔF1 ≥ **+0.05** absolute on
  the bucket, AND the bucket has ≥3 gold findings.
- **Global regression cap:** global micro F1 must stay within
  **±0.02** of v12 baseline (0.690). Anything outside requires
  product sign-off in `docs/ITERATION_LOG.md`.
- **Bucket regression cap:** no individual rule family may drop more
  than **−0.10** absolute F1. (Calibrated against v10→v11→v12
  transitions where a -0.12 drop in the post-op global-period bucket
  was the "leak" we caught late.)

---

## 4. Add vs. remove rules

### 4.1 When to add a rule

- A v12 false-negative is reproducible (≥2 of 3 runs miss the same
  encounter → same rule_id).
- The rule is **already in the ground-truth library**
  (`src/ai_billing_audit/ground_truth.py`). Adding a rule that
  isn't in the deterministic library will fail the
  *acceptance-rate* test (`scripts/aggregate_acceptance.py`) and
  is out of scope for prompt iteration.
- The rule's trigger phrase fits in ≤2 sentences. If it doesn't,
  it's a library issue, not a prompt issue.

### 4.2 When to remove a rule

Almost never. Each rule was added because a v0–v11 run failed without
it. Removing it is a deliberate recall sacrifice for precision; that
trade-off needs:

1. A **named target** in the prompt that covers the same ground
   (e.g., a generic "modifier misuse" rule subsumes a specific
   "modifier -25" rule).
2. An A/B test where removal strictly improves P without dropping R
   on the bucket it came from.
3. Sign-off recorded in `docs/ITERATION_LOG.md` with the bucket
   numbers.

### 4.3 The "leak" anti-pattern

The most expensive v8/v9/v10 mistake (see `prompts/MANIFEST.json`
archived entries) was **adding US billing rules to an AHCIP prompt**
(modifier -24 global-period references in a CA example). Symptom: P
stays high, R drops, *and* the per-bucket breakdown shows new misses
on unrelated buckets (model is confused).

**Detection:** if R drops but no per-bucket drop matches the
magnitude, the regression is **not** a missing-rule problem — it's a
leak. Re-read the diff for any "modifier -XX" string in an example
and remove it.

---

## 5. Regression testing before shipping a vN

Never ship a candidate without all four:

### 5.1 Eval-set F1

```bash
python scripts/optimize.py --candidate prompts/v<NEW>/auditor_prompt.txt \
  --eval-set data/val_ca.json \
  --runs 7 \
  --output artifacts/smartness_v<NEW>_chunk_0.json
python scripts/aggregate_smartness.py artifacts/smartness_v<NEW>_chunk_0.json
```

Compare `global_f1` against `runs/recall/v12_ahcip_clean.json`. Use
the decision rule in §3.

### 5.2 Holdout robustness

The holdout set lives at `data/synth/holdout_seed9999.json`. The
seed is in the filename on purpose — do not change it without
re-running v0–v12 on the new seed for an apples-to-apples history.

```bash
python scripts/eval_holdout.py \
  --prompt prompts/v<NEW>/auditor_prompt.txt \
  --holdout data/synth/holdout_seed9999.json \
  --output runs/holdout/v<NEW>_seed9999.json
```

Compare bucket-by-bucket to `runs/holdout/v12_seed9999.json` (create
this baseline first if it doesn't exist).

### 5.3 Acceptance-rate / refusal test

Catches the "model now refuses to answer" regression that v0 had:

```bash
python scripts/eval_final_test.py \
  --prompt prompts/v<NEW>/auditor_prompt.txt \
  --output runs/eval_final/v<NEW>.json
```

The acceptance rate must stay ≥ 90% (the v12 number). Below 90%
= the prompt is being over-cautious.

### 5.4 Live e2e (one 837P claim)

After the three dry runs pass:

```bash
# On the VPS, with the new prompt mounted:
curl -fsS -H "Authorization: Bearer $AUDIT_BEARER_TOKEN" \
  -F "file=@/app/data/sample_837p_clean.edi" \
  https://ai-billing-audit.ashbi.ca/encounters/upload/preview
```

Then a real submit + 30s wait. The response must contain
`audit_status: "ok"` and at least one findings row (it's a real
encounter, not a synthetic). This catches Caddy / Ollama / schema
drift the offline tests miss.

---

## 6. Updating `prompts/MANIFEST.json` correctly

The manifest is **append-only**. Existing entries are immutable
(see `prompts/MANIFEST.json` `notes` field). A new entry requires:

1. **Compute the version hash.** The schema is `sha256:<64 hex chars>`
   over the *prompt content only* — no metadata, no whitespace
   normalisation. Use:

   ```bash
   sha256sum prompts/v<NEW>/auditor_prompt.txt | awk '{print "sha256:"$1}'
   ```

2. **Set `parent_hash`** to the previous entry's `version_hash`.
   This forms the chain — `git log --follow prompts/MANIFEST.json`
   must always show a single linear history. Branching is forbidden.

3. **Required fields** for each entry (copy v12 and edit):

   ```json
   {
     "version_hash": "sha256:...",
     "parent_hash":  "sha256:...",
     "status":       "active",            // or "archived"
     "created_at":   "2026-MM-DDTHH:MM:SSZ",
     "llm_provider": "minimax",
     "model_version": "minimax/minimax-m2",
     "optimizer_config": {
       "optimizer":  "miprov2",
       "strategy":   "bootstrap-fewshot",
       "auto":       "medium",
       "max_bootstrapped_demos": 4,
       "max_labeled_demos": 4,
       "num_threads": 4
     },
     "metrics": {
       "global_p":    0.000,
       "global_r":    0.000,
       "global_f1":   0.000,
       "per_bucket":  { "...rule_id...": {"p": 0.0, "r": 0.0, "f1": 0.0, "n": 0} }
     },
     "replaces":     "sha256:<previous version_hash>",
     "rollback_to":  "sha256:<v12 hash>"
   }
   ```

4. **Set `status: "active"`** on the new entry **and** flip v12's
   status to `"archived"`. Exactly one entry may be `"active"` at any
   time. The marketing security page reads this field at build time —
   a broken invariant breaks `/security`.

5. **Do NOT** add entries for the archived v1–v11 prompts. They
   already have entries in `archived_versions`. Re-adding them would
   require fabricating R/P values, which is explicitly out of scope
   (see `prompts/MANIFEST.json` `status_note` field, audit task
   t_415b1e9b, 2026-06-22).

---

## 7. Shipping checklist (the final 5 minutes)

Before you commit and push:

- [ ] Eval F1 within ±0.02 of v12 OR an exception is recorded in
      `docs/ITERATION_LOG.md` with product sign-off.
- [ ] No per-bucket dropped > 0.10 F1.
- [ ] Holdout result written to `runs/holdout/v<NEW>_seed9999.json`.
- [ ] Acceptance rate ≥ 90% in `runs/eval_final/v<NEW>.json`.
- [ ] Live e2e on VPS returned `audit_status: "ok"`.
- [ ] `prompts/v<NEW>/auditor_prompt.txt` is the *exact* content used
      in the eval (no last-minute edits after the run).
- [ ] `prompts/MANIFEST.json` updated per §6.
- [ ] `docs/ITERATION_LOG.md` entry appended:
      `<timestamp> — <change> — Δ F1 — promoted?`
- [ ] `CHANGELOG.md` entry under a new version heading.
- [ ] Commit message uses Conventional Commits: `feat(prompts): v13 — <one-line rationale>`.

If any checkbox is unchecked, **do not push**. Open a PR titled
`WIP: v13 candidate — DO NOT MERGE` and link the eval artifacts so
the next person has the full context.

---

## 8. When to roll back

Roll back if any of these is true after deployment:

- Global F1 measured on the next 100-claim pilot batch drops > 0.05
  vs the v12 baseline.
- A regression report lands in `docs/BUGS_*.md` from a clinic
  ("Zorva flagged a clean claim as missing modifier X").
- The `audit_trail` chain shows ≥1 row with `model_run_id` referencing
  the new version that was rejected by `grader.py`.

Rollback procedure:

```bash
# On the VPS:
cd /opt/projects/ai-billing-audit
git revert --no-edit <merge-commit-sha>
docker compose -f docker-compose.yml up -d --build
curl -fsS https://ai-billing-audit.ashbi.ca/healthz | jq .
```

Then file a post-mortem in `docs/BUGS_<date>.md` with the regression
numbers. Do not delete the v13 prompt — keep it on disk for
diagnosis. Do flip its `MANIFEST.json` status back to `"archived"`.

---

## 9. Further reading

- `docs/ITERATION_LOG.md` — every past change with deltas.
- `docs/ITERATION_GUIDE.md` — DSPy MIPROv2 mechanics (the script
  side of this playbook).
- `docs/research/ROI-FORMULA.md` §3 — why 0.690 is the anchor.
- `docs/QA_RESEARCH_DSPY_INTEGRATION.md` — known gaps in
  `scripts/optimize.py` (the script is hermetic, not real-LLM; the
  eval runs are separate).
- `prompts/MANIFEST.json` `notes` field — the append-only invariant.