// /about — public marketing "about" page.
//
// The team-management page (/team) is gated to authenticated
// portal users — that's a different surface. This page is the
// public, buyer-facing "about" page that explains who Zorva is,
// who builds it, and why it exists. Lives at /about (per
// kanban t_df7045d8) instead of overloading /team, which is
// already taken by the tenant admin surface.
//
// Page sections:
//   1. One-paragraph story (why Zorva exists)
//   2. The team — three placeholder rows for the founders. Names
//      are placeholders so the page is safe to publish before the
//      hiring PR goes out; the real copy lands via a single edit.
//   3. The principles we work by (3-5 short statements)
//   4. CTA rail back to /contact and /pilot
//
// Public route: no auth, no PII collection. The middleware
// allowlist at src/proxy.ts already permits /about.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./about.module.css";

export const metadata: Metadata = {
  title: "About — Zorva",
  description:
    "Why Zorva exists, who builds it, and the principles we work by. " +
    "A pre-bill audit tool for Alberta clinics that reads every claim " +
    "against AHCIP and the SOMB before submission.",
};

type Founder = {
  name: string;
  role: string;
  bio: string;
};

const FOUNDERS: Founder[] = [
  {
    name: "Cameron Ashley",
    role: "Founder, engineering lead",
    bio: "Built pre-bill audit pipelines at two Alberta clinics before " +
      "deciding the work needed a dedicated product. Owns the model " +
      "behaviour, the audit-log hash chain, and the deploy story.",
  },
  {
    name: "Allison Caputo",
    role: "Clinical product",
    bio: "Runs the conversation with the billing teams that shape every " +
      "release. Background in medical-office administration and the " +
      "SOMB review cycle. Owns the per-clinic feedback loop.",
  },
  {
    name: "Hiring",
    role: "Open — clinical informatics lead",
    bio: "If you have shipped a billing-ops or health-information " +
      "management product inside an Alberta clinic and want to be the " +
      "third full-time hire, the /careers page has the email alias.",
  },
];

const PRINCIPLES: string[] = [
  "We only ship what a clinic operator has signed off on — never raw model output.",
  "Region is a contract artefact, not a runtime flag. Pin it at sign-up.",
  "Every privileged action lands in the hash-chain audit log. No exceptions.",
  "Flat-fee pricing, never per-claim. We do better when our customers do.",
  "Open documentation over secrecy. The pricing, the security model, and the pipeline are all public.",
];

export default function AboutPage() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}>About Zorva</span>
          <h1 className={styles.headline}>
            We built the tool we wished we&apos;d had on the billing desk.
          </h1>
          <p className={styles.subhead}>
            Zorva started as an internal pipeline that read Alberta
            claims against AHCIP and the SOMB before they were
            submitted. The clinics that used it kept the revenue they
            would have lost to missed codes, shadow-billed services, and
            underbilled modifiers. We turned it into a product so other
            billing teams could keep theirs.
          </p>
        </header>

        <section aria-labelledby="t-team" className={styles.team}>
          <h2 id="t-team">The team</h2>
          <p className={styles.lede}>
            A small group building a focused product. We hire slowly
            and prefer one strong generalist over two specialists.
          </p>
          <ul className={styles.founderList}>
            {FOUNDERS.map((f) => (
              <li key={f.name} className={styles.founderCard}>
                <div className={styles.founderName}>{f.name}</div>
                <div className={styles.founderRole}>{f.role}</div>
                <p className={styles.founderBio}>{f.bio}</p>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="t-principles" className={styles.principles}>
          <h2 id="t-principles">The principles we work by</h2>
          <ol className={styles.principleList}>
            {PRINCIPLES.map((p, i) => (
              <li key={i} className={styles.principleItem}>
                {p}
              </li>
            ))}
          </ol>
        </section>

        <section aria-label="Next steps" className={styles.cta}>
          <h2>Want the long version?</h2>
          <p>
            <Link href="/contact" className={styles.link}>
              Talk to us
            </Link>{" "}
            about a pilot, or{" "}
            <Link href="/security" className={styles.link}>
              read the controls matrix
            </Link>{" "}
            before the call.
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
          <Link href="/careers">Careers</Link>
        </div>
        <p>Questions? Email us at hello@zorva.ca</p>
      </footer>
    </div>
  );
}