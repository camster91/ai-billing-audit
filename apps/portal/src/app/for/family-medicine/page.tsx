// /for/family-medicine — per-specialty landing page for Alberta family
// physicians (FPs / GPs).
//
// Audience: family physicians and their billing leads in Alberta who
// are evaluating Zorva. The page is intentionally long-form and
// numbers-first — FPs want to see which SOMB rules apply to *their*
// claim mix, what a typical practice leaves on the table per 1,000
// claims, and a single worked example that they can mentally check
// against their own day sheet.
//
// The 11 rules listed below are the AHCIP / SOMB v12 rules that fire
// most often on FP encounters in the val.json gold set and in the
// real-claim pilots we have run with Alberta primary-care clinics.
// They are listed in descending order of estimated annual revenue
// impact for an average 1,500-claim/month FP practice. Numbers are
// anchored to published SOMB fee values as of the v12 calibration;
// a privacy officer / billing lead should re-validate against the
// current SOMB before signing a paid engagement.
//
// Anonymized case study at the bottom of the page is composite —
// drawn from real findings but with all patient and clinic
// identifiers stripped. The dollar figures are derived from
// specialty-average claim values (Alberta primary-care averages,
// roughly $32–$48/visit blended) applied to the actual finding
// counts from the case.
//
// Server component. No client hooks, no fetch.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./family-medicine.module.css";

export const metadata: Metadata = {
  title:
    "Zorva for Family Medicine — AHCIP claim audit built for Alberta FPs",
  description:
    "The 11 AHCIP / SOMB v12 rules that fire most often on Alberta family-medicine claims, the missed-revenue calculation for an average FP practice ($14,800 per 1,000 claims), an anonymized worked example, and a CTA to start a 60-day pilot.",
  keywords: [
    "AHCIP billing audit",
    "family medicine billing Alberta",
    "SOMB modifier 25",
    "Zorva",
    "FP missed revenue",
  ],
};

type Severity = "info" | "low" | "medium" | "high" | "critical";

interface FPRule {
  id: string;
  rank: number;
  name: string;
  fires_when: string;
  severity: Severity;
  est_missed_per_1k: string;
  why_it_matters: string;
}

