// src/lib/calibration.ts
//
// Per-clinic calibration signal — read path. Pairs with the
// CalibrationSignal Prisma table (see prisma/schema.prisma) and the
// Finding.ruleId field added in the 2026-06-27 scaffold migration.
//
// What this answers, for one tenant:
//   "Which rules does my biller consistently accept vs dismiss,
//    and which are stale or uncalibrated?"
//
// This is the portal-side counterpart to the FastAPI's
// src/ai_billing_audit/feedback.py:280 — the FastAPI side computes
// calibration on demand from the audit log; the portal pre-aggregates
// into CalibrationSignal rows so the dashboard can render without a
// round-trip. Both paths exist on purpose: the FastAPI side is the
// source of truth (full audit log), the portal side is the
// dashboard-fast path.
//
// Bucket semantics (mirrored from feedback.py:280, kept in sync by
// the calibration-bucket constants below):
//   acceptRate >= 0.70 → "calibrated"
//   0.40 <= acceptRate < 0.70 → "reviewing"
//   acceptRate < 0.40  → "overcalled"
//   actedOn < MIN_ACTED_ON → "uncalibrated"

import { prisma } from "@/lib/prisma";

/** Minimum number of biller actions required before a rule is
 *  considered calibrated at this clinic. Below this we report
 *  "uncalibrated" so we don't draw conclusions from <5 data points. */
export const CALIBRATION_MIN_ACTED_ON = 5;

/** Days after which a calibration signal is considered stale.
 *  Same staleness threshold as the FPAR tile (docs/APPROVAL_RATE_KPI.md §5). */
export const CALIBRATION_STALE_DAYS = 30;

export type CalibrationBucket = "calibrated" | "reviewing" | "overcalled" | "uncalibrated";

/** Per-rule calibration summary for one tenant. Shape is what the
 *  CalibrationCard component renders, not what the DB stores. */
export interface CalibrationSignalResult {
  ruleId: string;
  acceptCount: number;
  dismissCount: number;
  actedOn: number;
  /** null when actedOn < CALIBRATION_MIN_ACTED_ON, else 0.0..1.0. */
  acceptRate: number | null;
  bucket: CalibrationBucket;
  /** True when no biller action on this rule in the last
   *  CALIBRATION_STALE_DAYS days. */
  isStale: boolean;
  lastSignalAt: Date;
}

/** Top-level result for one tenant's calibration dashboard. */
export interface ClinicCalibration {
  tenantId: string;
  /** All CalibrationSignal rows for this tenant, sorted by
   *  "interesting-ness" — overcalled first (highest leverage for
   *  the biller), then reviewing, then calibrated, then uncalibrated.
   *  Within a bucket, larger actedOn ranks higher (more signal). */
  signals: CalibrationSignalResult[];
  /** Counts by bucket — drives the headline summary on the dashboard. */
  bucketCounts: Record<CalibrationBucket, number>;
}

/**
 * Read-path: load all calibration signals for one tenant and bucket them.
 * Pure function (IO is the Prisma query); no side effects.
 *
 * @param tenantId the tenant (clinic) to summarize
 * @param opts.now injectable for tests
 */
export async function computeCalibration(
  tenantId: string,
  opts: { now?: Date } = {},
): Promise<ClinicCalibration> {
  const now = opts.now ?? new Date();
  const staleMs = CALIBRATION_STALE_DAYS * 24 * 60 * 60 * 1000;

  // Cap the signal set — a clinic should not have tens of thousands of
  // distinct rule IDs. Unbounded findMany was a memory DoS surface.
  const rows = await prisma.calibrationSignal.findMany({
    where: { tenantId },
    orderBy: { lastSignalAt: "desc" },
    take: 5_000,
  });

  const signals: CalibrationSignalResult[] = rows.map((r) => {
    const actedOn = r.acceptCount + r.dismissCount;
    const acceptRate =
      actedOn < CALIBRATION_MIN_ACTED_ON
        ? null
        : Math.round((r.acceptCount / actedOn) * 1000) / 1000;
    const bucket = bucketFor(acceptRate, actedOn);
    const ageMs = now.getTime() - r.lastSignalAt.getTime();
    return {
      ruleId: r.ruleId,
      acceptCount: r.acceptCount,
      dismissCount: r.dismissCount,
      actedOn,
      acceptRate,
      bucket,
      isStale: ageMs > staleMs,
      lastSignalAt: r.lastSignalAt,
    };
  });

  // Sort: overcalled first (highest leverage), then reviewing,
  // then calibrated, then uncalibrated. Within a bucket, larger
  // actedOn first so the most-confident signals lead.
  const bucketOrder: Record<CalibrationBucket, number> = {
    overcalled: 0,
    reviewing: 1,
    calibrated: 2,
    uncalibrated: 3,
  };
  signals.sort((a, b) => {
    const ob = bucketOrder[a.bucket] - bucketOrder[b.bucket];
    if (ob !== 0) return ob;
    return b.actedOn - a.actedOn;
  });

  const bucketCounts: Record<CalibrationBucket, number> = {
    calibrated: 0,
    reviewing: 0,
    overcalled: 0,
    uncalibrated: 0,
  };
  for (const s of signals) bucketCounts[s.bucket] += 1;

  return { tenantId, signals, bucketCounts };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Pure bucket function — extracted for unit testing. Mirrors the
 * FastAPI's feedback.py:280 thresholds:
 *   actedOn < CALIBRATION_MIN_ACTED_ON → "uncalibrated"  (check FIRST)
 *   acceptRate >= 0.70 → "calibrated"
 *   0.40 <= acceptRate < 0.70 → "reviewing"
 *   acceptRate < 0.40  → "overcalled"
 *
 * NB: actedOn check must come FIRST. Even a 100% accept rate from 1
 * data point doesn't justify a "calibrated" label — the biller may
 * have accepted by reflex rather than judgment. We refuse to bucket
 * until we have at least CALIBRATION_MIN_ACTED_ON (5) data points.
 */
export function bucketFor(
  acceptRate: number | null,
  actedOn: number,
): CalibrationBucket {
  if (actedOn < CALIBRATION_MIN_ACTED_ON) return "uncalibrated";
  if (acceptRate === null) return "uncalibrated";
  if (acceptRate >= 0.7) return "calibrated";
  if (acceptRate >= 0.4) return "reviewing";
  return "overcalled";
}