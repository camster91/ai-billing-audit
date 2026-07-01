// /what-zorva-finds — public marketing social-proof gallery.
//
// Server component (no client hooks, no fetch). A scrollable grid of
// anonymized finding types that the v12 auditor surfaces in real
// claims, each with a dollar impact, a category badge, and a one-
// sentence "why this matters". The point of this page is to show
// prospects what the system *does*, not what it claims.
//
// Lives at /what-zorva-finds (not /findings) because /findings is
// already the authenticated work-queue inbox for clinic users. Two
// very different surfaces; the marketing gallery gets its own URL
// so the home, pricing, and CTAs can link to it without bouncing
// logged-in users to a public page.
//
// All copy is fully anonymized — no real patient or clinic data.
// Dollar amounts are illustrative ranges drawn from the v12 rule
// set, not historical aggregates.
//
// Style tokens mirror the rest of the marketing surface
// (/pricing, /how-it-works, /security) so it feels native.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./what-zorva-finds.module.css";

export const metadata: Metadata = {
  title: "What Zorva finds — real patterns caught by the auditor",
  description:
    "A live, anonymized gallery of finding types the Zorva pre-bill auditor surfaces in real Alberta claims: modifier-25, undercoded E/M, telehealth premiums, denial risks, and more.",
};

type Finding = {
  id: string;
  title: string;
  // Sign drives the chip color. "+" = revenue opportunity (green),
  // "-" = revenue lost / denied (red), "~" = process / documentation
  // gap (amber) or billing error (teal).
  impact: string;
  impactTone: "positive" | "negative" | "neutral";
  category: "Lost Revenue" | "Denial Risk" | "Documentation Gap" | "Billing Error";
  why: string;
  frequency: string;
  icon: React.ReactNode;
};

const FINDINGS: Finding[] = [
  {
    id: "missing-modifier-25",
    title: "Missing modifier-25",
    impact: "−$50 / claim",
    impactTone: "negative",
    category: "Lost Revenue",
    frequency: "Most common miss",
    why: "E/M visits billed on the same day as a procedure need -25 to be paid separately — without it, the visit pays at zero.",
    icon: <IconTag />,
  },
  {
    id: "undercoded-em",
    title: "Undercoded E/M visit",
    impact: "+$30 / claim",
    impactTone: "positive",
    category: "Lost Revenue",
    frequency: "Top revenue opportunity",
    why: "The clinical note supports a higher assessment level than the SOMB code billed — leaving a tier of reimbursement on the table.",
    icon: <IconLevel />,
  },
  {
    id: "missing-procedure",
    title: "Missing procedure (injection, EKG, vaccination)",
    impact: "−$20 to −$45 / claim",
    impactTone: "negative",
    category: "Lost Revenue",
    frequency: "Shadow-billed services",
    why: "A procedure is documented in the note but never made it onto the claim — free work the clinic performed and can't bill for.",
    icon: <IconSyringe />,
  },
  {
    id: "telehealth-premium",
    title: "Missing telehealth premium",
    impact: "+$15 / claim",
    impactTone: "positive",
    category: "Lost Revenue",
    frequency: "Post-pandemic pattern",
    why: "Phone and video visits qualify for a SOMB telehealth premium that billers routinely forget to add on top of the base code.",
    icon: <IconSignal />,
  },
  {
    id: "cmgp-not-billed",
    title: "CMGP not billed",
    impact: "+$25 / claim",
    impactTone: "positive",
    category: "Lost Revenue",
    frequency: "Common in chronic disease",
    why: "Visits with T2DM, HTN, COPD, CHF, or CKD meet the chronic disease management general premium criteria — most claims skip the modifier.",
    icon: <IconChronic />,
  },
  {
    id: "empty-dx",
    title: "Empty diagnosis codes",
    impact: "−$80 / claim (denied)",
    impactTone: "negative",
    category: "Denial Risk",
    frequency: "Most-frequent auto-denial",
    why: "An encounter with no ICD-10-CA on it is auto-denied at the payer — a guaranteed zero-pay claim that never needed to be submitted.",
    icon: <IconAlert />,
  },
  {
    id: "postop-global",
    title: "Post-op E/M in global period",
    impact: "−$60 to −$120 / claim (denied)",
    impactTone: "negative",
    category: "Denial Risk",
    frequency: "Surgical clinics",
    why: "An E/M billed inside a procedure's 90-day global period is bundled into the surgery — billing it triggers a takeback, not extra revenue.",
    icon: <IconClock />,
  },
  {
    id: "referring-npi",
    title: "Referring NPI not populated",
    impact: "−$40 / claim (rejected)",
    impactTone: "negative",
    category: "Billing Error",
    frequency: "Consultations",
    why: "Consultations (03.03A) need the referring provider's practitioner ID — a missing NPI rejects the claim on first submission.",
    icon: <IconNpi />,
  },
];

