// src/lib/fpar.ts
//
// First-Pass Approval Rate (FPAR) — per the spec in
// docs/APPROVAL_RATE_KPI.md, adapted to the portal's Prisma schema.
//
// Definition (locked at docs/APPROVAL_RATE_KPI.md §1):
//
//     FPAR = (count of audits where the biller accepted every finding as-is)
//            / 50
//
// Where:
//   - "audit" = one encounter with ≥ 1 finding produced.
//   - "Accepted every finding as-is" = every finding has
//     `status = 'accepted'` AND `dismissText IS NULL`.
//   - The window is the most recent 50 such audits, ordered by
//     `encounter.updatedAt` descending.
//
// Schema adaptation note: the original spec referenced a
// `biller_decision` column and a `what_should_this_have_been` column
// that exist on the FastAPI's Postgres but NOT on the portal's
// Prisma schema. The portal's Finding model uses:
//   - `status: "pending" | "accepted" | "dismissed"`
//   - `dismissText: String?`  — set on dismiss-with-text
// The portal doesn't have an explicit "modify" action — dismiss is
// the only non-accept path. So "accepted unchanged" reduces to
// "every finding has status='accepted'" (dismissText is set only
// on dismiss, never on accept).

import { prisma } from "@/lib/prisma";

/** Minimum number of acted-on audits required before FPAR is reported.
 *  Below this threshold the tile shows "Not enough data yet"
 *  (docs/APPROVAL_RATE_KPI.md §3). */
export const FPAR_MIN_WINDOW = 10;

/** Age threshold for the "stale" banner: if the oldest audit in
 *  the window is older than this, FPAR is reported but the tile
 *  shows a stale-data warning (docs/APPROVAL_RATE_KPI.md §5). */
export const FPAR_STALE_DAYS = 30;

/**
 * FPAR result shape, exported for the FPARTile component.
 * Matches the dashboard SQL in docs/APPROVAL_RATE_KPI.md §4.
 */
export interface FirstPassApprovalRate {
  /** 0..50, the size of the lookback window after filtering. */
  auditsInWindow: number;
  /** 0..50, the count of encounters accepted unchanged. */
  acceptedUnchangedCount: number;
  /** 0.0..1.0, or null when auditsInWindow < FPAR_MIN_WINDOW
   *  (the "not enough data yet" threshold). */
  rate: number | null;
  /** True when the oldest audit in the window is older than
   *  FPAR_STALE_DAYS. Signals "the recent pattern is stale;
   *  consider re-tuning" per docs/APPROVAL_RATE_KPI.md §5. */
  isStale: boolean;
}

/**
 * Pure predicate: is this encounter's finding set "accepted
 * unchanged"? Extracted for unit testing — see tests/fpar.test.ts.
 *
 * An encounter counts as accepted-unchanged when EVERY finding has
 * status='accepted' AND dismissText IS NULL. (dismissText is set
 * only on dismiss paths; on accept it's null by construction.)
 */
export function isAcceptedUnchanged(
  findings: ReadonlyArray<{ status: string; dismissText: string | null }>,
): boolean {
  if (findings.length === 0) return false;
  return findings.every(
    (f) => f.status === "accepted" && f.dismissText === null,
  );
}

/**
 * Compute FPAR for a single tenant. Reads from the portal's Prisma
 * DB (Finding + Encounter). Pure function in the sense that it
 * doesn't mutate state; not pure in the IO sense (it hits the DB).
 *
 * @param tenantId the tenant (clinic) to compute FPAR for
 * @param opts.now  used to compute `isStale`; defaults to `new Date()`.
 *                  Injectable for tests.
 */
export async function computeFPAR(
  tenantId: string,
  opts: { now?: Date } = {},
): Promise<FirstPassApprovalRate> {
  const now = opts.now ?? new Date();

  // Walk the most recent 50 ACTED-ON encounters (an "audit" = ≥1
  // finding, with at least one finding whose status is not 'pending').
  // We filter out pending-only encounters so a fresh tenant that
  // uploaded 100 encounters but didn't act on any of them doesn't
  // show a 0% FPAR — the spec says "not enough data yet".
  //
  // We over-fetch by 1 to detect the "no acted-on findings" case
  // without a second query; findMany() with `take: 50` returns
  // at most 50 rows regardless of how many total exist.
  const encounters = await prisma.encounter.findMany({
    where: {
      tenantId,
      findings: {
        some: {
          status: { in: ["accepted", "dismissed"] },
        },
      },
    },
    orderBy: { updatedAt: "desc" },
    take: 50,
    select: {
      id: true,
      updatedAt: true,
      findings: {
        select: {
          status: true,
          dismissText: true,
        },
      },
    },
  });

  if (encounters.length === 0) {
    return {
      auditsInWindow: 0,
      acceptedUnchangedCount: 0,
      rate: null,
      isStale: false,
    };
  }

  const acceptedUnchangedCount = encounters.filter((e) =>
    isAcceptedUnchanged(e.findings),
  ).length;

  const auditsInWindow = encounters.length;
  const rate =
    auditsInWindow < FPAR_MIN_WINDOW
      ? null
      : Math.round((acceptedUnchangedCount / auditsInWindow) * 1000) / 1000;

  // isStale: oldest encounter in the window > FPAR_STALE_DAYS old.
  // We use `encounter.updatedAt` as a proxy for the FastAPI's
  // `audit_completed_at` — the portal updates this column when
  // the biller accepts/dismisses a finding, which is when the
  // audit "completes" from the dashboard's perspective.
  const oldest = encounters[encounters.length - 1];
  const ageMs = now.getTime() - oldest.updatedAt.getTime();
  const staleMs = FPAR_STALE_DAYS * 24 * 60 * 60 * 1000;
  const isStale = ageMs > staleMs;

  return {
    auditsInWindow,
    acceptedUnchangedCount,
    rate,
    isStale,
  };
}