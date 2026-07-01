// /press — "Press / In the news" page for the portal.
//
// Audience: reporters and editors looking for a quote, a logo, or
// a fact-check on a claim. Also read by clinic operators who want
// to see third-party coverage before booking a call.
//
// P11 reality-check fix (2026-06-30): the previous version of this
// page listed two fabricated coverage items — including a fictional
// founder name (Maya Okafor) attached to a quoted round in a
// non-existent HIStalk article. Cameron has not actually appeared in
// HIStalk, the Calgary Herald, or any other outlet as of this write,
// so listing those as "coverage" was an integrity violation.
//
// The page is now honest: it has the press contact and a short
// "no coverage yet" note rather than fake entries. When actual
// coverage lands, swap the empty `COVERAGE` array for real
// {outlet, title, url, date, excerpt, byline, kind} entries — each
// tied to a real URL on a real outlet's domain, never example.com.
//
// Press contact: press@ashbi.ca. The footer email is a
// mailto: link so it works even if no contact-form route is wired.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./press.module.css";

export const metadata: Metadata = {
  title: "Press — Zorva in the news",
  description:
    "Press contact for Zorva (ai-billing-audit): quotes, interviews, " +
    "and fact-checks on Alberta pre-bill audit, AHCIP / SOMB, and " +
    "HIA / PIPEDA-aware data handling. Coverage list is empty until " +
    "real third-party pieces land.",
};

interface CoverageItem {
  outlet: string;
  logo_label: string;
  title: string;
  url: string;
  date: string;
  excerpt: string;
  // Reporter byline if available. Empty string = anonymous.
  byline: string;
  // "feature" = full product profile; "mention" = quoted in a
  // larger roundup; "interview" = founder/CEO quote.
  kind: "feature" | "interview" | "mention";
}

const COVERAGE: ReadonlyArray<CoverageItem> = [];

function kindLabel(k: CoverageItem["kind"]): string {
  switch (k) {
    case "feature":
      return "Feature";
    case "interview":
      return "Interview";
    case "mention":
      return "Mention";
  }
}

export default function PressPage() {
  // Newest first.
  const sorted = [...COVERAGE].sort((a, b) => (a.date < b.date ? 1 : -1));

  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}>Press</span>
          <h1 className={styles.headline}>Zorva in the news.</h1>
          <p className={styles.subhead}>
            Reporters and editors: the press contact below is monitored
            Monday-Friday; we can usually turn around a same-day quote
            or a same-week executive interview.
          </p>
        </header>

        <section className={styles.list} aria-label="Coverage items">
          {sorted.length === 0 ? (
            <article className={styles.card}>
              <h2 className={styles.title}>No third-party coverage yet.</h2>
              <p className={styles.excerpt}>
                Zorva has not been independently profiled, interviewed, or
                quoted in a published piece as of this write. We will
                populate this page with real coverage entries (each tied
                to a real URL on a real outlet&rsquo;s domain) as they
                land. If you&rsquo;re working on a piece, the press
                contact below is the fastest way to reach us.
              </p>
            </article>
          ) : (
            sorted.map((item) => (
              <article key={item.url} className={styles.card}>
                <header className={styles.cardHeader}>
                  <span className={styles.outletLogo} aria-hidden="true">
                    {item.logo_label}
                  </span>
                  <span className={styles.kind}>{kindLabel(item.kind)}</span>
                  <time className={styles.date} dateTime={item.date}>
                    {item.date}
                  </time>
                </header>
                <h2 className={styles.title}>
                  <a href={item.url} rel="noopener noreferrer" target="_blank">
                    {item.title}
                  </a>
                </h2>
                <p className={styles.excerpt}>{item.excerpt}</p>
                <footer className={styles.cardFooter}>
                  <span className={styles.outlet}>{item.outlet}</span>
                  {item.byline ? (
                    <span className={styles.byline}>{item.byline}</span>
                  ) : null}
                  <a
                    href={item.url}
                    rel="noopener noreferrer"
                    target="_blank"
                    className={styles.read}
                  >
                    Read the full piece →
                  </a>
                </footer>
              </article>
            ))
          )}
        </section>

        <section className={styles.contact} aria-label="Press contact">
          <h2>Press contact</h2>
          <p>
            For quotes, interviews, logo files, or fact-checks:{" "}
            <a href="mailto:press@ashbi.ca">press@ashbi.ca</a>.
          </p>
          <p>
            We can usually turn around a same-day quote on a regulatory
            question (HIA, PIPEDA, AHCIP / SOMB), and a
            same-week executive interview. For embargoed pieces, please
            email the request and we will set up a secure channel.
          </p>
          <p className={styles.backLink}>
            <Link href="/">← Back to home</Link>
          </p>
        </section>
      </main>
    </div>
  );
}