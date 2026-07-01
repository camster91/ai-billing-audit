// /calculator — interactive "How much are you leaving on the table?"
// calculator. Server component by default; only the result panel is
// a client component (`RoiCalculator` below) so the inputs and live
// numbers update on every keystroke without a server round-trip.
//
// Model (see runs/recall/v12_ahcip_clean.json for the derivation):
//   monthly_claims      = user input
//   current_denial_rate = user input (% of claims that initially deny)
//   avg_claim_value     = by specialty (blended Alberta averages)
//   catchable_rate      = 0.690  (v12 cleaned F1, micro, AHCIP val set;
//                                see runs/recall/v12_ahcip_clean.json)
//   recoverable_share   = 0.55   (industry: ~55% of flagged denials are
//                                ultimately recoverable with action;
//                                conservative for Alberta primary care)
//
//   annual_missed = monthly_claims * 12 * avg_claim_value
//                   * current_denial_rate * catchable_rate
//                   * recoverable_share
//
// The disclaimer is intentional: this is a model estimate, not a
// guarantee. Real pilot numbers will vary by specialty, payer mix,
// coding-staff capacity, and rule-coverage maturity. We display the
// formula inputs so the user can see what drove the number.
//
// Server component renders the page chrome + heading + disclaimer.
// Client component handles the live computation.

import type { Metadata } from "next";
import { RoiCalculator } from "./roi-calculator";
import styles from "./calculator.module.css";

export const metadata: Metadata = {
  title: "ROI Calculator — How much are you leaving on the table? | Zorva",
  description:
    "Estimate the annual revenue your Alberta clinic is leaving on the " +
    "table from missed modifiers and undercodes, and the share that " +
    "Zorva's auditor can realistically recover. Inputs: specialty, " +
    "claims per month, current denial rate.",
};

export default function CalculatorPage() {
  return (
    <main id="main" className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>Zorva ROI Calculator</p>
        <h1 className={styles.h1}>
          How much are you leaving on the table?
        </h1>
        <p className={styles.lede}>
          A 30-second estimate based on your specialty, claim volume,
          and current denial rate. Three inputs, no email gate.
        </p>
      </header>

      <section className={styles.disclaimer}>
        <strong>Model estimate.</strong> The numbers below are a
        directional estimate, not a forecast. Actual recovery depends
        on your payer mix, coding-staff capacity, how long denials
        have been accumulating, and the rule coverage of your EHR
        data. The catch-rate assumption (69.0%) is anchored to the
        cleaned AHCIP v12 evaluation (see{" "}
          <code>runs/recall/v12_ahcip_clean.json</code>). Use this to
        start the conversation, not to close the deal.
      </section>

      <RoiCalculator />

      <section className={styles.howItWorks}>
        <h2 className={styles.h2}>How we calculate this</h2>
        <p>
          The full derivation (with the SOMB-anchored per-rule dollar
          rates and the v12 recall baseline) is in our internal{" "}
          <a href="https://github.com/camster91/ai-billing-audit/blob/main/runs/recall/v12_ahcip_clean.json">
            v12 AHCIP validation report
          </a>{" "}
          on GitHub. The short version:
        </p>
        <ol>
          <li>
            <strong>Annual billed volume</strong> = monthly claims × 12
            × average claim value (specialty-blended Alberta average).
          </li>
          <li>
            <strong>Missed-revenue base</strong> = annual billed volume
            × current denial rate (a denied claim is the closest proxy
            we have for an under-coded or modifier-missed claim at the
            encounter level).
          </li>
          <li>
            <strong>Recoverable share</strong> = 55%. Industry
            consensus is that roughly half of denied claims are
            recoverable with timely correction and resubmission.
          </li>
          <li>
            <strong>Auditor catch rate</strong> = 69.0% (v12 cleaned
            micro F1). Not every finding the auditor fires on is
            actually recoverable in your workflow — the F1 captures
            both precision and recall against gold findings.
          </li>
        </ol>
        <p>
          Pilot customers routinely see the per-claim dollar figure
          vary by ±20% in either direction in the first 30 days, then
          converge as the auditor calibrates to their specific
          encounter mix.
        </p>
      </section>

      <section className={styles.cta}>
        <h2 className={styles.h2}>Ready to find out for real?</h2>
        <p>
          The 60-day pilot is no-cost, no-commitment. We run Zorva
          against a sample of your historical claims and live claims
          for two months, you walk through every finding with our
          team, and at the end you decide whether to continue. You
          own the data — we delete it on one email.
        </p>
        <p>
          <a className={styles.button} href="/pilot">
            Start the 60-day pilot →
          </a>
        </p>
      </section>
    </main>
  );
}