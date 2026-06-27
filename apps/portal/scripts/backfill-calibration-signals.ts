// Backfill CalibrationSignal rows from existing AuditTrailEntry +
// Finding rows.
//
// Why: the CalibrationSignal write hook landed in commit 678e3a4,
// but tenants that already had biller decisions in the chain before
// that commit have an empty CalibrationSignal table — the dashboard
// card will show "Not enough data yet" for them until they generate
// 5+ new decisions. This script derives the signal counts from the
// chain so the card lights up the moment it deploys.
//
// Idempotent — re-running is safe (the upsert uses the same
// (tenantId, ruleId) unique key the write hook uses).
//
// Usage:
//   pnpm tsx scripts/backfill-calibration-signals.ts
//   pnpm tsx scripts/backfill-calibration-signals.ts --dry-run
//
// Backfill semantics:
//   - Walks every AuditTrailEntry with action='accept' or
//     action='dismiss' (the only two non-pending dispositions).
//   - Joins to Finding.ruleId (nullable: legacy findings pre-2026-06-27
//     scaffold migration don't have it; those rows are SKIPPED — they
//     can't be calibrated and the dashboard surfaces them via the
//     empty-state copy).
//   - Aggregates by (tenantId, ruleId): counts accepts and dismisses,
//     picks the MAX(actionedAt) for lastSignalAt.
//   - Upserts one CalibrationSignal row per (tenantId, ruleId).
//
// Exit code 0 on success (including 0 signals backfilled when the
// Finding table is empty). Cron should treat non-zero as a
// maintenance alert — the next day's run will pick up the same
// rows.
//
// See research/00-ROADMAP.md W1.2 for context. Companion to the
// write hook in apps/portal/src/lib/calibration-write.ts.

import { prisma } from "../src/lib/prisma";

type BackfillRow = {
  tenantId: string;
  ruleId: string;
  acceptCount: number;
  dismissCount: number;
  lastSignalAt: Date;
};

async function computeBackfillRows(): Promise<BackfillRow[]> {
  // Aggregate counts + max(timestamp) per (tenantId, findingId) in
  // one round-trip. The `tenantId` comes from the AuditTrailEntry
  // (it's denormalised for the chain) so we don't need a second join.
  //
  // NB: Prisma 7's groupBy doesn't support `where` clauses on joined
  // relations, so we can't filter "ruleId IS NOT NULL" here directly.
  // The Finding.ruleId null check happens below via a follow-up query.
  const grouped = await prisma.auditTrailEntry.groupBy({
    by: ["tenantId", "findingId"],
    where: {
      action: { in: ["accept", "dismiss"] },
    },
    _count: { _all: true },
    _max: { timestamp: true },
  });

  if (grouped.length === 0) {
    return [];
  }

  // Pull ruleId + tenantId for every affected finding. tenantId
  // comes via encounter because the chain row's tenantId is the
  // tenant the action was taken for (may differ from the finding's
  // encounter.tenantId if the schema ever supports cross-tenant
  // operations — for now they should always match, but we use the
  // encounter's tenantId to be safe).
  const findingIds = grouped.map((g) => g.findingId);
  const findings = await prisma.finding.findMany({
    where: { id: { in: findingIds }, ruleId: { not: null } },
    select: {
      id: true,
      ruleId: true,
      actionedAt: true,
      encounter: { select: { tenantId: true } },
    },
  });

  // Group actions per (tenantId, ruleId). Use the AuditTrailEntry
  // groupBy counts as accept/dismiss tally (action is per-row, not
  // per-finding), so we need to go finer-grained — query the
  // chain rows directly.
  const actionsByFinding = new Map<
    string,
    { accept: number; dismiss: number; lastSignalAt: Date }
  >();
  const chainRows = await prisma.auditTrailEntry.findMany({
    where: {
      findingId: { in: findingIds },
      action: { in: ["accept", "dismiss"] },
    },
    select: {
      findingId: true,
      action: true,
      timestamp: true,
    },
  });
  for (const row of chainRows) {
    const cur = actionsByFinding.get(row.findingId) ?? {
      accept: 0,
      dismiss: 0,
      lastSignalAt: row.timestamp,
    };
    if (row.action === "accept") cur.accept += 1;
    else if (row.action === "dismiss") cur.dismiss += 1;
    if (row.timestamp > cur.lastSignalAt) cur.lastSignalAt = row.timestamp;
    actionsByFinding.set(row.findingId, cur);
  }

  // Roll up per (tenantId, ruleId).
  const rolled = new Map<string, BackfillRow>();
  for (const f of findings) {
    if (!f.ruleId) continue; // type guard; covered by the where filter
    const actions = actionsByFinding.get(f.id);
    if (!actions) continue; // finding with no chain rows (shouldn't happen)
    const key = `${f.encounter.tenantId}::${f.ruleId}`;
    const cur = rolled.get(key) ?? {
      tenantId: f.encounter.tenantId,
      ruleId: f.ruleId,
      acceptCount: 0,
      dismissCount: 0,
      lastSignalAt: actions.lastSignalAt,
    };
    cur.acceptCount += actions.accept;
    cur.dismissCount += actions.dismiss;
    if (actions.lastSignalAt > cur.lastSignalAt) {
      cur.lastSignalAt = actions.lastSignalAt;
    }
    rolled.set(key, cur);
  }

  return Array.from(rolled.values());
}

async function main(): Promise<void> {
  const dryRun = process.argv.includes("--dry-run");
  console.log(
    `[backfill-calibration] starting${dryRun ? " (DRY RUN — no writes)" : ""}`,
  );

  const rows = await computeBackfillRows();
  console.log(
    `[backfill-calibration] computed ${rows.length} (tenantId, ruleId) rows to upsert`,
  );

  if (dryRun) {
    // Print the first 10 so the operator can eyeball before committing.
    for (const r of rows.slice(0, 10)) {
      console.log(
        `  ${r.tenantId} :: ${r.ruleId}  accept=${r.acceptCount} dismiss=${r.dismissCount} lastSignal=${r.lastSignalAt.toISOString()}`,
      );
    }
    if (rows.length > 10) {
      console.log(`  ... and ${rows.length - 10} more`);
    }
    console.log("[backfill-calibration] dry-run done; no writes performed");
    return;
  }

  // Upsert in a transaction so a partial failure rolls back cleanly.
  // Batching is unnecessary at this scale (typically <1k rows); if
  // a deployment has >10k signals, switch to a createMany with skipDuplicates.
  let upserted = 0;
  for (const r of rows) {
    await prisma.calibrationSignal.upsert({
      where: {
        tenantId_ruleId: {
          tenantId: r.tenantId,
          ruleId: r.ruleId,
        },
      },
      create: {
        tenantId: r.tenantId,
        ruleId: r.ruleId,
        acceptCount: r.acceptCount,
        dismissCount: r.dismissCount,
        lastSignalAt: r.lastSignalAt,
      },
      update: {
        acceptCount: r.acceptCount,
        dismissCount: r.dismissCount,
        lastSignalAt: r.lastSignalAt,
      },
    });
    upserted += 1;
  }

  console.log(
    `[backfill-calibration] upserted ${upserted} CalibrationSignal rows`,
  );
}

main()
  .then(async () => {
    await prisma.$disconnect();
    process.exit(0);
  })
  .catch(async (err) => {
    console.error("[backfill-calibration] FAILED:", err);
    await prisma.$disconnect();
    process.exit(1);
  });