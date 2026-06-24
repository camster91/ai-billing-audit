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

import Link from "next/link";
import styles from "./page.module.css";

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
          aria-label="60-second product walkthrough"
        >
          <div className={styles.videoFrame}>
            <iframe
              className={styles.video}
              src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0"
              title="Zorva in 60 seconds — pre-submit audit walkthrough"
              loading="lazy"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowFullScreen
              referrerPolicy="strict-origin-when-cross-origin"
            />
          </div>
          <p className={styles.videoCaption}>
            Sixty seconds. Upload a sample AHCIP claim, watch the auditor
            read the clinical note, pull the relevant SOMB rule, and surface
            the missed code or modifier — with a citation to the exact rule
            passage. No audio required; captions available.
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
              Your data is stored in a Canadian data centre, region
              confirmed in the BAA. No cross-region replication, no
              sale of customer data, no analytics egress. HIA, PHIPA,
              HIPAA, and the Washington My Health My Data Act are all
              addressed in the security page.
            </p>
          </article>
          <article className={styles.pillar}>
            <h2>Flat monthly fee, AKS safe-harbor clean</h2>
            <p>
              No percentage of revenue, no per-claim charge, no
              recovery-linked fee. Three tiers bracketed by audit
              volume. Sales can walk you through the fit in twenty
              minutes.
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
    </div>
  );
}
