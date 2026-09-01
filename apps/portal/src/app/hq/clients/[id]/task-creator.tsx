"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { COMPANY_TASK_PRIORITIES } from "@/lib/company-task-rules";
import styles from "../../hq.module.css";

interface OwnerOption { userId: string; role: string; label: string }
interface Props { engagementId: string; owners: OwnerOption[] }

export function TaskCreator({ engagementId, owners }: Props) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("normal");
  const [ownerUserId, setOwnerUserId] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/hq/clients/${encodeURIComponent(engagementId)}/tasks`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ mutationId: crypto.randomUUID(), title, priority, ownerUserId: ownerUserId || null, dueAt: dueAt ? new Date(dueAt).toISOString() : null }),
      });
      const payload = (await response.json()) as { detail?: string; error?: string };
      if (!response.ok) {
        setMessage(payload.detail ?? payload.error ?? "Could not create task.");
        return;
      }
      setTitle("");
      setDueAt("");
      setMessage("Task created.");
      router.refresh();
    } catch {
      setMessage("Network error. No task creation was confirmed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <h3>Add company task</h3>
      <p className={styles.muted}>Use business workflow language only; never include patient or clinical details.</p>
      {message ? <div role="status" className={styles.muted}>{message}</div> : null}
      <label className={styles.field}>Task title
        <input className={styles.input} required minLength={3} maxLength={120} value={title} onChange={(event) => setTitle(event.target.value)} />
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
      <button className={styles.button} disabled={busy} type="submit">{busy ? "Creating…" : "Create task"}</button>
    </form>
  );
}
