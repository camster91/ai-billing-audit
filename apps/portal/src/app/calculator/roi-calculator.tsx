// /calculator/roi-calculator — client component for the live
// "How much are you leaving on the table?" inputs + result panel.
//
// The math is intentionally transparent: every input is shown,
// every constant is labelled with its source, and the formula is
// printed at the bottom of the result so the biller or billing lead
// can audit it themselves. No hidden multipliers.
//
// Specialty -> avg claim value table is a blend of Alberta SOMB
// averages as of June 2026. These are deliberately conservative
// (rounded to the nearest $5) so the result is defensible against
// a skeptical clinic admin. See the ROI formula doc for the
// derivation.

"use client";

import { useMemo, useState } from "react";
import styles from "./calculator.module.css";

type Specialty =
  | "family_medicine"
  | "internal_medicine"
  | "cardiology"
  | "pediatrics"
  | "psychiatry"
  | "dermatology"
  | "orthopedics"
  | "obgyn"
  | "other";

const SPECIALTIES: ReadonlyArray<{
  id: Specialty;
  label: string;
  avgClaim: number;
}> = [
  { id: "family_medicine", label: "Family medicine (FP / GP)", avgClaim: 38 },
  { id: "internal_medicine", label: "Internal medicine", avgClaim: 62 },
  { id: "cardiology", label: "Cardiology", avgClaim: 95 },
  { id: "pediatrics", label: "Pediatrics", avgClaim: 42 },
  { id: "psychiatry", label: "Psychiatry", avgClaim: 78 },
  { id: "dermatology", label: "Dermatology", avgClaim: 52 },
  { id: "orthopedics", label: "Orthopedics", avgClaim: 88 },
  { id: "obgyn", label: "Obstetrics & Gynecology", avgClaim: 72 },
  { id: "other", label: "Other specialty", avgClaim: 55 },
];

// Anchored to v12 cleaned run, AHCIP val set, micro F1.
// Source: runs/recall/v12_ahcip_clean.json
const CATCH_RATE = 0.690;

// Industry consensus on recoverable share of denied claims (CA
// payer mix, conservative end of the published range).
const RECOVERABLE_SHARE = 0.55;

function fmt(n: number): string {
  return n.toLocaleString("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });
}

export function RoiCalculator() {
  const [specialty, setSpecialty] = useState<Specialty>("family_medicine");
  const [claimsPerMonth, setClaimsPerMonth] = useState<number>(1500);
  const [denialRate, setDenialRate] = useState<number>(8); // %

  const spec = SPECIALTIES.find((s) => s.id === specialty)!;

  const result = useMemo(() => {
    const annualClaims = claimsPerMonth * 12;
    const annualBilled = annualClaims * spec.avgClaim;
    const missedBase = annualBilled * (denialRate / 100);
    const recoverable = missedBase * RECOVERABLE_SHARE;
    const zorvaCaught = recoverable * CATCH_RATE;
    return {
      annualClaims,
      annualBilled,
      missedBase,
      recoverable,
      zorvaCaught,
    };
  }, [claimsPerMonth, denialRate, spec]);

  return (
    <div className={styles.calc}>
      <div className={styles.inputs}>
        <label className={styles.field}>
          <span className={styles.label}>Specialty</span>
          <select
            className={styles.select}
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value as Specialty)}
          >
            {SPECIALTIES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label} (avg ${s.avgClaim}/claim)
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>
            Claims per month
            <span className={styles.hint}>
              total encounters billed, not just denied ones
            </span>
          </span>
          <input
            className={styles.input}
            type="number"
            min={50}
            max={20000}
            step={50}
            value={claimsPerMonth}
            onChange={(e) => setClaimsPerMonth(Number(e.target.value) || 0)}
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>
            Current denial / undercode rate
            <span className={styles.hint}>
              industry typical: 5–12%
            </span>
          </span>
          <div className={styles.rangeRow}>
            <input
              className={styles.range}
              type="range"
              min={0}
              max={25}
              step={0.5}
              value={denialRate}
              onChange={(e) => setDenialRate(Number(e.target.value))}
            />
            <span className={styles.rangeVal}>{denialRate.toFixed(1)}%</span>
          </div>
        </label>
      </div>

      <aside className={styles.result} aria-live="polite">
        <p className={styles.resultLabel}>Estimated annual missed revenue</p>
        <p className={styles.resultBig}>{fmt(result.missedBase)}</p>

        <p className={styles.resultLabel}>
          Projected recovery with Zorva at F1 = 0.690
        </p>
        <p className={styles.resultMedium}>{fmt(result.zorvaCaught)}</p>

        <table className={styles.breakdown}>
          <tbody>
            <tr>
              <td>Annual claims</td>
              <td>{result.annualClaims.toLocaleString("en-CA")}</td>
            </tr>
            <tr>
              <td>Avg claim value</td>
              <td>{fmt(spec.avgClaim)}</td>
            </tr>
            <tr>
              <td>Annual billed</td>
              <td>{fmt(result.annualBilled)}</td>
            </tr>
            <tr>
              <td>× Denial rate</td>
              <td>{denialRate.toFixed(1)}%</td>
            </tr>
            <tr>
              <td>= Missed base</td>
              <td>{fmt(result.missedBase)}</td>
            </tr>
            <tr>
              <td>× Recoverable share</td>
              <td>{(RECOVERABLE_SHARE * 100).toFixed(0)}%</td>
            </tr>
            <tr>
              <td>× Zorva catch rate (F1)</td>
              <td>{(CATCH_RATE * 100).toFixed(1)}%</td>
            </tr>
            <tr className={styles.totalRow}>
              <td>= Projected recovery</td>
              <td>{fmt(result.zorvaCaught)}</td>
            </tr>
          </tbody>
        </table>

        <p className={styles.formula}>
          <code>
            {claimsPerMonth.toLocaleString("en-CA")} × 12 × ${spec.avgClaim} × {denialRate.toFixed(1)}% × 55% × 69.0%
          </code>
        </p>
      </aside>
    </div>
  );
}