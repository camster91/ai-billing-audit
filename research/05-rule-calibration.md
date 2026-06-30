# 05 — Rule-based per-clinic calibration

**Author:** general subagent (research track)
**Date:** 2026-06-27
**Scope:** the per-clinic rule-calibration loop that sits between the biller's accept/dismiss decisions and the next MIPROv2 prompt tune. Covers `apps/portal/src/lib/calibration.ts` + `apps/portal/src/components/calibration-card.tsx` (just shipped, commit c33b88c) plus the missing write-side hookup, the FastAPI's `feedback.py:280` and `per_clinic_f1.py`, the Prisma `CalibrationSignal` model, and the per-clinic tuning spec gap in `docs/SPECIALTY_TUNING.md`.

> **TL;DR.** The dashboard scaffold is correct and the bucket math is sound, but the `CalibrationSignal` table has **no write path** — every production biller click today increments `Finding.status` and writes `AuditTrailEntry` but does NOT touch `CalibrationSignal.acceptCount` / `dismissCount`. The dashboard will render empty for everyone in production until the upsert is wired in. That wire-up is one helper added to `apps/portal/src/lib/audit-write.ts` (`writeAuditEntry` + `writeAuditBatch`). After that, three levers — **per-clinic F1**, **per-clinic (not per-specialty) MIPROv2** because most clinics are 1–2 specialties, and **cron-driven auto-tune triggers** keyed off the CalibrationSignal "overcalled" bucket — close the loop from biller click to the next prompt variant. The 5-action minimum is conservative but defensible; an `n=X` footnote on every bucket label is the cheapest single change to make the dashboard honest.

---

## 1. Current state

### 1.1 What just shipped (c33b88c, 2026-06-27)

The portal-side read path + dashboard card for per-clinic rule calibration:

- **Prisma additions** (`apps/portal/prisma/schema.prisma`):
  - `Finding.ruleId` (String?, indexed). Canonical machine-readable rule key (e.g. `rule_ahcip_dx_linkage`). Distinct from `billingRuleReference` (human citation).
  - `CalibrationSignal` (new model). One row per `(tenantId, ruleId)` with `acceptCount`, `dismissCount`, `lastSignalAt`, and a `@@unique([tenantId, ruleId])` index. Intentionally narrow — free-text + per-finding detail stays in `Finding` + `AuditTrail`; this is a read-side materialised view.

- **Read path** (`apps/portal/src/lib/calibration.ts`):
  - `computeCalibration(tenantId)` reads all `CalibrationSignal` rows for the tenant and buckets each rule:
    - `actedOn < 5` → **uncalibrated** (check first; protects against 1/1 = 100% being labelled "calibrated")
    - `acceptRate >= 0.70` → **calibrated**
    - `0.40 <= acceptRate < 0.70` → **reviewing**
    - `acceptRate < 0.40` → **overcalled**
  - Sort: overcalled → reviewing → calibrated → uncalibrated, with `actedOn desc` tiebreak. Thresholds mirror `feedback.py:280` exactly.

- **Dashboard card** (`apps/portal/src/components/calibration-card.tsx`):
  - Renders the top 5 rules by interesting-ness
  - Stale marker when `lastSignalAt > 30 days` (matches the FPAR tile pattern, `docs/APPROVAL_RATE_KPI.md §5`)
  - Empty state points at the `/findings` queue when the biller hasn't acted on anything yet

- **Tests**: 7 unit tests on the pure `bucketFor()` function, including off-by-one boundaries at 0.40 and 0.70 — caught a real bug (initial implementation checked `rate` before `actedOn`).

### 1.2 What is NOT shipped (the write side)

This is the gap. The hookup point should be `apps/portal/src/lib/audit-write.ts`, which already wraps the chain write + finding mutation in a single Prisma transaction:

