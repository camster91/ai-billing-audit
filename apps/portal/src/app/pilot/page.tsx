"use client";

// /pilot — 30/60/90-day pilot program page.
//
// Audience: clinic administrators and billing leads evaluating Zorva
// for a paid rollout. The page lays out, in three clearly labeled
// phase sections, what the clinic is expected to do and what Zorva is
// expected to deliver during the pilot.
//
// Client component per the task spec. No hooks are needed today, but
// future phases may add interactive elements (collapsible phase
// details, dynamic progress indicator). The component is rendered
// from a single page so a future editor only needs to update one file.

import Link from "next/link";
import styles from "./pilot.module.css";

type Phase = {
  id: string;
  number: string;
  title: string;
  lead: string;
  clinic: string[];
  zorva: string[];
};

const PHASES: Phase[] = [
  {
    id: "days-1-30",
    number: "Days 1–30",
    title: "Set up, import history, and measure your baseline",
    lead:
      "The first month is about getting clean data in and agreeing on a " +
      "starting line. By the end of day 30 you should know exactly what " +
      "Zorva sees when it looks at your last 60 days of claims.",
    clinic: [
      "Sign the affiliate agreement (HIA) or BAA (HIPAA) and complete onboarding.",
      "Provide 1–2 months of historical claim data plus the matching clinical notes.",
      "Pick a small pilot set: a single provider, location, or payer mix.",
    ],
    zorva: [
      "Stand up the tenant in your region (CA or US) and run the historical import.",
      "Compute the baseline F1 score against the historical import — your " +
        "starting number for measuring lift.",
      "Deliver a written baseline report to your billing lead.",
    ],
  },
  {
    id: "days-31-60",
    number: "Days 31–60",
    title: "Live audits, daily digests, and weekly reviews",
    lead:
      "The middle month is the actual pilot. Zorva audits every new " +
      "claim before it goes out, your biller reviews the findings, and " +
      "we meet every week to look at what the system caught and missed.",
    clinic: [
      "Route new claims through Zorva (CSV upload, SFTP, or portal).",
      "Review findings in the daily digest and accept / modify / dismiss each one.",
      "Join a 30-minute weekly review with your Zorva contact.",
    ],
    zorva: [
      "Run live audits on every new claim and surface findings in the portal.",
      "Send a daily digest email summarising catches and dollar impact.",
      "Run the weekly review with a written summary of catches, dismissals, " +
        "and calibration notes.",
    ],
  },
  {
    id: "days-61-90",
    number: "Days 61–90",
    title: "Measure ROI and decide whether to scale",
    lead:
      "The last month is the decision window. We measure the lift " +
      "against the day-30 baseline, write up the ROI, and you decide " +
      "whether to roll Zorva out to the rest of the practice.",
    clinic: [
      "Continue the live-audit workflow from days 31–60.",
      "Validate the ROI report against your own numbers and sign off.",
      "Decide: scale to more providers, extend the pilot, or stop.",
    ],
    zorva: [
      "Produce a final ROI report: dollars recovered, time saved, and " +
        "denials avoided against the day-30 baseline.",
      "Document any calibration work done during the pilot and lock the model.",
      "If you scale: hand off a rollout plan covering onboarding the " +
        "remaining providers and integrating with your billing system.",
    ],
  },
];

export default function PilotPage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>Pilot program</span>
        <h1>30 / 60 / 90-day pilot</h1>
        <p>
          A 90-day pilot with a written baseline on day 30, a weekly review
          during the middle month, and a measured ROI on day 90. Here is
          what we expect from you and what you can expect from us.
        </p>
      </header>

      <main className={styles.main} id="main">
        <section className={styles.phases} aria-label="Pilot phases">
          {PHASES.map((phase) => (
            <article
              key={phase.id}
              id={phase.id}
              className={styles.phase}
              aria-labelledby={`${phase.id}-title`}
            >
              <header className={styles.phaseHeader}>
                <span className={styles.phaseNumber} aria-hidden="true">
                  {phase.number}
                </span>
                <h2 id={`${phase.id}-title`}>{phase.title}</h2>
              </header>
              <p className={styles.phaseLead}>{phase.lead}</p>
              <div className={styles.phaseColumns}>
                <div className={styles.column}>
                  <h3>What we expect from the clinic</h3>
                  <ul>
                    {phase.clinic.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div className={styles.column}>
                  <h3>What you can expect from Zorva</h3>
                  <ul>
                    {phase.zorva.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </article>
          ))}
        </section>

        <section className={styles.ctaSection} aria-labelledby="pilot-cta">
          <h2 id="pilot-cta">Ready to start the 90-day pilot?</h2>
          <p className={styles.ctaSub}>
            Flat monthly pricing during the pilot. No percentage of revenue,
            no per-claim fees.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/contact" className={styles.ctaButton}>
              Start a pilot
            </Link>
            <Link href="/pricing" className={styles.ctaSecondary}>
              See pricing
            </Link>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerLinks}>
          <Link href="/how-it-works">How it works</Link>
          <span aria-hidden="true">·</span>
          <Link href="/pricing">Pricing</Link>
          <span aria-hidden="true">·</span>
          <Link href="/security">Security</Link>
        </div>
        <p>Questions? Email us at hello@ai-billing-audit.ashbi.ca</p>
      </footer>
    </div>
  );
}
