// /how-it-works — public-facing explainer page aimed at clinic administrators.
// Three steps (Upload → Audit → Review & submit) presented as a clear,
// scannable illustration row with small inline icons, plus a closing CTA
// to /pricing. Server component, no client hooks, no fetch.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./how-it-works.module.css";

export const metadata: Metadata = {
  title: "How it works — AI billing audit in 3 steps",
  description:
    "Upload your claims, let Zorva audit every encounter pre-bill, and have your billing team review the findings. Plain-English walkthrough for clinic administrators.",
};

export default function HowItWorksPage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>How it works</span>
        <h1>Three steps. Your claims, checked before they go out.</h1>
        <p>
          We sit alongside your billing system. Every claim is read by
          an AI auditor first; your team reviews what it finds; your
          biller submits. Nothing ships to the payer until a human
          signs off.
        </p>
      </header>

      <main className={styles.main}>
        <section className={styles.steps} aria-label="The three steps">
          <article className={styles.step}>
            <div className={styles.stepHeader}>
              <span className={styles.stepNumber} aria-hidden="true">
                1
              </span>
              <span className={styles.stepIcon} aria-hidden="true">
                <UploadIcon />
              </span>
            </div>
            <h2>Upload your claims and clinical notes</h2>
            <p className={styles.stepDesc}>
              Send 837P files or a CSV straight from your billing system.
              Drag-and-drop in the portal, or schedule a recurring SFTP
              drop — whichever fits your team. Clinical notes come along
              with the claim so the auditor has the full picture.
            </p>
          </article>

          <span className={styles.connector} aria-hidden="true">
            <ConnectorArrow />
          </span>

          <article className={styles.step}>
            <div className={styles.stepHeader}>
              <span className={styles.stepNumber} aria-hidden="true">
                2
              </span>
              <span className={styles.stepIcon} aria-hidden="true">
                <AuditIcon />
              </span>
            </div>
            <h2>Zorva audits each encounter</h2>
            <p className={styles.stepDesc}>
              For every claim, the AI flags what&apos;s wrong — coding
              errors, NCCI conflicts, denial risks — and surfaces what&apos;s
              missing: under-coded visits, unbilled procedures, missed
              premium modifiers. Each finding cites the exact rule and the
              exact passage in the note.
            </p>
          </article>

          <span className={styles.connector} aria-hidden="true">
            <ConnectorArrow />
          </span>

          <article className={styles.step}>
            <div className={styles.stepHeader}>
              <span className={styles.stepNumber} aria-hidden="true">
                3
              </span>
              <span className={styles.stepIcon} aria-hidden="true">
                <ReviewIcon />
              </span>
            </div>
            <h2>Your biller reviews, then submits</h2>
            <p className={styles.stepDesc}>
              Findings show up side-by-side with the claim. Your biller
              accepts the good catches and dismisses the false alarms,
              then submits the corrected claim. Zorva tracks every
              accept / dismiss / modify so the dashboard can show
              whether the auditor is getting better at YOUR patterns
              over time.
            </p>
          </article>
        </section>

        <section className={styles.ctaSection}>
          <h2 className={styles.ctaHeading}>
            See what your team is leaving on the table.
          </h2>
          <p className={styles.ctaSub}>
            Flat monthly pricing. No percentage of revenue. No per-claim
            fees. Start with a 60-day pilot.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/pricing" className={styles.ctaButton}>
              See pricing
            </Link>
            <Link href="/contact" className={styles.ctaSecondary}>
              Book a 15-min walkthrough
            </Link>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        Questions? Email us at hello@ashbi.ca
      </footer>
    </div>
  );
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M12 16V4" strokeLinecap="round" />
      <path d="M7 9l5-5 5 5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 18h14" strokeLinecap="round" />
    </svg>
  );
}

function AuditIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14z" />
      <path d="M16 16l4 4" strokeLinecap="round" />
      <path d="M8 11h6" strokeLinecap="round" />
      <path d="M8 8h4" strokeLinecap="round" />
    </svg>
  );
}

function ReviewIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M4 6h16v12H4z" />
      <path d="M8 10l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 14h8" strokeLinecap="round" />
    </svg>
  );
}

function ConnectorArrow() {
  return (
    <svg viewBox="0 0 24 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <line x1="0" y1="8" x2="20" y2="8" strokeLinecap="round" />
      <polyline points="15,3 20,8 15,13" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
