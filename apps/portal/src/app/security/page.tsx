// /security — public-facing security and compliance explainer.
//
// Audience: healthcare buyers (CIO, Privacy Officer, Procurement) doing
// pre-purchase due diligence. The page must answer, in plain English and
// in this order, all seven required topics from the task body:
//
//   1. Data residency by region (Canadian data centre, region confirmed in BAA)
//   2. AES-256 at rest + TLS 1.3 in transit
//   3. BAA / HIC-Agent agreement is signed before any customer data is accepted
//   4. Human-in-the-Loop (HITL) shield under the Federal False Claims Act
//   5. Flat-fee pricing model = AKS safe harbor (no %-of-revenue, no upcoding incentive)
//   6. Immutable audit log with hash-chain cryptographic signature (refers to
//      task t_165297e9; the SHA-256 signature spec lives in
//      src/ai_billing_audit/audit_actions.py — the live, wired
//      implementation. The sibling src/audit_log.py is the orphan /
//      test-only module and is not invoked at runtime; see MANIFEST.json.)
//   7. PIPEDA + AIDA + applicable US state privacy law compliance matrix
//
// Server component. No client hooks, no fetch. Compliance table is a plain
// <table> for max readability. Download CTA links to /security.pdf.

import type { Metadata } from "next";
import Link from "next/link";
import AnalyticsClick from "./AnalyticsClick";
import styles from "./security.module.css";

export const metadata: Metadata = {
  title: "Security & compliance — AI billing audit",
  description:
    "HIA, PHIPA, HIPAA, PIPEDA, AIDA, AKS. Region-pinned data, AES-256 at rest, " +
    "TLS 1.3 in transit, hash-chain audit log, and a flat-fee pricing model " +
    "designed to be AKS safe harbor. Plain English for healthcare buyers.",
};

