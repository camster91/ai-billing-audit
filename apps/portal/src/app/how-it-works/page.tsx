import type { Metadata } from "next";
import Link from "next/link";
import styles from "./how-it-works.module.css";

export const metadata: Metadata = {
  title: "How it works | A human-reviewed pre-submit workflow",
  description:
    "A plain-language introduction to Zorva's human-reviewed pre-submit workflow for clinic billing teams.",
  alternates: { canonical: "/how-it-works" },
};

const STEPS = [
  {
    title: "Bring an encounter into review",
    body: "Start with the encounter narrative and billed services your team wants to assess before submission.",
  },
  {
    title: "Review the available context",
    body: "The workflow is designed to place billing context and supporting references beside the encounter, so a biller can assess the next action without reconstructing the review from memory.",
  },
  {
    title: "Make the decision as a team",
    body: "Your billing team decides whether to act on a review item. Zorva does not replace clinical or billing judgment and does not submit claims on your behalf.",
  },
] as const;

export default function HowItWorksPage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>How it works</span>
        <h1>A practical review path before a claim is submitted.</h1>
        <p>
          Zorva is designed to sit alongside your existing billing process.
          Your team reviews the available context and keeps the final decision
          about what, if anything, is submitted.
        </p>
      </header>

      <main className={styles.main} id="main">
        <section className={styles.steps} aria-label="The review path">
          {STEPS.map((step, index) => (
            <article key={step.title} className={styles.step}>
              <div className={styles.stepHeader}>
                <span className={styles.stepNumber} aria-hidden="true">
                  {index + 1}
                </span>
              </div>
              <h2>{step.title}</h2>
              <p className={styles.stepDesc}>{step.body}</p>
            </article>
          ))}
        </section>

        <section className={styles.ctaSection}>
          <h2 className={styles.ctaHeading}>
            Start with the questions your team needs answered.
          </h2>
          <p className={styles.ctaSub}>
            We can discuss your current workflow, the information your team
            needs in a review, and whether Zorva is an appropriate fit.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/contact" className={styles.ctaButton}>
              Start a conversation
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}
