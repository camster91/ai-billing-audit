"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { SUPPORT_CATEGORIES, SUPPORT_SEVERITIES, SUPPORT_STATUSES } from "@/lib/support-case-rules";
import styles from "../../hq.module.css";

interface Owner { userId: string; role: string; label: string }
interface SupportCase { id: string; category: string; severity: string; status: string; safeSummary: string; ownerUserId: string | null; dueAt: string | null; linkedIssueReference: string | null; version: number }
function localDateTimeValue(value: string | null) { if (!value) return ""; const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16); }

export function CaseEditor({ supportCase, owners }: { supportCase: SupportCase; owners: Owner[] }) {
  const router = useRouter();
  const [category, setCategory] = useState(supportCase.category); const [severity, setSeverity] = useState(supportCase.severity);
  const [status, setStatus] = useState(supportCase.status); const [safeSummary, setSafeSummary] = useState(supportCase.safeSummary);
  const [ownerUserId, setOwnerUserId] = useState(supportCase.ownerUserId ?? ""); const [dueAt, setDueAt] = useState(localDateTimeValue(supportCase.dueAt));
  const [linkedIssueReference, setLinkedIssueReference] = useState(supportCase.linkedIssueReference ?? ""); const [busy, setBusy] = useState(false); const [message, setMessage] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(null);
    try {
      const response = await fetch(`/api/hq/support/${encodeURIComponent(supportCase.id)}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ expectedVersion: supportCase.version, mutationId: crypto.randomUUID(), category, severity, status, safeSummary, ownerUserId: ownerUserId || null, dueAt: dueAt ? new Date(dueAt).toISOString() : null, linkedIssueReference: linkedIssueReference || null }) });
      const payload = (await response.json()) as { detail?: string; error?: string };
      if (!response.ok) { setMessage(response.status === 409 ? "This case changed elsewhere. Reload before retrying." : payload.detail ?? payload.error ?? "Could not update case."); return; }
      router.refresh();
    } catch { setMessage("Network error. No case update was confirmed."); } finally { setBusy(false); }
  }
  return <form className={styles.form} onSubmit={submit}>
    <h2>Update case</h2>{message ? <div role="alert" className={styles.error}>{message}</div> : null}
    <label className={styles.field}>Category<select className={styles.select} value={category} onChange={(e) => setCategory(e.target.value)}>{SUPPORT_CATEGORIES.map((v) => <option key={v} value={v}>{v.replaceAll("_", " ")}</option>)}</select></label>
    <label className={styles.field}>Severity<select className={styles.select} value={severity} onChange={(e) => setSeverity(e.target.value)}>{SUPPORT_SEVERITIES.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
    <label className={styles.field}>Status<select className={styles.select} value={status} onChange={(e) => setStatus(e.target.value)}>{SUPPORT_STATUSES.map((v) => <option key={v} value={v}>{v.replaceAll("_", " ")}</option>)}</select></label>
    <label className={styles.field}>Safe operating summary<textarea className={styles.textarea} required minLength={5} maxLength={500} value={safeSummary} onChange={(e) => setSafeSummary(e.target.value)} /></label>
    <label className={styles.field}>Owner<select className={styles.select} value={ownerUserId} onChange={(e) => setOwnerUserId(e.target.value)}><option value="">Unassigned</option>{owners.map((owner) => <option key={owner.userId} value={owner.userId}>{owner.label} · {owner.role}</option>)}</select></label>
    <label className={styles.field}>Internal target date<input className={styles.input} type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} /></label>
    <label className={styles.field}>No-PHI product issue reference<input className={styles.input} maxLength={180} value={linkedIssueReference} onChange={(e) => setLinkedIssueReference(e.target.value)} placeholder="Example: github/issues/123" /></label>
    <button className={styles.button} disabled={busy} type="submit">{busy ? "Saving…" : "Save case"}</button>
  </form>;
}
