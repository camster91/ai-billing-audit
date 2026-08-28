import type { Metadata } from "next";
import Link from "next/link";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadHqOverview } from "@/lib/hq-data";
import { HqNav } from "./hq-nav";
import styles from "./hq.module.css";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function HqTodayPage() {
  const operator = await requirePlatformPage("hq:read", "hq_dashboard");
  const overview = await loadHqOverview();

  const metrics = [
    ["New leads", overview.newLeadCount],
    ["Unowned leads", overview.unownedLeadCount],
    ["Need follow-up", overview.needsFollowUpCount],
    ["Active clinic accounts", overview.activeClientCount],
  ] as const;

  return (
    <main id="main" className={styles.shell}>
      <HqNav />
      <span className={styles.eyebrow}>Private company workspace · {operator.role}</span>
      <h1 className={styles.heading}>Today</h1>
      <p className={styles.subheading}>
        Commercial and operating work requiring attention. Counts are generated
        from current portal records and contain no clinical encounter content.
      </p>

      <section className={styles.grid} aria-label="Company priorities">
        {metrics.map(([label, value]) => (
          <article className={styles.card} key={label}>
            <span className={styles.label}>{label}</span>
            <strong className={styles.metric}>{value}</strong>
          </article>
        ))}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Recent leads</h2>
          <Link href="/hq/leads" className={styles.navLink}>View all leads</Link>
        </div>
        {overview.recentLeads.length === 0 ? (
          <div className={styles.empty}>No leads yet. New contact requests will appear here.</div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>Clinic</th><th>Contact</th><th>Status</th><th>Source</th><th>Received</th></tr></thead>
              <tbody>
                {overview.recentLeads.map((lead) => (
                  <tr key={lead.id}>
                    <td>{lead.clinicName}</td><td>{lead.name}</td><td>{lead.status}</td>
                    <td>{lead.source ?? "Unknown"}</td><td>{lead.createdAt.toLocaleDateString("en-CA")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className={styles.freshness}>Generated {overview.generatedAt.toISOString()}</p>
      </section>
    </main>
  );
}
