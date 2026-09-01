import type { Metadata } from "next";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadCompanyReport, type CompanyMetric } from "@/lib/company-report";
import { HqNav } from "../hq-nav";
import styles from "../hq.module.css";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function formatMetric(metric: CompanyMetric): string {
  if (metric.value === null) return metric.state === "unavailable" ? "Unavailable" : "Unknown";
  if (metric.unit === "percent") return `${metric.value.toFixed(1)}%`;
  if (metric.unit === "hours") return `${metric.value.toFixed(1)} h`;
  if (metric.unit === "cad_cents") return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" }).format(metric.value / 100);
  return new Intl.NumberFormat("en-CA").format(metric.value);
}

export default async function ReportsPage() {
  const operator = await requirePlatformPage("reporting:read", "hq_reports");
  const generatedAt = new Date();
  const periodEndAt = generatedAt;
  const periodStartAt = new Date(periodEndAt.getTime() - 30 * 24 * 60 * 60 * 1000);
  const report = await loadCompanyReport(periodStartAt, periodEndAt, generatedAt);

  return <main id="main" className={styles.shell}>
    <HqNav />
    <span className={styles.eyebrow}>Read-only company evidence · {operator.role}</span>
    <h1 className={styles.heading}>Company report</h1>
    <p className={styles.subheading}>Trailing 30 days plus clearly labelled current snapshots. Unknown means the source has no measured value; unavailable means Zorva has no approved source.</p>

    <section className={styles.grid} aria-label="Company metrics">
      {report.metrics.map((item) => <article className={styles.card} key={item.key}>
        <span className={styles.label}>{item.label}</span>
        <strong className={styles.metric}>{formatMetric(item)}</strong>
        <p className={styles.muted}><strong>{item.state}</strong> · {item.definition}</p>
        <p className={styles.freshness}>Source: {item.source}</p>
      </article>)}
    </section>

    <section className={styles.section}>
      <h2>Latest campaign outcomes in period</h2>
      <p className={styles.muted}>One latest evidence snapshot per campaign. Rows are not summed because campaign periods may overlap.</p>
      {report.campaignOutcomes.length === 0 ? <div className={styles.empty}>Unknown: no campaign attribution snapshot ends in this reporting period.</div> : <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead><tr><th>Campaign</th><th>State</th><th>Period</th><th>Clients</th><th>Attributed revenue</th><th>Recorded spend</th><th>Evidence</th></tr></thead>
          <tbody>{report.campaignOutcomes.map((row) => <tr key={row.campaignId}>
            <td>{row.campaignName}<br /><span className={styles.freshness}>{row.sourceKey}</span></td>
            <td>{row.state}</td>
            <td>{row.periodStartAt.toLocaleDateString("en-CA")} – {row.periodEndAt.toLocaleDateString("en-CA")}</td>
            <td>{row.clientCount ?? "Unknown"}</td>
            <td>{row.revenueCents === null ? "Unknown" : new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" }).format(row.revenueCents / 100)}</td>
            <td>{row.recordedSpendCents === null ? "Unknown" : new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" }).format(row.recordedSpendCents / 100)}</td>
            <td>{row.sourceReference}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </section>
    <p className={styles.freshness}>Period {report.periodStartAt.toISOString()} to {report.periodEndAt.toISOString()} · generated {report.generatedAt.toISOString()}</p>
  </main>;
}
