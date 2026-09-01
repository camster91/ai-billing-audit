"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import styles from "../../hq.module.css";

interface OwnerOption { userId: string; role: string; label: string }

export function ClientConversion({ leadId, owners }: { leadId: string; owners: OwnerOption[] }) {
  const router = useRouter();
  const [ownerUserId, setOwnerUserId] = useState("");
  const [offerReference, setOfferReference] = useState("");
  const [pilotStartAt, setPilotStartAt] = useState("");
  const [pilotEndAt, setPilotEndAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/hq/leads/${encodeURIComponent(leadId)}/convert`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          mutationId: crypto.randomUUID(),
          ownerUserId: ownerUserId || null,
          offerReference: offerReference || null,
          pilotStartAt: pilotStartAt ? new Date(pilotStartAt).toISOString() : null,
          pilotEndAt: pilotEndAt ? new Date(pilotEndAt).toISOString() : null,
        }),
      });
      const payload = (await response.json()) as { engagement?: { id: string }; detail?: string; error?: string };
      if (!response.ok || !payload.engagement) {
        setError(payload.detail ?? payload.error ?? "Could not create the client engagement.");
        return;
      }
      router.push(`/hq/clients/${payload.engagement.id}`);
      router.refresh();
    } catch {
      setError("Network error. No client engagement was confirmed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      {error ? <div role="alert" className={styles.error}>{error}</div> : null}
      <label className={styles.field}>Client owner
        <select className={styles.select} value={ownerUserId} onChange={(event) => setOwnerUserId(event.target.value)}>
          <option value="">Unassigned</option>
          {owners.map((owner) => <option key={owner.userId} value={owner.userId}>{owner.label} · {owner.role}</option>)}
        </select>
      </label>
      <label className={styles.field}>Approved offer reference
        <input className={styles.input} maxLength={120} value={offerReference} onChange={(event) => setOfferReference(event.target.value)} placeholder="Example: Pilot offer PO-2026-001" />
      </label>
      <label className={styles.field}>Pilot start
        <input className={styles.input} type="datetime-local" value={pilotStartAt} onChange={(event) => setPilotStartAt(event.target.value)} />
      </label>
      <label className={styles.field}>Pilot end
        <input className={styles.input} type="datetime-local" value={pilotEndAt} onChange={(event) => setPilotEndAt(event.target.value)} />
      </label>
      <p className={styles.warning}>Creates an internal client record and onboarding tasks only. It does not create a clinic tenant, charge, or message anyone. Do not enter clinical information.</p>
      <button className={styles.button} disabled={busy} type="submit">{busy ? "Creating…" : "Create client engagement"}</button>
    </form>
  );
}
