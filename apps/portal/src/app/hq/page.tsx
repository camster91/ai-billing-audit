import type { Metadata } from "next";
import Link from "next/link";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadHqOverview } from "@/lib/hq-data";
import { hasPlatformCapability } from "@/lib/platform-capabilities";
import { HqNav } from "./hq-nav";
import styles from "./hq.module.css";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function HqTodayPage() {
  const operator = await requirePlatformPage("hq:read", "hq_dashboard");
  const canReadLeads = hasPlatformCapability(operator.role, true, "leads:read");
  const canReadClients = hasPlatformCapability(operator.role, true, "clients:read");
  const canReadSupport = hasPlatformCapability(operator.role, true, "support:read");
  const overview = await loadHqOverview(new Date(), { leads: canReadLeads, clients: canReadClients, support: canReadSupport });

  const metrics = [
    ...(canReadLeads ? [
      ["New leads", overview.newLeadCount],
      ["Unowned leads", overview.unownedLeadCount],
      ["Need follow-up", overview.needsFollowUpCount],
    ] as const : []),
    ...(canReadClients ? [
      ["Open client engagements", overview.activeClientCount],
      ["Open company tasks", overview.openCompanyTaskCount],
      ["Overdue company tasks", overview.overdueCompanyTaskCount],
    ] as const : []),
    ...(canReadSupport ? [
      ["Open support cases", overview.openSupportCaseCount],
      ["Overdue support cases", overview.overdueSupportCaseCount],
    ] as const : []),
  ];

  return (
    <main id="main" className={styles.shell}>
      <HqNav />
      <span className={styles.eyebrow}>Private company workspace · {operator.role}</span>
      <h1 className={styles.heading}>Today</h1>
      <p className={styles.subheading}>
        Commercial and operating work requiring attention. Counts are generated
        from current portal records and contain no clinical encounter content.
      </p>

      {metrics.length > 0 ? <section className={styles.grid} aria-label="Company priorities">
        {metrics.map(([label, value]) => (
          <article className={styles.card} key={label}>
            <span className={styles.label}>{label}</span>
            <strong className={styles.metric}>{value}</strong>
          </article>
        ))}
      </section> : <div className={styles.empty}>Your role has no operating-data module assigned yet.</div>}

      {canReadLeads ? <section className={styles.section}>
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
      </section> : null}
    </main>
  );
}
