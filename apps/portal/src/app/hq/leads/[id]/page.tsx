import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadHqLeadDetail } from "@/lib/hq-data";
import { hasPlatformCapability } from "@/lib/platform-capabilities";
import { HqNav } from "../../hq-nav";
import { LeadEditor } from "./lead-editor";
import { ClientConversion } from "./client-conversion";
import styles from "../../hq.module.css";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface PageProps { params: Promise<{ id: string }> }

export default async function HqLeadDetailPage({ params }: PageProps) {
  const operator = await requirePlatformPage("leads:read", "hq_lead_detail");
  const { id } = await params;
  const { lead, operators, clientOwners } = await loadHqLeadDetail(id);
  if (!lead) notFound();
  const canEditLead = hasPlatformCapability(operator.role, true, "leads:write");
  const canCreateClient = hasPlatformCapability(operator.role, true, "clients:write");

  return (
    <main id="main" className={styles.shell}>
      <HqNav />
      <span className={styles.eyebrow}>Lead record · version {lead.version}</span>
      <h1 className={styles.heading}>{lead.clinicName}</h1>
      <p className={styles.subheading}>Manage commercial follow-up without entering or accessing clinical information.</p>
      <div className={styles.detailGrid}>
        <section className={styles.card}>
          <h2>Pipeline</h2>
          {canEditLead ? <LeadEditor
            key={lead.version}
            leadId={lead.id}
            version={lead.version}
            status={lead.status}
            ownerUserId={lead.ownerUserId}
            nextAction={lead.nextAction}
            nextActionAt={lead.nextActionAt?.toISOString() ?? null}
            lostReason={lead.lostReason}
            qualificationStatus={lead.qualificationStatus}
            qualificationReason={lead.qualificationReason}
            qualificationEvidenceRef={lead.qualificationEvidenceRef}
            operators={operators.map((operator) => ({
              userId: operator.userId,
              role: operator.role,
              label: operator.user.name ?? operator.user.email,
            }))}
          /> : <p className={styles.muted}>Your platform role can review this lead but cannot change its pipeline fields.</p>}
        </section>
        <aside className={styles.card}>
          <h2>Lead details</h2>
          <dl className={styles.definitionList}>
            <dt>Contact</dt><dd>{lead.name}</dd>
            <dt>Email</dt><dd>{lead.email}</dd>
            <dt>Volume</dt><dd>{lead.claimVolume?.toLocaleString("en-CA") ?? "Unknown"}</dd>
            <dt>Setup</dt><dd>{lead.billingSetup}</dd>
            <dt>Source</dt><dd>{lead.source ?? "Unknown"}</dd>
            <dt>Qualification</dt><dd>{lead.qualificationStatus}</dd>
            <dt>Qualification reviewed</dt><dd>{lead.qualificationReviewedAt?.toLocaleString("en-CA") ?? "Not reviewed"}</dd>
            <dt>Public submissions</dt><dd>{lead.submissionCount.toLocaleString("en-CA")}</dd>
            <dt>Last submitted</dt><dd>{lead.lastSubmittedAt?.toLocaleString("en-CA") ?? lead.createdAt.toLocaleString("en-CA")}</dd>
            <dt>Last contact</dt><dd>{lead.lastContactedAt?.toLocaleString("en-CA") ?? "Never"}</dd>
          </dl>
        </aside>
      </div>
      <section className={styles.section}>
        <h2>Client handoff</h2>
        {lead.engagement ? (
          <p><Link className={styles.navLink} href={`/hq/clients/${lead.engagement.id}`}>Open {lead.engagement.status.replaceAll("_", " ")} client engagement</Link></p>
        ) : lead.status !== "pilot_signed" ? (
          <div className={styles.empty}>A client engagement can be created only after the lead reaches pilot signed.</div>
        ) : canCreateClient ? (
          <ClientConversion
            leadId={lead.id}
            owners={clientOwners.map((owner) => ({
              userId: owner.userId,
              role: owner.role,
              label: owner.user.name ?? owner.user.email,
            }))}
          />
        ) : (
          <div className={styles.empty}>A platform owner or client-success operator must create the client engagement.</div>
        )}
      </section>
      <section className={styles.section}>
        <h2>Activity</h2>
        {lead.activities.length === 0 ? <div className={styles.empty}>No operator activity yet.</div> : (
          <ol className={styles.timeline}>
            {lead.activities.map((activity) => (
              <li key={activity.id} className={styles.timelineItem}>
                <strong>{activity.kind.replaceAll("_", " ")}</strong>
                <p className={styles.muted}>{activity.actor?.email ?? activity.actorRole} · {activity.occurredAt.toLocaleString("en-CA")}</p>
                <p>{activity.fromValue ?? "—"} → {activity.toValue ?? "—"}</p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </main>
  );
}
