// apps/portal/src/lib/calibration-write.ts
//
// Write-side companion to apps/portal/src/lib/calibration.ts.
//
// Today (2026-06-27) the CalibrationSignal table is read by the
// dashboard card (apps/portal/src/components/calibration-card.tsx)
// but no route writes to it — every biller accept/dismiss updates
// Finding.status + the AuditTrailEntry chain, leaving the signal
// empty. This file is the missing write side.
//
// Wire-up: import { upsertCalibrationSignal } from
// "@/lib/calibration-write" and call it inside the same Prisma
// transaction as the Finding mutation in apps/portal/src/lib/audit-write.ts
// (writeAuditEntry + writeAuditBatch). The @@unique([tenantId, ruleId])
// constraint + Prisma upsert semantics make it idempotent and atomic
// with the chain write.

import type { Prisma } from "@/generated/prisma/client";

/**
 * Action that drove the calibration signal. Mirrors the
 * `AuditAction` type's "accept" / "dismiss" but expressed as the
 * field name we increment on the signal row.
 */
export type CalibrationAction = "accept" | "dismiss";

export interface UpsertCalibrationSignalArgs {
  tenantId: string;
  /**
   * The Finding's ruleId (added in the 2026-06-27 scaffold
   * migration). Null = no ruleId (legacy finding pre-2026-06-27
   * or ingest path that didn't set the field). Null ruleIds are
   * skipped — CalibrationSignal requires a non-null ruleId to
   * support the (tenantId, ruleId) unique constraint.
   */
  ruleId: string | null;
  /** Accept or dismiss — drives which counter increments. */
  action: CalibrationAction;
  /**
   * Wall-clock time of the biller decision. Caller controls so the
   * bulk path can pass the batch's `baseTimestamp` for determinism
   * (see apps/portal/src/lib/audit-write.ts:177).
   */
  timestamp: Date;
}

/**
 * Increment the accept/dismiss counter for (tenantId, ruleId) and
 * refresh `lastSignalAt`. Atomic under the @@unique([tenantId, ruleId])
 * constraint via Prisma upsert; safe to call inside a transaction.
 *
 * No-op when ruleId is null — the dashboard's empty-state copy
 * (src/components/calibration-card.tsx) will surface "not enough
 * data" for these findings and we don't want them to count toward
 * the calibration bucket.
 */
export async function upsertCalibrationSignal(
  tx: Prisma.TransactionClient,
  args: UpsertCalibrationSignalArgs,
): Promise<void> {
  if (!args.ruleId) return;

  const isAccept = args.action === "accept";
  await tx.calibrationSignal.upsert({
    where: {
      tenantId_ruleId: {
        tenantId: args.tenantId,
        ruleId: args.ruleId,
      },
    },
    create: {
      tenantId: args.tenantId,
      ruleId: args.ruleId,
      acceptCount: isAccept ? 1 : 0,
      dismissCount: isAccept ? 0 : 1,
      lastSignalAt: args.timestamp,
    },
    update: {
      acceptCount: isAccept ? { increment: 1 } : undefined,
      dismissCount: isAccept ? undefined : { increment: 1 },
      lastSignalAt: args.timestamp,
    },
  });
}

/**
 * Manual smoke-test recipe (used by tests/calibration.upsert.test.ts
 * and the deploy-runbook `scripts/verify_calibration_roundtrip.sh`):
 *
 *   1. Create a fresh tenant + finding + Encounter in the dev DB.
 *   2. Call upsertCalibrationSignal 5 times (all "accept") inside a
 *      Prisma transaction with the same ruleId.
 *   3. Read CalibrationSignal via prisma.calibrationSignal.findFirst
 *      and assert acceptCount=5, dismissCount=0.
 *   4. Call computeCalibration(tenantId) and assert the row's bucket
 *      is "calibrated" (acceptRate=1.0, actedOn=5 >= MIN_ACTED_ON).
 *   5. With a fresh tenant + 1 accept only, assert bucket is
 *      "uncalibrated" (actedOn=1 < 5).
 *
 * The unit test in tests/calibration.test.ts covers the bucket math
 * (pure function, no DB). This helper is the IO-bound counterpart
 * and is exercised via the DB-backed test in tests/calibration.upsert.test.ts.
 */