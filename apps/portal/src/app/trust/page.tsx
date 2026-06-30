// /trust — public-facing, consumer-grade "how we keep your data safe"
// explainer.
//
// Audience: a clinic billing lead who is not a security expert. They
// have been told to "vet the vendor" by their privacy officer, but
// they don't speak SOC 2 and they don't want to. They want to know:
//
//   1. Where does my data live? (country, type of building)
//   2. Who can see it? (the vendor, sub-processors, the AI)
//   3. What happens at the end of the pilot? (can I get it back, is
//      it actually deleted, or does it linger)
//
// This is intentionally a shorter, plainer sibling of /security.
// /security is for privacy officers and IT leads; /trust is for the
// biller who is doing a one-glance gut check before forwarding the
// link. Cross-link to /security at the bottom for the formal answer.
//
// Server component. No client hooks, no fetch.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./trust.module.css";

export const metadata: Metadata = {
  title: "How we keep your data safe — AI billing audit",
  description:
    "A plain-language answer to the three questions clinic billing leads " +
    "actually ask: where does my data live, who can see it, and what " +
    "happens at the end of the pilot.",
};

const SECTIONS: { id: string; title: string; body: string[]; cta?: string }[] = [
  {
    id: "where",
    title: "Where your data lives",
    body: [
      "Your claims, your clinical notes, and your audit results live in a single region that you choose at sign-up. Canadian clinics go to a Canadian-region facility; US clinics go to a US-region facility. We do not silently copy your data to a second region, and we do not move it after you sign up without writing to you first.",
      "The facility is a real, professionally operated building — not a closet. It provides physical security, redundant power and cooling, and network connectivity at scale. The exact provider, facility, and any third-party attestations they currently hold are written into the executed IMA / BAA your lawyer signs.",
      "Backups live in the same region as the live data. They are encrypted, and only a small number of named operators can read them — and only when there is a written reason on a ticket.",
    ],
  },
  {
    id: "who",
    title: "Who can see your data",
    body: [
      "The Zorva service runs your audits automatically. No human at our company reads your claims or your notes to do the audit. The only time a human sees your data is when you explicitly ask us to look — for example, you file a support ticket and paste in a finding, or you ask us to investigate a billing anomaly. That access is logged and you can ask for the log at any time.",
      "Our sub-processors (the companies that help us run the service — the cloud provider, the email sender, the error tracker) each have a written agreement that says they only use your data to provide the service we asked for. None of them are allowed to use it to train their own models, and none of them sell it.",
      "The AI model itself processes your data to produce a finding, then forgets the input. It does not remember your claims between audits and it does not learn from your data. If you want a model that runs entirely on your own infrastructure, we offer that as a deployment option after the pilot.",
    ],
  },
  {
    id: "end",
    title: "What happens at the end of the pilot",
    body: [
      "At the end of the pilot — whether you continue with us or not — you get a full export of every claim, every finding, every accept/dismiss decision, and every log line we have on file. The export is a standard format (CSV plus JSON), not a proprietary dump, so you can hand it to whoever you pick next.",
      "If you decide not to continue, we delete your data within 30 days. We then send you a one-page deletion certificate that names the date and the systems the data was removed from. If you want it deleted sooner — or if your province has a shorter retention rule — tell us and we will do it on that timeline instead.",
      "We do not keep a \"shadow copy\" of your data for model training, analytics, or any other reason after the contract ends. The deletion certificate is the proof.",
    ],
  },
];

export default function TrustPage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>Trust</span>
        <h1>How we keep your data safe</h1>
        <p>
          The plain-language answer, in three parts. If you are the privacy
          officer or the IT lead, the formal controls matrix is on the
          <Link href="/security" className={styles.inlineLink}>
            {" "}security page
          </Link>.
        </p>
      </header>

      <main className={styles.main} id="main">
        {SECTIONS.map((s, i) => (
          <section
            key={s.id}
            className={styles.card}
            aria-labelledby={`t-${s.id}`}
          >
            <div className={styles.cardHead}>
              <span className={styles.cardNumber}>{i + 1}</span>
              <h2 id={`t-${s.id}`} className={styles.cardTitle}>
                {s.title}
              </h2>
            </div>
            <div className={styles.cardBody}>
              {s.body.map((p, j) => (
                <p key={j}>{p}</p>
              ))}
            </div>
          </section>
        ))}

        <section className={styles.card} aria-labelledby="t-posture">
          <div className={styles.cardHead}>
            <span className={styles.cardNumber}>4</span>
            <h2 id="t-posture" className={styles.cardTitle}>
              What is live today (and what is on the roadmap)
            </h2>
          </div>
          <div className={styles.cardBody}>
            <p>
              <strong>Live today:</strong> TLS 1.3 in transit, AES-256 at
              rest, append-only hash-chain audit trail with a built-in
              verify_chain() walker, per-tenant role-scoped access
              (admin / biller / viewer), two-person approval on exports
              and re-audits, and salted SHA-256 hashing of patient
              identifiers before they reach storage.
            </p>
            <p>
              <strong>On our certification roadmap (not currently held):</strong>{" "}
              SOC 2 Type II, ISO 27001, ISO 27017, and ISO 27018. We will
              publish third-party reports on the{" "}
              <Link href="/security" className={styles.inlineLink}>
                security page
              </Link>{" "}
              as they are issued. Until then, we will not represent any of
              these as a current certification.
            </p>
          </div>
        </section>

        <section className={styles.ctaSection} aria-labelledby="t-cta">
          <h2 id="t-cta">Want the formal version?</h2>
          <p>
            The security page has the full controls matrix — encryption,
            access logs, audit trail, compliance frameworks — written for
            your privacy officer. The trust page (this one) is the
            short-form gut check; the security page is the document you
            forward to legal.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/security" className={styles.ctaButton}>
              Read the security page
            </Link>
            <Link href="/contact" className={styles.ctaSecondary}>
              Ask a question →
            </Link>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerLinks}>
          <Link href="/pricing">Pricing</Link>
          <span aria-hidden="true">·</span>
          <Link href="/how-it-works">How it works</Link>
          <span aria-hidden="true">·</span>
          <Link href="/security">Security</Link>
        </div>
        <p>Questions? Email us at hello@zorva.ca</p>
      </footer>
    </div>
  );
}
