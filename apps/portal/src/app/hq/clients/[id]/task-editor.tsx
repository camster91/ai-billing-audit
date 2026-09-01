"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { COMPANY_TASK_PRIORITIES, COMPANY_TASK_STATUSES } from "@/lib/company-task-rules";
import styles from "../../hq.module.css";

interface OwnerOption { userId: string; role: string; label: string }
interface TaskEditorProps {
  engagementId: string;
  task: { id: string; title: string; status: string; priority: string; ownerUserId: string | null; dueAt: string | null; evidenceReference: string | null; version: number };
  owners: OwnerOption[];
}

function localDateTimeValue(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function TaskEditor({ engagementId, task, owners }: TaskEditorProps) {
  const router = useRouter();
  const [status, setStatus] = useState(task.status);
  const [priority, setPriority] = useState(task.priority);
  const [ownerUserId, setOwnerUserId] = useState(task.ownerUserId ?? "");
  const [dueAt, setDueAt] = useState(localDateTimeValue(task.dueAt));
  const [evidenceReference, setEvidenceReference] = useState(task.evidenceReference ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/hq/clients/${encodeURIComponent(engagementId)}/tasks/${encodeURIComponent(task.id)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          expectedVersion: task.version,
          mutationId: crypto.randomUUID(),
          status,
          priority,
          ownerUserId: ownerUserId || null,
          dueAt: dueAt ? new Date(dueAt).toISOString() : null,
          evidenceReference: evidenceReference || null,
        }),
      });
      const payload = (await response.json()) as { detail?: string; error?: string };
      if (!response.ok) {
        setMessage(response.status === 409 ? "This task changed elsewhere. Reload before retrying." : payload.detail ?? payload.error ?? "Could not update task.");
        return;
      }
      router.refresh();
    } catch {
      setMessage("Network error. No task update was confirmed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <strong>{task.title}</strong>
      {message ? <div role="alert" className={styles.error}>{message}</div> : null}
      <label className={styles.field}>Status
        <select className={styles.select} value={status} onChange={(event) => setStatus(event.target.value)}>
          {COMPANY_TASK_STATUSES.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
        </select>
      </label>
      <label className={styles.field}>Priority
        <select className={styles.select} value={priority} onChange={(event) => setPriority(event.target.value)}>
          {COMPANY_TASK_PRIORITIES.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label className={styles.field}>Owner
        <select className={styles.select} value={ownerUserId} onChange={(event) => setOwnerUserId(event.target.value)}>
          <option value="">Unassigned</option>
          {owners.map((owner) => <option key={owner.userId} value={owner.userId}>{owner.label} · {owner.role}</option>)}
        </select>
      </label>
      <label className={styles.field}>Due date
        <input className={styles.input} type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
      </label>
      <label className={styles.field}>Business evidence reference
        <input className={styles.input} maxLength={180} value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} placeholder="Example: approval/PO-2026-001" />
      </label>
      <button className={styles.button} disabled={busy} type="submit">{busy ? "Saving…" : "Save task"}</button>
    </form>
  );
}
