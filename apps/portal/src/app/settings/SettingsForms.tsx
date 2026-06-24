"use client";

// /settings — interactive edit panels.
//
// Three controlled forms that POST to the matching /api/settings/*
// route and call router.refresh() on success so the parent server
// component re-fetches the latest values. Each form owns its own
// busy / error state so one failure doesn't poison the others.
//
// The data-residency form is the only conditional UI: when the
// server-rendered page tells us the region is locked (region-locked
// flag from the wizard, OR an Encounter row exists), the dropdown
// is disabled, a lock icon is shown, and a tooltip explains why.
// The server still enforces the lock — the UI just makes it
// discoverable.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import styles from "./settings.module.css";

interface SettingsFormsProps {
  tenantId: string;
  initial: {
    clinicName: string | null;
    clinicAddress: string | null;
    clinicNpi: string | null;
    clinicTimezone: string | null;
    dataResidencyRegion: string | null;
    redactPatientNamesInExports: boolean;
  };
  residencyRegions: ReadonlyArray<string>;
  residencyLocked: boolean;
}

export default function SettingsForms({
  tenantId,
  initial,
  residencyRegions,
  residencyLocked,
}: SettingsFormsProps) {
  // tenantId is unused on the client today but kept in the prop shape
  // so the server can pass it through for future client-driven lookups
  // (audit-count badge, region-flag tip) without an API round-trip.
  void tenantId;

  return (
    <div>
      <ClinicProfileForm initial={initial} />
      <ResidencyForm
        initialRegion={initial.dataResidencyRegion}
        regions={residencyRegions}
        locked={residencyLocked}
      />
      <PhiRedactionForm initial={initial.redactPatientNamesInExports} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Clinic profile
// ---------------------------------------------------------------------------

function ClinicProfileForm({
  initial,
}: {
  initial: {
    clinicName: string | null;
    clinicAddress: string | null;
    clinicNpi: string | null;
    clinicTimezone: string | null;
  };
}) {
  const router = useRouter();
  const [clinicName, setClinicName] = useState(initial.clinicName ?? "");
  const [clinicAddress, setClinicAddress] = useState(
    initial.clinicAddress ?? "",
  );
  const [clinicNpi, setClinicNpi] = useState(initial.clinicNpi ?? "");
  const [clinicTimezone, setClinicTimezone] = useState(
    initial.clinicTimezone ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [isPending, startTransition] = useTransition();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch("/api/settings/clinic-profile", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          clinicName,
          clinicAddress,
          clinicNpi,
          clinicTimezone,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.message ?? `Save failed (${res.status})`);
        return;
      }
      setSaved(true);
      startTransition(() => router.refresh());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.card}>
      <header className={styles.cardHeader}>
        <h2>Clinic profile</h2>
      </header>
      <form onSubmit={onSubmit}>
        <Field
          id="clinicName"
          label="Clinic name"
          value={clinicName}
          onChange={setClinicName}
          placeholder="Display name shown across the portal"
          maxLength={120}
        />
        <Field
          id="clinicAddress"
          label="Mailing address"
          value={clinicAddress}
          onChange={setClinicAddress}
          placeholder="Street, city, province/state, postal code"
          maxLength={500}
          multiline
        />
        <Field
          id="clinicNpi"
          label="Billing NPI"
          value={clinicNpi}
          onChange={setClinicNpi}
          placeholder="10-digit US NPI, or 6–15 char alphanumeric"
          maxLength={15}
        />
        <Field
          id="clinicTimezone"
          label="Default timezone"
          value={clinicTimezone}
          onChange={setClinicTimezone}
          placeholder="IANA tz, e.g. America/Toronto"
          maxLength={64}
        />
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.button}
            disabled={busy || isPending}
          >
            {busy ? "Saving…" : "Save profile"}
          </button>
          {error ? <span className={styles.error}>{error}</span> : null}
          {saved && !error ? (
            <span className={styles.saved}>Saved.</span>
          ) : null}
        </div>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Data residency
// ---------------------------------------------------------------------------

function ResidencyForm({
  initialRegion,
  regions,
  locked,
}: {
  initialRegion: string | null;
  regions: ReadonlyArray<string>;
  locked: boolean;
}) {
  const router = useRouter();
  const [region, setRegion] = useState(initialRegion ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [isPending, startTransition] = useTransition();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (locked) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch("/api/settings/region", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ region }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.message ?? `Save failed (${res.status})`);
        return;
      }
      setSaved(true);
      startTransition(() => router.refresh());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.card}>
      <header className={styles.cardHeader}>
        <h2>Data residency</h2>
        {locked ? (
          <span
            className={styles.lockBadge}
            title="Region is immutable: the wizard completed or the first audit has been recorded."
            aria-label="Region locked"
          >
            <LockIcon /> locked
          </span>
        ) : null}
      </header>
      <p className={styles.cardSub}>
        Where audit data is stored. {regions.length} regions available.
      </p>
      <form onSubmit={onSubmit}>
        <label className={styles.label} htmlFor="region">
          Region
        </label>
        <select
          id="region"
          className={styles.select}
          value={region}
          onChange={(e) => setRegion(e.target.value)}
          disabled={locked}
          aria-describedby={locked ? "region-lock-help" : undefined}
        >
          <option value="" disabled>
            Select a region…
          </option>
          {regions.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        {locked ? (
          <p id="region-lock-help" className={styles.helpText}>
            Region is immutable after the wizard completed or after the
            first audit has been recorded.
          </p>
        ) : null}
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.button}
            disabled={busy || isPending || locked || !region}
          >
            {busy ? "Saving…" : "Save region"}
          </button>
          {error ? <span className={styles.error}>{error}</span> : null}
          {saved && !error ? (
            <span className={styles.saved}>Saved.</span>
          ) : null}
        </div>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------------------
