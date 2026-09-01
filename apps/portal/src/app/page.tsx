// / — marketing landing page.
//
// Redesign: warm editorial system repainted onto the portal's
// dark-only design contract. Fraunces serif display + IBM Plex Mono
// micro-labels (both loaded via `next/font/google` in layout.tsx, so
// the production CSP `font-src 'self' data:` is satisfied without an
// external stylesheet fetch). Single clinical-green accent + amber
// reserved for shadow-bill findings. Sections: hero + code-drawn audit
// mockup, rules strip, stats band, walkthrough band, four-step audit
// flow, pillars, security checklist, quote, FAQ (<details> accordions
// — no client JS), CTA band.
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
  "E/M level",
  "NCCI edits",
  "MUE limits",
  "Modifier pairs",
  "Payer policy",
  "AHCIP",
  "SOMB",
];

const STEPS = [
  {
    n: "01",
    title: "Read",
    body: "The auditor ingests the clinical narrative and billed codes for every encounter — no sampling, no queue triage.",
  },
  {
    n: "02",
    title: "Retrieve",
    body: "It pulls the governing rules for each service: AHCIP policy, SOMB schedule items, general rules, and payer edits.",
  },
  {
    n: "03",
    title: "Find",
    body: "Missed codes, underbilled modifiers, and shadow-billed services surface as findings — each citing the exact rule and passage.",
  },
  {
    n: "04",
    title: "Review",
    body: "Your billing team accepts, edits, or dismisses each finding. Nothing is submitted until a human signs off.",
  },
];