| Route                                                                                              | Helper          | Frequency           | ruleId source                                  |
|----------------------------------------------------------------------------------------------------|-----------------|---------------------|-----------------------------------------------|
| `apps/portal/src/app/api/encounters/[id]/findings/[findingId]/accept/route.ts`                     | `writeAuditEntry`  | one click           | read from `finding.ruleId`                     |
| `apps/portal/src/app/api/encounters/[id]/findings/[findingId]/dismiss/route.ts`                    | `writeAuditEntry`  | one click           | read from `finding.ruleId`                     |
| `apps/portal/src/app/api/findings/bulk/accept/route.ts`                                            | `writeAuditBatch`  | many at once        | read from each `finding.ruleId`                 |
| `apps/portal/src/app/api/findings/bulk/dismiss/route.ts`                                           | `writeAuditBatch`  | many at once        | read from each `finding.ruleId`                 |
| `src/ai_billing_audit/api.py` (`encounter_accept_all` / `encounter_dismiss` / `finding_accept` / `finding_dismiss` / bulk) | `_record_feedback` | (FastAPI path)     | mirrors portal but writes JSONL not Prisma     |

None of these paths touch `CalibrationSignal`. The dashboard will render empty for every tenant in production until one is added.

### 1.3 What the FastAPI side has

Two related but distinct surfaces:

- **`src/ai_billing_audit/feedback.py:280`** (`confidence_for_rule(rule_id)`) — a read-only helper that walks the JSONL feedback log and emits a `"high" | "medium" | "low" | "uncalibrated"` bucket per rule. Buckets are based on **accept count alone** (`>10 → high`, `3–10 → medium`, `<3 → low`, `0 → uncalibrated`), not on accept/dismiss ratio. Different axes from the portal's CalibrationSignal (which is ratio-based).

