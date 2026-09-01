// / — marketing landing page.
//
// The editorial layout is intentionally claim-light. Public wording is limited
// to the Alberta-first, human-reviewed workflow and conversation CTA approved
// by docs/MASTER_PLAN.md. Pricing, performance, savings, infrastructure,
// compliance, and customer-result claims remain off this indexable route until
// their evidence and accountable approvals exist.
//
// Server component — no hooks, no fetch. The FAQ uses native
// <details>/<summary> so the whole page ships zero client JavaScript
// beyond Next's runtime.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./page.module.css";

const SITE_URL = "https://zorva.ashbi.ca";

export const metadata: Metadata = {
  title: "Zorva — AI pre-bill audit for Alberta clinics",
  description:
    "Explore Zorva's human-reviewed pre-submit billing workflow for Alberta clinics, including AHCIP and SOMB context.",
  alternates: { canonical: SITE_URL },
  openGraph: {
    title: "Zorva — AI pre-bill audit for Alberta clinics",
    description:
      "A human-reviewed pre-submit workflow for Alberta billing teams.",
    url: SITE_URL,
  },
};

const RULES = [
  "Encounter narrative",
  "Billed services",
  "AHCIP context",
  "SOMB context",
  "Supporting references",
  "Biller decision",
];

const STEPS = [
  {
    n: "01",
    title: "Bring",
    body: "Bring the encounter narrative and billed services your team wants to assess into one review path.",
  },
  {
    n: "02",
    title: "Review",
    body: "Place the available billing context and supporting references beside the encounter for assessment.",
  },
  {
    n: "03",
    title: "Decide",
    body: "Your billing team decides whether to act, investigate further, or leave the claim unchanged.",
  },
  {
    n: "04",
    title: "Record",
    body: "Keep the review decision connected to the workflow without handing submission control to Zorva.",
  },
];

const FAQS = [
  {
    q: "Does Zorva submit claims on our behalf?",
    a: "No. Zorva is designed as a pre-submit review step. Your clinic's authorized billing team keeps the final decision about what, if anything, is submitted.",
  },
  {
    q: "Who is the current conversation for?",
    a: "We are initially exploring fit with Alberta primary-care teams using AHCIP, with a named billing-workflow owner and a human reviewer who remains responsible for submission decisions.",
  },
  {
    q: "What should we share in a first conversation?",
    a: "Non-clinical workflow context: who owns review, where context is assembled, and what creates rework. Do not send patient, claim, credential, or other sensitive production information through the contact form.",
  },
  {
    q: "Can we start using it immediately?",
    a: "The current public step is a reviewed request for a conversation, not self-serve production access. Product fit, privacy, onboarding, and any pilot terms must be reviewed first.",
  },
];

