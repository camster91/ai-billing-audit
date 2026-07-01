// /contact — public marketing-site contact form.
//
// Server component shell that renders the headline + the
// `<ContactForm />` client component. Mirrors the dark blue gradient
// theme used by /pricing, /how-it-works, and /security so the form
// feels native to the marketing surface — not a bolted-on widget.
//
// Public route: the proxy.ts allowlist already includes /api/leads,
// and `/contact` itself is a public page (no auth gate). Anyone can
// hit this URL. Rate-limiting is the upstream reverse-proxy's job.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./contact.module.css";
import ContactForm from "./ContactForm";

export const metadata: Metadata = {
  title: "Contact sales",
  description:
    "Talk to the AI Pre-Bill Audit team. Five fields, no drip campaign — we'll reply within one business day.",
};

export default function ContactPage() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.header}>
          <span className={styles.eyebrow}>Contact sales</span>
          <h1>Talk to us about pre-bill audit for your clinic.</h1>
          <p className={styles.lede}>
            Five fields. We reply within one business day with next steps
            and a link to book a 20-minute walkthrough. No drip campaign,
            no marketing list.
          </p>
        </header>

        <ContactForm />

        <aside className={styles.bookingCta} aria-label="Book a discovery call">
          <h2 className={styles.bookingHeadline}>
            Skip the form — book a 10-minute discovery call
          </h2>
          <p className={styles.bookingBody}>
            Pick a time that works for you and we&apos;ll spend ten minutes on
            your top missed-revenue question. No slides, no demo if you
            don&apos;t want one — just a straight answer about whether Zorva
            would catch the billing gaps you&apos;re seeing this month.
          </p>
          <div className={styles.bookingActions}>
            <a
              href="https://cal.com/zorva/discovery"
              className={styles.bookingButton}
              target="_blank"
              rel="noopener noreferrer"
            >
              Book a 10-minute discovery call
            </a>
            <Link href="/how-it-works" className={styles.bookingSecondary}>
              or read how it works first →
            </Link>
          </div>
          <p className={styles.bookingFootnote}>
            Calendar opens in a new tab (Cal.com). If the link doesn&apos;t
            work, email{" "}
            <a href="mailto:sales@ashbi.ca" className={styles.bookingSecondary}>
              sales@ashbi.ca
            </a>{" "}
            and we&apos;ll send three times that fit your week.
          </p>
        </aside>

        <aside className={styles.altPath}>
          <h2>Not ready to fill out a form?</h2>
          <p>
            Email{" "}
            <a href="mailto:sales@ashbi.ca" className={styles.link}>
              sales@ashbi.ca
            </a>{" "}
            and we&apos;ll respond the same way. Or read the{" "}
            <Link href="/how-it-works" className={styles.link}>
              how-it-works
            </Link>{" "}
            page and the{" "}
            <Link href="/pricing" className={styles.link}>
              pricing
            </Link>{" "}
            page first — most of the questions you have are already
            answered there.
          </p>
        </aside>
      </main>
    </div>
  );
}
