// /security — public-facing security and compliance explainer.
//
// Audience: privacy officers and IT leads doing pre-purchase due
// diligence on behalf of a clinic. The page must answer, in plain
// English and in a single controls matrix, all six required topics
// from the task body:
//
//   1. Data residency
//   2. Encryption in transit + at rest
//   3. Access controls
//   4. Audit trail with hash chain
//   5. PII handling
//   6. Compliance posture
//
// The compliance posture section names the four frameworks with their
// jurisdictions: HIA + PIPEDA (Alberta / Canada), HIPAA (US), NOM-024
// (Mexico).
//
// Server component. No client hooks, no fetch. The controls matrix is
// a plain <table> for max readability. CTAs link to /security.pdf and
// the BAA / HIC-Agent / affiliate-agreement request mailto.

import type { Metadata } from "next";
import Link from "next/link";
import AnalyticsClick from "./AnalyticsClick";
import styles from "./security.module.css";

export const metadata: Metadata = {
  title: "Security & compliance — AI billing audit",
  description:
    "Controls matrix: data residency, encryption in transit and at rest, " +
    "access controls, hash-chain audit trail, PII handling, and compliance " +
    "posture under HIA, PIPEDA, HIPAA, and NOM-024.",
};

type Cell = string | { text: string; muted?: boolean };

type Row = {
  area: string;
  control: string;
  status: Cell;
  region: Cell;
};

const ROWS: Row[] = [
  {
    area: "Data residency",
    control:
      "Customer data is stored in a single, region-pinned facility " +
      "documented in the executed IMA / BAA. Canadian customers are " +
      "served from a Canadian-region facility; US customers from a " +
      "US-region facility. Region is locked at sign-up and confirmed " +
      "in the executed agreement. No cross-region replication, no " +
      "movement out of the chosen region without written notice.",
    status: {
      text:
        "Active. Region locked per tenant at sign-up. The actual " +
        "hosting provider, facility, and any third-party attestations " +
        "they currently hold (where they exist) are documented in the " +
        "executed IMA / BAA. SOC 2 Type II and ISO 27001 are on our " +
        "certification roadmap (not currently held).",
    },
    region: { text: "CA / US" },
  },
  {
    area: "Encryption in transit",
    control:
      "TLS 1.3 only on the public edge. Older protocol versions disabled " +
      "at the load balancer. Service-to-service calls inside the VPC use " +
      "mutual TLS. Certificate rotation is automated.",
    status: "Active. TLS 1.3 enforced at the edge; mTLS inside the VPC.",
    region: { text: "All regions" },
  },
  {
    area: "Encryption at rest",
    control:
      "AES-256 on every volume, snapshot, and backup. Customer-managed " +
      "keys are available on the Enterprise tier.",
    status: "Active. AES-256 everywhere at rest. CMK available on Enterprise.",
    region: { text: "All regions" },
  },
  {
    area: "Audit trail with hash chain",
    control:
      "Append-only audit_trail table. Every row carries a SHA-256 " +
      "hash-chain cryptographic signature computed over the previous " +
      "signature plus the row contents (event id, timestamp, user, " +
      "action, patient hash, data elements, model run id). First row " +
      "in a chain uses 64 ASCII zeros as the previous signature. A " +
      "built-in verify_chain() walks the chain in timestamp order and " +
      "returns the first row whose recomputed signature does not match.",
    status: {
      text:
        "Active. SHA-256 hash chain, append-only. verify_chain() returns " +
        "the index of the first broken row (or None when intact). " +
        "Implementations: src/audit_log.py (canonical) and " +
        "src/ai_billing_audit/audit_actions.py (parallel — see QA audit log).",
    },
    region: { text: "All regions" },
  },
  {
    area: "Access controls",
    control:
      "Per-tenant isolation. Role-based access (admin, biller, viewer) with " +
      "least-privilege defaults. Two-person approval for high-impact " +
      "actions (export, bulk re-audit, billing changes). Every privileged " +
      "action is written to the audit trail.",
    status:
      "Active. RBAC enforced; two-person approval on destructive / " +
      "export actions; full session audit trail.",
    region: { text: "All regions" },
  },
  {
    area: "PII handling",
    control:
      "An internal encounter identifier is hashed (salted SHA-256) " +
      "before it reaches the audit log; that salted hash is the only " +
      "patient-shaped value that flows through audit_trail, the " +
      "feedback log, and the model prompt. Raw patient identifiers " +
      "(PHN, MRN, name, DOB) live only in the encrypted encounter " +
      "table for the duration of the audit lifecycle and are purged " +
      "within 30 days of pilot termination. Minimum-necessary " +
      "access: only the fields the auditor needs are passed in.",
    status:
      "Active. Salted SHA-256 patient_hash on both the portal and " +
      "FastAPI paths, using the same patient-hash:v1 domain format " +
      "and PATIENT_HASH_PEPPER env var. Backed by a hex CHECK " +
      "constraint on the audit_trail SQL schema. The FastAPI service " +
      "fails fast at startup if PATIENT_HASH_PEPPER is unset or " +
      "shorter than 16 characters in production. Raw patient " +
      "identifiers are stored only in the encrypted encounter " +
      "table, never in the audit log.",
    region: { text: "All regions" },
  },
  {
    area: "Compliance posture",
    control:
      "Frameworks we currently operate under, with the contract " +
      "artefact per region. Canadian clinics are covered today " +
      "(HIA + PIPEDA). US (HIPAA) and Ontario (PHIPA) pilots are " +
      "supported via the BAA / HIC-Agent template on request — " +
      "the templates exist but are not pre-signed for " +
      "jurisdictions where we do not currently have a customer. " +
      "Mexico (NOM-024) and other jurisdictions are on the 2027 " +
      "roadmap. All agreements are countersigned before any " +
      "customer data — including test claims — is uploaded or " +
      "processed.",
    status: {
      text:
        "Active. HIA + PIPEDA (Alberta / Canada) covered today. " +
        "HIPAA (US) and PHIPA (Ontario) supported on request via " +
        "template. NOM-024 (Mexico) on 2027 roadmap. All " +
        "agreements countersigned before any data is accepted.",
    },
    region: { text: "CA / US / MX" },
  },
];

