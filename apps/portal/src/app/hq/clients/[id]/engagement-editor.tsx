"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  CLIENT_ENGAGEMENT_STATUSES,
  CLIENT_HEALTH_STATUSES,
  PRIVACY_APPROVAL_STATUSES,
} from "@/lib/client-engagement-rules";
import styles from "../../hq.module.css";

interface Props {
  client: { id: string; status: string; privacyApprovalStatus: string; firstValueAt: string | null; healthStatus: string; version: number };
}

function localDateTimeValue(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function EngagementEditor({ client }: Props) {
  const router = useRouter();
  const [status, setStatus] = useState(client.status);
  const [privacyApprovalStatus, setPrivacyApprovalStatus] = useState(client.privacyApprovalStatus);
  const [firstValueAt, setFirstValueAt] = useState(localDateTimeValue(client.firstValueAt));
  const [healthStatus, setHealthStatus] = useState(client.healthStatus);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/hq/clients/${encodeURIComponent(client.id)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          expectedVersion: client.version,
          mutationId: crypto.randomUUID(),
          status,
          privacyApprovalStatus,
          firstValueAt: firstValueAt ? new Date(firstValueAt).toISOString() : null,
          healthStatus,
        }),
      });
      const payload = (await response.json()) as { detail?: string; error?: string };
      if (!response.ok) {
        setMessage(response.status === 409 ? "This engagement changed elsewhere. Reload before retrying." : payload.detail ?? payload.error ?? "Could not update engagement.");
        return;
      }
      router.refresh();
    } catch {
      setMessage("Network error. No engagement update was confirmed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <h2>Update milestones</h2>
      <p className={styles.muted}>Operational status only. This does not provision a tenant or contact the client.</p>
      {message ? <div role="alert" className={styles.error}>{message}</div> : null}
      <label className={styles.field}>Engagement status
        <select className={styles.select} value={status} onChange={(event) => setStatus(event.target.value)}>
          {CLIENT_ENGAGEMENT_STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
        </select>
      </label>
      <label className={styles.field}>Privacy approval
        <select className={styles.select} value={privacyApprovalStatus} onChange={(event) => setPrivacyApprovalStatus(event.target.value)}>
          {PRIVACY_APPROVAL_STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
        </select>
      </label>
      <label className={styles.field}>First value reached
        <input className={styles.input} type="datetime-local" value={firstValueAt} onChange={(event) => setFirstValueAt(event.target.value)} />
      </label>
      <label className={styles.field}>Client health
        <select className={styles.select} value={healthStatus} onChange={(event) => setHealthStatus(event.target.value)}>
          {CLIENT_HEALTH_STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
        </select>
      </label>
      <button className={styles.button} disabled={busy} type="submit">{busy ? "Saving…" : "Save milestones"}</button>
    </form>
  );
}
