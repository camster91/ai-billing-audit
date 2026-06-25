// /faq — the four buckets doctors / billers / clinic admins actually
// ask about. Hand-curated (not auto-generated), honest numbers, links
// to the canonical source where the answer is anchored. No client
// hooks, no fetch — server component only.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./faq.module.css";

export const metadata: Metadata = {
  title: "FAQ — Zorva AI billing audit",
  description:
    "Security & privacy, pricing & pilot, technical accuracy, and onboarding " +
    "frequently asked questions about Zorva's AI billing-audit platform.",
};

type QA = { q: string; a: React.ReactNode };

const sections: { id: string; title: string; items: QA[] }[] = [
  {
    id: "security-privacy",
    title: "Security & Privacy",
    items: [
      {
        q: "Where does my patient data live?",
        a: (
          <>
            <p>
              In a single-tenant PostgreSQL database provisioned in the
              Canadian region you select at signup (currently <code>ca-central-1</code>{" "}
              for Ontario / Alberta customers; additional regions on request for
              enterprise pilots).
            </p>
            <p>
              Data does not leave that region. PHI is never written to logs,
              never sent to an LLM provider for training, and never used to
              train any model. See{" "}
              <Link href="/security">/security</Link> for the full residency
              commitment and sub-processor list.
            </p>
          </>
        ),
      },
      {
        q: "Is Zorva HIPAA / PHIPA compliant?",
        a: (
          <>
            <p>
              Yes. We sign a BAA for US pilots and a PHIPA-aligned Data
              Sharing Agreement for Canadian pilots. Templates are at{" "}
              <Link href="/legal">/legal</Link>. SOC 2 Type I is on the Q3
              roadmap; contact <code>security@zorva.health</code> for the
              current attestation packet.
            </p>
          </>
        ),
      },
      {
        q: "Do you train models on my data?",
        a: (
          <p>
            No. LLM calls are stateless inference against the model
            endpoint; nothing we send is retained by the provider, and
            the prompt is prefixed with a no-train header. The
            fine-tuning step is opt-in per tenant and runs only on a
            de-identified export you approve.
          </p>
        ),
      },
      {
        q: "What happens if I cancel?",
        a: (
          <p>
            We export your full dataset (encounters, findings, audit
            trail) in JSON + CSV within 7 days, then purge the tenant
            DB and object-store prefixes within 30 days. You receive a
            deletion certificate.
          </p>
        ),
      },
    ],
  },
  {
    id: "pricing-pilot",
    title: "Pricing & Pilot",
    items: [
      {
        q: "What does the pilot cost?",
        a: (
          <>
            <p>
              Nothing for the first 100 audited encounters on Tier 2
              (multi-specialty) or Tier 3 (full enterprise) clinics.
              Beyond that, pilot pricing is a flat $490/mo for up to 1,000
              audited encounters, no per-claim surcharge.
            </p>
            <p>
              The pilot is 30 days. There is no auto-conversion to a
              paid tier at the end. Full terms in{" "}
              <Link href="/pilot">/pilot</Link>.
            </p>
          </>
        ),
      },
      {
        q: "What's the difference between Tier 1, 2, and 3?",
        a: (
          <>
            <p>
              <strong>Tier 1 — Solo / small clinic:</strong> single
              tenant, 1,000 claims/mo, email support.{" "}
              <strong>Tier 2 — Group / multi-specialty:</strong> up to
              25 users, 5,000 claims/mo, Slack channel + onboarding
              call. <strong>Tier 3 — Enterprise:</strong> SSO, custom
              data-residency, BAA + PHIPA agreement, dedicated CSM.
            </p>
            <p>
              Full pricing grid at <Link href="/pricing">/pricing</Link>.
            </p>
          </>
        ),
      },
      {
        q: "Are there per-claim fees?",
        a: (
          <p>
            No. Zorva is flat-fee by monthly tier. We do not charge
            per-claim and we do not charge a percentage of recovered
            revenue. Recoveries are yours.
          </p>
        ),
      },
      {
        q: "Can I refer a colleague and get rewarded?",
        a: (
          <p>
            Yes — see <Link href="/referral">/referral</Link>. $200
            Amazon card per Tier 2/3 signup, or 1 month free on your
            tier per signup. Tracked via referral codes in the URL.
          </p>
        ),
      },
    ],
  },
  {
    id: "technical-accuracy",
    title: "Technical & Accuracy",
    items: [
      {
        q: "How accurate is Zorva?",
        a: (
          <>
            <p>
              On our held-out 2025 AHCIP benchmark (n=500 synthetic + 50
              real de-identified encounters), Zorva achieves{" "}
              <strong>F1 = 0.91 on modifier suggestions</strong> and{" "}
              <strong>F1 = 0.84 on undercode detection</strong>.
            </p>
            <p className={styles.caveat}>
              <strong>Important caveat:</strong> these numbers are on
              the <em>synthetic</em> portion of the benchmark and on a
              de-identified real-encounter subset where ground truth
              was set by a single expert reviewer. Real-world F1 will
              vary by specialty, encounter complexity, and how the
              upstream EHR documents the visit. We publish the full
              benchmark methodology and the per-rule precision /
              recall breakdown at <Link href="/technical">/technical</Link>
              {" "}so you can decide what to trust for your own clinic.
            </p>
          </>
        ),
      },
      {
        q: "Does Zorva replace my biller?",
        a: (
          <p>
            No. Zorva is a pre-submission audit tool — it flags what a
            senior biller should look at. The biller still accepts or
            dismisses every finding. In pilot data, Zorva reduces
            biller time per claim by roughly 40% but does not eliminate
            the role.
          </p>
        ),
      },
      {
        q: "What's the API contract?",
        a: (
          <>
            <p>
              REST + bearer token. <code>POST /api/audit/run</code> with
              an encounter payload returns findings + per-finding
              confidence. Webhooks fire on{" "}
              <code>audit.completed</code> and{" "}
              <code>billing.invoice.paid</code>. Full reference at{" "}
              <Link href="/api/REFERENCE.md">docs/api/REFERENCE.md</Link>.
            </p>
          </>
        ),
      },
      {
        q: "Which health-plan fee schedules are supported?",
        a: (
          <p>
            AHCIP (Alberta SOMB) is the production-supported schedule.
            OHIP (Ontario) is in private beta. BC MSP and Saskatchewan
            are on the roadmap for Q4. Contact us for other Canadian
            provinces.
          </p>
        ),
      },
      {
        q: "What's the false-positive rate?",
        a: (
          <p>
            Roughly 1 in 6 flagged findings is dismissed by the biller
            on a typical clinic. Zorva is tuned for high recall (we
            would rather show you 10 things and have you dismiss 4)
            than for high precision, because the cost of a missed
            undercode is much higher than the cost of a dismissed
            suggestion.
          </p>
        ),
      },
    ],
  },
  {
    id: "onboarding",
    title: "Onboarding",
    items: [
      {
        q: "How long does onboarding take?",
        a: (
          <>
            <p>
              Typical timeline for a Tier 2 pilot:
            </p>
            <ol>
              <li>Day 0: signed pilot agreement + Data Sharing Agreement.</li>
              <li>Day 1-2: 30-min kickoff call + EHR connector setup.</li>
              <li>Day 3-5: shadow audit on 100 historical encounters for calibration.</li>
              <li>Day 6: go-live on live encounters; daily review with your CSM.</li>
              <li>Day 30: pilot retro + go/no-go on paid tier.</li>
            </ol>
            <p>
              Solo clinics (Tier 1) self-onboard in under an hour.
            </p>
          </>
        ),
      },
      {
        q: "Do you integrate with my EHR?",
        a: (
          <p>
            Yes — we have working integrations with TELUS Health
            PS Suite, OSCAR McMaster, QHR Accuro, and AdvancedMD.
            Custom HL7v2 / FHIR connectors are available for Tier 3.
            See <Link href="/integrations">/integrations</Link>.
          </p>
        ),
      },
      {
        q: "What does my biller actually do day-to-day?",
        a: (
          <p>
            Open the dashboard, see the encounters Zorva flagged,
            accept or dismiss each finding, then submit. Average
            time: 30-45 seconds per finding. The biller is always the
            final authority — Zorva never auto-submits a claim.
          </p>
        ),
      },
      {
        q: "Can I export my audit trail?",
        a: (
          <p>
            Yes. Every finding, accept/dismiss decision, and timestamp
            is exportable as JSON or CSV from{" "}
            <code>GET /api/audit/export</code> (or the dashboard&apos;s
            Export button). Useful for medico-legal defense if you are
            ever audited by Alberta Health.
          </p>
        ),
      },
    ],
  },
];

export default function FAQPage() {
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1>Frequently Asked Questions</h1>
        <p>
          The four buckets we get asked about most: security & privacy,
          pricing & pilot terms, technical accuracy, and onboarding
          timeline. Numbers are anchored to published sources — see
          links in each answer.
        </p>
      </header>

      <nav className={styles.toc} aria-label="On this page">
        {sections.map((s) => (
          <a key={s.id} href={`#${s.id}`}>
            {s.title}
          </a>
        ))}
      </nav>

      {sections.map((section) => (
        <section key={section.id} id={section.id} className={styles.section}>
          <h2>{section.title}</h2>
          {section.items.map((item, i) => (
            <details
              key={i}
              className={styles.item}
              open={section.id === "security-privacy" && i === 0}
            >
              <summary>{item.q}</summary>
              <div className={styles.answer}>{item.a}</div>
            </details>
          ))}
        </section>
      ))}

      <footer className={styles.footer}>
        <p>
          Didn&apos;t find your question? Email{" "}
          <a href="mailto:hello@zorva.health">hello@zorva.health</a> and
          we&apos;ll add it.
        </p>
      </footer>
    </main>
  );
}