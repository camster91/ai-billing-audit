// /demo-request — public demo-request landing page.
//
// Scope (per kanban t_c091d2b5): "Add /demo-request page (or wire
// the CTA to /contact)". We do BOTH:
//   - Stand up /demo-request as a thin, demo-specific page (so the
//     URL on the marketing CTAs is meaningful, not a 404)
//   - The form on /demo-request POSTs to the same /api/leads endpoint
//     that /contact uses, so the lead pipeline is one.
//
// Why a separate page and not just /contact?
//
//   - The "Book a demo" CTA on the home page and /how-it-works points
//     at /demo-request. A landing page that says "demo" rather than
//     "contact" sets the right expectation (this is for buyers who
//     have already decided they want a walkthrough, not tire-kickers).
//   - The form is shorter: 3 fields instead of 5. Bypass the
//     "what's your clinic size" question — we ask that on the call.
//
// Public route: no auth. The proxy.ts allowlist (see PR adding
// /demo-request to PUBLIC_PREFIXES) lets unauthenticated traffic
// reach it. Form submission is the existing /api/leads handler —
// no new endpoint needed.

import type { Metadata } from "next";
import Link from "next/link";
import DemoRequestForm from "./DemoRequestForm";
import styles from "./demo-request.module.css";

export const metadata: Metadata = {
  title: "Book a demo — Zorva",
  description:
    "Pick a 20-minute walkthrough with the Zorva team. We'll show you " +
    "exactly which claims Zorva would flag in a sample of your real " +
    "encounters — no slides.",
};

export default function DemoRequestPage() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}>Book a demo</span>
          <h1 className={styles.headline}>
            See Zorva run on a sample of your real claims.
          </h1>
          <p className={styles.subhead}>
            Twenty minutes, no slides. We load a sample of your recent
            encounters and walk through what Zorva would have flagged
            before submission. You leave the call knowing exactly which
            revenue your billing team is leaving on the table this month.
          </p>
        </header>

        <DemoRequestForm />

        <aside className={styles.faq} aria-label="Common questions">
          <h2>What happens after I submit?</h2>
          <ol className={styles.faqList}>
            <li>
              We reply within one business day with a Calendly link to
              pick a 20-minute slot.
            </li>
            <li>
              On the call we share our screen, load your sample
              encounters, and walk through the findings live.
            </li>
            <li>
              If the numbers are interesting and the fit is real, we
              send a short pilot proposal — flat fee, 30/60/90-day
              scope, one clinic.
            </li>
            <li>
              If not, we&apos;ll point you at the resources we have on{" "}
              <Link href="/blog" className={styles.link}>
                the blog
              </Link>{" "}
              and wish you well.
            </li>
          </ol>
        </aside>
      </main>
      <footer className={styles.footer}>
        <div className={styles.footerLinks}>
          <Link href="/">Home</Link>
          <span aria-hidden="true">·</span>
          <Link href="/pricing">Pricing</Link>
          <span aria-hidden="true">·</span>
          <Link href="/security">Security</Link>
          <span aria-hidden="true">·</span>
          <Link href="/contact">Contact</Link>
        </div>
        <p>Questions? Email us at hello@ashbi.ca</p>
      </footer>
    </div>
  );
}