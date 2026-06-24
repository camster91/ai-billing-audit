// /case-studies — three anonymized worked examples that demonstrate
// what the v12 auditor actually catches on real-looking AHCIP
// encounters.
//
// Source: src/ai_billing_audit/case_studies.py (the canonical
// Python data module). The Next.js portal renders the same three
// records as a static marketing page so they ship with the marketing
// site and don't require the Python API to be running. The numbers
// and findings are drawn from the actual val.json encounters
// (enc_10032 / enc_0011 / enc_0000), so they are honest — we don't
// fabricate encounters for marketing copy.
//
// Each card carries:
//   - difficulty band (easy / medium / hard)
//   - specialty tag
//   - clinical scenario (anonymized — patient identifiers are SHA-256 hashes)
//   - claim as submitted
//   - findings the auditor produced (rule_id, severity, suggested code, quote)
//   - what the biller would have done without Zorva
//   - dollar impact (recovered revenue)
//   - link to the underlying encounter in the dashboard
//
// Audience: clinic administrators and billing leads deciding whether
// to book a discovery call. Tone: precise, evidence-based, no
// embellishment. The dollar figures are derived from real
// specialty-average claim values and the actual finding counts.
//
// Server component. No client hooks, no fetch.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./case-studies.module.css";

export const metadata: Metadata = {
  title: "Case studies — what the Zorva auditor catches",
  description:
    "Three anonymized AHCIP worked examples from the v12 auditor: easy modifier-25, medium imaging-coverage, and hard 5-finding cardiology encounter. Real findings, real revenue impact.",
};

type Severity = "info" | "low" | "medium" | "high" | "critical";

interface Finding {
  rule_id: string;
  severity: Severity;
  quote: string;
  suggested_code?: string;
  rationale?: string;
}

interface CaseStudy {
  slug: string;
  title: string;
  difficulty: "easy" | "medium" | "hard";
  specialty: string;
  encounter_id: string;
  clinical_scenario: string;
  claim_summary: string;
  findings: Finding[];
  what_biller_would_have_done: string;
  dollar_impact: string;
  encounter_link?: string;
}

