// /changelog — public release notes for audit-rule updates and
// security / compliance changes.
//
// Audience: clinic privacy officers, IT leads, and billing admins
// who need to know when audit rules ship, when a rule's behaviour
// changes, and when the security posture changes (e.g. a new
// framework attestation, a sub-processor change, a region move).
// These readers often subscribe via RSS or "watch this page" so
// we render entries newest-first and pin a stable RSS link at the
// top.
//
// Entries are intentionally hand-curated rather than auto-generated
// from git tags — release notes should be readable to a clinic
// admin who has never seen a git log, not to a developer. The
// `audience` and `action` fields make it clear who in a clinic
// needs to do what when a rule change ships.
//
// Server component. No client hooks, no fetch. The page is static
// at build time; entries are appended by hand as part of the
// release checklist (see docs/RELEASE_CHECKLIST.md).

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./changelog.module.css";

export const metadata: Metadata = {
  title: "Changelog — audit rule & security updates",
  description:
    "Release notes for Zorva audit-rule updates and security / compliance changes. " +
    "Subscribed to by clinic privacy officers and billing admins to know when a rule ships.",
};

type Audience = "billers" | "privacy" | "it" | "all";

type Category = "rule" | "security" | "compliance" | "platform";

interface Entry {
  // ISO date (YYYY-MM-DD) for stable sorting and RSS-friendly URLs.
  date: string;
  // Short version label, e.g. "2026.06.A" — bumped per release.
  version: string;
  category: Category;
  title: string;
  // One-line TL;DR visible in the summary block.
  summary: string;
  // 1-3 sentence plain-English description. Avoid jargon.
  body: string;
  // Who in the clinic should read this. "all" = everyone with a
  // dashboard login.
  audience: Audience;
  // What the reader should do, if anything. Empty string = no
  // action required (informational).
  action: string;
  // Severity hint for the rule body itself (HIGH/MED/LOW/INFO).
  // Security / compliance entries leave this undefined.
  severity?: "HIGH" | "MED" | "LOW" | "INFO" | "n/a";
  // Optional stable URL (e.g. to the rule reference doc).
  href?: string;
}

const ENTRIES: ReadonlyArray<Entry> = [
  {
    date: "2026-06-22",
    version: "2026.06.A",
    category: "rule",
    title: "New rule: missing-procedure (service documented, never billed)",
    summary:
      "Auditor now flags encounters where the note documents a service " +
      "(injection, EKG, lab order, vaccination) but no SOMB code was billed.",
    body:
      "This is the single biggest source of lost revenue for primary-care " +
      "clinics. The rule fires only when the clinical narrative clearly " +
      "supports a separately billable service that the claim omits — it does " +
      "not flag services that are bundled into the E/M. Suggested action: add " +
      "the missing SOMB code before submission.",
    audience: "billers",
    action:
      "Review flagged encounters in the Findings tab; add the suggested code and resubmit.",
    severity: "HIGH",
    href: "/what-zorva-finds",
  },
  {
    date: "2026-06-15",
    version: "2026.06.A",
    category: "rule",
    title: "Modifier-25 unlock rule promoted from MED to HIGH severity",
    summary:
      "E/M billed same-day as a procedure without modifier -25 now fires HIGH, not MED.",
    body:
      "Without -25, payers bundle the E/M into the procedure and pay only the " +
      "procedure. This is a $40-$80 per missed -25. The rule now also includes " +
      "an explicit 'separately evaluable problem' check so it does not fire on " +
      "routine pre-procedure assessments.",
    audience: "billers",
    action:
      "Re-check last 30 days of E/M + procedure same-day pairs; add -25 where indicated.",
    severity: "HIGH",
  },
  {
    date: "2026-06-08",
    version: "2026.06.A",
    category: "security",
    title: "Quarterly sub-processor review completed",
    summary:
      "Updated sub-processor list published; no new vendors added this quarter.",
    body:
      "Per our HIA-aligned vendor review, the only active sub-processor this " +
      "quarter is the Canadian-region Postgres provider. The US-region " +
      "Postgres provider was retired 2026-05-30. The full sub-processor list " +
      "and the data-flow diagram are linked from the security page.",
    audience: "privacy",
    action:
      "No action required. Update your internal Records of Processing if you " +
      "mirror the Zorva sub-processor list.",
    severity: "n/a",
  },
  {
    date: "2026-05-30",
    version: "2026.05.C",
    category: "compliance",
    title: "Certification roadmap update (FY2026)",
    summary:
      "SOC 2 Type II and ISO 27001 are on the certification roadmap; neither is held today. We are publishing this honestly while preparation is in progress.",
    body:
      "We have updated /security and /trust so the marketing site no longer claims SOC 2 Type II or ISO 27001 as held certifications. " +
      "Both are on our certification roadmap with a target observation window in the next reporting cycle. The data centre provider's own attestations (where they exist) " +
      "remain documented in the executed BAA / affiliate agreement. Until a third-party report is issued, we will not represent either framework as a current certification.",
    audience: "privacy",
    action:
      "Privacy officers: the security page now lists current posture separately from certifications on the roadmap. Ask your account contact for a copy of any third-party reports we do hold (e.g., the hosting provider's attestations).",
    severity: "n/a",
    href: "/security",
  },
  {
    date: "2026-05-12",
    version: "2026.05.B",
    category: "platform",
    title: "Findings tab now paginates at 50 per page with a 'jump to rule' filter",
    summary:
      "Quality-of-life update for clinics with >1,000 findings per month.",
    body:
      "The Findings tab now defaults to 50 per page (was 20), and a new " +
      "rule-id filter input lets a billing lead jump straight to one rule's " +
      "open findings. CSV export still produces the full set; only the " +
      "in-browser list is paginated.",
    audience: "all",
    action: "No action required.",
    severity: "INFO",
  },
];

