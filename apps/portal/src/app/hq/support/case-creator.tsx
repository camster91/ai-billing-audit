"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { SUPPORT_CATEGORIES, SUPPORT_SEVERITIES } from "@/lib/support-case-rules";
import styles from "../hq.module.css";

interface Option { id: string; label: string }
interface Owner { userId: string; role: string; label: string }

export function CaseCreator({ engagements, owners }: { engagements: Option[]; owners: Owner[] }) {
  const router = useRouter();
  const [engagementId, setEngagementId] = useState(engagements[0]?.id ?? "");
  const [category, setCategory] = useState("workflow");
  const [severity, setSeverity] = useState("normal");
  const [safeSummary, setSafeSummary] = useState("");
  const [ownerUserId, setOwnerUserId] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(null);
    try {
      const response = await fetch("/api/hq/support", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ mutationId: crypto.randomUUID(), engagementId, category, severity, safeSummary, ownerUserId: ownerUserId || null, dueAt: dueAt ? new Date(dueAt).toISOString() : null }),
      });
      const payload = (await response.json()) as { detail?: string; error?: string; supportCase?: { id: string } };
      if (!response.ok) { setMessage(payload.detail ?? payload.error ?? "Could not create case."); return; }
      if (payload.supportCase?.id) router.push(`/hq/support/${encodeURIComponent(payload.supportCase.id)}`);
    } catch { setMessage("Network error. No support case was confirmed."); }
    finally { setBusy(false); }
  }

  if (engagements.length === 0) return <div className={styles.empty}>Create an active client engagement before opening an internal support case.</div>;
  return <form className={styles.form} onSubmit={submit}>
    <h2>Open internal case</h2>
    <p className={styles.muted}>No patient, claim, or clinical content. Creating a case does not message the client or promise an SLA.</p>
    {message ? <div role="alert" className={styles.error}>{message}</div> : null}
    <label className={styles.field}>Client engagement<select className={styles.select} value={engagementId} onChange={(event) => setEngagementId(event.target.value)}>{engagements.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
    <label className={styles.field}>Category<select className={styles.select} value={category} onChange={(event) => setCategory(event.target.value)}>{SUPPORT_CATEGORIES.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
    <label className={styles.field}>Severity<select className={styles.select} value={severity} onChange={(event) => setSeverity(event.target.value)}>{SUPPORT_SEVERITIES.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
    <label className={styles.field}>Safe operating summary<textarea className={styles.textarea} required minLength={5} maxLength={500} value={safeSummary} onChange={(event) => setSafeSummary(event.target.value)} /></label>
    <label className={styles.field}>Owner<select className={styles.select} value={ownerUserId} onChange={(event) => setOwnerUserId(event.target.value)}><option value="">Unassigned</option>{owners.map((owner) => <option key={owner.userId} value={owner.userId}>{owner.label} · {owner.role}</option>)}</select></label>
    <label className={styles.field}>Internal target date<input className={styles.input} type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label>
    <button className={styles.button} disabled={busy} type="submit">{busy ? "Opening…" : "Open case"}</button>
  </form>;
}