export default function WhatZorvaFindsPage() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.header}>
          <span className={styles.eyebrow}>What Zorva finds</span>
          <h1>What Zorva finds</h1>
          <p className={styles.subtitle}>
            Real patterns caught by the auditor, anonymized from live claims.
          </p>
        </header>

        <section
          className={styles.gallery}
          aria-label="Anonymized audit findings from live claims"
        >
          {FINDINGS.map((f) => (
            <FindingCard key={f.id} finding={f} />
          ))}
        </section>

        <section className={styles.ctaSection} aria-label="See it on your own claims">
          <h2 className={styles.ctaHeading}>
            These are the patterns we see on the first 100 claims.
          </h2>
          <p className={styles.ctaSub}>
            Upload a sample encounter and we&apos;ll show you which of these
            fire on your own clinic&apos;s data — before you commit to a pilot.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/contact" className={styles.ctaPrimary}>
              Book a 20-min walkthrough
            </Link>
            <Link href="/how-it-works" className={styles.ctaSecondary}>
              How it works
            </Link>
          </div>
        </section>

        <p className={styles.disclaimer}>
          Findings and dollar amounts shown are illustrative examples drawn
          from the v12 auditor rule set. Per-finding impact varies by SOMB
          code, modifier context, and payer — no two clinics see the same
          mix. The numbers on this page are not a guarantee of recovered
          revenue on your own claims.
        </p>
      </main>

      <footer className={styles.footer}>
        Questions? Email us at hello@ashbi.ca
      </footer>
    </div>
  );
}

function cardClassFor(category: Finding["category"]): string {
  switch (category) {
    case "Lost Revenue":
      return styles.cardRevenue;
    case "Denial Risk":
      return styles.cardRisk;
    case "Documentation Gap":
      return styles.cardGap;
    case "Billing Error":
      return styles.cardBilling;
  }
}

function badgeClassFor(category: Finding["category"]): string {
  switch (category) {
    case "Lost Revenue":
      return styles.badgeRevenue;
    case "Denial Risk":
      return styles.badgeRisk;
    case "Documentation Gap":
      return styles.badgeGap;
    case "Billing Error":
      return styles.badgeBilling;
  }
}

function FindingCard({ finding }: { finding: Finding }) {
  const impactClass =
    finding.impactTone === "positive"
      ? styles.impactPositive
      : finding.impactTone === "negative"
        ? styles.impactNegative
        : styles.impactNeutral;

  return (
    <article className={`${styles.card} ${cardClassFor(finding.category)}`}>
      <div className={styles.cardHeader}>
        <div className={styles.iconWrap} aria-hidden="true">
          {finding.icon}
        </div>
        <div className={styles.titleRow}>
          <h3 className={styles.cardTitle}>{finding.title}</h3>
          <span
            className={`${styles.impact} ${impactClass}`}
            aria-label={`Estimated impact: ${finding.impact}`}
          >
            {finding.impact}
          </span>
        </div>
      </div>
      <div className={styles.badgeRow}>
        <span className={`${styles.badge} ${badgeClassFor(finding.category)}`}>
          {finding.category}
        </span>
        <span className={styles.frequency}>{finding.frequency}</span>
      </div>
      <p className={styles.why}>{finding.why}</p>
    </article>
  );
}

/* ------- Inline icons -------
   Hand-rolled SVGs to avoid pulling a full icon library into the
   marketing surface. Kept at a 24x24 viewBox so the 20px card
   size renders crisply. Each icon is a single path or shape with
   stroke=currentColor so the parent .iconWrap color controls the
   hue (green / red / amber / teal by tone). */

function IconTag() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
      <circle cx="7" cy="7" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  );
}

function IconLevel() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 17l5-5 4 4 8-8" />
      <path d="M14 8h6v6" />
    </svg>
  );
}

function IconSyringe() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 2l4 4" />
      <path d="M17 5l-2-2" />
      <path d="M15 7l-9 9v4h4l9-9" />
      <path d="M9 11l4 4" />
    </svg>
  );
}

function IconSignal() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 20h20" />
      <path d="M5 16a4 4 0 0 1 4-4" />
      <path d="M5 16v4" />
      <path d="M9 12v8" />
      <path d="M13 8v12" />
      <path d="M17 4v16" />
    </svg>
  );
}

function IconChronic() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
      <path d="M3.5 12h6l1.5-2 2 4 1.5-2h6" />
    </svg>
  );
}

function IconAlert() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function IconClock() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <polyline points="12 7 12 12 15 14" />
    </svg>
  );
}

function IconNpi() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <line x1="3" y1="10" x2="21" y2="10" />
      <line x1="7" y1="14" x2="11" y2="14" />
      <line x1="7" y1="17" x2="13" y2="17" />
    </svg>
  );
}