// PHI redaction toggle
// ---------------------------------------------------------------------------

function PhiRedactionForm({ initial }: { initial: boolean }) {
  const router = useRouter();
  const [redact, setRedact] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [isPending, startTransition] = useTransition();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch("/api/settings/phi-redaction", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ redact }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.message ?? `Save failed (${res.status})`);
        return;
      }
      setSaved(true);
      startTransition(() => router.refresh());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.card}>
      <header className={styles.cardHeader}>
        <h2>PHI handling</h2>
      </header>
      <p className={styles.cardSub}>
        Audit log exports (encounters CSV, findings CSV) embed a 12-char
        prefix of the per-encounter patient hash. When this toggle is on,
        the export route replaces the prefix with &quot;[redacted]&quot; so
        downstream spreadsheets don&apos;t carry the fingerprint that
        links a row back to a patient identifier.
      </p>
      <form onSubmit={onSubmit}>
        <label className={styles.toggleRow} htmlFor="phi-redact">
          <input
            id="phi-redact"
            type="checkbox"
            checked={redact}
            onChange={(e) => setRedact(e.target.checked)}
          />
          <span>Redact patient names in audit log exports</span>
        </label>
        <div className={styles.actions}>
          <button
            type="submit"
            className={styles.button}
            disabled={busy || isPending}
          >
            {busy ? "Saving…" : "Save preference"}
          </button>
          {error ? <span className={styles.error}>{error}</span> : null}
          {saved && !error ? (
            <span className={styles.saved}>Saved.</span>
          ) : null}
        </div>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Small shared bits
// ---------------------------------------------------------------------------

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  maxLength,
  multiline = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  maxLength?: number;
  multiline?: boolean;
}) {
  return (
    <div className={styles.fieldRow}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      {multiline ? (
        <textarea
          id={id}
          className={styles.textarea}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          maxLength={maxLength}
          rows={3}
        />
      ) : (
        <input
          id={id}
          type="text"
          className={styles.input}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          maxLength={maxLength}
          autoComplete="off"
        />
      )}
    </div>
  );
}

function LockIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M4 7V5a4 4 0 1 1 8 0v2h1a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h1Zm2 0h4V5a2 2 0 1 0-4 0v2Z"
        fill="currentColor"
      />
    </svg>
  );
}