const COMPLIANCE: { framework: string; jurisdiction: string; what: string }[] = [
  {
    framework: "HIA",
    jurisdiction: "Alberta, Canada",
    what:
      "Health Information Act. Custodianship, affiliate agreements, and " +
      "safeguards for individually identifying health information. " +
      "Covered today — Information Manager Agreement template in DRAFT, " +
      "lawyer review in progress, available for signing before any " +
      "Alberta customer data is uploaded.",
  },
  {
    framework: "PIPEDA",
    jurisdiction: "Federal Canada",
    what:
      "Personal Information Protection and Electronic Documents Act. " +
      "Consent, limiting use, accuracy, safeguards, openness, individual " +
      "access — applied to any non-health personal data we handle. " +
      "Covered today as the federal-floor personal-data regime.",
  },
  {
    framework: "HIPAA",
    jurisdiction: "United States",
    what:
      "Health Insurance Portability and Accountability Act. Administrative, " +
      "physical, and technical safeguards for Protected Health Information " +
      "(PHI); BAAs with business associates. Supported on request via the " +
      "BAA template — no US customers in production today; not a pre-signed " +
      "default.",
  },
  {
    framework: "PHIPA",
    jurisdiction: "Ontario, Canada",
    what:
      "Personal Health Information Protection Act. Custodianship, HIC-Agent " +
      "agreements, and safeguards for individually identifying health " +
      "information in Ontario. Supported on request via the HIC-Agent " +
      "template — no Ontario customers in production today.",
  },
  {
    framework: "NOM-024",
    jurisdiction: "Mexico",
    what:
      "Norma Oficial Mexicana 024. Electronic health-record interoperability " +
      "and patient-data handling standards. On the 2027 roadmap; not " +
      "implemented in production today.",
  },
];

