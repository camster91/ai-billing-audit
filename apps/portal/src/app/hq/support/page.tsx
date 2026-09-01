import type { Metadata } from "next";
import Link from "next/link";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadHqSupportCases } from "@/lib/hq-data";
import { hasPlatformCapability } from "@/lib/platform-capabilities";
import { HqNav } from "../hq-nav";
import styles from "../hq.module.css";
import { CaseCreator } from "./case-creator";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function HqSupportPage() {
  const operator = await requirePlatformPage("support:read", "hq_support");
  const { cases, engagements, owners } = await loadHqSupportCases();
  const canWrite = hasPlatformCapability(operator.role, true, "support:write");
  const ownerOptions = owners.map((owner) => ({ userId: owner.userId, role: owner.role, label: owner.user.name ?? owner.user.email }));
  return <main id="main" className={styles.shell}>
    <HqNav />
    <span className={styles.eyebrow}>Internal support operations · {operator.role}</span>
    <h1 className={styles.heading}>Support cases</h1>
    <p className={styles.subheading}>No-PHI issue coordination, ownership, internal targets, and product linkage. Nothing here sends a customer message.</p>
    {canWrite ? <section className={styles.card}><CaseCreator engagements={engagements.map((item) => ({ id: item.id, label: item.clinicName }))} owners={ownerOptions} /></section> : null}
    <section className={styles.section}>
      <h2>Case queue</h2>
      {cases.length === 0 ? <div className={styles.empty}>No support cases.</div> : <div className={styles.tableWrap}><table className={styles.table}>
        <thead><tr><th>Client</th><th>Summary</th><th>Severity</th><th>Status</th><th>Owner</th><th>Target</th></tr></thead>
        <tbody>{cases.map((item) => <tr key={item.id}>
          <td><Link className={styles.navLink} href={`/hq/support/${item.id}`}>{item.engagement.clinicName}</Link></td>
          <td>{item.safeSummary}</td><td>{item.severity}</td><td>{item.status.replaceAll("_", " ")}</td>
          <td>{item.owner?.name ?? item.owner?.email ?? "Unassigned"}</td><td>{item.dueAt?.toLocaleString("en-CA") ?? "No target"}</td>
        </tr>)}</tbody>
      </table></div>}
    </section>
  </main>;
}
