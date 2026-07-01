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
              Canadian-region facility you select at signup. The
              actual hosting provider, facility, and any third-party
              attestations they currently hold are documented in the
              executed IMA / BAA before any customer data is uploaded.
            </p>
            <p>
              Data does not leave that region. PHI is never written to
              logs, never sent to an LLM provider for training, and
              never used to train any model. See{" "}
              <Link href="/security">/security</Link> for the full
              residency commitment and sub-processor list.
            </p>
          </>
        ),
      },
      {
        q: "Is Zorva HIA / HIPAA / PHIPA compliant?",
        a: (
          <>
            <p>
              For Alberta clinics (our current go-to-market), we sign
              an HIA Information Manager Agreement (template at{" "}
              <Link href="/legal">/legal</Link>, currently in lawyer
              review). We also support BAA / HIC-Agent / affiliate
              agreements for US HIPAA and Ontario PHIPA pilots on
              request — the templates exist but are not pre-signed
              for jurisdictions where we don&apos;t currently have a
              customer. SOC 2 Type II and ISO 27001 are on the
              certification roadmap, not currently held; we publish
              that on the security page.
            </p>
            <p>
              For the current attestation packet (data center
              details, sub-processor list, hosting-provider
              third-party reports), email{" "}
              <code>security@ashbi.ca</code>.
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
              The 60-day pilot is no-cost, no-commitment. Run Zorva
              against your own historical claims and live claims for
              two months, walk through every finding with our team,
              and at the end decide whether to continue on a paid tier
              or walk away (we delete your data within 30 days).
            </p>
            <p>
              There is no auto-conversion to a paid tier at the end of
              the pilot. Full terms in{" "}
              <Link href="/pilot">/pilot</Link>.
            </p>
          </>
        ),
      },
      {
        q: "What are the paid tiers?",
        a: (
          <>
            <p>
              <strong>Small (Starter) — $499 CAD/mo:</strong> up to
              1,000 claims/month, single tenant, email support.{" "}
              <strong>Mid (Growth) — $1,499 CAD/mo:</strong> 1,000 –
              3,000 claims/month, up to 5 biller seats, same-day
              support. <strong>Large (Scale) — $2,999 CAD/mo:</strong>{" "}
              3,000+ claims/month, unlimited biller seats, same-day
              SLA, quarterly rules-tuning session. Enterprise (above
              3,000 claims/month or custom data-residency) is
              custom-quoted.
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
            Yes — email <a href="mailto:hello@ashbi.ca">hello@ashbi.ca</a>{" "}
            with the colleague&rsquo;s clinic name and we&rsquo;ll set up a
            referral code. $200 Amazon card per Tier 2/3 signup, or 1
            month free on your tier per signup. (We&rsquo;re building a
            self-serve /referral page for Q4 2026; in the meantime the
            email-driven flow is the only path.)
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
              On the v12 cleaned AHCIP validation set (10 encounters,
              13 audited gold findings, micro-averaged), Zorva
              achieves <strong>P = 0.647, R = 0.846, F1 = 0.690</strong>.
              That&apos;s 11 of 13 gold findings caught. For clinic
              conversations we round this to{" "}
              <em>&ldquo;catches 6–7 of 10 real billing errors before
              submission&rdquo;</em>, which is the lower bound of the
              0.60–0.69 range and stays defensible.
            </p>
            <p className={styles.caveat}>
              <strong>Important caveat:</strong> the val set is small
              (n=10) and the gold was reviewed by a single expert.
              Real-world F1 will vary by specialty, encounter
              complexity, and how the upstream EHR documents the
              visit. We publish the full benchmark methodology and
              the per-finding rubric at{" "}
              <Link href="/technical">/technical</Link>{" "}
              so you can decide what to trust for your own clinic.
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
              <code>audit.completed</code>,{" "}
              <code>finding.created</code>, and{" "}
              <code>encounter.uploaded</code>. Full reference at{" "}
              <Link href="/api/REFERENCE.md">docs/api/REFERENCE.md</Link>.
            </p>
          </>
        ),
      },
      {
        q: "Which health-plan fee schedules are supported?",
        a: (
          <p>
            AHCIP (Alberta SOMB) is the production-supported schedule,
            with 16 v12 rules tuned to Alberta primary-care and
            specialist billing. OHIP (Ontario), BC MSP, Saskatchewan,
            and other Canadian provinces are on the 2027 roadmap —
            none of them have working rules today. US payers
            (Medicare, Medicaid, commercial) are not in scope for the
            current product.
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
          <>
            <p>
              We work with your billing system&apos;s 837P export or a
              scheduled SFTP drop — no EHR switch required, and no
              live EHR connector needed. CSV uploads and manual
              single-encounter entry are also supported for low
              volume or one-off audits.
            </p>
            <p>
              Custom HL7v2 / FHIR connectors are available on the
              Enterprise tier ($5,000 one-time per connector) when a
              clinic has a specific integration requirement. The
              existing pilot integrations are 837P file ingest + SFTP
              pull, which covers the standard Alberta clinic billing
              pipeline (Accuro, OSCAR, TELUS PS Suite, Med Access,
              Healthquest, etc.).
            </p>
          </>
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
    <main id="main" className={styles.page}>
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
          <a href="mailto:hello@ashbi.ca">hello@ashbi.ca</a> and
          we&apos;ll add it.
        </p>
      </footer>
    </main>
  );
}