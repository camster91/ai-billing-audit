// /legal/terms — Terms of Service stub.
//
// Template scaffold for the Zorva (ai-billing-audit) marketing portal.
// Not legal advice. Cam must have it reviewed by a real lawyer before
// signing the BAA with any pilot clinic.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "../privacy/privacy.module.css";

export const metadata: Metadata = {
  title: "Terms of Service — Zorva",
  description:
    "Terms of service for the Zorva AI medical billing audit platform.",
};

export default function TermsPage() {
  return (
    <main className={styles.page}>
      <article className={styles.article}>
        <header className={styles.header}>
          <p className={styles.eyebrow}>Legal</p>
          <h1>Terms of Service</h1>
          <p className={styles.meta}>
            Effective: 2026-06-25 · Version: 0.1 (draft, pending legal review)
          </p>
        </header>

        <section>
          <h2>1. The service</h2>
          <p>
            Zorva (operated by Ashbi under the brand &quot;Zorva&quot;)
            provides AI-assisted medical billing audits for Alberta
            custodians. The service surfaces coding, modifier, and
            fee-schedule discrepancies for clinician review. Zorva does
            not submit claims, modify records, or replace human
            judgment.
          </p>
        </section>

        <section>
          <h2>2. Acceptable use</h2>
          <p>
            You may use Zorva to audit encounters that you (or your
            organization) are authorized to access under the Alberta
            Health Information Act (HIA) and any applicable federal
            privacy law (PIPEDA, HIPAA for cross-jurisdiction work).
            You may not use Zorva to re-identify hashed patient
            identifiers or to train competing models.
          </p>
        </section>

        <section>
          <h2>3. Fees &amp; cancellation</h2>
          <p>
            Pilot: 60 days at no cost, capped at 500 encounters/mo.
            Standard tiers are $499 / $1,499 / $2,999 CAD/mo (see{" "}
            <Link href="/pricing">/pricing</Link>). You can cancel
            anytime; no pro-rated refunds on monthly plans, but
            annual plans are pro-rated.
          </p>
        </section>

        <section>
          <h2>4. Disclaimers</h2>
          <p>
            Zorva is a decision-support tool. Coding and fee-schedule
            recommendations are advisory. The clinician of record
            remains responsible for claim submission and any downstream
            liability. Zorva does not guarantee reimbursement or
            compliance with any specific payer.
          </p>
        </section>

        <section>
          <h2>5. Liability</h2>
          <p>
            To the maximum extent permitted by law, Zorva&apos;s total
            liability is capped at the fees you paid in the 12 months
            preceding the claim. We are not liable for consequential,
            incidental, or punitive damages.
          </p>
        </section>

        <section>
          <h2>6. Termination</h2>
          <p>
            We may suspend access for material breach (e.g., attempting
            to circumvent rate limits, uploading data you are not
            authorized to handle). On termination, your data is
            exportable for 30 days, then permanently deleted.
          </p>
        </section>

        <section>
          <h2>7. Governing law</h2>
          <p>
            Alberta, Canada. Disputes are resolved by binding
            arbitration in Calgary under the Alberta Arbitration Act.
          </p>
        </section>

        <section>
          <h2>8. Contact</h2>
          <p>
            <a href="mailto:legal@ashbi.ca">legal@ashbi.ca</a> for
            BAA / HIC-Agent agreements, MSA redlines, or DPA requests.
          </p>
        </section>

        <p className={styles.disclaimer}>
          <strong>Not legal advice.</strong> This page is a template
          scaffold. The full editorial draft is in{" "}
          <code>docs/terms-of-service.md</code> and must be reviewed by
          counsel before the BAA is signed.
        </p>

        <p className={styles.backLink}>
          <Link href="/">← Back to home</Link>
        </p>
      </article>
    </main>
  );
}
