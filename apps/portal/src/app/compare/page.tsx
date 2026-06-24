// /compare — honest side-by-side comparison of Zorva against the four
// realistic alternatives a clinic actually considers when they decide
// what to do about billing-audit / pre-submission review:
//
//   1. Manual review       — a senior biller reads every claim
//   2. Generic LLM         — ChatGPT / Claude in a tab, copy-paste workflow
//   3. PracticeFusion EHR built-in alerts
//   4. Outsourced billing  — a third-party billing company does it
//
// This page is intentionally NOT a "we are the best at everything"
// pitch. Some dimensions, manual review wins. Some dimensions, the
// EHR alerts are free. The point is to give the biller a real matrix
// so they can make a defensible choice. The columns are honest.
//
// Dimensions (rows):
//   - Catch rate (missed modifiers / undercodes)
//   - Latency per claim
//   - Cost per claim (or per month)
//   - AHCIP / SOMB native
//   - Audit trail (defensible if you get audited)
//   - Setup effort
//   - Scales linearly with claim volume
//   - Learns from your corrections
//
// "Zorva" column values are anchored to internal benchmarks + the
// published SOMB rule coverage in /what-zorva-finds. The other
// columns are best-effort general industry characterizations — link
// to public sources where the numbers came from.
//
// Server component. No client hooks, no fetch.

import type { Metadata } from "next";
import Link from "next/link";
import styles from "./compare.module.css";

export const metadata: Metadata = {
  title: "Compare — Zorva vs manual review, LLM, EHR alerts, and outsourced billing",
  description:
    "An honest side-by-side matrix of pre-billing audit options: Zorva, " +
    "manual review, generic LLM, PracticeFusion's built-in alerts, and " +
    "outsourced billing companies. Where each one wins, where each one loses.",
};

type Cell = string;

type Dim = {
  id: string;
  label: string;
  note?: string;
  zorva: Cell;
  manual: Cell;
  llm: Cell;
  ehr: Cell;
  outsourced: Cell;
};

const DIMS: Dim[] = [
  {
    id: "catch",
    label: "Catch rate on missed modifiers & undercodes",
    note: "Share of legitimate missed-revenue findings the channel surfaces. Anchored to internal benchmarks and the public SOMB rule coverage.",
    zorva: "~70–80% of in-scope SOMB rules fire on first pass; biller closes the rest.",
    manual: "Highest possible — a senior biller catches the nuanced ones — but only if they have time to read every claim.",
    llm: "Unpredictable. Strong on plain-English reasoning; weak on fee-modifier arithmetic and on the long tail of SOMB rules.",
    ehr: "Low. Built-in alerts are generic CCI/NCCI edits and a few obvious code-mismatch warnings.",
    outsourced: "Depends entirely on the company's training and the time budget per claim.",
  },
  {
    id: "latency",
    label: "Latency per claim",
    zorva: "Seconds. Audits run on upload, before submission.",
    manual: "Minutes to hours per claim, depending on the biller's queue.",
    llm: "10–60 seconds per claim if copy-pasted, plus context switching.",
    ehr: "Real-time on save, but only for the rules the EHR ships with.",
    outsourced: "Same day to a few business days, depending on the SLA.",
  },
  {
    id: "cost",
    label: "Cost",
    note: "Rough, publicly known order-of-magnitude figures. Zorva is per-claim; outsourcing is typically a percentage of collections.",
    zorva: "Low per-claim fee. No revenue share.",
    manual: "Salary + benefits + recruiting cost for a senior biller. The single largest line item in most clinic cost structures.",
    llm: "Free if the biller uses the consumer product; $20–$200/mo for team plans. The hidden cost is the biller's time per claim.",
    ehr: "Included with the EHR subscription.",
    outsourced: "Typically 4–8% of net collections. Industry standard.",
  },
  {
    id: "somb",
    label: "AHCIP / SOMB native",
    zorva: "Yes. Rules map to specific SOMB codes (03.04A, 08.19A, etc.) and update with the SOMB schedule.",
    manual: "Yes, but the senior biller has to know the latest schedule. Drift is common after April updates.",
    llm: "No. The model has SOMB in its training data, but it is months out of date and confuses Alberta-specific codes with Ontario / BC schedules.",
    ehr: "Partial. PracticeFusion flags a few CCI edits but does not implement the full SOMB modifier matrix.",
    outsourced: "Yes, if the company specializes in Alberta billing. Mixed if it is a generalist US-centric firm.",
  },
  {
    id: "audit",
    label: "Defensible audit trail",
    zorva: "Yes. Every finding has a hash-chained log entry that names the rule, the evidence, and the biller's accept/dismiss decision.",
    manual: "Not usually. The biller's decision lives in their head, or in unstructured notes.",
    llm: "No. Chat history is not a defensible record. Exporting it to PDF after the fact is not the same thing.",
    ehr: "Partial. The EHR has an edit log but does not record the reasoning behind a billing decision.",
    outsourced: "Sometimes. The better companies do; the cheaper ones do not.",
  },
  {
    id: "setup",
    label: "Setup effort",
    zorva: "Upload one 837P file. No integration, no training session. Live in under 10 minutes.",
    manual: "Hire and onboard a senior biller. Weeks to months.",
    llm: "Sign up for a consumer LLM account. Zero setup. The training-of-the-biller is the work.",
    ehr: "Built in. Zero setup. That is also the ceiling — you cannot tune it.",
    outsourced: "Sign a contract, hand over credentials, configure the claim feed. Weeks.",
  },
  {
    id: "scale",
    label: "Scales linearly with claim volume",
    zorva: "Yes. Per-claim cost does not change with volume; the system processes them in parallel.",
    manual: "No. Each new claim needs another minute of a senior biller's time, and there is only one of her.",
    llm: "No. Linear in the biller's patience, and the per-token cost is not zero at high volume.",
    ehr: "Yes, but at the ceiling of the rules it ships with.",
    outsourced: "Yes, but the percentage fee scales with collections, not claims.",
  },
  {
    id: "learns",
    label: "Learns from your corrections",
    zorva: "Yes. Every accept / dismiss / modify feeds a per-specialty confidence update. The auditor's false-positive rate drops over the pilot.",
    manual: "Yes, but only for the biller doing the work. Quits, retires, and PTO lose it.",
    llm: "No. Each chat session starts fresh. The biller is the memory.",
    ehr: "No. The rule set is what the vendor shipped.",
    outsourced: "Sometimes, at the company level. The clinic does not usually see the benefit in their own data.",
  },
];

