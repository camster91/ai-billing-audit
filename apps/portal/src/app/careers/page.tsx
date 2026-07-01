// /careers — public marketing careers landing page.
//
// No current openings. The point of this page is to put a Careers
// link somewhere on the marketing site (footer, "About" rail) so
// candidates who arrive via word-of-mouth, conference swag, or
// referral don't bounce to a 404. Lists the kinds of roles Zorva
// expects to hire for through 2026 so prospective candidates can
// self-screen before sending a cold intro, and gives a single
// email alias to send those intros to.
//
// Public route: no auth, no PII collection. Anyone can hit this URL
// (the proxy.ts allowlist already permits it). All copy is fully
// public-safe — no internal team size, no salary bands, no specific
// candidate names.
//
// Style tokens mirror the rest of the marketing surface
// (/pricing, /how-it-works, /changelog) so the page feels native.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./careers.module.css";

export const metadata: Metadata = {
  title: "Careers — Zorva",
  description:
    "Zorva is not actively hiring right now, but we're always glad to hear " +
    "from people who'd be a great fit for the kinds of roles we'll be " +
    "hiring for through 2026: applied ML, clinical-informatics, billing-ops, " +
    "developer relations, and security engineering.",
};

type Role = {
  // Short team label shown as a chip.
  team: string;
  // Human-readable role title.
  title: string;
  // 1-2 sentence description of what this person would own.
  blurb: string;
  // Light signal on what background tends to fit.
  background: string;
};

const FUTURE_ROLES: ReadonlyArray<Role> = [
  {
    team: "ML / Auditor",
    title: "Applied ML engineer — billing-rule modelling",
    blurb:
      "Own the rule-set that turns raw encounter text into a structured " +
      "missed-revenue finding. Most of the work is rule authoring and " +
      "evaluation; the LLM is one ingredient, not the whole kitchen.",
    background:
      "Comfortable with Python, evaluation harnesses, and reading " +
      "denial-reason taxonomies. Prior exposure to clinical or financial " +
      "rule systems is a plus, not a must.",
  },
  {
    team: "Clinical",
    title: "Clinical informaticist (Alberta billing)",
    blurb:
      "Keep the SOMB schedule, AHCIP rules, and modifier logic in the " +
      "auditor current as the Alberta Health publishes updates. Partner " +
      "with the ML team on edge cases and with pilot clinics on " +
      "rollout communications.",
    background:
      "Background in Alberta medical billing, HIA / PIPEDA, or " +
      "clinical-coding (HIM). RHIAs and experienced clinic billers " +
      "welcome.",
  },
  {
    team: "Biller Ops",
    title: "Customer engineer — biller success",
    blurb:
      "Be the human a clinic's biller talks to when the auditor flags " +
      "something they disagree with. Triage false positives, capture " +
      "feedback into the learning loop, and turn recurring patterns " +
      "into new rules.",
    background:
      "Background as a working medical biller, claims reviewer, or " +
      "denial-management specialist. Comfortable reading a claim line " +
      "and an EOB without a glossary.",
  },
  {
    team: "Engineering",
    title: "Full-stack engineer (TypeScript + Python)",
    blurb:
      "Build the surfaces clinics actually use: the findings inbox, " +
      "the per-clinic F1 dashboard, the upload pipeline. Stack is " +
      "Next.js, FastAPI, Postgres, and a small Rust audit-rule " +
      "evaluator.",
    background:
      "Production experience shipping Next.js and one of (Python, " +
      "Node, Go). Comfortable owning a feature end-to-end from the " +
      "first PR through the on-call page.",
  },
  {
    team: "DevRel",
    title: "Developer relations — privacy / health-tech",
    blurb:
      "Help privacy officers, IT leads, and clinic CIOs evaluate " +
      "Zorva against their HIA, PIPEDA, and My Health My Data " +
      "obligations. Mostly docs, demos, and the Trust page; " +
      "occasionally a webinar.",
    background:
      "Comfortable talking to both engineers and lawyers. Writing " +
      "samples required.",
  },
  {
    team: "Security",
    title: "Security engineer — SOC 2 preparation + health-data",
    blurb:
      "Drive the SOC 2 Type II preparation roadmap, sub-processor " +
      "review, and incident-response runbook. Work directly with the " +
      "founders and pilot clinics' privacy officers as we build toward " +
      "our first observation window.",
    background:
      "Hands-on experience preparing for SOC 2, HITRUST, or " +
      "an equivalent health-data security framework (readiness, controls mapping, evidence collection). " +
      "Comfortable with Postgres access controls and audit logging.",
  },
];