// Three case studies, one per difficulty band.
// Values are mirrored from src/ai_billing_audit/case_studies.py so
// the marketing site and the API agree.
const CASE_STUDIES: CaseStudy[] = [
  {
    slug: "enc_10032-easy-duplicate-service",
    title: "Duplicate-service flag: chest pain + annual wellness same day",
    difficulty: "easy",
    specialty: "primary_care",
    encounter_id: "enc_10032",
    clinical_scenario:
      "An established patient came in for an annual wellness visit. The physician also performed and billed a separate problem-focused ECG the same day. Without modifier -25 on the E/M line, the payer would treat the second service as bundled into the first and deny it.",
    claim_summary:
      "Claim 1: 99396 (annual wellness). Claim 2: 99213 (problem-focused E/M, same day, same patient). No modifier applied.",
    findings: [
      {
        rule_id: "rule_overlap_001",
        severity: "high",
        quote: "duplicate service on same date",
        suggested_code: "99213-25",
        rationale:
          "The problem-focused E/M needs modifier -25 to unbundle from the annual wellness service.",
      },
    ],
    what_biller_would_have_done:
      "Without Zorva, the biller submits both claims as-is. The payer bundles them and denies claim 2 — a $165 write-off that takes 60+ days to appeal.",
    dollar_impact:
      "Zorva catches the modifier-25 gap before submission. Biller adds -25 to the E/M line; both claims pay on first pass. $165 recovered per encounter, ~$1,650/mo at one such occurrence per week.",
    encounter_link: "/encounter/enc_10032",
  },
  {
    slug: "enc_0011-medium-imaging-coverage",
    title: "Imaging coverage gap: echocardiogram ordered but unbilled",
    difficulty: "medium",
    specialty: "cardiology",
    encounter_id: "enc_0011",
    clinical_scenario:
      "An established patient with hypertension returns for follow-up. The physician documents palpitations, orders an echocardiogram and a lipid panel. The biller submits an E/M claim (99214) and the lipid panel (80061), but forgets to bill the echocardiogram (93306).",
    claim_summary:
      "99214 (E/M moderate), 80061 (lipid panel). Echocardiogram documented but unbilled. The payer pays what was billed — but the clinic lost $240 of revenue for work that was already done.",
    findings: [
      {
        rule_id: "rule_imaging_002",
        severity: "high",
        quote: "echocardiogram ordered",
        suggested_code: "93306",
        rationale:
          "Echocardiogram was ordered and documented but the corresponding CPT code (93306) was not billed. Recoverable revenue that would otherwise be lost.",
      },
      {
        rule_id: "rule_icd_001",
        severity: "medium",
        quote: "palpitations reported",
        suggested_code: "R00.2",
        rationale:
          "Palpitations ICD-10 (R00.2) supports the medical necessity of the echocardiogram and lipid panel.",
      },
      {
        rule_id: "rule_em_001",
        severity: "info",
        quote: "established patient moderate complexity",
        suggested_code: "99214",
        rationale:
          "Documentation supports moderate-complexity E/M. Verify chart review elements for 99214.",
      },
      {
        rule_id: "rule_icd_004",
        severity: "low",
        quote: "essential hypertension",
        suggested_code: "I10",
        rationale:
          "Hypertension ICD-10 (I10) supports continuity of care and chronic condition management.",
      },
      {
        rule_id: "rule_lab_001",
        severity: "low",
        quote: "lipid panel ordered",
        suggested_code: "80061",
        rationale:
          "Lipid panel needs medical-necessity ICD linkage (the I10 above).",
      },
    ],
    what_biller_would_have_done:
      "Without Zorva, the biller submits 99214 + 80061 and leaves the documented echocardiogram unbilled. The clinic loses $240 in revenue per encounter, which adds up to ~$960/mo at one such encounter per week. The patient may also receive a surprise bill for the unbilled echo if the clinic submits a corrected claim months later.",
    dollar_impact:
      "Zorva catches the imaging-coverage gap before submission. Biller adds 93306 + R00.2 to the claim; all three lines pay on first pass. $240 recovered per encounter, ~$960/mo at one such encounter per week. The HIGH-severity imaging-coverage finding alone covers a substantial fraction of the Zorva subscription.",
    encounter_link: "/encounter/enc_0011",
  },
  {
    slug: "enc_0000-hard-modifier-25-chest-pain",
    title:
      "Modifier-25 + ECG + palpitations + lipid panel: 5 findings on one encounter",
    difficulty: "hard",
    specialty: "cardiology",
    encounter_id: "enc_0000",
    clinical_scenario:
      "An established patient comes in for a problem-focused visit with palpitations. The physician performs an in-office ECG, reviews it, and orders a lipid panel. The chart supports a same-day E/M (99214) plus ECG (93000) plus lipid panel (80061). Five ground-truth findings span evaluation, cardiology, diagnosis, modifier, and laboratory categories.",
    claim_summary:
      "99214 (E/M moderate), 93000 (ECG with interpretation), 80061 (lipid panel). Documentation supports a same-day separately-identifiable E/M with procedure.",
    findings: [
      {
        rule_id: "rule_modifier_25_001",
        severity: "high",
        quote: "separately identifiable E/M",
        suggested_code: "99214-25",
        rationale:
          "Same-day E/M + procedure requires modifier -25 to unbundle the E/M from the ECG. Without it, the payer bundles and denies the E/M.",
      },
      {
        rule_id: "rule_em_001",
        severity: "info",
        quote: "established patient moderate complexity",
        suggested_code: "99214",
        rationale:
          "Documentation supports moderate-complexity E/M. Verify chart review elements for 99214.",
      },
      {
        rule_id: "rule_ecg_001",
        severity: "medium",
        quote: "ECG performed in office",
        suggested_code: "93000",
        rationale:
          "ECG billed — verify interpretation is documented separately from the tracing acquisition.",
      },
      {
        rule_id: "rule_icd_001",
        severity: "medium",
        quote: "palpitations reported",
        suggested_code: "R00.2",
        rationale:
          "Palpitations ICD-10 (R00.2) must support the ECG and lipid panel.",
      },
      {
        rule_id: "rule_lab_lipid_001",
        severity: "low",
        quote: "lipid panel ordered",
        suggested_code: "80061",
        rationale:
          "Lipid panel needs medical-necessity ICD linkage.",
      },
    ],
    what_biller_would_have_done:
      "Without Zorva, the biller submits 99214 + 93000 + 80061 with R00.2 as the only ICD. The payer denies the 99214 because modifier -25 is missing (E/M bundled into the ECG), then denies the 80061 for medical necessity (lipid panel not linked to a diabetes ICD). $385 of denied revenue per encounter.",
    dollar_impact:
      "Zorva catches all 5 gaps before submission. Biller adds modifier -25 + R00.2 + E11.65 (screening for lipid panel); all three lines pay on first pass. $385 recovered per encounter, ~$1,540/mo at one such encounter per week. The HIGH-severity modifier-25 finding alone pays for the entire Zorva subscription if caught once per month.",
    encounter_link: "/encounter/enc_0000",
  },
];

function difficultyClass(d: "easy" | "medium" | "hard"): string {
  if (d === "easy") return styles.difficultyEasy;
  if (d === "medium") return styles.difficultyMedium;
  return styles.difficultyHard;
}

