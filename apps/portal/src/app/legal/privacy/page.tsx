// /legal/privacy — Privacy Policy stub.
//
// This is a template scaffold for the Zorva (ai-billing-audit) marketing
// portal. It is NOT legal advice. Cam must have it reviewed by a real
// lawyer (or his privacy officer, for HIA/PHIPA/PIPEDA/HIPAA-aware clinics)
// before signing the BAA / IMA with any pilot clinic.
//
// The route is intentionally short: it tells prospects what data we
// collect, why, how long we keep it, and how to contact us. The full
// text is in `docs/privacy-policy.md` for editorial review.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./privacy.module.css";

export const metadata: Metadata = {
  title: "Privacy Policy — Zorva",
  description:
    "How Zorva (ai-billing-audit) handles patient health information: HIA / PIPEDA / HIPAA-aware data handling for Alberta billing audits.",
};

export default function PrivacyPage() {
  return (
    <main className={styles.page}>
      <article className={styles.article}>
        <header className={styles.header}>
          <p className={styles.eyebrow}>Legal</p>
          <h1>Privacy Policy</h1>
          <p className={styles.meta}>
            Effective: 2026-06-25 · Version: 0.1 (draft, pending legal review)
          </p>
        </header>

        <section>
          <h2>1. What we collect</h2>
          <p>
            Zorva processes the encounter records, claim forms, and SOMB /
            OHIP Schedules you submit. We do not collect patient names
            unless you include them in the uploaded document. All data is
            hashed at the field level (PHN, MRN) before any model call.
          </p>
        </section>

        <section>
          <h2>2. How we use it</h2>
          <p>
            Submitted records are passed through the Zorva rules engine to
            surface coding, modifier, and fee-schedule discrepancies. We
            do not train foundation models on your data. Audit runs are
            retained for the life of your subscription, plus 7 years
            (Alberta HIA default).
          </p>
        </section>

        <section>
          <h2>3. Where it lives</h2>
          <p>
            Data is stored in our Canadian-region Postgres cluster. Audit
            trails are append-only, signed, and exportable as CSV for the
            privacy officer&apos;s annual report. Backups are encrypted
            at rest (AES-256) and in transit (TLS 1.3).
          </p>
        </section>

        <section>
          <h2>4. Sub-processors</h2>
          <p>
            MiniMax (model inference — zero-retention endpoint),
            Hostinger (hosting — Canadian-region facility, documented in
            the executed IMA / BAA before any customer data is
            uploaded), and Resend (transactional email — magic-link
            authentication only, not used for any patient-data
            correspondence). A current list of sub-processors lives at{" "}
            <Link href="/security">/security</Link>.
          </p>
        </section>

        <section>
          <h2>5. Your rights</h2>
          <p>
            Access, correction, and deletion requests go to{" "}
            <a href="mailto:privacy@ashbi.ca">privacy@ashbi.ca</a>. We
            respond within 30 days. For Alberta custodians, this satisfies
            the HIA s.61 individual&apos;s right of access.
          </p>
        </section>

        <section>
          <h2>6. Contact</h2>
          <p>
            Privacy Officer:{" "}
            <a href="mailto:privacy@ashbi.ca">privacy@ashbi.ca</a>.
            <br />
            BAA / HIC-Agent agreement requests:{" "}
            <a href="mailto:legal@ashbi.ca?subject=BAA%20request">
              legal@ashbi.ca
            </a>
            .
          </p>
        </section>

        <p className={styles.disclaimer}>
          <strong>Not legal advice.</strong> This page is a template
          scaffold. The full editorial draft is in{" "}
          <code>docs/privacy-policy.md</code> and must be reviewed by
          counsel before the BAA is signed.
        </p>

        <p className={styles.backLink}>
          <Link href="/">← Back to home</Link>
        </p>
      </article>
    </main>
  );
}
