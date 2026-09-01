import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { requirePlatformPage } from "@/lib/platform-auth";
import { loadHqSupportCaseDetail } from "@/lib/hq-data";
import { hasPlatformCapability } from "@/lib/platform-capabilities";
import { HqNav } from "../../hq-nav";
import styles from "../../hq.module.css";
import { CaseEditor } from "./case-editor";

export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic"; export const runtime = "nodejs";
interface Props { params: Promise<{ id: string }> }
function changedFieldLabels(value: string): string {
  try {
    const parsed = JSON.parse(value) as { changedFields?: unknown };
    return Array.isArray(parsed.changedFields) && parsed.changedFields.every((item) => typeof item === "string")
      ? parsed.changedFields.join(", ")
      : "case";
  } catch {
    return "case";
  }
}

export default async function HqSupportDetail({ params }: Props) {
  const operator = await requirePlatformPage("support:read", "hq_support_detail"); const { id } = await params;
  const { supportCase, owners } = await loadHqSupportCaseDetail(id); if (!supportCase) notFound();
  const canWrite = hasPlatformCapability(operator.role, true, "support:write");
  const ownerOptions = owners.map((owner) => ({ userId: owner.userId, role: owner.role, label: owner.user.name ?? owner.user.email }));
  return <main id="main" className={styles.shell}><HqNav />
    <span className={styles.eyebrow}>Support case · version {supportCase.version}</span><h1 className={styles.heading}>{supportCase.engagement.clinicName}</h1>
    <p className={styles.subheading}>{supportCase.safeSummary}</p>
    <div className={styles.detailGrid}><section className={styles.card}><h2>Case state</h2><dl className={styles.definitionList}>
      <dt>Status</dt><dd>{supportCase.status.replaceAll("_", " ")}</dd><dt>Severity</dt><dd>{supportCase.severity}</dd><dt>Category</dt><dd>{supportCase.category.replaceAll("_", " ")}</dd>
      <dt>Owner</dt><dd>{supportCase.owner?.name ?? supportCase.owner?.email ?? "Unassigned"}</dd><dt>Internal target</dt><dd>{supportCase.dueAt?.toLocaleString("en-CA") ?? "Not set"}</dd>
      <dt>Acknowledged</dt><dd>{supportCase.acknowledgedAt?.toLocaleString("en-CA") ?? "Not yet"}</dd><dt>Resolved</dt><dd>{supportCase.resolvedAt?.toLocaleString("en-CA") ?? "Not yet"}</dd>
      <dt>Product issue</dt><dd>{supportCase.linkedIssueReference ?? "Not linked"}</dd></dl></section>
      <aside className={styles.card}><h2>Client link</h2><Link className={styles.navLink} href={`/hq/clients/${supportCase.engagement.id}`}>{supportCase.engagement.clinicName}</Link><p className={styles.muted}>No automated acknowledgement or reply is sent.</p></aside></div>
    {canWrite ? <section className={styles.section}><CaseEditor supportCase={{ id: supportCase.id, category: supportCase.category, severity: supportCase.severity, status: supportCase.status, safeSummary: supportCase.safeSummary, ownerUserId: supportCase.ownerUserId, dueAt: supportCase.dueAt?.toISOString() ?? null, linkedIssueReference: supportCase.linkedIssueReference, version: supportCase.version }} owners={ownerOptions} /></section> : null}
    <section className={styles.section}><h2>Activity</h2><div className={styles.timeline}>{supportCase.activities.map((activity) => <div className={styles.timelineItem} key={activity.id}><strong>{activity.kind}</strong><p className={styles.muted}>{changedFieldLabels(activity.changesJson)} · {activity.actor?.name ?? activity.actor?.email ?? activity.actorRole} · {activity.occurredAt.toLocaleString("en-CA")}</p></div>)}</div></section>
  </main>;
}
