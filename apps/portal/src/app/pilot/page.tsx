// /pilot — 60-day no-cost pilot program page.
//
// Audience: clinic administrators and billing leads evaluating Zorva
// for a paid rollout. The page lays out, in two clearly labeled
// phase sections, what the clinic is expected to do and what Zorva is
// expected to deliver during the pilot.
//
// Server component. The page contains no client-side state today; if a
// future phase needs interactivity (collapsible phase details, dynamic
// progress indicator), split the interactive part into a small
// `"use client"` subcomponent rather than converting the whole page.
//
// P11 reality-check fix (2026-06-30): the previous version of this page
// claimed a "30/60/90 day pilot" but the program is actually a 60-day
// no-cost pilot (the df9bf0f reality-check commit established this).
// The 90-day framing was leftover marketing copy from before the
// pilot was scoped down. Other inconsistencies fixed:
//   - Removed the "daily digest email" promise — Zorva surfaces
//     findings in the portal, not by auto-email. The portal has a
//     weekly digest opt-in instead.
//   - Title metadata aligned to "60-day" (matches the body).
//   - Hero says "60 days" (matches /pricing, /faq, /contact, /legal).
//   - "Pilot ends day 90" replaced with "Pilot ends day 60, then
//     decide: scale, extend, or walk away."

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./pilot.module.css";

export const metadata: Metadata = {
  title: "Pilot program — 60-day no-cost rollout for Alberta clinics",
  description:
    "The Zorva 60-day no-cost pilot for Alberta clinics: import historical claims, baseline missed revenue, then roll into full coverage. Human-reviewed throughout, no revenue share.",
};

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
      "Sign the IMA (HIA) or BAA (HIPAA) and complete onboarding.",
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
    title: "Live audits, weekly reviews, and the decision call",
    lead:
      "The second month is the actual pilot. Zorva audits every new " +
      "claim before it goes out, your biller reviews the findings in " +
      "the portal, and we meet every week to look at what the system " +
      "caught and missed. The pilot ends on day 60 with a decision " +
      "call: scale to a paid tier, extend, or walk away.",
    clinic: [
      "Route new claims through Zorva (CSV upload, SFTP, or portal).",
      "Review findings in the portal — accept, modify, or dismiss each one.",
      "Join a 30-minute weekly review with your Zorva contact.",
      "On or before day 60, decide: scale, extend, or walk away.",
    ],
    zorva: [
      "Run live audits on every new claim and surface findings in the portal.",
      "Run the weekly review with a written summary of catches, dismissals, " +
        "and calibration notes.",
      "On day 60, deliver a final ROI report: dollars recovered, time saved, " +
        "and denials avoided against the day-30 baseline.",
      "Document any calibration work done during the pilot and lock the model.",
    ],
  },
];

export default function PilotPage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>Pilot program</span>
        <h1>60-day no-cost pilot</h1>
        <p>
          A two-month pilot with a written baseline on day 30, a weekly
          review during the second month, and a measured ROI on day 60.
          No-cost, no-commitment, no auto-conversion to a paid tier.
          Here is what we expect from you and what you can expect from
          us.
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
          <h2 id="pilot-cta">Ready to start the 60-day pilot?</h2>
          <p className={styles.ctaSub}>
            Flat monthly pricing during the pilot. No percentage of revenue,
            no per-claim fees. If you walk away at day 60, we delete your
            data within 30 days and send you a deletion certificate.
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
        <p>Questions? Email us at hello@ashbi.ca</p>
      </footer>
    </div>
  );
}
