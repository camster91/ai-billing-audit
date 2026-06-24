# First-Pass Approval Rate — KPI Tile Design

Status: design doc, ready for implementation.
Owner: learning-loop, P5 first-pass-approval-rate task (`t_f2047c46`).
Last updated: 2026-06-24.

This document specifies the **first-pass approval rate** KPI tile for
the home dashboard. The metric answers one question for the biller and
the clinic owner:

> *Of the model's recent suggestions, what percentage did the biller
> accept unchanged?*

A high rate means the model is well-calibrated for this clinic's
patterns. A low rate means the model is overcalling, misclassifying, or
applying rules the clinic doesn't consider correct. The tile is the
quick visual signal that something has drifted and the model needs
recalibration or a per-specialty tune (see `docs/SPECIALTY_TUNING.md`).

---

## 1. Definition (locked)

**First-pass approval rate (FPAR) for a clinic, computed over the
last 50 audits:**

```
FPAR = (count of audits where the biller accepted every finding as-is)
       / 50
```

Where:

- An "audit" is one encounter with ≥ 1 finding produced.
- "Accepted every finding as-is" means: every finding on the encounter
  has `biller_decision = accept` AND no `what_should_this_have_been`
  was recorded (no `modify` either). The encounter is unchanged from
  the model's output.
- The window is the **most recent 50 such audits**, ordered by
  `audit_completed_at` descending. We do **not** filter by date
  directly — we filter by recency-of-event, then take 50.

### 1.1 What FPAR is NOT

- **Not** precision. Precision is "of the things the model flagged,
  what % were correct?" That's computed on a labeled set, not on
  live production. FPAR is the live, per-clinic analog.
- **Not** a global model-quality score. FPAR is **per-clinic** because
  clinic patterns differ. A clinic that bills differently from the
  pilot baseline will see a low FPAR even when the model is fine for
  the general population.
- **Not** the rate at which the biller accepts individual findings. We
  count the encounter, not the finding, so a single `dismiss` on a
  10-finding encounter counts the whole encounter as "not accepted
  unchanged."

---

## 2. Where the data comes from

The signal lives in two tables that are already wired:

| Table                       | Columns we use                                          |
|-----------------------------|---------------------------------------------------------|
| `AuditRun` / encounter      | `id`, `tenantId`, `auditCompletedAt`                    |
| `Finding`                   | `id`, `encounterId`, `billerDecision`, `whatShouldThisHaveBeen` |

The `billerDecision` enum is `accept | dismiss | modify | null`.
The `accept-unchanged` predicate is:

```sql
biller_decision = 'accept'
AND what_should_this_have_been IS NULL
```

This is the same predicate the weekly-digest email uses for its
"denial-prevented" count (see `apps/portal/src/lib/emails/weekly-digest.ts`),
so we get one definition shared across the dashboard, the email, and
the per-clinic F1 panel.

---

## 3. Query

```sql
WITH recent_audits AS (
  SELECT e.id, e.audit_completed_at
  FROM encounter e
  WHERE e.tenant_id = :tenant_id
    AND e.audit_completed_at IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM finding f
      WHERE f.encounter_id = e.id
        AND f.biller_decision IS NOT NULL
    )
  ORDER BY e.audit_completed_at DESC
  LIMIT 50
),
accepted_unchanged AS (
  SELECT 1
  FROM recent_audits ra
  WHERE NOT EXISTS (
    SELECT 1 FROM finding f
    WHERE f.encounter_id = ra.id
      AND (
        f.biller_decision <> 'accept'
        OR f.what_should_this_have_been IS NOT NULL
      )
  )
)
SELECT
  COUNT(*) FILTER (WHERE TRUE) AS audits_in_window,
  (SELECT COUNT(*) FROM accepted_unchanged) AS accepted_unchanged_count
FROM recent_audits;
```

The `EXISTS` / `NOT EXISTS` pair keeps the query O(50 × findings_per_encounter)
in the worst case, which is fine — we cap at 50.

If `audits_in_window < 10` the tile renders a **"Not enough data yet"**
state instead of a percentage. We don't show a misleading low number
based on three encounters.

---

## 4. Backend surface

Add a single function in
`apps/portal/src/lib/dashboard.ts` (new file, sibling to
`billing-page.ts`):

```ts
export interface FirstPassApprovalRate {
  auditsInWindow: number;          // 0..50
  acceptedUnchangedCount: number;  // 0..50
  rate: number | null;             // 0..1, null when auditsInWindow < 10
  isStale: boolean;                // true when oldest audit in window is > 30 days old
}

export async function getFirstPassApprovalRate(
  tenantId: string,
  prisma: PrismaClient,
): Promise<FirstPassApprovalRate>;
```

The function is **tenant-scoped** (no cross-tenant reads), pure
(no writes), and idempotent. It returns `rate: null` when
`auditsInWindow < 10` so the UI can render the empty state.

