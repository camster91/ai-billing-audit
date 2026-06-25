// /blog — public resources / blog stub.
//
// Scope (per kanban t_7492f223): "Add /blog or /resources stub".
// We use /blog (shorter URL, more conventional) and ship a stub
// that says what the surface will be and where to send pitches.
//
// Why a stub and not a full blog:
//
//   1. The marketing site does not have a CMS or markdown
//      pipeline yet; standing one up is a different workstream
//      (separate kanban boards exist for the publishing pipeline).
//   2. A stub that says "coming soon — pitches to ..." is more
//      honest than a half-built feed with one placeholder post.
//   3. A future PR replaces this page in-place once the
//      publishing pipeline lands. The URL stays /blog.
//
// Public route: no auth. The proxy.ts allowlist (see PR adding
// /blog to PUBLIC_PREFIXES) lets unauthenticated traffic reach
// it.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./blog.module.css";

export const metadata: Metadata = {
  title: "Blog — Zorva",
  description:
    "Writing on Alberta medical billing, AHCIP / SOMB updates, and the " +
    "operational patterns we see in pre-bill audit pipelines. Currently " +
    "in pre-launch — pitches to writing@zorva.ca.",
};

const UPCOMING_TOPICS: string[] = [
  "What 'shadow-billed services' actually means in a family medicine practice",
  "How the SOMB fee navigator maps to a real claim at the billing desk",
  "The five claim-edit patterns that account for ~80% of missed revenue",
  "Why we hash patient identifiers before they touch the audit log",
  "A walkthrough of one real (anonymized) finding end to end",
];

export default function BlogPage() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}>Zorva blog</span>
          <h1 className={styles.headline}>
            Writing on Alberta medical billing, soon.
          </h1>
          <p className={styles.subhead}>
            We&apos;re putting the publishing pipeline in place now. In
            the meantime, this page lists the topics we&apos;ll cover
            first. If you have a perspective worth publishing — a billing
            ops case study, a SOMB change you&apos;ve lived through, or a
            privacy-officer view on AI in healthcare — we&apos;d like to
            hear from you.
          </p>
          <p className={styles.contact}>
            Pitches and ideas:{" "}
            <a href="mailto:writing@zorva.ca" className={styles.link}>
              writing@zorva.ca
            </a>
          </p>
        </header>

        <section aria-labelledby="t-topics" className={styles.topics}>
          <h2 id="t-topics">First posts on the runway</h2>
          <ol className={styles.topicList}>
            {UPCOMING_TOPICS.map((t, i) => (
              <li key={i} className={styles.topicItem}>
                {t}
              </li>
            ))}
          </ol>
        </section>

        <section aria-label="Back to site" className={styles.cta}>
          <p>
            <Link href="/" className={styles.link}>
              ← Back to the marketing home
            </Link>{" "}
            ·{" "}
            <Link href="/changelog" className={styles.link}>
              See the release notes
            </Link>{" "}
            ·{" "}
            <Link href="/security" className={styles.link}>
              Read the controls matrix
            </Link>
          </p>
        </section>
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
        <p>Questions? Email us at hello@zorva.ca</p>
      </footer>
    </div>
  );
}