function CheckIcon() {
  return (
    <svg
      className={styles.checkIcon}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="7.5" stroke="currentColor" />
      <path
        d="M5 8.2l2 2 4-4.4"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Home() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        {/* ── hero ─────────────────────────────────────────── */}
        <section className={styles.hero}>
          <span className={styles.eyebrow}>
            Pre-submit audit for Alberta clinic billing teams
          </span>
          <div className={styles.heroGrid}>
            <div>
              <h1 className={styles.headline}>
                Review Alberta claims with your billing team{" "}
                <em>in control.</em>
              </h1>
              <p className={styles.subhead}>
                Zorva is designed as a human-reviewed, pre-submit AHCIP
                workflow for Alberta primary-care billing teams. Bring the
                available context into review, assess the next action, and keep
                the final submission decision with your clinic.
              </p>
              <div className={styles.ctaRow}>
                <Link href="/contact" className={styles.primary} data-analytics="home_hero_contact">
                  Start a conversation <span className={styles.arr}>→</span>
                </Link>
                <Link href="/how-it-works" className={styles.secondary} data-analytics="home_hero_how_it_works">
                  See how review works{" "}
                  <span className={styles.arr}>→</span>
                </Link>
              </div>
              <p className={styles.heroNote}>
                Start with workflow questions, not patient or claim data.
              </p>
            </div>

            {/* code-drawn audit mockup */}
            <div className={styles.audit} aria-label="Example pre-submit review">
              <div className={styles.auditBar} data-a11y-tone="secondary">
                <span className={styles.dots} aria-hidden="true">
                  <span /><span /><span />
                </span>
                ZORVA / ILLUSTRATIVE PRE-SUBMIT REVIEW
                <span className={styles.auditFile}>encounter_0417.xml</span>
              </div>
              <div className={styles.auditBody}>
                <div className={styles.claimLine}>
                  <span className={styles.code}>Encounter narrative</span>
                  <span className={styles.val}>Available</span>
                </div>
                <div className={styles.claimLine}>
                  <span className={styles.code}>Billed services</span>
                  <span className={styles.val}>Available</span>
                </div>
                <div className={styles.claimLine}>
                  <span className={styles.code}>Supporting context</span>
                  <span className={styles.val}>Review</span>
                </div>
                <div className={`${styles.finding} ${styles.findingGreen}`}>
                  <div className={styles.findingHead}>
                    <span>Review item</span>
                    <span>Biller decision</span>
                  </div>
                  <p>
                    The available context raises a billing question worth
                    reviewing. Confirm the applicable guidance and decide
                    whether any change is appropriate.
                  </p>
                </div>
                <div className={`${styles.finding} ${styles.findingAmber}`}>
                  <div className={styles.findingHead}>
                    <span>Supporting reference</span>
                    <span>Check source</span>
                  </div>
                  <p>
                    Keep the source and review context beside the item so the
                    authorized biller can assess it without an automatic
                    submission decision.
                  </p>
                </div>
              </div>
              <div className={styles.auditFoot}>
                <span data-a11y-tone="secondary">Illustrative workflow · no patient data</span>
                <span className={styles.signoff}>Human decision required</span>
              </div>
            </div>
          </div>
        </section>

        {/* ── rules strip ──────────────────────────────────── */}
        <div className={styles.rulesStrip}>
          <span className={styles.rulesLabel}>Review context</span>
          {RULES.map((r) => (
            <span key={r} className={styles.ruleTag}>{r}</span>
          ))}
        </div>

        {/* ── stats band ───────────────────────────────────── */}
        <section className={styles.stats} aria-label="At a glance">
          <div className={styles.stat}>
            <span className={styles.monoTag}>Focus</span>
            <div className={styles.big}>Before <em>submission</em></div>
            <p className={styles.cap}>
              Add a deliberate review step before the clinic makes its final
              claim decision.
            </p>
          </div>
          <div className={styles.stat}>
            <span className={styles.monoTag}>Review model</span>
            <div className={styles.big}>Human <em>decision</em></div>
            <p className={styles.cap}>
              The authorized billing team decides whether to act on a review
              item.
            </p>
          </div>
          <div className={styles.stat}>
            <span className={styles.monoTag}>Current entry</span>
            <div className={styles.big}>Conversation <em>first</em></div>
            <p className={styles.cap}>
              Fit, privacy, onboarding, and pilot terms are reviewed before
              production use.
            </p>
          </div>
        </section>

        {/* ── walkthrough band ─────────────────────────────── */}
        <section className={styles.walk} aria-label="Product walkthrough — coming soon">
          <div>
            <span className={styles.eyebrow}>Product walkthrough</span>
            <h2 className={styles.h2}>
              See the review path <em>before</em> sharing data.
            </h2>
            <p className={styles.bodyText}>
              We&apos;re recording a fresh demo. In the meantime, the{" "}
              <Link href="/how-it-works" className={styles.link}>
                how-it-works page
              </Link>{" "}
              explains how encounter context, supporting references, and a
              human decision fit together before submission.
            </p>
          </div>
          <div className={styles.videoShell}>
            <div className={styles.videoInner}>
              <span className={styles.videoMono}>Recording in progress</span>
              <strong>Walkthrough coming soon</strong>
              <span>
                The{" "}
                <Link href="/how-it-works" className={styles.videoLink}>
                  how-it-works page
                </Link>{" "}
                covers the same flow in text.
              </span>
            </div>
          </div>
        </section>

        {/* ── four-step flow ───────────────────────────────── */}
        <section className={styles.flow} aria-label="How the review works">
          <span className={styles.eyebrow}>How the review works</span>
          <h2 className={styles.h2}>
            From available context to a <em>human</em> decision.
          </h2>
          <p className={styles.flowLede}>
            Four steps before submission, with your clinic retaining control
            of the final decision.
          </p>
          <div className={styles.steps}>
            {STEPS.map((s) => (
              <div key={s.n} className={styles.step}>
                <div className={styles.ring}>{s.n}</div>
                <h3 className={styles.stepTitle}>{s.title}</h3>
                <p className={styles.stepBody}>{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── pillars ──────────────────────────────────────── */}
        <section className={styles.pillars} aria-label="Workflow principles">
          <span className={styles.eyebrow}>Workflow principles</span>
          <h2 className={styles.h2}>
            Designed around accountable <em>review.</em>
          </h2>

          <div className={styles.pillar}>
            <span className={styles.pillarNum}>/ 01</span>
            <h3 className={styles.pillarTitle}>
              Bring review context together
            </h3>
            <p className={styles.pillarBody}>
              Place the encounter narrative, billed services, and available
              supporting references in one path so the biller can assess the
              next action deliberately.
            </p>
          </div>
          <div className={styles.pillar}>
            <span className={styles.pillarNum}>/ 02</span>
            <h3 className={styles.pillarTitle}>Keep the decision with the clinic</h3>
            <p className={styles.pillarBody}>
              Zorva does not submit claims on the clinic&apos;s behalf. The
              authorized billing team decides whether a review item warrants a
              change, more investigation, or no action.
            </p>
          </div>
          <div className={styles.pillar}>
            <span className={styles.pillarNum}>/ 03</span>
            <h3 className={styles.pillarTitle}>
              Start with a bounded fit conversation
            </h3>
            <p className={styles.pillarBody}>
              The public next step is a reviewed conversation about the current
              workflow. Pricing, production access, and pilot terms are not
              offered through this page.
            </p>
          </div>
        </section>

        {/* ── security checklist ───────────────────────────── */}
        <section className={styles.security} aria-label="Operating boundaries">
          <span className={styles.eyebrow}>Operating boundaries</span>
          <h2 className={styles.h2}>
            Clear limits before a <em>pilot</em> begins.
          </h2>
          <p className={styles.bodyText}>
            A first conversation should establish fit and required review. It
            should not collect clinic production data or imply terms that have
            not been approved.
          </p>
          <div className={styles.checkList}>
            <div className={styles.checkItem}>
              <CheckIcon />
              <div>
                <span className={styles.checkKey}>
                  No autonomous submission
                </span>{" "}
                <span className={styles.checkDesc}>
                  — the clinic&apos;s authorized biller keeps the final decision.
                </span>
              </div>
            </div>
            <div className={styles.checkItem}>
              <CheckIcon />
              <div>
                <span className={styles.checkKey}>
                  No outcome promise
                </span>{" "}
                <span className={styles.checkDesc}>
                  — no savings, recovery, accuracy, or ROI guarantee is made.
                </span>
              </div>
            </div>
            <div className={styles.checkItem}>
              <CheckIcon />
              <div>
                <span className={styles.checkKey}>
                  No sensitive data in first contact
                </span>{" "}
                <span className={styles.checkDesc}>
                  — discuss workflow only until privacy and onboarding review is complete.
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* ── quote ────────────────────────────────────────── */}
        <section className={styles.quote} aria-label="Review principle">
          <p className={styles.blockquote}>
            A useful review supports the <strong>person accountable for the
            decision</strong>; it does not remove them from the workflow.
          </p>
          <div className={styles.quoteAttr}>Human review remains required</div>
        </section>

        {/* ── faq ──────────────────────────────────────────── */}
        <section className={styles.faq} aria-label="Common questions">
          <span className={styles.eyebrow}>Common questions</span>
          <h2 className={styles.h2}>
            What clinic teams ask <em>first.</em>
          </h2>
          {FAQS.map((f) => (
            <details key={f.q} className={styles.faqItem}>
              <summary className={styles.faqQ}>
                {f.q}
                <span className={styles.faqPm} aria-hidden="true">+</span>
              </summary>
              <p className={styles.faqA}>{f.a}</p>
            </details>
          ))}
        </section>

        {/* ── cta band ─────────────────────────────────────── */}
        <section className={styles.ctaBand} aria-label="Next steps">
          <h2 className={styles.ctaTitle}>
            Start with your current <em>workflow.</em>
          </h2>
          <p className={styles.ctaText}>
            Tell us who owns review today, where context is assembled, and what
            your team needs before deciding whether a controlled evaluation is
            appropriate.
          </p>
          <div className={styles.ctaRowCenter}>
            <Link href="/contact" className={styles.primaryInverse} data-analytics="home_bottom_contact">
              Start a conversation <span className={styles.arr}>→</span>
            </Link>
            <Link href="/how-it-works" className={styles.secondaryInverse}>
              How it works <span className={styles.arr}>→</span>
            </Link>
          </div>
          <div className={styles.ctaLinks}>
            <Link href="/contact">Contact</Link>
            <span aria-hidden="true">·</span>
            <Link href="/how-it-works">How it works</Link>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerLinks}>
          <Link href="/how-it-works">How it works</Link>
          <span aria-hidden="true">·</span>
          <Link href="/contact">Contact</Link>
        </div>
        <p>Questions? Email us at hello@ashbi.ca</p>
      </footer>
    </div>
  );
}
