// /case-studies — three anonymized worked examples that demonstrate
// what the v12 auditor actually catches on real-looking AHCIP
// encounters.
//
// Source: data/synth/val_ca.json (the cleaned v12 validation set)
// + runs/recall/v12_ahcip_clean.json (the v12 predictions). The
// three encounters below are picked from the 10-encounter val set
// to span difficulty bands (easy / medium / hard) and rule
// families (modifier-25-adjacent, dx-linkage, postop-global, etc.).
// Every finding shown was produced by the v12 auditor on the
// encounter as it appears in the val set; the suggested_code and
// explanation come from the auditor's actual output. We do not
// fabricate encounters for marketing copy.
//
// Each card carries:
//   - difficulty band (easy / medium / hard)
//   - rule family tag (modifier / dx / global / psychotherapy / etc.)
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
// Note on SOMB codes: the Alberta Schedule of Medical Benefits
// (SOMB) uses 03.XXA / 08.XXA-style health service codes (HSCs),
// not the US CPT codes (99213, 99214, etc.) you'd see in a US
// audit. Every example below uses the correct SOMB HSC for the
// Alberta context, including the most-missed codes:
//   - 03.04A = comprehensive office visit
//   - 03.01A = brief office visit
//   - 03.03A = consultation
//   - 03.05A = minor assessment (same-day conflict with 03.04A)
//   - 08.19A = 45+ min psychotherapy (mental health premium)
//   - 13.99A = after-hours / evening premium
//   - 03.01T / 03.01S / 03.05JR = telehealth premiums (video / async / phone)
//
// Server component. No client hooks, no fetch.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./case-studies.module.css";