const FAQS = [
  {
    q: "Does Zorva submit claims on our behalf?",
    a: "No. Zorva is a pre-submit audit layer. It reads encounters and surfaces findings with rule and passage citations; your billing team reviews and approves each one. Nothing ships until a human signs off.",
  },
  {
    q: "How is pricing structured?",
    a: "A flat monthly fee in three tiers bracketed by audit volume. No percentage of revenue, no per-claim charge, no recovery-linked fee. AKS safe-harbor-aligned for US pilots; published in the executed IMA for Canadian clinics.",
  },
  {
    q: "Where is our data stored?",
    a: "In a single, region-pinned facility documented in your executed IMA / BAA. There is no cross-region replication, no sale of customer data, and no clinical-data analytics egress. Full HIA / PHIPA / HIPAA posture is on the security page.",
  },
  {
    q: "Which rules does the auditor check?",
    a: "Every encounter is checked against AHCIP and the SOMB — E/M level, NCCI edits, MUE limits, modifier pairs, and payer policy. Each finding cites the exact rule and the exact passage in the clinical note it was drawn from.",
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
                Find the revenue your billers are{" "}
                <em>leaving on the table.</em>
              </h1>
              <p className={styles.subhead}>
                Zorva reads every Alberta claim against AHCIP and the
                SOMB before it leaves your desk — catching the missed
                codes, underbilled modifiers, and shadow-billed services
                that quietly drain your monthly revenue. Your billing
                team reviews what it finds. Nothing ships until a human
                signs off.
              </p>
              <div className={styles.ctaRow}>
                <Link href="/contact" className={styles.primary} data-analytics="home_hero_contact">
                  Talk to sales <span className={styles.arr}>→</span>
                </Link>
                <Link href="/how-it-works" className={styles.secondary} data-analytics="home_hero_how_it_works">
                  Calculate your revenue opportunity{" "}
                  <span className={styles.arr}>→</span>
                </Link>
              </div>
              <p className={styles.heroNote}>
                Every finding cites the exact rule and the exact passage
                in the note.
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
                  <span className={styles.code}>03.03A — office visit, age 45–64</span>
                  <span className={styles.val}>$38.03</span>
                </div>
                <div className={styles.claimLine}>
                  <span className={styles.code}>13.59A — diagnostic interview</span>
                  <span className={styles.val}>$72.90</span>
                </div>
                <div className={styles.claimLine}>
                  <span className={styles.code}>08.19A — minor procedure tray</span>
                  <span className={styles.val}>—</span>
                </div>
                <div className={`${styles.finding} ${styles.findingGreen}`}>
                  <div className={styles.findingHead}>
                    <span>Underbilled</span>
                    <span>+ $41.19</span>
                  </div>
                  <p>
                    Narrative supports complex assessment —{" "}
                    <span className={styles.cite}>03.03C</span> — not
                    03.03A. SOMB Schedule, GP section, p. 14; note
                    passage: “45 min, multi-system review…”
                  </p>
                </div>
                <div className={`${styles.finding} ${styles.findingAmber}`}>
                  <div className={styles.findingHead}>
                    <span>Shadow bill missed</span>
                    <span>+ $28.40</span>
                  </div>
                  <p>
                    Tray fee <span className={styles.cite}>08.19A</span>{" "}
                    billable alongside procedure per SOMB GR 4.7. Not
                    claimed on this encounter.
                  </p>
                </div>
              </div>
              <div className={styles.auditFoot}>
                <span data-a11y-tone="secondary">Illustrative data · 2 findings</span>
                <span className={styles.signoff}>Human sign-off required</span>
              </div>
            </div>
          </div>
        </section>

        {/* ── rules strip ──────────────────────────────────── */}
        <div className={styles.rulesStrip}>
          <span className={styles.rulesLabel}>Checked against</span>
          {RULES.map((r) => (
            <span key={r} className={styles.ruleTag}>{r}</span>
          ))}
        </div>

        {/* ── stats band ───────────────────────────────────── */}
        <section className={styles.stats} aria-label="At a glance">
          <div className={styles.stat}>
            <span className={styles.monoTag}>Coverage</span>
            <div className={styles.big}>Every <em>claim</em></div>
            <p className={styles.cap}>
              Audited before submission — not a sample, not just the
              flagged ones.
            </p>
          </div>
          <div className={styles.stat}>
            <span className={styles.monoTag}>Review model</span>
            <div className={styles.big}>Human <em>sign-off</em></div>
            <p className={styles.cap}>
              Nothing leaves your desk until your billing team approves
              it.
            </p>
          </div>
          <div className={styles.stat}>
            <span className={styles.monoTag}>Pricing</span>
            <div className={styles.big}>Flat <em>monthly</em></div>
            <p className={styles.cap}>
              No recovery share, no per-claim charge, no percentage of
              revenue.
            </p>
          </div>
        </section>

        {/* ── walkthrough band ─────────────────────────────── */}
        <section className={styles.walk} aria-label="Product walkthrough — coming soon">
          <div>
            <span className={styles.eyebrow}>Product walkthrough</span>
            <h2 className={styles.h2}>
              See the audit <em>before</em> the claim ships.
            </h2>
            <p className={styles.bodyText}>
              We&apos;re recording a fresh demo. In the meantime, the{" "}
              <Link href="/how-it-works" className={styles.link}>
                how-it-works page
              </Link>{" "}
              walks through the same flow in text — what the auditor
              reads, what rules it pulls, and how the findings surface
              to your billing team for review before anything is
              submitted.
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
        <section className={styles.flow} aria-label="How the audit runs">
          <span className={styles.eyebrow}>How the audit runs</span>
          <h2 className={styles.h2}>
            From encounter note to <em>reviewed</em> claim.
          </h2>
          <p className={styles.flowLede}>
            Four steps, all before submission. Your team stays in
            control of the final word on every claim.
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
        <section className={styles.pillars} aria-label="Why teams switch">
          <span className={styles.eyebrow}>Why teams switch</span>
          <h2 className={styles.h2}>
            Built for billing teams, <em>not</em> around them.
          </h2>

          <div className={styles.pillar}>
            <span className={styles.pillarNum}>/ 01</span>
            <h3 className={styles.pillarTitle}>
              Audit every claim, not just the flagged ones
            </h3>
            <p className={styles.pillarBody}>
              The auditor reads the clinical narrative, the billed
              codes, and the retrieved rules for every encounter — E/M
              level, NCCI edits, MUE limits, modifier pairs, payer
              policy. Findings cite the exact rule and the exact
              passage in the note.
            </p>
          </div>
          <div className={styles.pillar}>
            <span className={styles.pillarNum}>/ 02</span>
            <h3 className={styles.pillarTitle}>Region-pinned data</h3>
            <p className={styles.pillarBody}>
              Your data is stored in a single, region-pinned facility
              documented in the executed IMA / BAA. No cross-region
              replication, no sale of customer data, no clinical-data analytics
              egress. The current HIA / PHIPA / HIPAA posture is
              detailed on the{" "}
              <Link href="/security" className={styles.link}>
                security page
              </Link>
              .
            </p>
          </div>
          <div className={styles.pillar}>
            <span className={styles.pillarNum}>/ 03</span>
            <h3 className={styles.pillarTitle}>
              Flat monthly fee, no recovery share
            </h3>
            <p className={styles.pillarBody}>
              No percentage of revenue, no per-claim charge, no
              recovery-linked fee. Three tiers bracketed by audit
              volume. Pricing and data-handling terms are documented
              in the executed agreement for legal and operational review.
            </p>
          </div>
        </section>

        {/* ── security checklist ───────────────────────────── */}
        <section className={styles.security} aria-label="Security and compliance">
          <span className={styles.eyebrow}>Security and compliance</span>
          <h2 className={styles.h2}>
            Your data stays where <em>you</em> put it.
          </h2>
          <p className={styles.bodyText}>
            Clinic data never moves across regions, never trains shared
            models, and never leaves the facility documented in your
            executed agreement.
          </p>
          <div className={styles.checkList}>
            <div className={styles.checkItem}>
              <CheckIcon />
              <div>
                <span className={styles.checkKey}>
                  Single region-pinned facility
                </span>{" "}
                <span className={styles.checkDesc}>
                  — named in the executed IMA / BAA.
                </span>
              </div>
            </div>
            <div className={styles.checkItem}>
              <CheckIcon />
              <div>
                <span className={styles.checkKey}>
                  No cross-region replication
                </span>{" "}
                <span className={styles.checkDesc}>
                  — no sale of customer data or clinical-data analytics egress.
                </span>
              </div>
            </div>
            <div className={styles.checkItem}>
              <CheckIcon />
              <div>
                <span className={styles.checkKey}>
                  HIA / PHIPA / HIPAA posture
                </span>{" "}
                <span className={styles.checkDesc}>
                  — documented in full on the{" "}
                  <Link href="/security" className={styles.link}>
                    security page
                  </Link>
                  .
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* ── quote ────────────────────────────────────────── */}
        <section className={styles.quote} aria-label="Review principle">
          <p className={styles.blockquote}>
            Findings are designed to show the <strong>rule, passage,
            and estimated impact</strong> so a biller can make the final call.
          </p>
          <div className={styles.quoteAttr}>Human review remains required</div>
        </section>

        {/* ── faq ──────────────────────────────────────────── */}
        <section className={styles.faq} aria-label="Common questions">
          <span className={styles.eyebrow}>Common questions</span>
          <h2 className={styles.h2}>
            What counsel and billing <em>leads</em> ask.
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
            Want the full picture <em>first?</em>
          </h2>
          <p className={styles.ctaText}>
            Pricing, the audit flow, and our compliance posture —
            everything counsel and your billing lead will ask about, in
            plain language.
          </p>
          <div className={styles.ctaRowCenter}>
            <Link href="/pricing" className={styles.primaryInverse} data-analytics="home_bottom_pricing">
              See pricing <span className={styles.arr}>→</span>
            </Link>
            <Link href="/how-it-works" className={styles.secondaryInverse}>
              How it works <span className={styles.arr}>→</span>
            </Link>
          </div>
          <div className={styles.ctaLinks}>
            <Link href="/pricing">Pricing</Link>
            <span aria-hidden="true">·</span>
            <Link href="/how-it-works">How it works</Link>
            <span aria-hidden="true">·</span>
            <Link href="/security">Security and compliance</Link>
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
          <span aria-hidden="true">·</span>
          <Link href="/legal/privacy">Privacy</Link>
          <span aria-hidden="true">·</span>
          <Link href="/legal/terms">Terms</Link>
        </div>
        <p>Questions? Email us at hello@ashbi.ca</p>
      </footer>
    </div>
  );
}