export default function CareersPage() {
  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <header className={styles.header}>
          <span className={styles.eyebrow}>Careers</span>
          <h1 className={styles.headline}>
            We&rsquo;re not hiring right now — but we&rsquo;d still love to hear from you.
          </h1>
          <p className={styles.subhead}>
            Zorva is a small team building pre-bill audit software for
            Alberta clinics. We open hiring in waves tied to pilot
            growth, so the cleanest way to get on the radar for the next
            wave is a short intro email. No formal application
            portal — just a real human (Cam) reading what you send.
          </p>
        </header>

        <section
          className={styles.openRoles}
          aria-label="Roles we expect to hire for through 2026"
        >
          <h2 className={styles.sectionTitle}>
            Roles we expect to hire for through 2026
          </h2>
          <p className={styles.sectionLede}>
            This isn&rsquo;t a job board — there are no live reqs below.
            It&rsquo;s a list of the kinds of work we&rsquo;ll be scaling
            into as the pilot base grows, so you can self-screen before
            reaching out. If your background maps to one of these, a
            short intro is genuinely welcome.
          </p>
          <ul className={styles.roleList}>
            {FUTURE_ROLES.map((r) => (
              <li key={r.title} className={styles.roleCard}>
                <div className={styles.roleHead}>
                  <span className={styles.teamChip}>{r.team}</span>
                  <h3 className={styles.roleTitle}>{r.title}</h3>
                </div>
                <p className={styles.roleBlurb}>{r.blurb}</p>
                <p className={styles.roleBackground}>
                  <span className={styles.roleBackgroundLabel}>
                    Background that tends to fit:
                  </span>{" "}
                  {r.background}
                </p>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.howToReach} aria-label="How to reach us">
          <h2 className={styles.sectionTitle}>How to reach us</h2>
          <p>
            Send a short intro to{" "}
            <a className={styles.emailLink} href="mailto:careers@ashbi.ca">
              careers@ashbi.ca
            </a>
            . Two or three paragraphs is the sweet spot — what you do
            now, what part of the list above excites you, and one link
            we should look at (a writing sample, a public repo, a " +
            "talk recording, whatever you&rsquo;re proud of). We read
            every intro, even when there isn&rsquo;t a role open yet.
          </p>
          <p>
            If you&rsquo;d rather wait for a specific role to open,
            subscribe to the changelog RSS — every new posting is
            announced there before it goes on any job board.{" "}
            <Link className={styles.inlineLink} href="/changelog">
              Subscribe to changelog
            </Link>
            .
          </p>
        </section>

        <section className={styles.principles} aria-label="How we work">
          <h2 className={styles.sectionTitle}>How we work</h2>
          <ul className={styles.principleList}>
            <li>
              <strong>Calgary-based, remote-first across Canada.</strong>{" "}
              Optional quarterly co-working weeks in Calgary. We sponsor
              TN / intra-company transfers for US-based candidates
              already on the team.
            </li>
            <li>
              <strong>Compensation is transparent.</strong> Same band for
              the same role, posted internally. Equity for every full-time
              hire from the first offer.
            </li>
            <li>
              <strong>Bilingual English / French is a plus, not a gate.</strong>{" "}
              Quebec clinics are on the 2026 roadmap, so French is
              useful but not a hiring requirement.
            </li>
            <li>
              <strong>Health-data seriousness is non-negotiable.</strong>{" "}
              Everyone on the team completes HIA / PIPEDA training in
              their first 30 days, and the security engineer is the
              first reviewer on any code that touches clinical text.
            </li>
          </ul>
        </section>

        <p className={styles.backLink}>
          <Link href="/">&larr; Back to home</Link>
        </p>
      </main>
    </div>
  );
}