Add the call inside `apps/portal/src/app/dashboard/page.tsx` next to
the existing quota + onboarding data fetch — single round-trip if
Prisma can run them in parallel via `Promise.all`.

---

## 5. UI tile

The tile lives on the home dashboard, in a 2-column grid of KPI tiles
sitting above the existing "Your clinics" card. The grid wraps to a
single column on mobile.

### 5.1 Layout

```
┌────────────────────────────────────────┐
│ First-pass approval rate               │
│                                        │
│  87%                                   │
│  ▲ +3 vs last week                     │
│                                        │
│  Of the last 50 audits you accepted     │
│  every finding as-is.                  │
│  ─────────────                         │
│  Updated: 2 minutes ago                │
└────────────────────────────────────────┘
```

### 5.2 Color rules

| FPAR range   | Color (token)        | Meaning                            |
|--------------|----------------------|------------------------------------|
| ≥ 80%        | `emerald-600`        | Healthy — model is well-calibrated |
| 60–79%       | `amber-500`          | Watch — some overcalling, monitor  |
| < 60%        | `red-600`            | Recalibrate — model is overcalling  |
| < 10 audits  | `slate-400`          | Not enough data yet                |

The threshold table lives in `apps/portal/src/lib/dashboard.ts` as
exported constants (`FPAR_HEALTHY_THRESHOLD`, etc.) so product can
tune them without a code change to the tile.

### 5.3 Trend indicator

A small ▲/▼ next to the percentage shows the change from the prior
50-audit window. Compute it the same way (last 50 audits before the
current window) and diff the rates. If the prior window has < 10
audits, hide the trend — don't show "▲ +3" against a meaningless
baseline.

### 5.4 Stale data warning

If the oldest audit in the current 50-audit window is more than
30 days old (`isStale: true`), the tile shows a small `IconInfo` with
the text "Last audit >30 days ago" in `slate-500`. This catches the
"clinic went on vacation" or "the auditor is broken" case.

---

## 6. Caching

The tile is `dynamic = "force-dynamic"` on the dashboard route, so it
recomputes per request. To avoid hammering the DB:

- Cache the result in the existing dashboard-data cache (Redis, 60s
  TTL per tenant) if and only if the call site has access to the
  cache. The query is cheap (< 5ms with the right indexes), so cache
  is optional.
- Add a covering index:
  ```sql
  CREATE INDEX idx_finding_decision ON finding(encounter_id, biller_decision)
    WHERE biller_decision IS NOT NULL;
  ```
  This makes the inner `NOT EXISTS` subquery an index-only scan.

---

## 7. Edge cases

| Case                                        | Tile behavior                          |
|---------------------------------------------|----------------------------------------|
| Tenant has 0 audits                         | "Not enough data yet"                  |
| Tenant has 1–9 audits                       | "Not enough data yet"                  |
| 10+ audits, all in last 24h                 | Full number, no trend (prior < 10)     |
| 10+ audits, spread over 6 months            | Full number, `isStale: true` warning   |
| Biller hasn't decided anything yet          | Those audits are excluded from window  |
| Finding has `biller_decision IS NULL`       | Encounter excluded from window          |
| Finding has `biller_decision = 'modify'`    | Encounter counts as "not unchanged"    |
| 50-audit window rolls forward on new audit  | Recomputed each request (no caching of the window itself) |

---

## 8. Tests

| Test file                              | Covers                                |
|----------------------------------------|---------------------------------------|
| `test_fpar_query.ts`                   | SQL: window of 50, accept-unchanged predicate, audit-completion gate |
| `test_dashboard_fpar_tile.tsx`         | Renders the right color for each FPAR band, "not enough data" state, trend arrow, stale warning |
| `test_fpar_edge_cases.ts`              | < 10 audits returns null rate; mixed accept/modify counts correctly; cross-tenant isolation |

All three are unit tests; no LLM calls; no network; runs in < 1s.

---

## 9. Acceptance checklist

When the task moves to "done":

- [ ] `getFirstPassApprovalRate` exists in
      `apps/portal/src/lib/dashboard.ts` and is called from
      `apps/portal/src/app/dashboard/page.tsx`.
- [ ] The KPI tile renders on the home dashboard, in the 2-column
      grid above "Your clinics".
- [ ] The percentage is computed from the last 50 audits where
      every finding was `biller_decision = 'accept'` with no
      `what_should_this_have_been`.
- [ ] The tile color matches the threshold table in **§5.2**.
- [ ] The trend indicator shows ▲/▼ vs the prior 50-audit window.
- [ ] The "Not enough data yet" state shows when `auditsInWindow < 10`.
- [ ] The "Last audit >30 days ago" warning shows when the window is stale.
- [ ] The covering index in **§6** is created via a migration.
- [ ] All three test files pass in CI.
- [ ] No cross-tenant reads — the function takes `tenantId` and uses
      it in the WHERE clause.
