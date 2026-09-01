"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { LEAD_QUALIFICATION_STATUSES, LEAD_STAGES } from "@/lib/lead-workflow-rules";
import styles from "../../hq.module.css";

interface OperatorOption {
  userId: string;
  role: string;
  label: string;
}

interface LeadEditorProps {
  leadId: string;
  version: number;
  status: string;
  ownerUserId: string | null;
  nextAction: string | null;
  nextActionAt: string | null;
  lostReason: string | null;
  qualificationStatus: string;
  qualificationReason: string | null;
  qualificationEvidenceRef: string | null;
  operators: OperatorOption[];
}

function localDateTimeValue(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function LeadEditor(props: LeadEditorProps) {
  const router = useRouter();
  const [status, setStatus] = useState(props.status);
  const [ownerUserId, setOwnerUserId] = useState(props.ownerUserId ?? "");
  const [nextAction, setNextAction] = useState(props.nextAction ?? "");
  const [nextActionAt, setNextActionAt] = useState(localDateTimeValue(props.nextActionAt));
  const [lostReason, setLostReason] = useState(props.lostReason ?? "");
  const [qualificationStatus, setQualificationStatus] = useState(props.qualificationStatus);
  const [qualificationReason, setQualificationReason] = useState(props.qualificationReason ?? "");
  const [qualificationEvidenceRef, setQualificationEvidenceRef] = useState(props.qualificationEvidenceRef ?? "");
  const [logContactNow, setLogContactNow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "error" | "success"; text: string } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/hq/leads/${encodeURIComponent(props.leadId)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          expectedVersion: props.version,
          mutationId: crypto.randomUUID(),
          status,
          ownerUserId: ownerUserId || null,
          nextAction: nextAction || null,
          nextActionAt: nextActionAt ? new Date(nextActionAt).toISOString() : null,
          lostReason: lostReason || null,
          qualificationStatus,
          qualificationReason: qualificationReason || null,
          qualificationEvidenceRef: qualificationEvidenceRef || null,
          logContactNow,
        }),
      });
      const payload = (await response.json()) as { error?: string; detail?: string };
      if (!response.ok) {
        const conflict = response.status === 409
          ? "This lead changed in another session. Reload before trying again."
          : payload.detail ?? payload.error ?? "Could not update the lead.";
        setMessage({ type: "error", text: conflict });
        return;
      }
      setMessage({ type: "success", text: "Lead updated and recorded in the activity timeline." });
      setLogContactNow(false);
      router.refresh();
    } catch {
      setMessage({ type: "error", text: "Network error. Nothing was confirmed; retry when connected." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      {message ? <div role="status" className={message.type === "error" ? styles.error : styles.success}>{message.text}</div> : null}
      <label className={styles.field}>Stage
        <select className={styles.select} value={status} onChange={(event) => setStatus(event.target.value)}>
          {LEAD_STAGES.map((stage) => <option key={stage} value={stage}>{stage.replaceAll("_", " ")}</option>)}
        </select>
      </label>
      <label className={styles.field}>Owner
        <select className={styles.select} value={ownerUserId} onChange={(event) => setOwnerUserId(event.target.value)}>
          <option value="">Unassigned</option>
          {props.operators.map((operator) => <option key={operator.userId} value={operator.userId}>{operator.label} · {operator.role}</option>)}
        </select>
      </label>
      <label className={styles.field}>Next action
        <textarea className={styles.textarea} maxLength={240} value={nextAction} onChange={(event) => setNextAction(event.target.value)} placeholder="Example: Confirm discovery-call attendees" />
      </label>
      <label className={styles.field}>Next-action due date
        <input className={styles.input} type="datetime-local" value={nextActionAt} onChange={(event) => setNextActionAt(event.target.value)} />
      </label>
      <label className={styles.field}>Loss reason
        <textarea className={styles.textarea} maxLength={300} value={lostReason} onChange={(event) => setLostReason(event.target.value)} disabled={status !== "lost"} />
      </label>
      <fieldset className={styles.fieldset}>
        <legend>Qualification</legend>
        <label className={styles.field}>Decision
          <select className={styles.select} value={qualificationStatus} onChange={(event) => setQualificationStatus(event.target.value)}>
            {LEAD_QUALIFICATION_STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className={styles.field}>Commercial rationale
          <textarea className={styles.textarea} maxLength={500} value={qualificationReason} onChange={(event) => setQualificationReason(event.target.value)} disabled={qualificationStatus === "unreviewed"} placeholder="Example: Alberta primary-care clinic, target volume, and identified billing owner" />
        </label>
        <label className={styles.field}>Business evidence reference
          <input className={styles.input} maxLength={500} value={qualificationEvidenceRef} onChange={(event) => setQualificationEvidenceRef(event.target.value)} disabled={qualificationStatus === "unreviewed"} placeholder="Example: discovery-call note ID or approved CRM reference" />
        </label>
      </fieldset>
      <label className={styles.checkbox}>
        <input type="checkbox" checked={logContactNow} onChange={(event) => setLogContactNow(event.target.checked)} />
        <span>Record that a human contact occurred now. This does not send a message.</span>
      </label>
      <p className={styles.warning}>Commercial context only. Do not enter patient, clinical-note, diagnosis, or medical-record information.</p>
      <button className={styles.button} disabled={busy} type="submit">{busy ? "Saving…" : "Save lead"}</button>
    </form>
  );
}
