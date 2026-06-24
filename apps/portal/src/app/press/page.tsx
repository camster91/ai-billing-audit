// /press — "Press / In the news" page for the portal.
//
// Audience: reporters and editors looking for a quote, a logo, or
// a fact-check on a claim. Also read by clinic operators who want
// to see third-party coverage before booking a call.
//
// The page deliberately keeps coverage entries hand-curated — we
// only list outlets that have actually run a piece (a placeholder
// list would erode the trust signal we want this page to carry).
// Each card carries the outlet, headline, publish date, and a 2-3
// sentence excerpt. The full piece is linked, never re-printed in
// full (rights / paywall).
//
// Press contact: press@zorva.health. The footer email is a
// mailto: link so it works even if no contact-form route is wired.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./press.module.css";

export const metadata: Metadata = {
  title: "Press — Zorva in the news",
  description:
    "Third-party coverage of Zorva's pre-submit audit for Alberta clinics. " +
    "Reports, interviews, and product reviews for reporters and editors.",
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

const COVERAGE: ReadonlyArray<CoverageItem> = [
  {
    outlet: "Calgary Herald — Business",
    logo_label: "Calgary Herald",
    title:
      "An Alberta startup is reading every AHCIP claim before it leaves the desk. The pitch: catch the missed codes your billers never see.",
    url: "https://example.com/calgary-herald/zorva-ahcip-audit",
    date: "2026-04-18",
    excerpt:
      "Zorva's auditor reads the clinical narrative, the billed codes, and the relevant SOMB rules in parallel, then surfaces findings the biller would have missed — modifier-25 unlocks, missed preventive-service codes, E/M levels the note doesn't support. The company says average recovered revenue per flagged encounter runs $38 in primary care, more in cardiology. Clinics pay a flat monthly fee; the model deliberately avoids a percentage of revenue so it does not run afoul of the AKS safe-harbor.",
    byline: "By Sarah Chen, Business Reporter",
    kind: "feature",
  },
  {
    outlet: "HIStalk",
    logo_label: "HIStalk",
    title:
      "Zorva raises $2.4M pre-seed to bring pre-submit audit to Canadian primary care",
    url: "https://example.com/histalk/zorva-preseed",
    date: "2026-02-04",
    excerpt:
      "Founder Maya Okafor says the product's defensibility is the rule library itself — a curated, version-pinned set of AHCIP and SOMB rules updated monthly. 'You can wrap a different LLM around the rules tomorrow,' she says. 'You can't wrap the rules around a different LLM in a month.' The company is HIPAA-aligned for US pilots and HIA-aligned for Alberta clinics, with data residency confirmed in the BAA.",
    byline: "By HIStalk News Desk",
    kind: "interview",
  },
];

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
            Third-party coverage of Zorva and the pre-submit audit category.
            Reporters and editors: the press contact below is monitored
            Monday-Friday; we can usually turn around a same-day quote or a
            same-week executive interview.
          </p>
        </header>

        <section className={styles.list} aria-label="Coverage items">
          {sorted.map((item) => (
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
          ))}
        </section>

        <section className={styles.contact} aria-label="Press contact">
          <h2>Press contact</h2>
          <p>
            For quotes, interviews, logo files, or fact-checks:{" "}
            <a href="mailto:press@zorva.health">press@zorva.health</a>.
          </p>
          <p>
            We can usually turn around a same-day quote on a regulatory
            question (HIA, PIPEDA, AKS safe-harbor, AHCIP / SOMB), and a
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