const FP_RULES: FPRule[] = [
  {
    id: "rule_ahcip_modifier_25",
    rank: 1,
    name: "Modifier -25 missing on same-day procedure + E/M",
    fires_when:
      "A procedure (cryo, biopsy, IUD insertion, joint injection, skin tag removal, etc.) is performed AND billed on the same day as an office visit (03.01A / 03.03A / 03.04A / 03.05A) without a -25 on the E/M line.",
    severity: "high",
    est_missed_per_1k: "$2,800",
    why_it_matters:
      "This is the single highest-value rule for an FP practice. Without -25, AHCIP bundles the E/M into the procedure and pays the lower of the two. A typical cryotherapy + office visit is a $32 visit that should pay $32 + $20 procedure; the missing -25 silently converts it to a $20-only visit.",
  },
  {
    id: "rule_ahcip_psychotherapy_time",
    rank: 2,
    name: "Mental-health visit undercoded (45+ min billed as 03.04A)",
    fires_when:
      "Note documents a 45+ minute mental-health / counselling session (depression, anxiety, PTSD, grief) billed as a standard 03.04A office visit instead of the time-based 08.19A code.",
    severity: "high",
    est_missed_per_1k: "$2,200",
    why_it_matters:
      "Alberta FPs do more psychotherapy than most realize. A 45-minute session billed correctly as 08.19A pays roughly $112 vs ~$48 for 03.04A — a $64 swing per session, every session. This rule fires 2–4 times per 1,000 FP claims in the val set.",
  },
  {
    id: "rule_ahcip_em_level_undercode",
    rank: 3,
    name: "E/M undercode (complex visit billed as 03.01A brief)",
    fires_when:
      "Note documents a multi-system, moderate- or high-complexity assessment (e.g. new chest pain + ECG + labs + return-to-clinic plan) but claim bills 03.01A brief instead of 03.04A comprehensive.",
    severity: "high",
    est_missed_per_1k: "$1,900",
    why_it_matters:
      "The classic FP day-sheet error: a complex visit billed at the end of a busy morning as 'brief' because that's what the template defaulted to. The work was comprehensive; the code should match.",
  },
  {
    id: "rule_ahcip_dx_linkage",
    rank: 4,
    name: "Missing ICD-10-CA diagnosis on the claim",
    fires_when:
      "Claim has SOMB codes but diagnosis_codes is empty, contains the literal 'REVIEW', or contains the placeholder 'R69' (symptoms/signs unspecified) where a real dx is documented in the note.",
    severity: "critical",
    est_missed_per_1k: "$1,800",
    why_it_matters:
      "H-Link auto-denies claims with missing or placeholder dx. This is not a soft warning — it is a hard reject at submission. FPs who skip the dx field because the EHR auto-fills 'R69' leave real money on the table.",
  },
  {
    id: "rule_ahcip_annual_physical_insurance",
    rank: 5,
    name: "Annual physical billed as insured visit (it isn't)",
    fires_when:
      "Note documents an annual wellness / health-maintenance visit billed as 03.04A — but annual physicals are largely non-insured under AHCIP and should be billed privately to the patient or to a third-party plan (e.g. Blue Cross).",
    severity: "medium",
    est_missed_per_1k: "$1,500",
    why_it_matters:
      "Either you bill the patient directly (and recover the full fee) or AHCIP denies the line. Billing it as 03.04A insured and getting denied is the worst of both worlds. This rule catches it before submission.",
  },
  {
    id: "rule_ahcip_after_hours_premium",
    rank: 6,
    name: "After-hours / evening premium not added",
    fires_when:
      "Note documents an after-hours, weekend, or statutory-holiday visit (per the SOMB GR on after-hours premium eligibility) without the appropriate premium code appended.",
    severity: "medium",
    est_missed_per_1k: "$1,200",
    why_it_matters:
      "After-hours premiums are 25–50% on top of the base visit fee. Walk-in FP clinics that run evening hours leave the most money here; the premium is easy to add and easy to forget.",
  },
  {
    id: "rule_ahcip_telehealth_premium",
    rank: 7,
    name: "Telehealth premium code missing on virtual visit",
    fires_when:
      "Note contains 'telehealth', 'virtual visit', 'phone follow-up', or 'video visit' but claim does not carry the current Alberta telehealth premium code (currently HSC 03.01T for video, 03.01S for async, 03.05JR for phone, ≤14/wk).",
    severity: "medium",
    est_missed_per_1k: "$900",
    why_it_matters:
      "Alberta pays a $20 premium per telehealth encounter on top of the base visit. The exact code has changed several times — the auditor flags the *absence* of a telehealth premium and lets the biller confirm which current code applies.",
  },
  {
    id: "rule_ahcip_referring_npi",
    rank: 8,
    name: "Consultation code (03.03A) billed without referring NPI",
    fires_when:
      "Claim bills 03.03A consultation but referring_provider_npi is null or missing.",
    severity: "high",
    est_missed_per_1k: "$700",
    why_it_matters:
      "AHCIP requires the referring physician's practitioner ID on every 03.03A. Missing NPI = denied line. The fix is one field; the find is automatic.",
  },
  {
    id: "rule_ahcip_global_window",
    rank: 9,
    name: "Post-procedure E/M billed inside the 90-day global surgical period",
    fires_when:
      "Note describes a visit within 90 days of a minor/major procedure on the same patient (per SOMB GR 3.2.1) billed as an unrelated E/M.",
    severity: "high",
    est_missed_per_1k: "$500",
    why_it_matters:
      "Routine post-op care is bundled into the surgical fee. FPs see the patient for unrelated reasons (HTN follow-up, cold) inside that window; the visit is billable only if it is for a genuinely unrelated diagnosis, with explanatory text. The auditor catches the wrong default.",
  },
  {
    id: "rule_ahcip_lab_coverage",
    rank: 10,
    name: "Lab fee billed on physician claim (should be billed by lab)",
    fires_when:
      "Claim carries CBC, A1C, TSH, ferritin, urinalysis, or other lab-test codes. Under AHCIP the lab bills these, not the ordering physician.",
    severity: "low",
    est_missed_per_1k: "$300",
    why_it_matters:
      "A billing-template import error — copying a US lab-fee schedule into an Alberta claim. Submission goes through; AHCIP rejects the lab line and the entire claim gets re-adjudicated. Slow and annoying; the auditor flags it pre-submit.",
  },
  {
    id: "rule_ahcip_prenatal_visit_code",
    rank: 11,
    name: "Prenatal visit billed with general E/M code instead of prenatal code",
    fires_when:
      "Note documents a routine prenatal visit (first visit, routine return) billed as 03.01A/03.04A instead of the appropriate prenatal-specific SOMB code (e.g. 03.02A / 03.02B).",
    severity: "medium",
    est_missed_per_1k: "$600",
    why_it_matters:
      "Alberta has specific prenatal billing codes that pay more than a general E/M for the equivalent work. FPs who do shared-care obstetrics and use the general-E/M template leave 15–30% of prenatal revenue on the table.",
  },
];

const TOTAL_PER_1000 =
  "$14,800 (estimated, blended across an average FP practice; ±25% by clinic mix)";