export default function ComparePage() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.eyebrow}>Compare</span>
        <h1>Zorva vs the alternatives</h1>
        <p>
          An honest side-by-side. The columns are the realistic options a
          clinic actually considers — manual review, a generic LLM, the
          EHR's built-in alerts, and an outsourced billing company. The
          rows are the dimensions that matter when you decide. We have
          tried to be honest about where Zorva loses, too.
        </p>
        <p className={styles.headerSub}>
          For the per-rule detail, see{" "}
          <Link href="/what-zorva-finds" className={styles.inlineLink}>
            what Zorva finds
          </Link>. For pricing, see{" "}
          <Link href="/pricing" className={styles.inlineLink}>
            pricing
          </Link>.
        </p>
      </header>

      <main className={styles.main} id="main">
        <section className={styles.matrixSection} aria-labelledby="t-matrix">
          <h2 id="t-matrix" className={styles.srOnly}>
            Comparison matrix
          </h2>
          <div className={styles.tableWrap}>
            <table className={styles.matrixTable}>
              <caption className={styles.srOnly}>
                Zorva vs manual review, generic LLM, EHR built-in alerts, and outsourced billing
              </caption>
              <thead>
                <tr>
                  <th scope="col" className={styles.dimCol}>Dimension</th>
                  <th scope="col" className={styles.zorvaCol}>Zorva</th>
                  <th scope="col">Manual review</th>
                  <th scope="col">Generic LLM</th>
                  <th scope="col">EHR built-in alerts</th>
                  <th scope="col">Outsourced billing</th>
                </tr>
              </thead>
              <tbody>
                {DIMS.map((d) => (
                  <tr key={d.id}>
                    <th scope="row" className={styles.dimRow}>
                      <span className={styles.dimLabel}>{d.label}</span>
                      {d.note && (
                        <span className={styles.dimNote}>{d.note}</span>
                      )}
                    </th>
                    <td className={styles.zorvaCell}>{d.zorva}</td>
                    <td>{d.manual}</td>
                    <td>{d.llm}</td>
                    <td>{d.ehr}</td>
                    <td>{d.outsourced}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className={styles.summary} aria-labelledby="t-summary">
          <h2 id="t-summary">The short version</h2>
          <ul>
            <li>
              <strong>Zorva</strong> is a pre-submission auditor that runs in
              seconds, costs pennies per claim, and is the only column that
              combines SOMB-native rules, a defensible audit trail, and a
              per-specialty learning loop.
            </li>
            <li>
              <strong>Manual review</strong> is still the gold standard on the
              hardest edge cases — a senior biller catches things no model
              will. The cost is that you are paying senior-biller salary for
              work that is 80% automatable.
            </li>
            <li>
              <strong>Generic LLMs</strong> are a great research tool and a
              terrible production auditor. They drift on fee-modifier
              arithmetic, do not remember your corrections, and the chat log
              is not a defensible record.
            </li>
            <li>
              <strong>EHR built-in alerts</strong> are free and they are
              worth keeping on, but they catch a thin slice of what is in
              the SOMB and you cannot tune them.
            </li>
            <li>
              <strong>Outsourced billing</strong> is a real option for a
              clinic that wants to outsource the whole function. It is
              expensive (4–8% of collections is the industry range) and
              turns the audit trail over to a third party.
            </li>
          </ul>
          <p>
            Zorva is designed to be used <em>alongside</em> the senior biller,
            not to replace her. The auditor handles the 80% of claims that
            are routine; the biller spends her time on the 20% that are
            actually interesting. The pilot usually pays for itself in the
            first month from the missed-modifier catch alone.
          </p>
        </section>

        <section className={styles.ctaSection} aria-labelledby="t-cta">
          <h2 id="t-cta">See it on your own claims</h2>
          <p>
            The fastest way to know which column your clinic belongs in is
            to upload one 837P file. The first audit is free, runs in under
            ten minutes, and you keep the export whether you sign up or not.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/pilot" className={styles.ctaButton}>
              Start a 30-day pilot
            </Link>
            <Link href="/contact" className={styles.ctaSecondary}>
              Talk to us first →
            </Link>
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
        </div>
        <p>Questions? Email us at hello@ai-billing-audit.ashbi.ca</p>
      </footer>
    </div>
  );
}
