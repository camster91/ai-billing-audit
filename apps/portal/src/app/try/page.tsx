// /try — public sandbox demonstrating Zorva's pre-submission audit on a
// synthetic AHCIP encounter. Goal: drop cold-outreach prospects onto a page
// that shows real-looking audit findings in <30s, with no PHI required,
// no signup, no upload. (research/P0-PRODUCT-ROADMAP.md W1.1, gap G9 in
// research/P6-product-gaps.md.)
//
// Synthetic-data banner is rendered at top + bottom of the encounter to
// keep the page HIA-clean: no real patient data, no audit chain write,
// no portal account. Closing CTA points at /demo-request for the real
// thing.

import type { Metadata } from "next";
import Link from "next/link";
import { TRY_DEMO } from "@/data/try-demo";
import type { CannedFinding } from "@/data/try-demo";
import styles from "./try.module.css";

export const metadata: Metadata = {
  title: "Try Zorva — no signup, synthetic data",
  description:
    "See a real Zorva AHCIP audit output in 30 seconds. Synthetic patient encounter, canned findings, no PHI uploaded, no signup.",
  // Tell search engines not to index the demo (the canned encounter is
  // technically public but we don't want it ranked as "Zorva demo").
  robots: { index: false, follow: true },
};

// Severity → badge class. Mirrors the bucket-style colours used on
// /dashboard so cold prospects get the same visual language the
// portal's actual biller users see.
function severityClass(sev: CannedFinding["severity"]): string {
  switch (sev) {
    case "critical":
      return styles.severityCritical;
    case "high":
      return styles.severityHigh;
    case "medium":
      return styles.severityMedium;
    case "low":
      return styles.severityLow;
    case "info":
    default:
      return styles.severityInfo;
  }
}

export default function TryPage() {
  const { encounter, findings } = TRY_DEMO;

  // Findings with action-required severities first (medium+), then info.
  // Same priority mental-model as the FPAR tile (CalibrationCard /
  // apps/portal/src/components/calibration-card.tsx).
  const orderedFindings = [...findings].sort((a, b) => {
    const order = { critical: 0, high: 1, medium: 2, low: 3, info: 4 } as const;
    return order[a.severity] - order[b.severity];
  });

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>Try Zorva</span>
        <h1>A real AHCIP audit, on synthetic data, in 30&nbsp;seconds.</h1>
        <p>
          Below is the actual output of Zorva&apos;s auditor on a synthetic
          new-patient consultation. No signup, no upload, no real patient
          data — just what your biller would see after dropping an
          encounter into the portal.
        </p>
        <p className={styles.syntheticBanner} role="status">
          <strong>Synthetic data only.</strong> This encounter is
          fabricated for demonstration. No PHI, no HIA-protected data, no
          audit trail written. Per
          {" "}<a href="/legal/privacy">privacy policy</a>.
        </p>
      </header>

      <main className={styles.main}>
        <section className={styles.encounter} aria-label="Synthetic encounter">
          <h2 className={styles.sectionTitle}>The encounter</h2>

          <div className={styles.encounterMeta}>
            <span className={styles.metaPill}>
              {encounter.market}/{encounter.province}
            </span>
            <span className={styles.metaPill}>{encounter.compliance_law}</span>
            <span className={styles.metaPill}>{encounter.encounter_id}</span>
          </div>

          <details className={styles.noteBlock} open>
            <summary>Clinical note</summary>
            <p>{encounter.clinical_note}</p>
          </details>

          <details className={styles.claimBlock}>
            <summary>The billed claim</summary>
            <table className={styles.claimTable}>
              <tbody>
                <tr>
                  <th scope="row">SOMB code(s)</th>
                  <td>{encounter.claim.som_b_codes.join(", ")}</td>
                </tr>
                <tr>
                  <th scope="row">Diagnosis codes</th>
                  <td>{encounter.claim.diagnosis_codes.join(", ")}</td>
                </tr>
                <tr>
                  <th scope="row">Modifier</th>
                  <td>
                    {encounter.claim.modifier === null
                      ? <span className={styles.nullHint}>(none on claim)</span>
                      : encounter.claim.modifier}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Date of service</th>
                  <td>{encounter.claim.date_of_service}</td>
                </tr>
                <tr>
                  <th scope="row">Referring provider</th>
                  <td>
                    {encounter.claim.referring_provider_npi === null
                      ? <span className={styles.nullHint}>(none on claim)</span>
                      : encounter.claim.referring_provider_npi}
                  </td>
                </tr>
              </tbody>
            </table>
          </details>
        </section>

        <section className={styles.findings} aria-label="Audit findings">
          <h2 className={styles.sectionTitle}>
            {findings.length} findings the auditor flagged
          </h2>

          <ol className={styles.findingsList}>
            {orderedFindings.map((f) => (
              <li key={f.rule_id} className={styles.finding}>
                <div className={styles.findingHeader}>
                  <span
                    className={`${styles.severityBadge} ${severityClass(f.severity)}`}
                    aria-label={`Severity: ${f.severity}`}
                  >
                    {f.severity}
                  </span>
                  <code className={styles.ruleId}>{f.rule_id}</code>
                  <span className={styles.category}>{f.category}</span>
                </div>

                <p className={styles.explanation}>{f.explanation}</p>

                <details className={styles.quoteBlock}>
                  <summary>Anchored to</summary>
                  <blockquote>{f.quote}</blockquote>
                </details>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.summary} aria-label="Why this matters">
          <h2 className={styles.sectionTitle}>What your biller does next</h2>
          <ol className={styles.billerSteps}>
            <li>
              <strong>Accept the rule.</strong> The finding is correct
              (e.g., add Dr. Smith&apos;s practitioner ID to the claim) —
              one tap in the portal.
            </li>
            <li>
              <strong>Dismiss with reason.</strong> The finding is wrong
              for this clinic (e.g., the visit really is consultation
              only) — choose a reason, add a note if needed.
            </li>
            <li>
              <strong>Move on.</strong> Everything else gets a pass-through
              rating in your per-rule calibration dashboard — see
              {" "}<Link href="/dashboard">/dashboard</Link> for an example
              (you&apos;ll need a free account).
            </li>
          </ol>
        </section>

        <section className={styles.cta} aria-label="Talk to us">
          <h2>Want this on your actual claims?</h2>
          <p>
            30-minute demo on your own encounters. No PHI uploaded until
            you sign the HIA Information Manager Agreement (see
            {" "}<Link href="/security">/security</Link>).
          </p>
          <Link href="/demo-request" className={styles.ctaButton}>
            Book a 30-min demo →
          </Link>
        </section>
      </main>

      <footer className={styles.footer}>
        <p className={styles.syntheticBanner} role="status">
          <strong>Synthetic data only.</strong> This encounter is
          fabricated for demonstration. No PHI, no HIA-protected data, no
          audit trail written. Canned findings from
          {" "}<code>runs/recall/v12_ahcip_clean.json</code>.
        </p>
        <p className={styles.footerNav}>
          <Link href="/">Home</Link> ·{" "}
          <Link href="/how-it-works">How it works</Link> ·{" "}
          <Link href="/pricing">Pricing</Link> ·{" "}
          <Link href="/legal/privacy">Privacy</Link>
        </p>
      </footer>
    </div>
  );
}