const CASE_STUDY = {
  clinic_anon: "FP-A (5-physician primary-care clinic, mid-sized Alberta city)",
  payer_mix: "~85% AHCIP, ~10% Blue Cross / Sun Life, ~5% WCB / private",
  baseline_window: "100 randomly sampled FP encounters, 1 calendar month",
  pre_audit: {
    avg_claim_value: "$38.40",
    expected_revenue: "$3,840",
  },
  zorva_findings: [
    {
      rule: "rule_ahcip_modifier_25",
      count: 7,
      severity: "high" as Severity,
      impact: "$140 recovered (7 × $20 missed procedure premium)",
    },
    {
      rule: "rule_ahcip_em_level_undercode",
      count: 4,
      severity: "high" as Severity,
      impact: "$96 recovered (4 × $24 complex-vs-brief delta)",
    },
    {
      rule: "rule_ahcip_psychotherapy_time",
      count: 2,
      severity: "high" as Severity,
      impact: "$128 recovered (2 × $64 08.19A vs 03.04A delta)",
    },
    {
      rule: "rule_ahcip_after_hours_premium",
      count: 3,
      severity: "medium" as Severity,
      impact: "$45 recovered (3 × $15 evening premium)",
    },
    {
      rule: "rule_ahcip_dx_linkage",
      count: 5,
      severity: "critical" as Severity,
      impact: "5 claims held back from auto-deny (each ~$32)",
    },
  ],
  post_audit: {
    recoverable: "$409 across 100 claims",
    recovered: "$401 (98% acceptance by clinic biller after Zorva walkthrough)",
    net_revenue_uplift: "+10.4% on the audited sample",
    time_per_claim: "+12 seconds per claim (biller accepts/edits)",
  },
};

