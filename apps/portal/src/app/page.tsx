// / — marketing landing page (t_fa2149e1 wiring).
//
// Lightweight, single-column landing: a one-line value prop, the three
// pillars the spec leans on (audit every claim / region-pinned data /
// flat-fee pricing), and a "Talk to sales" CTA that links to the
// /contact form. Server component — no client hooks, no fetch.
//
// The previous incarnation was the `create-next-app` starter
// ("To get started, edit the page.tsx file"), which is fine for a
// greenfield scaffold but is the wrong message to ship to a
// prospective clinic operator. Replacing it with a real landing
// page was a natural side effect of adding the /contact form, so
// the marketing surface has a CTA at every entry point.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./page.module.css";

export const metadata: Metadata = {
  title: "Zorva — AI pre-bill audit for Alberta clinics",
  description:
    "Zorva reads every Alberta claim against AHCIP and the SOMB before submission, surfacing missed codes and underbilled modifiers that drain your monthly revenue. Human-reviewed.",
};

export default function Home() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}>Pre-submit audit for Alberta clinic billing teams</span>
          <h1 className={styles.headline}>
            Find the revenue your billers are leaving on the table.
          </h1>
          <p className={styles.subhead}>
            Zorva reads every Alberta claim against AHCIP and the SOMB
            before it leaves your desk — catching the missed codes,
            underbilled modifiers, and shadow-billed services that
            quietly drain your monthly revenue. Your billing team
            reviews what it finds. Nothing ships until a human signs
            off.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/contact" className={styles.primary}>
              Book a demo
            </Link>
            <Link href="/how-it-works" className={styles.secondary}>
              Calculate your revenue opportunity →
            </Link>
            <Link href="/pricing" className={styles.secondary}>
              See pricing
            </Link>
          </div>
        </header>

        <section
          className={styles.videoWrap}
          aria-label="Product walkthrough — coming soon"
        >
          <div className={styles.videoFrame}>
            <div
              className={styles.videoPlaceholder}
              role="img"
              aria-label="Product walkthrough video coming soon"
            >
              <span className={styles.videoPlaceholderTitle}>
                Product walkthrough coming soon
              </span>
              <span className={styles.videoPlaceholderSub}>
                We&apos;re recording a fresh demo. In the meantime, the
                <Link href="/how-it-works" className={styles.link}>
                  {" "}how-it-works
                </Link>{" "}
                page walks through the same flow.
              </span>
            </div>
          </div>
          <p className={styles.videoCaption}>
            Until the walkthrough is ready, the how-it-works page covers
            the same flow in text — what the auditor reads, what rules it
            pulls, and how the findings surface to your billing team for
            review before anything is submitted.
          </p>
        </section>

        <section className={styles.pillars} aria-label="What the product does">
          <article className={styles.pillar}>
            <h2>Audit every claim, not just the flagged ones</h2>
            <p>
              The auditor reads the clinical narrative, the billed
              codes, and the retrieved rules for every encounter —
              E/M level, NCCI edits, MUE limits, modifier pairs, payer
              policy. Findings cite the exact rule and the exact
              passage in the note.
            </p>
          </article>
          <article className={styles.pillar}>
            <h2>Region-pinned data</h2>
            <p>
              Your data is stored in a single, region-pinned facility
              documented in the executed IMA / BAA. No cross-region
              replication, no sale of customer data, no analytics
              egress. The current HIA / PHIPA / HIPAA posture is
              detailed on the security page.
            </p>
          </article>
          <article className={styles.pillar}>
            <h2>Flat monthly fee, no recovery share</h2>
            <p>
              No percentage of revenue, no per-claim charge, no
              recovery-linked fee. Three tiers bracketed by audit
              volume. AKS safe-harbor-aligned for any US pilots;
              published in the executed IMA for Canadian clinics so
              counsel can sign off without further review.
            </p>
          </article>
        </section>

        <section className={styles.altPath} aria-label="Other ways to learn more">
          <h2>Want the full picture first?</h2>
          <p>
            <Link href="/pricing" className={styles.link}>
              See pricing
            </Link>{" "}
            ·{" "}
            <Link href="/how-it-works" className={styles.link}>
              How it works
            </Link>{" "}
            ·{" "}
            <Link href="/security" className={styles.link}>
              Security and compliance
            </Link>
          </p>
        </section>
      </main>
      <footer className={styles.footer}>
        <div className={styles.footerLinks}>
          <Link href="/pricing">Pricing</Link>
          <span aria-hidden="true">·</span>
          <Link href="/how-it-works">How it works</Link>
          <span aria-hidden="true">·</span>
          <Link href="/security">Security</Link>
          <span aria-hidden="true">·</span>
          <Link href="/legal/privacy">Privacy</Link>
          <span aria-hidden="true">·</span>
          <Link href="/legal/terms">Terms</Link>
        </div>
        <p>Questions? Email us at hello@ashbi.ca</p>
      </footer>
    </div>
  );
}
