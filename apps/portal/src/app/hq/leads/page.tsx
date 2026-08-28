import type { Metadata } from "next";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadHqLeads } from "@/lib/hq-data";
import { HqNav } from "../hq-nav";
import styles from "../hq.module.css";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function HqLeadsPage() {
  await requirePlatformPage("leads:read", "hq_leads");
  const leads = await loadHqLeads();

  return (
    <main id="main" className={styles.shell}>
      <HqNav />
      <span className={styles.eyebrow}>Private company workspace</span>
      <h1 className={styles.heading}>Leads</h1>
      <p className={styles.subheading}>Read-only commercial records. No clinic claims, notes, encounters, or findings are queried.</p>
      {leads.length === 0 ? (
        <div className={styles.empty}>No leads yet.</div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>Clinic</th><th>Contact</th><th>Email</th><th>Status</th><th>Source</th><th>Last contact</th></tr></thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.id}>
                  <td>{lead.clinicName}</td><td>{lead.name}</td><td>{lead.email}</td><td>{lead.status}</td>
                  <td>{lead.source ?? "Unknown"}</td><td>{lead.lastContactedAt?.toLocaleDateString("en-CA") ?? "Never"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
