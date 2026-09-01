import type { Metadata } from "next";
import Link from "next/link";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadHqClients } from "@/lib/hq-data";
import { HqNav } from "../hq-nav";
import styles from "../hq.module.css";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function HqClientsPage() {
  await requirePlatformPage("clients:read", "hq_clients");
  const clients = await loadHqClients();
  return (
    <main id="main" className={styles.shell}>
      <HqNav />
      <span className={styles.eyebrow}>Private company workspace</span>
      <h1 className={styles.heading}>Clients and pilots</h1>
      <p className={styles.subheading}>Commercial delivery status and no-PHI company work. Clinical records remain in the tenant product.</p>
      {clients.length === 0 ? <div className={styles.empty}>No client engagements yet.</div> : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>Clinic</th><th>Status</th><th>Owner</th><th>Privacy</th><th>Open work</th><th>Pilot dates</th></tr></thead>
            <tbody>{clients.map((client) => (
              <tr key={client.id}>
                <td><Link className={styles.navLink} href={`/hq/clients/${client.id}`}>{client.clinicName}</Link></td>
                <td>{client.status.replaceAll("_", " ")}</td>
                <td>{client.owner?.name ?? client.owner?.email ?? "Unassigned"}</td>
                <td>{client.privacyApprovalStatus}</td>
                <td>{client._count.tasks}</td>
                <td>{client.pilotStartAt?.toLocaleDateString("en-CA") ?? "Not set"} – {client.pilotEndAt?.toLocaleDateString("en-CA") ?? "Not set"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </main>
  );
}