- **`src/ai_billing_audit/per_clinic_f1.py`** — the FastAPI-side per-clinic precision/recall/F1 number. Computes `tp = accept`, `fp = dismiss`, `modify → 0.5/0.5` from `feedback.py` and emits `weekly_f1` + `per_rule_metrics`. Uses `biller_id` as a proxy for `clinic_id` (the `FeedbackEntry` schema doesn't carry `tenant_id`). Recall is a stand-in: `support[rule_id] / max(support)` within the clinic — the dashboard renders this as "recall (within-clinic)".

The portal's CalibrationSignal does **not** carry `modifyCount`, so the portal-side dashboard cannot compute the same per-clinic F1 that `per_clinic_f1.py` does today.

---

## 2. Pain points

Each of these is currently shipped, broken, or misleading:

1. **The dashboard will always be empty in production.** No write hook. The card's empty-state copy ("Calibration signals unlock after the biller has acted on at least 5 findings per rule at this clinic") will fire for every tenant until the upsert lands. **Severity: ship-blocker for the read-path's headline promise.**

2. **The dashboard hides the sample size.** A rule that's "reviewing" at 40% (2 accept / 3 dismiss) looks the same as one at 60% (12 accept / 8 dismiss). Both render `0.50` (after rounding) or `0.60` accept rate, but the second is a stable signal and the first is noise. `bucketFor` already knows `actedOn` — the UI just doesn't render it as a confidence note. The dashboard's `(ruleId, acceptRate, decisions)` columns include the raw count, but there's no "n=2 — too few" affordance.

3. **The dashboard does not distinguish "never seen" from "seen and dismissed".** A rule with `acceptCount=0, dismissCount=0` (biller has never seen a finding from this rule at this clinic) and a rule with `acceptCount=0, dismissCount=12` (biller actively rejects every instance) both render as "overcalled" or empty depending on the threshold check. The first is missing data; the second is a clean calibration signal. The portal needs a separate `unseen` (or `pending_data`) bucket for "no signal yet, not even a stale one".

4. **The "5-action minimum" is baked into the same module that does the bucketing.** `CALIBRATION_MIN_ACTED_ON = 5` is exported as a constant from `calibration.ts` and hardcoded into `bucketFor()`'s first branch. That's good for the bucket label but bad for analytics: a separate `computeCalibrationStats()` that ALSO returns the raw accept/dismiss counts (even when below threshold) would let the dashboard show "this rule was overcalled 8/12 times — almost enough to trust the bucket". The constant is also exported and unchanged, but the dashboard never shows the threshold itself to the user.

5. **The bucket thresholds are mirrored, not shared.** `feedback.py:280` (FastAPI) uses accept-count thresholds (`>10`, `3–10`, `<3`); `calibration.ts` (portal) uses accept-rate thresholds (`>=0.70`, `0.40–0.70`, `<0.40`). These are different signals — accept count tells you "have we observed enough", accept rate tells you "is the model right when it fires". The current portal card calls them "calibrated/reviewing/overcalled" while the FastAPI encounter-detail template calls them "high/medium/low". Same domain, different axes, no shared vocabulary. The portal-only dashboard makes the wrong-axis choice silently.

6. **Per-clinic F1 lives only in FastAPI.** `per_clinic_f1.py` already computes P/R/F1 from the same feedback data, but it uses `biller_id` as a clinic proxy, doesn't have a portal-facing API, and the dashboard card on the portal shows nothing from it. Two parallel sources of truth (CalibrationSignal in Prisma, per-rule F1 in feedback.py) with no join — same biller click feeds both, but they're queried separately and can disagree.

7. **The 30-day staleness threshold is silent.** A `lastSignalAt` from 90 days ago renders as a normal row with a "stale" tag — but the bucket label (`calibrated` / `overcalled` / etc.) still reflects a number that may be from a prior billing configuration (different EHR, different staff, different payer mix). The card displays the same accept-rate number without a date hint beyond the tooltip. For a clinic that's only just adopted a new payer mix, "calibrated" on data from before the mix change is a false trust signal.

8. **No write hook for the `modify` action.** `modify` is its own action verb on the biller's UI (change severity, change category, optionally add rationale). It's distinct from accept/dismiss in the per-rule precision stat (it's "directionally right but magnitude wrong") and the existing CalibrationSignal schema has no `modifyCount` column. Either we add the column (clean), or we treat `modify` as `accept * 0.5 + dismiss * 0.5` in the bucket math (fast but lossy). The FastAPI `per_clinic_f1.py` chose the lossy route; the portal silently drops `modify` from CalibrationSignal.

9. **No data flywheel from "overcalled" back to prompt tuning.** `docs/SPECIALTY_TUNING.md` is a per-specialty MIPROv2 design doc. The CalibrationSignal gives us per-clinic overcall data, not per-specialty. Per-clinic is the natural unit for a solo operator — most clinics are 1–2 specialties — but the doc doesn't currently know about the CalibrationSignal scaffold. There's no cron that reads "CalibrationSignal.tenant=X overcalled rule=Y for 3 consecutive windows" and triggers a re-tune.

---

## 3. Proposed improvements

Ranked by leverage × implementation cost. Each item is independent and can ship alone.

### 3.1 Wire the CalibrationSignal upsert (HIGHEST LEVERAGE)

**What:** Add a single helper `upsertCalibrationSignal(tx, tenantId, ruleId, action)` to `apps/portal/src/lib/calibration.ts`. Call it from `writeAuditEntry()` (single-finding path) and `writeAuditBatch()` (bulk path) inside the existing Prisma transaction.

```ts
// pseudo-code, ~10 lines
await tx.calibrationSignal.upsert({
  where: { tenantId_ruleId: { tenantId, ruleId } },
  create: {
    tenantId, ruleId,
    acceptCount: action === "accept" ? 1 : 0,
    dismissCount: action === "dismiss" ? 1 : 0,
    lastSignalAt: timestamp,
  },
  update: {
    acceptCount: action === "accept" ? { increment: 1 } : undefined,
    dismissCount: action === "dismiss" ? { increment: 1 } : undefined,
    lastSignalAt: timestamp,
  },
});
```

The hookup lives in `audit-write.ts` because that's the only place that already (a) has the `ruleId` from the Finding row, (b) knows whether the action was `accept` vs `dismiss`, and (c) is already inside a Prisma transaction with the Finding + AuditTrail writes. Adding it here means a single helper added in two places gets the dashboard populating for every biller click going forward.

**Why this matters:** without it, the dashboard is theatre. With it, every tenant's calibration data appears automatically and the rest of this list becomes legible.

**Effort:** ~30 minutes including a backfill script for in-flight tenants (the existing 5-action threshold gives us breathing room — `actedOn < 5` rows are correctly labelled "uncalibrated" while they fill).

### 3.2 Show the sample size next to every bucket label (cheap, honest)

**What:** Augment the dashboard card to render `(n=2)` or `(n=23)` next to the bucket badge — the same way the per-clinic F1 tile already does (`docs/APPROVAL_RATE_KPI.md §5`). The bucket math doesn't change; the UI just stops hiding the denominator.

For rules with `actedOn < CALIBRATION_MIN_ACTED_ON` (currently the "uncalibrated" bucket), the badge should read "Uncalibrated" with a tooltip "Need 5 decisions before this bucket is meaningful — currently n=2". That converts the current binary "we have / we don't have data" into a smooth gradient that the biller can act on.

**Why this matters:** the current dashboard looks deterministic. It isn't. A "reviewing" label from 4 events and a "reviewing" label from 40 events carry very different epistemic weight. The biller can't tell which they're looking at.

**Effort:** ~1 hour. Pure UI change in `calibration-card.tsx`.

### 3.3 Per-clinic F1 dashboard (portal-side counterpart to `per_clinic_f1.py`)

**What:** Add a `modifyCount` column to `CalibrationSignal` (Prisma migration) and extend the read path so the portal dashboard can render precision/recall/F1 per rule per tenant, mirroring the FastAPI `per_clinic_f1.per_rule_metrics()` math but with the actual `tenantId` (not the biller_id proxy the FastAPI uses today).

The simplest version: a new `computeRuleF1(tenantId)` in `calibration.ts` that returns `[{ruleId, precision, recall, f1, support}]`, computed as:
- `precision = acceptCount / (acceptCount + dismissCount + 0.5 * modifyCount)`
- `recall = support / max_support` (the same within-clinic stand-in `per_clinic_f1.py:251` uses, surfaced as "recall (within-clinic)" so the biller knows the axis)
- `f1 = 2 * p * r / (p + r)`

Then a new card on the dashboard (or an expansion of the existing one) renders the F1 number next to the bucket badge. "calibrated · F1=0.78 (n=23)" tells the biller both what the bucket says AND what the math says.

**Why this matters:** the CalibrationSignal's bucket (`calibrated`/`overcalled`) is a coarse classifier. F1 is the number the optimizer actually maximizes (`scripts/optimize.py:615` calls `match_findings()`, which is `(category, suggested_code, quote-Jaccard)` matching). Showing the biller the same number the tuner uses closes the loop.

**Effort:** ~half a day (Prisma migration + helper + card expansion + tests).

### 3.4 Auto-tuning triggers (cron + CalibrationSignal state)

**What:** A nightly job `scripts/check_calibration_triggers.py` (sibling to existing scripts) that, for each tenant, reads the CalibrationSignal rows in the trailing 14-day window and emits a "needs tuning" flag if:
- A single rule has been in the `overcalled` bucket for >=3 of the last 5 weekly snapshots, OR
- A single rule's `dismissCount` exceeded its `acceptCount` by >=10 in the last 30 days, OR
- A tenant's mean accept rate across all rules dropped by >=0.10 over the last 30 days

The flag is just a row in a new `PendingTuning` table (or a field on `Tenant` — out of scope for this doc). A separate manual / scheduled task reads the flag, fires MIPROv2 on that tenant's encounter set, writes the tuned prompt, and clears the flag.

**Why this matters:** the per-clinic F1 dashboard is the diagnostic; the auto-tune trigger is the cure. Without it, "overcalled at this clinic" is just a label. With it, the label drives a re-tune that improves the very number the biller is looking at.

**Effort:** ~1 day for the trigger logic + flag table. The MIPROv2 wiring already exists in `scripts/optimize.py`; the per-clinic specialization is what `docs/SPECIALTY_TUNING.md` doesn't yet cover (see §4).

### 3.5 Per-clinic (not per-specialty) tuning unit

**What:** Update `docs/SPECIALTY_TUNING.md` to acknowledge that per-clinic is the primary tuning unit (most clinics are 1–2 specialties), and per-specialty is the fallback (used when many clinics share a specialty AND the per-clinic data is too thin to tune on). The marketplace loader becomes:

```python
def load_prompt(tenant: Tenant) -> LoadedPrompt:
    # Prefer per-clinic variant when it exists and is recent.
    clinic_candidate = f"prompts/clinic/{tenant.id}_v1.md"
    if file_exists(clinic_candidate) and not is_stale(clinic_candidate):
        return LoadedPrompt(path=clinic_candidate, source="clinic")
    # Fall back to per-specialty.
    return specialty_loader_fallback(tenant)
```

**Why this matters:** the data flywheel is per-clinic by construction — the CalibrationSignal table is keyed on `(tenantId, ruleId)`, not `(specialty, ruleId)`. Forcing the tuner to slice per-specialty means we either pool multiple clinics (which destroys the calibration signal) or we wait until one clinic accumulates enough specialty-specific feedback (which most never will). Per-clinic + per-specialty fallback is the natural shape.

**Effort:** ~half a day (spec update + loader change + 1–2 marketplace tests).

### 3.6 Surface staleness as a tier, not a binary flag

**What:** Replace the current single-line "stale" badge (when `lastSignalAt > 30 days`) with three tiers:
- **fresh** (lastSignalAt <= 7 days): no extra label, bucket as-is
- **aging** (7–30 days): a dimmer badge colour + tooltip "data is from 12 days ago — refresh by acting on a few more findings"
- **stale** (>30 days): current red badge + tooltip "data is too old to trust; act on a few findings to refresh"

The 7/30/∞ tiers mirror the FPAR tile (`docs/APPROVAL_RATE_KPI.md §5`).

**Why this matters:** "calibrated" from 90 days ago is worse than "uncalibrated" today — it gives false confidence. The current single 30-day cutoff is too coarse: it treats 31-day-old and 300-day-old data the same.

**Effort:** ~1 hour. Two thresholds instead of one, no schema change.

---

## 4. Recommended first move

**Item 3.1: Wire the CalibrationSignal upsert.**

Single helper added to `apps/portal/src/lib/audit-write.ts`, called from both `writeAuditEntry()` and `writeAuditBatch()`. Roughly 30 lines of code including a backfill helper for the in-flight tenants that have accept/dismiss history in `AuditTrailEntry` but no CalibrationSignal rows yet (the backfill walks `AuditTrailEntry` grouped by `(tenantId, finding.ruleId, action)` and upserts counts).

This is the **highest-leverage** single change because:
1. **Without it, every other item on this list is theatre.** The dashboard renders empty; the F1 math has no live counts; the auto-tune trigger has nothing to read.
2. **The hookup point already exists.** `audit-write.ts` is the only place in the codebase that (a) has `ruleId`, (b) knows `action`, (c) runs inside the same transaction as the Finding + AuditTrail writes. Adding the upsert there is the cheapest possible integration.
3. **It's idempotent by construction.** The `@@unique([tenantId, ruleId])` constraint plus `upsert` semantics mean a partial failure (the upsert throws after the audit row writes) is caught by the outer transaction and rolled back together with the chain write. No torn state possible.
4. **It unlocks the data flywheel.** Once CalibrationSignal rows are populating, items 3.2–3.6 become "polish on a working system" instead of "build the system from scratch".

The backfill is the only non-obvious bit: any tenant that accepted/dismissed findings before this PR lands needs their `CalibrationSignal` rows populated from the existing `AuditTrailEntry` history. That's a one-shot script (`scripts/backfill_calibration_signals.ts`), run once at deploy time, idempotent because the upsert key is `(tenantId, ruleId)`.

After 3.1 ships, the natural next two are **3.2 (sample size in the UI, 1 hour)** and **3.3 (per-clinic F1, half a day)**. Both add real value, both depend on 3.1's data being live, and both are small enough to ship in a single afternoon.

---

## 5. Out of scope (rejected approaches)

These were considered and explicitly rejected — either they violate the existing constraint surface, they're already done elsewhere, or they're a higher-cost path to a lower-leverage outcome.

### 5.1 Per-finding weight adjustments

The dashboard could let the biller adjust per-rule weights ("this rule is 80% important to me, that rule is 120%"). Rejected: the biller's "weight" signal is `accept` (trust) or `dismiss` (don't trust), not a continuous slider. Introducing continuous weights creates a UI surface that doesn't map to a downstream action — MIPROv2 consumes binary accept/dismiss, not weights. The CalibrationSignal's `acceptCount`/`dismissCount` are already the right shape.

### 5.2 Per-rule threshold auto-bumps

The "calibrated/reviewing/overcalled" thresholds (0.70 / 0.40) could auto-adjust based on tenant history. Rejected: the threshold tuning is a per-rule problem (some rules are inherently higher-precision, e.g. `rule_modifier_25_missing` runs at 90%+ accept historically, while a judgement-call rule like `rule_em_level` runs at 50%). Auto-bumping a global threshold hides the rule-specific story. If we ever need per-rule thresholds, the right place is a per-rule config file, not a learned threshold — and that file belongs in the marketplace prompt loader, not the CalibrationSignal.

### 5.3 Retraining model weights

`docs/SPECIALTY_TUNING.md §7` explicitly rules this out: "Not retraining model weights. Prompt optimization only." Reaffirmed here. CalibrationSignal data is the per-clinic / per-rule training signal for MIPROv2 (prompt optimization), not for weight fine-tuning. The data flywheel's terminal point is a tuned `.md` prompt file served by the marketplace loader — never a `.bin` weights file.

### 5.4 Cross-tenant rule calibration sharing

Two clinics both overcall `rule_modifier_25_missing` — could we share that signal? Rejected: each clinic's billing patterns are local (different payer mix, different modifier-25 frequency, different staff training). Pooling across tenants collapses the per-clinic calibration the dashboard exists to surface. If we ever want cross-tenant signal, it goes through the per-specialty fallback (item 3.5), not through CalibrationSignal.

### 5.5 Streaming CalibrationSignal updates to a live dashboard

The dashboard could subscribe to a websocket and update in real time as the biller clicks. Rejected: the dashboard already renders the latest snapshot on page load, the staleness window is 7–30 days, and websocket infra on Next.js + Prisma + SQLite is not free. Re-render on page load is the right cadence for a daily-use dashboard.

### 5.6 Replacing CalibrationSignal with a pure read-side computation

Today the dashboard reads from `CalibrationSignal`. We could compute it on demand from `Finding` + `AuditTrailEntry` (group by `(tenantId, ruleId)`, count accept/dismiss). The FastAPI `per_clinic_f1.py` already does this for the F1 number. Rejected: the read path is the dashboard's hot path (every page load), and the denormalised `CalibrationSignal` rows are the difference between "instant render" and "compute every page load". The current dual-path design — Prisma for the dashboard, JSONL scan for the FastAPI batch jobs — is the right shape; we should keep both.

### 5.7 Lowering the 5-action minimum to 3

`per_clinic_f1.py:420` uses `INSUFFICIENT_DATA_THRESHOLD = 3` for its own empty-state copy. Could the CalibrationSignal match? Rejected: the F1 helper has a different definition of "enough" (it needs enough samples for the binomial variance to be tolerable for a single F1 number; CalibrationSignal needs enough samples for the bucket label — calibrated vs overcalled — to be stable). The two thresholds serve different questions. If we ever want one knob for both, the knob belongs in the marketplace prompt loader config, not in `calibration.ts`.

### 5.8 Building a CalibrationSignal write hook in the FastAPI side

The FastAPI's `feedback.py` writes JSONL (`/app/logs/feedback.jsonl`), not Prisma. The portal and FastAPI are separate processes. We could add a FastAPI route that POSTs to the portal's CalibrationSignal upsert endpoint. Rejected: this is the exact "two sources of truth, must reconcile" pattern that item 1 (the missing write hook) was supposed to avoid. The portal's accept/dismiss routes already write the audit chain; adding the CalibrationSignal upsert in the same transaction is the single-source-of-truth fix. The FastAPI's `_record_feedback` path writes the JSONL for offline MIPROv2 / batch jobs only — that's a separate concern from the live dashboard.

---

## 6. Acceptance criteria

When this research is acted on (i.e. when items 3.1–3.6 ship), the following should be true:

- [ ] `apps/portal/src/lib/audit-write.ts` calls a `upsertCalibrationSignal(tx, tenantId, ruleId, action)` helper in both `writeAuditEntry` and `writeAuditBatch`.
- [ ] A backfill script `scripts/backfill_calibration_signals.ts` populates CalibrationSignal rows for any tenant with existing AuditTrailEntry history.
- [ ] The dashboard card renders the sample size (`n=X`) next to every bucket badge.
- [ ] The dashboard card renders a per-rule F1 number (precision / recall / F1) computed from CalibrationSignal.
- [ ] A nightly cron `scripts/check_calibration_triggers.py` emits a "needs tuning" flag for tenants with persistent overcalls.
- [ ] `docs/SPECIALTY_TUNING.md` is updated to describe the per-clinic primary tuning unit and the per-specialty fallback.
- [ ] The marketplace prompt loader prefers `prompts/clinic/<tenantId>_v1.md` when present and falls back to `prompts/specialty/<specialty>_v1.md`.
- [ ] All new tests pass in CI; the existing 7 CalibrationSignal bucket tests still pass unchanged.

## 7. Open questions

1. **Modify action handling.** Should `CalibrationSignal` carry `modifyCount` (clean schema) or should the bucket math absorb `modify` as `accept * 0.5 + dismiss * 0.5` (FastAPI's current approach)? Clean schema is more honest; lossy is more backwards-compatible. Recommendation: clean schema (`modifyCount`), with the dashboard explicitly rendering "modify" as a third state.
2. **Backfill scope.** The backfill script will replay every existing AuditTrailEntry. For a tenant with months of history and thousands of decisions, this is a one-time O(n) on a SQLite table. Acceptable; but should we backfill the JSONL feedback log too, so the FastAPI's `per_clinic_f1.py` agrees with the portal's CalibrationSignal? Yes — they should agree, and a sync job is cheap.
3. **What if a tenant's CalibrationSignal table grows unbounded?** One row per `(tenantId, ruleId)` is bounded by the number of rules (currently <30 in `rules/`). No pruning needed. But the `lastSignalAt` index is on every row — should we instead drop rows older than 12 months? No — the historical record is the audit log, the CalibrationSignal is a current-state view, and 30+ rows × a few hundred tenants is small.
4. **Per-clinic vs per-specialty for the marketplace loader.** When a tenant has both per-clinic and per-specialty variants, which wins? Recommendation: per-clinic always (most specific), regardless of `last_tuned_at`. The per-specialty is only the fallback when per-clinic is missing.