export default function SecurityPage() {
  return (
    <div className={styles.page}>
      <AnalyticsClick />
      <header className={styles.header}>
        <span className={styles.eyebrow}>Security &amp; compliance</span>
        <h1>Security controls matrix</h1>
        <p>
          The full table, in plain English. Send it to your privacy officer
          and your IT lead. The PDF one-pager has the same content in a
          single printable page.
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
        <section className={styles.matrix} aria-labelledby="t-matrix">
          <h2 id="t-matrix">Controls matrix</h2>
          <p className={styles.matrixIntro}>
            One row per control area. The status column says what is live
            today and where it is wired in the code. The region column says
            which deployment regions the control applies to.
          </p>
          <div className={styles.tableWrap}>
            <table className={styles.matrixTable}>
              <caption className={styles.srOnly}>
                Security controls matrix
              </caption>
              <thead>
                <tr>
                  <th scope="col">Control area</th>
                  <th scope="col">Control &amp; description</th>
                  <th scope="col">Status &amp; evidence</th>
                  <th scope="col">Region scope</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map((r) => (
                  <tr key={r.area}>
                    <th scope="row">{r.area}</th>
                    <td>{r.control}</td>
                    <td>
                      {typeof r.status === "string" ? (
                        r.status
                      ) : (
                        <>
                          {r.status.text}
                          {r.status.muted && (
                            <span className={styles.muted}>
                              {" "}
                              {r.status.muted}
                            </span>
                          )}
                        </>
                      )}
                    </td>
                    <td>{typeof r.region === "string" ? r.region : r.region.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className={styles.matrix} aria-labelledby="t-compliance">
          <h2 id="t-compliance">Compliance posture</h2>
          <p className={styles.matrixIntro}>
            The four frameworks we commit to on day one, with their
            jurisdictions. Contracts are countersigned before any customer
            data — including test claims — is accepted.
          </p>
          <div className={styles.tableWrap}>
            <table className={styles.matrixTable}>
              <caption className={styles.srOnly}>
                Compliance frameworks and jurisdictions
              </caption>
              <thead>
                <tr>
                  <th scope="col">Framework</th>
                  <th scope="col">Jurisdiction</th>
                  <th scope="col">What it requires</th>
                </tr>
              </thead>
              <tbody>
                {COMPLIANCE.map((c) => (
                  <tr key={c.framework}>
                    <th scope="row">{c.framework}</th>
                    <td>{c.jurisdiction}</td>
                    <td>{c.what}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className={styles.matrix} aria-labelledby="t-posture">
          <h2 id="t-posture">Current security posture</h2>
          <p className={styles.matrixIntro}>
            What is actually live today. Anything not listed here is on the
            roadmap below, not a current capability.
          </p>
          <ul className={styles.matrixIntro} style={{ listStyle: "disc", paddingLeft: "1.25rem" }}>
            <li><strong>TLS 1.3 in transit.</strong> Older protocol versions disabled at the load balancer; service-to-service calls use mTLS.</li>
            <li><strong>AES-256 at rest.</strong> On every volume, snapshot, and backup.</li>
            <li><strong>Hash-chain audit trail.</strong> Append-only audit_trail table, SHA-256 signatures, built-in verify_chain() walker.</li>
            <li><strong>Role-scoped access.</strong> Per-tenant isolation with admin / biller / viewer roles and least-privilege defaults.</li>
            <li><strong>Two-person approval</strong> on high-impact actions (export, bulk re-audit, billing changes); every privileged action is written to the audit trail.</li>
            <li><strong>Salted SHA-256 patient_hash.</strong> An internal encounter identifier is hashed (salted SHA-256) before it reaches the audit log; the raw patient identifiers (PHN, MRN, name) live only in the encrypted encounter table and are purged within 30 days of pilot termination; minimum-necessary pass-through to the model.</li>
          </ul>
          <p className={styles.matrixIntro} style={{ marginTop: "0.75rem" }}>
            <strong>On the certification roadmap (not currently held):</strong> SOC 2 Type II, ISO 27001, ISO 27017, ISO 27018. We will publish third-party reports here as they are issued; until then, we will not represent any of these as held.
          </p>
        </section>

        <section className={styles.ctaSection} aria-labelledby="t-cta">
          <h2 id="t-cta">Send this to your privacy officer and your IT lead</h2>
          <p className={styles.ctaSub}>
            The one-pager has the same content in a single printable page.
            For the BAA, HIC-Agent, or affiliate agreement, email us and we
            will send a draft inside two business days.
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
              href="mailto:legal@zorva.ca?subject=BAA%20%2F%20HIC-Agent%20agreement%20request"
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
        <p>Questions? Email us at hello@zorva.ca</p>
      </footer>
    </div>
  );
}
