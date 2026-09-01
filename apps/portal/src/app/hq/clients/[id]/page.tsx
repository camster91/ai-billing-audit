import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadHqClientDetail } from "@/lib/hq-data";
import { hasPlatformCapability } from "@/lib/platform-capabilities";
import { HqNav } from "../../hq-nav";
import styles from "../../hq.module.css";
import { TaskEditor } from "./task-editor";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface PageProps { params: Promise<{ id: string }> }

export default async function HqClientDetailPage({ params }: PageProps) {
  const operator = await requirePlatformPage("clients:read", "hq_client_detail");
  const { id } = await params;
  const { client, owners } = await loadHqClientDetail(id);
  if (!client) notFound();
  const canEdit = hasPlatformCapability(operator.role, true, "clients:write");
  const ownerOptions = owners.map((owner) => ({
    userId: owner.userId,
    role: owner.role,
    label: owner.user.name ?? owner.user.email,
  }));

  return (
    <main id="main" className={styles.shell}>
      <HqNav />
      <span className={styles.eyebrow}>Client engagement · version {client.version}</span>
      <h1 className={styles.heading}>{client.clinicName}</h1>
      <p className={styles.subheading}>Internal commercial and delivery coordination only. Do not enter or copy clinical information.</p>
      <div className={styles.detailGrid}>
        <section className={styles.card}>
          <h2>Engagement</h2>
          <dl className={styles.definitionList}>
            <dt>Status</dt><dd>{client.status.replaceAll("_", " ")}</dd>
            <dt>Owner</dt><dd>{client.owner?.name ?? client.owner?.email ?? "Unassigned"}</dd>
            <dt>Offer</dt><dd>{client.offerReference ?? "Not recorded"}</dd>
            <dt>Privacy approval</dt><dd>{client.privacyApprovalStatus}</dd>
            <dt>Pilot</dt><dd>{client.pilotStartAt?.toLocaleDateString("en-CA") ?? "Not set"} – {client.pilotEndAt?.toLocaleDateString("en-CA") ?? "Not set"}</dd>
            <dt>First value</dt><dd>{client.firstValueAt?.toLocaleString("en-CA") ?? "Not reached"}</dd>
            <dt>Health</dt><dd>{client.healthStatus}</dd>
          </dl>
        </section>
        <aside className={styles.card}>
          <h2>Connections</h2>
          <p><Link className={styles.navLink} href={`/hq/leads/${client.lead.id}`}>Lead: {client.lead.name}</Link></p>
          <p>{client.lead.email}</p>
          <p>{client.tenant ? `Tenant linked: ${client.tenant.name}` : "No clinic tenant linked. Tenant creation remains a separate approved customer action."}</p>
        </aside>
      </div>
      <section className={styles.section}>
        <h2>Company work</h2>
        <p className={styles.muted}>No-PHI onboarding checklist. Updates are versioned and operator-audited; they do not send messages.</p>
        <div className={styles.timeline}>
          {client.tasks.map((task) => canEdit ? (
            <TaskEditor
              key={`${task.id}-${task.version}`}
              engagementId={client.id}
              task={{
                id: task.id,
                title: task.title,
                status: task.status,
                priority: task.priority,
                ownerUserId: task.ownerUserId,
                dueAt: task.dueAt?.toISOString() ?? null,
                evidenceReference: task.evidenceReference,
                version: task.version,
              }}
              owners={ownerOptions}
            />
          ) : (
            <div key={task.id} className={styles.timelineItem}>
              <strong>{task.title}</strong>
              <p className={styles.muted}>{task.status} · {task.priority} · {task.owner?.name ?? task.owner?.email ?? "Unassigned"} · {task.dueAt?.toLocaleString("en-CA") ?? "No due date"}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