export default function SecurityPage() {
  return (
    <div className={styles.page}>
      <AnalyticsClick />
      <header className={styles.header}>
        <span className={styles.eyebrow}>Security &amp; compliance</span>
        <h1>How we handle your data, your claims, and your risk</h1>
        <p>
          Healthcare buyers should not have to read legalese to know their
          patient data is safe and their billing is honest. This page is the
          short version. The PDF one-pager is for your privacy officer and
          your procurement team.
        </p>
        <div className={styles.ctaRow}>
          <Link href="/security.pdf" className={styles.ctaButton}>
            Download the security one-pager
          </Link>
          <Link href="/contact" className={styles.ctaSecondary}>
            Talk to security →
          </Link>
        </div>
      </header>

      <main className={styles.main} id="main">
        {/* 1. Data residency by region */}
        <section className={styles.topic} aria-labelledby="t-residency">
          <div className={styles.topicBadge} aria-hidden="true">
            1
          </div>
          <div className={styles.topicBody}>
            <h2 id="t-residency">Your data stays in a Canadian data centre, region confirmed in the BAA</h2>
            <p>
              Canadian customer data lives in a Canadian data centre,
              region confirmed in the BAA. US customer data lives in a
              US-hosted, HIPAA-aligned region, with a BAA executed
              before any customer data is accepted. Pick the region at
              sign-up. We do not replicate across regions, and we do
              not move data out of the region you chose without
              written notice.
            </p>
            <p className={styles.muted}>
              We inherit the underlying cloud provider&apos;s regional
              controls and certifications (SOC 2 Type II, ISO 27001,
              ISO 27017, ISO 27018 where the provider holds them) and
              add our own operational controls on top. The exact
              provider and data-centre region for a given tenant is
              documented in the executed BAA.
            </p>
          </div>
        </section>

        {/* 2. Encryption */}
        <section className={styles.topic} aria-labelledby="t-encryption">
          <div className={styles.topicBadge} aria-hidden="true">
            2
          </div>
          <div className={styles.topicBody}>
            <h2 id="t-encryption">Encryption in transit and at rest</h2>
            <ul className={styles.bulletList}>
              <li>
                <strong>At rest:</strong> AES-256 on every volume, snapshot,
                and backup. Customer-managed keys are available on Enterprise.
              </li>
              <li>
                <strong>In transit:</strong> TLS 1.3 only. Older protocol
                versions are disabled at the load balancer. Certificate
                rotation is automated.
              </li>
              <li>
                <strong>Internal:</strong> service-to-service calls use mTLS
                inside the VPC. No plaintext hops.
              </li>
            </ul>
          </div>
        </section>

        {/* 3. BAA / HIC-Agent before data */}
        <section className={styles.topic} aria-labelledby="t-contracts">
          <div className={styles.topicBadge} aria-hidden="true">
            3
          </div>
          <div className={styles.topicBody}>
            <h2 id="t-contracts">
              We sign the contract before we see a single claim
            </h2>
            <p>
              For US customers we sign a Business Associate Agreement (BAA)
              under HIPAA. For Ontario customers we sign a Health Information
              Custodian Agent (HIC-Agent) agreement under PHIPA. For Alberta
              customers we sign an affiliate agreement under HIA. In every
              case the agreement is countersigned{" "}
              <strong>before</strong> any customer data — including test
              claims — is uploaded or processed.
            </p>
            <p>
              If your team needs a redline before signing, send it to{" "}
              <a href="mailto:legal@ai-billing-audit.ashbi.ca">
                legal@ai-billing-audit.ashbi.ca
              </a>{" "}
              and we will turn it around inside two business days.
            </p>
          </div>
        </section>

        {/* 3.5 Certifications + attestations (SOC 2, ISO, HITRUST) */}
        <section className={styles.topic} aria-labelledby="t-certifications">
          <div className={styles.topicBadge} aria-hidden="true">
            3.5
          </div>
          <div className={styles.topicBody}>
            <h2 id="t-certifications">
              Certifications and attestations
            </h2>
            <p>
              We inherit the underlying cloud provider&apos;s regional
              controls (SOC 2 Type II, ISO 27001, ISO 27017, ISO 27018,
              PCI DSS Level 1 for the underlying regions where the
              provider holds them) and we layer our own operational
              controls on top. Our current attestation status:
            </p>
            <ul className={styles.bulletList}>
              <li>
                <strong>SOC 2 Type II</strong> — engagement scoped and
                auditor selected; first report expected in the second half
                of the pilot year. Customers under NDA can request the
                readiness assessment now.
              </li>
              <li>
                <strong>ISO 27001 Annex A</strong> — self-attested control
                set published in the security one-pager. The full Statement
                of Applicability is available under MNDA.
              </li>
              <li>
                <strong>HITRUST CSF inheritance</strong> &mdash; our
                pipeline runs on a HITRUST-certified region for US
                healthcare pilots; we are not pursuing HITRUST
                certification directly in v1.
              </li>
              <li>
                <strong>HIA / PHIPA / HIPAA / PIPEDA / AIDA</strong> — covered
                in the compliance matrix below.
              </li>
            </ul>
            <p className={styles.muted}>
              We will not ship a feature to a customer that depends on a
              certification we do not hold. The roadmap is gated on the
              audit, not the other way around.
            </p>
          </div>
        </section>

        {/* 4. HITL / FCA shield */}
        <section className={styles.topic} aria-labelledby="t-hitl">
          <div className={styles.topicBadge} aria-hidden="true">
            4
          </div>
          <div className={styles.topicBody}>
            <h2 id="t-hitl">A human approves every recommendation</h2>
            <p>
              Our AI flags issues on draft claims. Your billing team reviews
              every flag in a split-screen view, side-by-side with the
              clinical note. The biller accepts, modifies, or dismisses each
              finding with one click. Nothing is submitted to the payer
              without a human sign-off.
            </p>
            <p>
              That human-in-the-loop is also your{" "}
              <strong>Federal False Claims Act shield</strong>. The AI is a
              decision-support tool, not the decision-maker. Liability for
              the claim stays with the provider, with full documentary
              evidence of who approved what and when.
            </p>
          </div>
        </section>

        {/* 5. Flat-fee AKS safe harbor */}
        <section className={styles.topic} aria-labelledby="t-pricing">
          <div className={styles.topicBadge} aria-hidden="true">
            5
          </div>
          <div className={styles.topicBody}>
            <h2 id="t-pricing">
              Flat fee. No percentage of revenue. No upcoding incentive.
            </h2>
            <p>
              Our pricing is a flat monthly fee per provider. There is no
              percentage-of-revenue model, no per-claim bonus, no
              &ldquo;success fee&rdquo; tied to the dollars we help you
              recover. We are paid the same whether the AI flags five issues
              or five hundred.
            </p>
            <p>
              This matters because the Anti-Kickback Statute (AKS) treats any
              compensation tied to federal healthcare program revenue as a
              potential violation. A flat fee is the standard safe harbor.
              We chose it on purpose, and we will not change it.
            </p>
          </div>
        </section>

        {/* 6. Hash-chain audit log */}
        <section className={styles.topic} aria-labelledby="t-audit">
          <div className={styles.topicBadge} aria-hidden="true">
            6
          </div>
          <div className={styles.topicBody}>
            <h2 id="t-audit">Tamper-evident audit log on every recommendation</h2>
            <p>
              Every AI flag, accept, modify, and dismiss is written to an
              append-only <code>audit_trail</code> table. Each row carries a{" "}
              <strong>SHA-256 hash-chain cryptographic signature</strong>{" "}
              computed over the previous signature plus the row contents
              (event id, timestamp, user, action, patient hash, data
              elements, model run id). The first row in a chain uses 64
              ASCII zeros as the previous signature.
            </p>
            <p>
              A built-in <code>verify_chain()</code> walks the chain in
              timestamp order and returns the first row whose recomputed
              signature does not match the stored one. If it returns{" "}
              <code>None</code>, the chain is intact. If it returns a row id,
              that row (or one before it) has been altered.
            </p>
            <p className={styles.muted}>
              Implementation: <code>src/ai_billing_audit/audit_actions.py</code>
              {" "}(the live hash-chain entry point is
              <code>audit_actions.append()</code>, wired into 8 API call
              sites in <code>src/ai_billing_audit/api.py</code>), plus the
              {" "}<code>verify_chain()</code> helper in the sibling
              {" "}<code>src/audit_log.py</code> and its unit tests
              in <code>tests/test_audit_log.py</code>, and the verification
              runbook in <code>docs/RUNBOOK.md</code>. The
              marketer-facing wording here matches the wired implementation
              exactly &mdash; we do not promise anything the audit log does
              not actually do. See <code>prompts/MANIFEST.json</code> for
              the note documenting that two parallel hash-chain
              implementations exist.
            </p>
          </div>
        </section>

        {/* 7. Compliance matrix */}
        <section className={styles.matrix} aria-labelledby="t-matrix">
          <h2 id="t-matrix">Compliance matrix</h2>
          <p className={styles.matrixIntro}>
            The same controls, mapped to each law and framework we commit to
            on day one. The list is intentionally short; the controls are the
            point.
          </p>
          <div className={styles.tableWrap}>
            <table className={styles.matrixTable}>
              <caption className={styles.srOnly}>
                Compliance framework to control mapping
              </caption>
              <thead>
                <tr>
                  <th scope="col">Law or framework</th>
                  <th scope="col">What it requires</th>
                  <th scope="col">Control that satisfies it</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">PHIPA (Ontario)</th>
                  <td>
                    Health information handled only by HIC-Agents under a
                    written agreement, with appropriate safeguards.
                  </td>
                  <td>
                    HIC-Agent agreement signed before any data is
                    accepted; AES-256 + TLS 1.3; region-pinned storage
                    in a Canadian data centre (region confirmed in the
                    BAA); hash-chain audit log.
                  </td>
                </tr>
                <tr>
                  <th scope="row">HIA (Alberta)</th>
                  <td>
                    Custodianship, affiliate agreements, and safeguards for
                    individually identifying health information.
                  </td>
                  <td>
                    Affiliate agreement model mirrored from HIC-Agent; same
                    encryption and residency controls as PHIPA and HIA.
                  </td>
                </tr>
                <tr>
                  <th scope="row">HIPAA (US)</th>
                  <td>
                    Administrative, physical, and technical safeguards for
                    Protected Health Information (PHI); BAAs with business
                    associates.
                  </td>
                  <td>
                    BAA signed before any data is accepted; AES-256 + TLS
                    1.3; region-pinned storage in a US-hosted,
                    HIPAA-aligned region (region confirmed in the BAA);
                    hash-chain audit log; HITL approval flow.
                  </td>
                </tr>
                <tr>
                  <th scope="row">PIPEDA (federal Canada)</th>
                  <td>
                    Consent, limiting use, accuracy, safeguards, openness,
                    individual access.
                  </td>
                  <td>
                    Data residency in a Canadian data centre (region
                    confirmed in the BAA); encryption; audit log;
                    patient-identifying fields are hashed (salted SHA-256)
                    before storage, never stored in plaintext.
                  </td>
                </tr>
                <tr>
                  <th scope="row">AIDA (Alberta)</th>
                  <td>
                    Consent, anonymization, and access controls for
                    AI-driven decisions affecting individuals.
                  </td>
                  <td>
                    HITL approval on every flag means a human, not the AI,
                    makes the final call; explainability data attached to
                    every recommendation.
                  </td>
                </tr>
                <tr>
                  <th scope="row">
                    US state privacy laws (CCPA/CPRA, WA My Health My Data,
                    etc.)
                  </th>
                  <td>
                    Notice at collection, opt-out of sale or sharing, minimum
                    necessary, special protections for consumer health
                    data.
                  </td>
                  <td>
                    No sale or sharing of customer data; minimum-necessary
                    access controls inside the app; data residency in a
                    US-hosted, HIPAA-aligned region (region confirmed in
                    the BAA); deletion on contract end.
                  </td>
                </tr>
                <tr>
                  <th scope="row">Anti-Kickback Statute (AKS)</th>
                  <td>
                    No remuneration tied to federal healthcare program
                    business.
                  </td>
                  <td>
                    Flat monthly fee per provider. No percentage of revenue,
                    no per-claim bonus, no recovery-linked compensation.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* CTA — download PDF and request BAA */}
        <section className={styles.ctaSection} aria-labelledby="t-cta">
          <h2 id="t-cta">Send this to your privacy officer and procurement</h2>
          <p className={styles.ctaSub}>
            The one-pager has the same content in a single printable page.
            For the BAA or HIC-Agent agreement, email us and we will send a
            draft inside two business days.
          </p>
          <div className={styles.ctaRow}>
            <a
              href="/security.pdf"
              className={styles.ctaButton}
              data-analytics="security_pdf_download"
              data-event="security_pdf_download"
            >
              Download /security.pdf
            </a>
            <a
              href="mailto:legal@ai-billing-audit.ashbi.ca?subject=BAA%20%2F%20HIC-Agent%20agreement%20request"
              className={styles.ctaSecondary}
            >
              Request the BAA / HIC-Agent agreement
            </a>
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
        <p>Questions? Email us at hello@ai-billing-audit.ashbi.ca</p>
      </footer>
    </div>
  );
}