function formatCategory(c: Category): string {
  switch (c) {
    case "rule":
      return "Audit rule";
    case "security":
      return "Security";
    case "compliance":
      return "Compliance";
    case "platform":
      return "Platform";
  }
}

function audienceLabel(a: Audience): string {
  switch (a) {
    case "billers":
      return "Billing leads";
    case "privacy":
      return "Privacy officers";
    case "it":
      return "IT leads";
    case "all":
      return "All clinic admins";
  }
}

export default function ChangelogPage() {
  // Newest first — entries are hand-appended in order so we sort on
  // the date string (ISO so lexical == chronological).
  const sorted = [...ENTRIES].sort((a, b) => (a.date < b.date ? 1 : -1));

  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}>Changelog</span>
          <h1 className={styles.headline}>
            Audit-rule and security updates.
          </h1>
          <p className={styles.subhead}>
            Every change to the Zorva auditor and every material change to
            the security / compliance posture is recorded here. Privacy
            officers and billing admins can subscribe via RSS to know when
            a rule ships or when a vendor is added to the sub-processor
            list.
          </p>
          <div className={styles.ctaRow}>
            <a href="/changelog.xml" className={styles.primary}>
              Subscribe via RSS
            </a>
            <Link href="/security" className={styles.secondary}>
              View security page →
            </Link>
            <Link href="/trust" className={styles.secondary}>
              Trust Center →
            </Link>
          </div>
        </header>

        <section className={styles.feed} aria-label="Recent changelog entries">
          {sorted.map((e) => (
            <article key={`${e.date}-${e.version}-${e.title}`} className={styles.entry}>
              <header className={styles.entryHeader}>
                <time className={styles.date} dateTime={e.date}>
                  {e.date}
                </time>
                <span className={`${styles.cat} ${styles[`cat_${e.category}`] ?? ""}`}>
                  {formatCategory(e.category)}
                </span>
                <span className={styles.version}>v{e.version}</span>
                {e.severity ? (
                  <span className={`${styles.sev} ${styles[`sev_${e.severity}`] ?? ""}`}>
                    {e.severity}
                  </span>
                ) : null}
              </header>
              <h2 className={styles.entryTitle}>{e.title}</h2>
              <p className={styles.summary}>{e.summary}</p>
              <p className={styles.body}>{e.body}</p>
              <footer className={styles.entryFooter}>
                <span className={styles.audience}>
                  Audience: <strong>{audienceLabel(e.audience)}</strong>
                </span>
                {e.action ? (
                  <span className={styles.action}>
                    Action: <strong>{e.action}</strong>
                  </span>
                ) : (
                  <span className={styles.action}>No action required.</span>
                )}
                {e.href ? (
                  <Link href={e.href} className={styles.more}>
                    Read more →
                  </Link>
                ) : null}
              </footer>
            </article>
          ))}
        </section>

        <section className={styles.subscribe} aria-label="Subscribe to updates">
          <h2>Subscribe</h2>
          <p>
            The cleanest way to follow this page is RSS — most clinic
            governance tools (OneTrust, Collibra, internal wikis) accept an
            RSS feed directly. The feed is{" "}
            <a href="/changelog.xml">/changelog.xml</a> and updates within an
            hour of every entry being published here.
          </p>
          <p>
            For monthly digest emails instead, ask your account manager to
            add the privacy-officer mailing list to your tenant. The list is
            region-scoped — Alberta clinics receive AHCIP-relevant entries
            only.
          </p>
        </section>
      </main>
    </div>
  );
}