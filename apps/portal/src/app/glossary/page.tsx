// /glossary — billing/claims terms for non-billers.
//
// Audience: clinic administrators, billing leads, and revenue-cycle
// staff who are NOT billing specialists. The definitions are aimed
// at a biller lead who is fluent in healthcare operations but not
// fluent in the SOMB and the auditor's vocabulary.
//
// Six terms, one paragraph each. Plain English. No unexplained
// jargon. Static — no client hooks, no fetch.
//
// Server component. Matches the dark blue gradient theme of
// /security, /case-studies, /pricing, /how-it-works, /contact.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./glossary.module.css";

export const metadata: Metadata = {
  title: "Glossary — billing terms for non-billers",
  description:
    "Plain-English definitions of the billing and claims terms that show up across the Zorva dashboard: AHCIP, SOMB, F1, P/R, modifier-25, telehealth premium.",
};

interface Term {
  name: string;
  body: string;
}

const TERMS: Term[] = [
  {
    name: "AHCIP",
    body:
      "Alberta Health Care Insurance Plan — the public-payer system that reimburses physician services for Alberta residents. If your clinic is in Alberta, the bulk of your claim volume is AHCIP. Zorva's v12 auditor is tuned for AHCIP rules first; US payer rules are a separate, later scoring layer.",
  },
  {
    name: "SOMB",
    body:
      "Schedule of Medical Benefits — the fee schedule that lists every billable service code AHCIP will pay for, along with the dollar amount attached to each. When Zorva reports a 'revenue opportunity' for an encounter, the dollar figure is computed from the SOMB fee for the suggested service code.",
  },
  {
    name: "F1",
    body:
      "A single-number score of an auditor's accuracy. It's the harmonic mean of precision (of all the findings the auditor flagged, how many were real?) and recall (of all the real findings in the validation set, how many did the auditor catch?). F1 = 1.0 is perfect; F1 = 0.0 means the auditor found nothing real. Zorva's v12 auditor currently sits at F1 = 0.690 on the cleaned AHCIP validation set, which translates to 'catches 6 to 7 of every 10 real billing errors before submission.' See /technical for the full formula.",
  },
  {
    name: "P/R",
    body:
      "The professional / technical split on a diagnostic-imaging or facility claim. Some AHCIP service codes can be billed as two separate lines: the professional component (the physician reading the image) and the technical component (the equipment and the facility running the test). When Zorva flags a P/R mismatch, it usually means the biller submitted only one of the two lines and missed the other.",
  },
  {
    name: "modifier-25",
    body:
      "A two-digit modifier (-25) you append to an E/M visit code to tell the payer 'this evaluation was a separately identifiable service from the procedure I billed on the same day, do not bundle it.' Without modifier-25, a same-day E/M + procedure (for example, an office visit plus an ECG) gets bundled into the procedure and the E/M line pays zero. Zorva flags modifier-25 gaps as HIGH severity because they cause predictable denials.",
  },
  {
    name: "telehealth premium",
    body:
      "An extra fee the payer adds when a visit is delivered by video or phone instead of in person, to compensate the physician for the different workflow and patient-acuity mix. Alberta's SOMB lists a small telehealth premium that has to be billed with the right indicator code on the claim. Zorva flags a telehealth visit that was billed at the in-person rate (or without the telehealth indicator) as a MEDIUM-severity missed-revenue finding.",
  },
];

export default function GlossaryPage() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.header}>
          <span className={styles.eyebrow}>Glossary</span>
          <h1>Billing terms, in plain English.</h1>
          <p className={styles.lede}>
            The dashboard and the audit reports use a few acronyms and
            modifier codes that aren&apos;t part of everyday clinic
            vocabulary. This page is the short list — enough to read a
            Zorva finding without a billing dictionary open in another
            tab. If you want the deeper technical version, the{" "}
            <Link href="/technical">/technical</Link> page explains how
            the auditor arrives at the numbers.
          </p>
        </header>

        <section className={styles.glossary} aria-label="Glossary terms">
          {TERMS.map((t) => (
            <article key={t.name} className={styles.term}>
              <h2>{t.name}</h2>
              <p>{t.body}</p>
            </article>
          ))}
        </section>

        <p className={styles.footer}>
          Missing a term? Email{" "}
          <a href="mailto:hello@zorva.ca">hello@zorva.ca</a> and we&apos;ll
          add it. For the F1 formula and the audit_trail hash chain
          schema, see <Link href="/technical">/technical</Link>.
        </p>
      </main>
    </div>
  );
}