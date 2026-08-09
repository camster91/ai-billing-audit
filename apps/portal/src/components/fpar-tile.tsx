// src/components/fpar-tile.tsx
//
// First-Pass Approval Rate tile — rendered on the dashboard home page
// (src/app/dashboard/page.tsx) per docs/APPROVAL_RATE_KPI.md.
//
// The tile shows one of three states:
//
//   1. rate === null (auditsInWindow < 10): "Not enough data yet" with
//      a hint that the biller needs to accept/dismiss ~10 audits to
//      unlock the metric.
//
//   2. rate !== null + isStale === false: the percentage with a
//      one-line interpretation (good / fair / investigate) per
//      docs/APPROVAL_RATE_KPI.md §5. (Calibrated thresholds: 0.85+
//      "great", 0.70-0.85 "well calibrated", 0.50-0.70 "check",
//      <0.50 "investigate".)
//
//   3. rate !== null + isStale === true: the percentage with a stale
//      banner ("Last audit > 30 days ago — recent pattern may have
//      drifted").
//
// All three states share the same card chrome (matches the rest of
// the portal's dashboard — see src/app/portal/shell.module.css for
// the design system tokens).

import Link from "next/link";
import type { FirstPassApprovalRate } from "@/lib/fpar";
import styles from "./fpar-tile.module.css";

interface FPARTileProps {
  tenantId: string;
  fpar: FirstPassApprovalRate;
  /** Path to the audit log where the biller can drill in. */
  drillInHref?: string;
}

/**
 * Render the FPAR tile for a tenant. Pure presentational component
 * — receives the computed FPAR object as a prop; the dashboard page
 * does the prisma work (via computeFPAR) and passes the result.
 */
export function FPARTile({ fpar, drillInHref }: FPARTileProps) {
  const { auditsInWindow, acceptedUnchangedCount, rate, isStale } = fpar;

  // Rate interpretation: docs/APPROVAL_RATE_KPI.md §5 recommends
  // these bands for clinic owners — high = well-calibrated, low =
  // overcalling. Same thresholds used in docs/SPECIALTY_TUNING.md
  // §3 to flag a clinic for recalibration.
  const band = rateBand(rate);

  return (
    <section
      className={styles.tile}
      aria-label="First-pass approval rate"
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>First-pass approval rate</p>
          <h2 className={styles.title}>
            {rate === null ? "—" : `${Math.round(rate * 100)}%`}
          </h2>
        </div>
        <span
          className={`${styles.badge} ${styles[`band_${band.key}`]}`}
          aria-label={`Interpretation: ${band.label}`}
        >
          {band.label}
        </span>
      </header>

      {rate === null ? (
        <p className={styles.muted}>
          Not enough data yet — FPAR unlocks after the biller acts on
          {" "}
          <strong>10 audits</strong> at this clinic.{" "}
          <Link
            href="/encounters?status=pending"
            className={styles.drillIn}
          >
            Review pending findings →
          </Link>
        </p>
      ) : (
        <p className={styles.muted}>
          <strong>{acceptedUnchangedCount}</strong> of the last{" "}
          <strong>{auditsInWindow}</strong> audits were accepted
          unchanged. {band.summary}{" "}
          {drillInHref ? (
            <Link href={drillInHref} className={styles.drillIn}>
              View audit log →
            </Link>
          ) : null}
        </p>
      )}

      {isStale ? (
        <p className={styles.stale}>
          <span aria-hidden>⚠</span> Last audit in this window is more
          than 30 days old. Recent clinic pattern may have drifted —
          consider running a fresh pilot or re-tuning per{" "}
          <Link href="/security#calibration">the calibration guide</Link>.
        </p>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface RateBand {
  key: "great" | "good" | "fair" | "low" | "insufficient";
  label: string;
  summary: string;
}

function rateBand(rate: number | null): RateBand {
  if (rate === null) {
    return {
      key: "insufficient",
      label: "Insufficient data",
      summary: "",
    };
  }
  if (rate >= 0.85) {
    return {
      key: "great",
      label: "Well calibrated",
      summary: "The model's suggestions match this clinic's review pattern.",
    };
  }
  if (rate >= 0.7) {
    return {
      key: "good",
      label: "Calibrated",
      summary: "Most suggestions land. A few overcalls are normal.",
    };
  }
  if (rate >= 0.5) {
    return {
      key: "fair",
      label: "Check calibration",
      summary: "More than half of audits are being modified. Worth reviewing.",
    };
  }
  return {
    key: "low",
    label: "Investigate",
    summary: "The model is overcalling for this clinic. Consider per-clinic tuning.",
  };
}