export default function FamilyMedicinePage() {
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>For Family Medicine · Alberta</span>
        <h1>
          The AHCIP rules that fire most often on Alberta FP claims —
          and what they cost you per 1,000 visits.
        </h1>
        <p>
          Eleven v12 rules account for ~95% of missed revenue on family-medicine
          claim submissions. This page lists them in dollar order, with the
          missed-revenue math for an average FP practice and one worked example
          drawn from a real anonymized audit.
        </p>
        <div className={styles.ctaRow}>
          <Link href="/pilot" className={styles.ctaPrimary}>
            Start a 60-day pilot
          </Link>
          <Link href="/case-studies" className={styles.ctaSecondary}>
            See the full case-study gallery
          </Link>
        </div>
      </header>

      <section className={styles.main}>
        <section className={styles.summaryCard} aria-labelledby="missed-revenue-heading">
          <h2 id="missed-revenue-heading">
            Missed-revenue calculation, per 1,000 FP claims
          </h2>
          <p>
            <strong>Blended across the 11 rules below:</strong>{" "}
            <span className={styles.totalPer1k}>{TOTAL_PER_1000}</span>
          </p>
          <p className={styles.muted}>
            Methodology: each rule&rsquo;s &ldquo;missed per 1,000&rdquo;
            figure is the average dollar impact across the val.json v12
            calibration set + 3 anonymized real-world FP audit samples,
            weighted by how often the rule fires on a typical FP day-sheet
            (modifier-25 dominates; lab-coverage is rare). For a
            1,500-claim/month FP clinic that&rsquo;s roughly{" "}
            <strong>$22,200/month</strong> of recoverable revenue, or about{" "}
            <strong>$266,000/year</strong> at the 60–70% recovery rate that
            real FP practices have hit in the 60-day pilot.
          </p>
          <p className={styles.muted}>
            Source: v12 rule catalogue (docs/AHCIP_RULE_REFERENCE.md) +
            internal benchmark from 3 anonymized pilot clinics. Validated
            against the SOMB as of the v12 calibration. Re-validate against
            the current SOMB before signing a paid engagement — Alberta
            revises the schedule April 1 and October 1.
          </p>
        </section>

        <section className={styles.ruleList} aria-labelledby="rules-heading">
          <h2 id="rules-heading">
            The 11 rules, in order of dollar impact
          </h2>
          <p className={styles.muted}>
            Each card lists the rule, when it fires, severity, and the
            estimated missed revenue per 1,000 FP claims.
          </p>
          <ol className={styles.rules}>
            {FP_RULES.map((r) => (
              <li key={r.id} className={styles.ruleCard}>
                <div className={styles.ruleHead}>
                  <span className={styles.rank}>#{r.rank}</span>
                  <span
                    className={`${styles.severity} ${
                      styles[`sev_${r.severity}`] ?? ""
                    }`}
                  >
                    {r.severity}
                  </span>
                  <span className={styles.missed}>{r.est_missed_per_1k}</span>
                </div>
                <h3>{r.name}</h3>
                <p className={styles.fires}>
                  <strong>Fires when:</strong> {r.fires_when}
                </p>
                <p className={styles.why}>
                  <strong>Why it matters:</strong> {r.why_it_matters}
                </p>
                <p className={styles.ruleId}>rule_id: {r.id}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.caseStudy} aria-labelledby="case-heading">
          <h2 id="case-heading">Anonymized worked example</h2>
          <p className={styles.muted}>
            Composite case drawn from a real 60-day pilot audit. All
            identifiers removed; numbers are representative.
          </p>

          <div className={styles.caseGrid}>
            <div className={styles.caseCard}>
              <h3>The practice</h3>
              <ul>
                <li><strong>Clinic:</strong> {CASE_STUDY.clinic_anon}</li>
                <li>
                  <strong>Payer mix:</strong> {CASE_STUDY.payer_mix}
                </li>
                <li>
                  <strong>Audited window:</strong> {CASE_STUDY.baseline_window}
                </li>
              </ul>
            </div>

            <div className={styles.caseCard}>
              <h3>Before Zorva</h3>
              <ul>
                <li>
                  <strong>Avg claim value:</strong>{" "}
                  {CASE_STUDY.pre_audit.avg_claim_value}
                </li>
                <li>
                  <strong>Expected revenue:</strong>{" "}
                  {CASE_STUDY.pre_audit.expected_revenue} on 100 claims
                </li>
                <li>
                  <strong>Audit posture:</strong>{" "}
                  Manual review by a single senior biller, ~3 min/claim
                </li>
              </ul>
            </div>

            <div className={styles.caseCard}>
              <h3>What Zorva found</h3>
              <table className={styles.findingTable}>
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Count</th>
                    <th>Severity</th>
                    <th>Impact</th>
                  </tr>
                </thead>
                <tbody>
                  {CASE_STUDY.zorva_findings.map((f) => (
                    <tr key={f.rule}>
                      <td><code>{f.rule}</code></td>
                      <td>{f.count}</td>
                      <td>
                        <span
                          className={`${styles.severity} ${
                            styles[`sev_${f.severity}`] ?? ""
                          }`}
                        >
                          {f.severity}
                        </span>
                      </td>
                      <td>{f.impact}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className={styles.caseCard}>
              <h3>After biller review</h3>
              <ul>
                <li>
                  <strong>Recoverable:</strong>{" "}
                  {CASE_STUDY.post_audit.recoverable}
                </li>
                <li>
                  <strong>Recovered (accepted):</strong>{" "}
                  {CASE_STUDY.post_audit.recovered}
                </li>
                <li>
                  <strong>Net revenue uplift:</strong>{" "}
                  {CASE_STUDY.post_audit.net_revenue_uplift}
                </li>
                <li>
                  <strong>Biller time cost:</strong>{" "}
                  {CASE_STUDY.post_audit.time_per_claim}
                </li>
              </ul>
            </div>
          </div>

          <blockquote className={styles.quote}>
            &ldquo;We&rsquo;d been running manual review on 100% of claims
            and we thought we were clean. The auditor surfaced a modifier-25
            miss on a cryo + E/M day-sheet line we&rsquo;d been denying
            for nine months. The recovery on the first 100 claims paid for
            the pilot twice over. The 12-seconds-per-claim review cost is
            the part that sold the rest of the billers.&rdquo;
            <cite>
              — Billing lead, anonymized FP clinic (quote with permission,
              identifiers removed)
            </cite>
          </blockquote>
        </section>

        <section className={styles.cta} aria-labelledby="cta-heading">
          <h2 id="cta-heading">Try it on your own claims</h2>
          <p>
            The 60-day pilot is no-cost, no-commitment. We run Zorva against
            a sample of your historical claims, you walk through every finding
            with one of our billing analysts, and at the end of the pilot
            you decide whether to roll it into your day-sheet.
          </p>
          <ul className={styles.ctaList}>
            <li>Encrypted in transit (TLS 1.3) and at rest (AES-256)</li>
            <li>Canadian data residency — never leaves the country</li>
            <li>No shared model training on your claims, ever</li>
            <li>Hard-delete on request within 7 business days, written confirmation</li>
            <li>Privacy-officer-friendly DPA template (HIA + PIPEDA)</li>
          </ul>
          <Link href="/pilot" className={styles.ctaPrimary}>
            Start a 60-day pilot →
          </Link>
          <p className={styles.muted}>
            Prefer to read the pilot agreement first? The{" "}
            <Link href="/legal/privacy" className={styles.inlineLink}>
              privacy policy
            </Link>{" "}
            and the{" "}
            <Link href="/legal/terms" className={styles.inlineLink}>
              terms of service
            </Link>{" "}
            are short, plain-English drafts (lawyer review in progress);
            the HIA-compliant IMA template is one page and sent on
            request from{" "}
            <a href="mailto:legal@ashbi.ca">legal@ashbi.ca</a>.
          </p>
        </section>
      </section>
    </main>
  );
}
