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
          <span className={styles.eyebrow}>Pre-bill audit for clinic billing teams</span>
          <h1 className={styles.headline}>
            Catch the wrong code before the claim goes out.
          </h1>
          <p className={styles.subhead}>
            An AI auditor reads every claim against your clinical note
            and the active payer rules. Your billing team reviews what
            it finds. Nothing ships until a human signs off.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/contact" className={styles.primary}>
              Talk to sales
            </Link>
            <Link href="/how-it-works" className={styles.secondary}>
              See how it works →
            </Link>
          </div>
        </header>

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
              ca-central-1 for Canadian clinics, us-east-1 for US. No
              cross-region replication, no sale of customer data, no
              analytics egress. HIA, PHIPA, HIPAA, and the Washington My
              Health My Data Act are all addressed in the security
              page.
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