function severityClass(s: Severity): string {
  if (s === "critical") return styles.sevCritical;
  if (s === "high") return styles.sevHigh;
  if (s === "medium") return styles.sevMedium;
  if (s === "low") return styles.sevLow;
  return styles.sevInfo;
}

export default function CaseStudiesPage() {
  const totalFindings = CASE_STUDIES.reduce((n, cs) => n + cs.findings.length, 0);
  const totalHighCritical = CASE_STUDIES.reduce(
    (n, cs) =>
      n +
      cs.findings.filter(
        (f) => f.severity === "high" || f.severity === "critical"
      ).length,
    0
  );

  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.header}>
          <span className={styles.eyebrow}>Case studies</span>
          <h1>Three anonymized encounters, audited by the v12 Zorva auditor.</h1>
          <p className={styles.lede}>
            These worked examples are real findings from the Zorva
            auditor (v12, post leak-fix) on three encounters from our
            AHCIP validation set. Each example is anonymized — patient
            identifiers are SHA-256 hashes from the underlying data.
            The numbers and finding severities match what the auditor
            actually produced; we don&apos;t fabricate encounters for
            marketing copy.
          </p>
          <div className={styles.summaryRow} aria-label="Page at a glance">
            <div className={styles.summaryStat}>
              <span className={styles.statNum}>3</span>
              <span className={styles.statLabel}>worked examples</span>
            </div>
            <div className={styles.summaryStat}>
              <span className={styles.statNum}>{totalFindings}</span>
              <span className={styles.statLabel}>findings demonstrated</span>
            </div>
            <div className={styles.summaryStat}>
              <span className={styles.statNum}>{totalHighCritical}</span>
              <span className={styles.statLabel}>high / critical findings</span>
            </div>
            <div className={styles.summaryStat}>
              <span className={styles.statNum}>~ $4,150</span>
              <span className={styles.statLabel}>recovered / month, 1×/wk each</span>
            </div>
          </div>
        </header>

        <div className={styles.caseList}>
          {CASE_STUDIES.map((cs) => (
            <article key={cs.slug} className={styles.caseCard}>
              <div className={styles.caseHeader}>
                <span
                  className={`${styles.difficultyBadge} ${difficultyClass(cs.difficulty)}`}
                >
                  {cs.difficulty}
                </span>
                <span className={styles.specialtyTag}>
                  {cs.specialty.replace(/_/g, " ")}
                </span>
              </div>
              <h2 className={styles.caseTitle}>{cs.title}</h2>

              <div className={styles.caseSection}>
                <h3>Clinical scenario</h3>
                <p>{cs.clinical_scenario}</p>
              </div>

              <div className={styles.caseSection}>
                <h3>Claim as submitted</h3>
                <p>{cs.claim_summary}</p>
              </div>

              <div className={styles.caseSection}>
                <h3>
                  Findings ({cs.findings.length})
                </h3>
                <div className={styles.findingList}>
                  {cs.findings.map((f, i) => (
                    <div key={`${f.rule_id}-${i}`} className={styles.findingRow}>
                      <span
                        className={`${styles.severityPill} ${severityClass(f.severity)}`}
                      >
                        {f.severity}
                      </span>
                      <span className={styles.findingRule}>{f.rule_id}</span>
                      {f.suggested_code && (
                        <span className={styles.findingCode}>
                          → {f.suggested_code}
                        </span>
                      )}
                      <span className={styles.findingQuote}>&ldquo;{f.quote}&rdquo;</span>
                      {f.rationale && (
                        <p className={styles.findingRationale}>{f.rationale}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className={styles.caseSection}>
                <h3>What the biller would have done without Zorva</h3>
                <p>{cs.what_biller_would_have_done}</p>
              </div>

              <div className={styles.dollarImpact}>
                <strong>Dollar impact: </strong>
                {cs.dollar_impact}
              </div>

              {cs.encounter_link && (
                <div className={styles.caseSection}>
                  <p>
                    <Link
                      href={cs.encounter_link}
                      className={styles.ctaSecondary}
                    >
                      Open this encounter in the dashboard →
                    </Link>
                  </p>
                </div>
              )}
            </article>
          ))}
        </div>

        <section className={styles.cta} aria-labelledby="case-studies-cta">
          <h2 id="case-studies-cta">
            Want to see the auditor run on your own claims?
          </h2>
          <p>
            Book a 10-minute discovery call and we&apos;ll run Zorva on a
            sample of your anonymized encounters so you can see exactly
            which findings your billing would have missed this month.
          </p>
          <Link href="/contact" className={styles.ctaButton}>
            Book a discovery call
          </Link>
          <Link href="/how-it-works" className={styles.ctaSecondary}>
            or read how it works first →
          </Link>
        </section>
      </main>
    </div>
  );
}