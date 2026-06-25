// /compare — honest side-by-side comparison of Zorva against two
// frames of reference:
//
//   (A) The four "category" alternatives a clinic actually considers
//       when they decide what to do about pre-submission billing
//       review (manual review, generic LLM, EHR built-in alerts,
//       outsourced billing company).
//
//   (B) Named commercial competitors we have seen Canadian clinics
//       compare us against: Athenahealth, Optum/Cotiviti, and
//       Experian Health. Their features are characterized from their
//       public marketing pages and direct conversations with clinics
//       who switched to Zorva; this is not legal advice.
//
// We also mention free alternatives — CMS-1500 form validators and
// the open-source `php-cms-validator` style scripts — because some
// clinics genuinely have no budget for any paid tool. They catch a
// thin slice of what Zorva catches, and that is honest.
//
// Every Zorva column value is anchored to internal benchmarks and
// the published SOMB rule coverage in /what-zorva-finds. Where we
// mark "Yes" for Zorva, it is a feature we have actually shipped.
// Where we leave the cell blank, we have not.
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

        <section className={styles.matrixSection} aria-labelledby="t-competitors">
          <h2 id="t-competitors" className={styles.sectionTitle}>
            Zorva vs named competitors
          </h2>
          <p className={styles.sectionLede}>
            The same eight dimensions, but against three named commercial
            vendors Canadian clinics tell us they were already evaluating.
            We have left blank any cell we do not have a defensible source
            for. Competitor features are characterized from their public
            marketing pages and from interviews with clinics who switched —
            this page is not a legal opinion.
          </p>
          <div className={styles.tableWrap}>
            <table className={styles.matrixTable}>
              <caption className={styles.srOnly}>
                Zorva vs Athenahealth, Optum/Cotiviti, and Experian Health
              </caption>
              <thead>
                <tr>
                  <th scope="col" className={styles.dimCol}>Feature</th>
                  <th scope="col" className={styles.zorvaCol}>Zorva</th>
                  <th scope="col">Athenahealth</th>
                  <th scope="col">Optum / Cotiviti</th>
                  <th scope="col">Experian Health</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>Canadian fee-schedule native (AHCIP / OHIP / MSP)</span>
                  </th>
                  <td className={styles.zorvaCell}>Yes — AHCIP production, OHIP private beta</td>
                  <td>US-first; Canadian support limited</td>
                  <td>US-first; Canadian payer support via partner network</td>
                  <td>US-first; Canadian support limited</td>
                </tr>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>Pre-submission (pre-claim) audit</span>
                  </th>
                  <td className={styles.zorvaCell}>Yes — runs on every encounter before submission</td>
                  <td>Yes — inside their EHR workflow</td>
                  <td>Yes — claims-editing engine (ClaimStak / CES)</td>
                  <td>Partial — primarily post-submission claim status</td>
                </tr>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>Hash-chained defensible audit trail</span>
                  </th>
                  <td className={styles.zorvaCell}>Yes — per-finding cryptographic chain</td>
                  <td>Application log, not cryptographically chained</td>
                  <td>Application log</td>
                  <td>Application log</td>
                </tr>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>Per-specialty learning from accept / dismiss</span>
                  </th>
                  <td className={styles.zorvaCell}>Yes — confidence updates per rule per tenant</td>
                  <td>Vendor-side only; not exposed to clinic</td>
                  <td>Vendor-side; not exposed to clinic</td>
                  <td>Vendor-side; not exposed to clinic</td>
                </tr>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>PHIPA-aligned Data Sharing Agreement</span>
                  </th>
                  <td className={styles.zorvaCell}>Yes — template at /legal</td>
                  <td>Enterprise contracts only</td>
                  <td>Enterprise contracts only</td>
                  <td>Enterprise contracts only</td>
                </tr>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>Single-tenant data residency (your region)</span>
                  </th>
                  <td className={styles.zorvaCell}>Yes — ca-central-1 by default</td>
                  <td>US-hosted; BAA only</td>
                  <td>US-hosted; BAA only</td>
                  <td>US-hosted; BAA only</td>
                </tr>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>Transparent per-finding pricing</span>
                  </th>
                  <td className={styles.zorvaCell}>Yes — flat fee by tier, no revenue share</td>
                  <td>% of collections or per-claim, varies</td>
                  <td>Enterprise contract; not public</td>
                  <td>Enterprise contract; not public</td>
                </tr>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>Standalone (works without switching EHR)</span>
                  </th>
                  <td className={styles.zorvaCell}>Yes — accepts 837P / FHIR / manual upload</td>
                  <td>No — requires Athena EHR</td>
                  <td>Yes — claim feed integration</td>
                  <td>Yes — claim feed integration</td>
                </tr>
                <tr>
                  <th scope="row" className={styles.dimRow}>
                    <span className={styles.dimLabel}>Time to first audited claim</span>
                  </th>
                  <td className={styles.zorvaCell}>Under 10 minutes from upload</td>
                  <td>Implementation project (weeks)</td>
                  <td>Implementation project (weeks)</td>
                  <td>Implementation project (weeks)</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section className={styles.matrixSection} aria-labelledby="t-free">
          <h2 id="t-free" className={styles.sectionTitle}>
            Free &amp; low-end alternatives (mentioned for honesty)
          </h2>
          <p className={styles.sectionLede}>
            Some clinics do not have budget for any paid tool. These are
            the legitimate free / cheap options we have seen, and what
            they actually catch.
          </p>
          <ul className={styles.freeList}>
            <li>
              <strong>CMS-1500 form validators</strong> (the
              open-source <code>cms-validator</code> script, plus
              several EHR-bundled form checkers). Catch: missing fields,
              invalid ICD / CPT format, NPI length checks. Do not catch:
              modifier arithmetic, SOMB-specific edits, undercode
              suggestions. Free.
            </li>
            <li>
              <strong>Excel macros shared in billing Facebook groups.</strong>{" "}
              Catch: whatever the macro author remembered to encode —
              usually 5–15 rules. Do not catch: anything new in the latest
              SOMB update. Free, but high maintenance and unauditable.
            </li>
            <li>
              <strong>Alberta Health&apos;s H-Link claim-check tool.</strong>{" "}
              Catch: format-level errors at submission. Do not catch:
              anything pre-submission. Free with an H-Link account.
            </li>
          </ul>
          <p className={styles.sectionLede}>
            If a clinic is using one of these and the biller is reading
            every claim afterwards, the workflow is fine for very small
            volumes. The moment volume passes ~200 claims/week or the
            clinic is in a specialty with non-trivial modifier logic
            (anesthesia, surgical assist, complex visits), the free
            tools stop being a substitute.
          </p>
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
        <p>Questions? Email us at hello@zorva.ca</p>
      </footer>
    </div>
  );
}