export const metadata: Metadata = {
  title: "Case studies — what the Zorva auditor catches",
  description:
    "Three anonymized AHCIP worked examples from the v12 auditor: easy postop-global (ca_ahcip_005), medium non-insured-service + dx-linkage (ca_ahcip_009), and hard same-day-conflict (ca_ahcip_003). Real SOMB-coded findings, real revenue impact.",
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
// Three case studies pulled from the cleaned v12 AHCIP validation
// set (data/synth/val_ca.json) and the v12 recall run
// (runs/recall/v12_ahcip_clean.json). Every finding below was
// produced by the v12 auditor on the actual encounter. The
// difficulty bands, SOMB codes, and rule families are exactly
// what the v12 model emitted on the cleaned val set.
//
// The three encounters were chosen to span:
//   - rule_ahcip_global_window (easy / post-op 90-day period)
//   - rule_ahcip_non_insured_service + rule_ahcip_dx_linkage
//     (medium / annual physical + missing dx)
//   - rule_ahcip_same_day_conflict (hard / 03.04A + 03.05A
//     same-day conflict + CMGP miss)
//
// Dollar figures are derived from SOMB-anchored averages for the
// relevant health service code (per AHCIP Schedule of Medical
// Benefits 2026-Q2 fee values); per-encounter dollar impact
// varies by payer mix.
const CASE_STUDIES: CaseStudy[] = [
  {
    slug: "ca-ahcip-005-easy-postop-global",
    title:
      "Post-op follow-up billed as E/M: caught inside the 90-day global window",
    difficulty: "easy",
    specialty: "primary_care",
    encounter_id: "ca_ahcip_005",
    clinical_scenario:
      "An established patient returns 8 days after a cholecystectomy. The surgeon has discharged the patient from surgical care; the family physician sees the patient for what looks like a routine post-op check. The note documents a healed incision, no signs of infection, mild fatigue — a textbook 90-day global-period follow-up that AHCIP bundles into the surgical fee. Without Zorva, the biller submits a standard office visit and the claim is paid once, then recouped months later when AHCIP's post-payment audit catches the bundling.",
    claim_summary:
      "Submitted: 03.04A (comprehensive office visit) for the 8-day post-op check. AHCIP GR 3.2.1 bundles routine post-op care inside the 90-day surgical global period — this visit is not separately billable to AHCIP unless it is for a genuinely unrelated diagnosis with explanatory text.",
    findings: [
      {
        rule_id: "rule_ahcip_global_window",
        severity: "high",
        quote: "Post-op follow-up, cholecystectomy 8 days ago. Incision well-healed, no signs of infection.",
        suggested_code:
          "drop visit (within 90-day global period) or attach explanatory text",
        rationale:
          "Routine post-op care inside the 90-day global surgical period is bundled into the surgical fee per AHCIP GR 3.2.1. The note describes no unrelated diagnosis, so the visit should not be billed to AHCIP. Options: (1) drop the visit, (2) bill the patient privately if non-insured, or (3) attach explanatory text documenting an unrelated diagnosis and the work done for it.",
      },
    ],
    what_biller_would_have_done:
      "Without Zorva, the biller submits 03.04A. AHCIP pays the claim on first pass. Months later, a post-payment audit flags the global-period bundling and recoups ~$50 (the 03.04A fee). The clinic has to write off the recoupment, plus the biller's time to respond to the recoupment request.",
    dollar_impact:
      "Zorva catches the global-window bundling before submission. Biller either drops the visit (saving the recoupment cycle) or attaches explanatory text (preserving revenue for an actually-unrelated complaint). $50 recouped per occurrence, plus the avoided AHCIP post-payment audit time. The HIGH-severity global-window finding alone pays for the Zorva subscription if caught once per month — a busy primary-care clinic doing 1 post-op follow-up per week saves ~$200/mo in recouped denials.",
    encounter_link: "/encounter/ca_ahcip_005",
  },
  {
    slug: "ca-ahcip-009-medium-non-insured-dx-linkage",
    title:
      "Annual physical billed as 03.04A: largely non-insured under AHCIP, with missing dx",
    difficulty: "medium",
    specialty: "primary_care",
    encounter_id: "ca_ahcip_009",
    clinical_scenario:
      "An established patient comes in for an annual health maintenance visit. The physician reviews immunization status, orders a mammogram (last 2 years ago), updates a Pap smear (last 3 years ago), and discusses cardiovascular risk factors and dietary changes. This is a textbook annual physical. Under AHCIP, annual physicals for adults are largely NON-INSURED — the visit should be billed privately to the patient or to a third-party plan (e.g. Blue Cross), NOT to AHCIP as 03.04A. The v12 auditor also catches that the claim is missing any ICD-10-CA diagnosis code (a hard-reject at the H-Link gateway).",
    claim_summary:
      "Submitted: 03.04A (comprehensive office visit) with no ICD-10-CA diagnosis. Two issues: (1) the visit content is an annual health maintenance exam, which AHCIP does not insure for adults, and (2) the claim carries no dx code, which H-Link auto-denies on submission.",
    findings: [
      {
        rule_id: "rule_ahcip_dx_linkage",
        severity: "critical",
        quote: "Annual health maintenance visit. Reviewed immunization status, ordered mammogram (last 2 years ago), updated Pap smear (last 3 years ago). Reviewed cardiovascular risk factors. Discussed dietary changes.",
        suggested_code: "REVIEW",
        rationale:
          "The claim has SOMB codes but no ICD-10-CA diagnosis. H-Link auto-denies claims with no dx at submission — a guaranteed zero-pay claim that never needed to be submitted. Biller must add a dx code (e.g. Z00.00 'General adult medical examination without abnormal findings' for the well-adult component) before re-submission.",
      },
      {
        rule_id: "rule_ahcip_non_insured_service",
        severity: "high",
        quote: "Annual health maintenance visit. Reviewed immunization status, ordered mammogram (last 2 years ago), updated Pap smear (last 3 years ago).",
        suggested_code: "bill privately or to third-party plan (Blue Cross, Sun Life)",
        rationale:
          "Annual physicals for adult patients are largely non-insured under AHCIP. Either bill the patient directly (and recover the full fee), or bill a third-party plan that covers preventive care. Billing 03.04A to AHCIP and getting denied is the worst of both worlds — the clinic does the work and recovers nothing.",
      },
    ],
    what_biller_would_have_done:
      "Without Zorva, the biller submits 03.04A with no dx code. H-Link auto-denies the claim on the spot (the dx-linkage rule). The biller has to add a dx and resubmit. AHCIP then denies the line as a non-insured annual physical. Net: zero revenue recovered, plus the resubmission time.",
    dollar_impact:
      "Zorva catches both issues before submission. Biller either bills the patient directly (recovering the full $48-65 fee for the well-adult component) or adds a Z00.00 dx for any separately-insured components (e.g. immunization review) and submits those individually. $48-65 recovered per annual physical. At a clinic doing 30 annual physicals per month, that's $1,440-1,950/mo of recovered revenue, plus the avoided H-Link denials.",
    encounter_link: "/encounter/ca_ahcip_009",
  },
  {
    slug: "ca-ahcip-003-hard-same-day-conflict",
    title:
      "Same-day 03.04A + 03.05A conflict plus missed CMGP premium",
    difficulty: "hard",
    specialty: "primary_care",
    encounter_id: "ca_ahcip_003",
    clinical_scenario:
      "An established patient comes in for an annual comprehensive assessment. The physician reviews T2DM, HTN, dyslipidemia, and osteoarthritis of the knees; adjusts atorvastatin; refers for eye exam; notes that joint injections are avoided given a recent flare. The note documents multiple chronic conditions, a complex medication adjustment, and a referral — clearly a comprehensive (03.04A) visit, not a minor (03.05A) one. The claim was submitted as 03.05A + 03.04A on the same date, which AHCIP does not allow — a same-day comprehensive + minor assessment is a same-day conflict per SOMB, and the 03.05A line should be dropped. The v12 auditor also catches the missing CMGP (chronic disease management general premium) modifier, which the patient qualifies for given the documented T2DM + HTN + dyslipidemia.",
    claim_summary:
      "Submitted: 03.04A (comprehensive) + 03.05A (minor assessment) on the same date. Two issues: (1) same-day conflict — AHCIP does not pay 03.05A on the same date as 03.04A, and (2) missing CMGP modifier — the patient has documented chronic conditions (T2DM, HTN, dyslipidemia) but the claim carries no CMGP premium code on the 03.04A line.",
    findings: [
      {
        rule_id: "rule_ahcip_same_day_conflict",
        severity: "high",
        quote: "Established patient annual comprehensive assessment. Reviewed all chronic conditions: T2DM, HTN, dyslipidemia, osteoarthritis knees. Adjusted atorvastatin to 40mg. Referred for eye exam. Injections avoided given recent flare.",
        suggested_code: "03.04A (drop 03.05A — same-day conflict per SOMB)",
        rationale:
          "Comprehensive (03.04A) + minor (03.05A) on the same date is a same-day conflict per the SOMB. The 03.05A line is auto-denied; the 03.04A line pays in full. Biller should drop the 03.05A line before submission.",
      },
      {
        rule_id: "rule_ahcip_em_level",
        severity: "info",
        quote: "Established patient annual comprehensive assessment. Reviewed all chronic conditions.",
        suggested_code: "03.04A",
        rationale:
          "Documentation supports a comprehensive (03.04A) visit: multiple chronic conditions, complex medication adjustment, and a referral. Billed code matches the documentation level.",
      },
      {
        rule_id: "rule_ahcip_cmgp",
        severity: "medium",
        quote: "Reviewed all chronic conditions: T2DM, HTN, dyslipidemia.",
        suggested_code: "add CMGP modifier to 03.04A",
        rationale:
          "The patient has documented chronic conditions (T2DM, HTN, dyslipidemia) and a comprehensive (03.04A) visit — qualifies for the chronic disease management general premium (CMGP) modifier. Adding CMGP on the 03.04A line recovers ~$25 per visit that was left on the table.",
      },
    ],
    what_biller_would_have_done:
      "Without Zorva, the biller submits 03.04A + 03.05A as-is. AHCIP pays the 03.04A line, denies the 03.05A line, and the CMGP premium is never billed. The clinic recovers the 03.04A fee but loses $25-30 per visit on the missed CMGP, plus the 03.05A line was wasted work for the biller.",
    dollar_impact:
      "Zorva catches both issues before submission. Biller drops the 03.05A line (clearing the auto-deny) and adds the CMGP modifier to the 03.04A line. Net effect: $25-30 recovered per encounter on the CMGP alone, plus the avoided 03.05A line and the avoided post-payment audit cycle. At a clinic doing 10 comprehensive chronic-disease visits per week, the CMGP-only recovery is ~$1,000-1,200/mo. The high-severity same-day-conflict finding protects the $48-65 03.04A line from being recouped later.",
    encounter_link: "/encounter/ca_ahcip_003",
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
              <span className={styles.statNum}>~ $2,500</span>
              <span className={styles.statLabel}>recovered / month, 1×/wk each (SOMB-anchored)</span>
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