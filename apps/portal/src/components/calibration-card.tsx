// src/components/calibration-card.tsx
//
// Per-clinic calibration card — rendered on the dashboard home page
// (src/app/dashboard/page.tsx) next to the FPAR tile.
//
// Shows the biller which rules the auditor is consistently getting
// right at their clinic ("calibrated"), which ones the biller is
// sometimes overriding ("reviewing"), and which ones the auditor is
// overcalling ("overcalled" — worth per-clinic tuning per
// docs/SPECIALTY_TUNING.md §1).
//
// Empty state: when the tenant has zero calibration signals (i.e.
// the biller hasn't acted on any findings yet), shows a "no signal
// yet" hint that points the biller at the findings queue.

import Link from "next/link";
import type { ClinicCalibration, CalibrationSignalResult } from "@/lib/calibration";
import styles from "./calibration-card.module.css";

interface CalibrationCardProps {
  calibration: ClinicCalibration;
}

const BUCKET_LABELS: Record<CalibrationSignalResult["bucket"], string> = {
  calibrated: "Calibrated",
  reviewing: "Reviewing",
  overcalled: "Overcalled",
  uncalibrated: "Uncalibrated",
};

const BUCKET_DESCRIPTIONS: Record<CalibrationSignalResult["bucket"], string> = {
  calibrated: "Auditor's signal is trusted at your clinic",
  reviewing: "Mixed signal — review before trusting",
  overcalled: "Auditor fires this rule more than your biller accepts",
  uncalibrated: "Not enough data yet",
};

export function CalibrationCard({ calibration }: CalibrationCardProps) {
  const { signals, bucketCounts } = calibration;

  // Show the top 5 most-interesting rules. The computeCalibration
  // function already sorts (overcalled → reviewing → calibrated →
  // uncalibrated, then by actedOn desc).
  const top = signals.slice(0, 5);

  return (
    <section
      className={styles.card}
      aria-label="Per-rule calibration for this clinic"
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Rule calibration</p>
          <h2 className={styles.title}>
            {signals.length === 0
              ? "Not enough data yet"
              : `${bucketCounts.overcalled} overcalled · ${bucketCounts.reviewing} reviewing · ${bucketCounts.calibrated} calibrated`}
          </h2>
        </div>
      </header>

      {signals.length === 0 ? (
        <p className={styles.muted}>
          Calibration signals unlock after the biller has acted on at
          least <strong>5 findings per rule</strong> at this clinic.{" "}
          <Link href="/findings" className={styles.drillIn}>
            Review pending findings →
          </Link>
        </p>
      ) : (
        <>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col" className={styles.numCol}>Accept rate</th>
                <th scope="col" className={styles.numCol}>Decisions</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {top.map((s) => (
                <tr key={s.ruleId} className={s.isStale ? styles.staleRow : undefined}>
                  <td className={styles.ruleCell}>
                    <code className={styles.ruleId}>{s.ruleId}</code>
                    {s.isStale ? (
                      <span className={styles.staleTag} title={`Last decision: ${s.lastSignalAt.toISOString().slice(0, 10)}`}>
                        stale
                      </span>
                    ) : null}
                  </td>
                  <td className={styles.numCol}>
                    {s.acceptRate === null ? "—" : `${Math.round(s.acceptRate * 100)}%`}
                  </td>
                  <td className={styles.numCol}>{s.actedOn}</td>
                  <td>
                    <span
                      className={`${styles.badge} ${styles[`bucket_${s.bucket}`]}`}
                      aria-label={`Status: ${BUCKET_LABELS[s.bucket]} — ${BUCKET_DESCRIPTIONS[s.bucket]}`}
                      title={BUCKET_DESCRIPTIONS[s.bucket]}
                    >
                      {BUCKET_LABELS[s.bucket]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {signals.length > 5 ? (
            <p className={styles.muted} style={{ marginTop: "0.75rem" }}>
              Showing 5 of {signals.length} rules. Full breakdown is in
              the per-clinic calibration report (coming soon).
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}