import type { Metadata } from "next";
import Link from "next/link";
import styles from "./page.module.css";

const SITE_URL = "https://zorva.ashbi.ca";

export const metadata: Metadata = {
  title: "Zorva | Pre-submit review for Alberta clinic billing teams",
  description:
    "Explore Zorva's human-reviewed pre-submit billing workflow for Alberta clinics and how to request a conversation.",
  alternates: { canonical: SITE_URL },
  openGraph: {
    title: "Zorva | Pre-submit review for Alberta clinic billing teams",
    description:
      "A human-reviewed pre-submit workflow for billing teams that want a clearer review queue before claims are sent.",
    url: SITE_URL,
  },
};

const STEPS = [
  {
    number: "01",
    title: "Bring the encounter into review",
    body: "Start with the encounter narrative and billed services your team wants to review before submission.",
  },
  {
    number: "02",
    title: "Compare against the relevant context",
    body: "The workflow is designed to put billing context and source references beside the encounter instead of asking a biller to reconstruct them from memory.",
  },
  {
    number: "03",
    title: "Review findings as a team",
    body: "Your team can assess a finding, its supporting context, and the next action in one review surface.",
  },
  {
    number: "04",
    title: "Keep the final decision human",
    body: "Zorva supports review; it does not replace the billing team's judgment or submit a claim on its own.",
  },
];

const PRINCIPLES = [
  ["Built around review", "Keep the biller in control of the decision, context, and follow-up."],
  ["Traceable context", "Make it easier to see the rule or note passage behind a finding."],
  ["A deliberate rollout", "Start with a conversation about your clinic, workflow, and readiness."],
] as const;

function Arrow() {
  return <span aria-hidden="true">→</span>;
}

export default function Home() {
  return (
    <div className={styles.page}>
      <main id="main">
        <section className={styles.hero} aria-labelledby="hero-title">
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>For Alberta clinic billing teams</p>
            <h1 id="hero-title">
              Give every claim a more deliberate <em>last look.</em>
            </h1>
            <p className={styles.lede}>
              Zorva is a pre-submit review workflow for teams that want a
              clearer way to assess billing context before a claim leaves the
              clinic. The final decision stays with your people.
            </p>
            <div className={styles.actions}>
              <Link className={styles.primaryAction} href="/contact">
                Start a conversation <Arrow />
              </Link>
              <Link className={styles.secondaryAction} href="/how-it-works">
                See how the workflow works <Arrow />
              </Link>
            </div>
            <p className={styles.heroNote}>
              No automatic claim submission. No replacement for clinical or
              billing judgment.
            </p>
          </div>

          <aside className={styles.reviewCard} aria-label="Illustrative pre-submit review">
            <div className={styles.reviewTopline}>
              <span>Illustrative review</span>
              <span>Pre-submit</span>
            </div>
            <div className={styles.reviewBody}>
              <div className={styles.reviewHeader}>
                <span>Encounter queue</span>
                <span className={styles.status}>Ready for review</span>
              </div>
              <div className={styles.reviewRow}>
                <span>Billing context</span>
                <strong>Included</strong>
              </div>
              <div className={styles.reviewRow}>
                <span>Supporting reference</span>
                <strong>Linked</strong>
              </div>
              <div className={styles.finding}>
                <p className={styles.findingLabel}>Review prompt</p>
                <p>
                  Confirm that the billed service and the documented encounter
                  support the intended submission.
                </p>
                <span>Illustrative only — not patient data</span>
              </div>
            </div>
            <div className={styles.reviewFooter}>
              <span>Human decision required</span>
              <span>01 item</span>
            </div>
          </aside>
        </section>

        <section className={styles.signalBand} aria-label="What Zorva is designed to support">
          <p>Designed to support</p>
          <ul>
            <li>Pre-submit review</li>
            <li>Billing context</li>
            <li>Human decision-making</li>
            <li>Clinic-led rollout</li>
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="workflow-title">
          <p className={styles.eyebrow}>A clearer review path</p>
          <div className={styles.sectionHeading}>
            <h2 id="workflow-title">From encounter to a decision your team can stand behind.</h2>
            <p>
              The workflow is intentionally simple: put the relevant context in
              front of the right person, then make the review and next action
              explicit.
            </p>
          </div>
          <ol className={styles.steps}>
            {STEPS.map((step) => (
              <li key={step.number} className={styles.step}>
                <span className={styles.stepNumber}>{step.number}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.principles} aria-labelledby="principles-title">
          <div>
            <p className={styles.eyebrow}>The working principles</p>
            <h2 id="principles-title">Useful review software should feel calm, legible, and accountable.</h2>
          </div>
          <div className={styles.principleList}>
            {PRINCIPLES.map(([title, body], index) => (
              <article key={title} className={styles.principle}>
                <span>0{index + 1}</span>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className={styles.cta} aria-labelledby="cta-title">
          <p className={styles.eyebrow}>Start with your workflow</p>
          <h2 id="cta-title">See whether a more deliberate pre-submit review fits your clinic.</h2>
          <p>
            Start with a practical conversation about your billing process,
            current tools, and the questions your team needs answered.
          </p>
          <Link className={styles.inverseAction} href="/contact">
            Contact Zorva <Arrow />
          </Link>
        </section>
      </main>

      <footer className={styles.footer}>
        <p>Zorva</p>
        <nav aria-label="Footer">
          <Link href="/how-it-works">How it works</Link>
          <Link href="/contact">Contact</Link>
        </nav>
      </footer>
    </div>
  );
}
