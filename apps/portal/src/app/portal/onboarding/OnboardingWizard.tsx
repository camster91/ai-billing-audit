"use client";

// /portal/onboarding — multi-step client wizard.
//
// Steps:
//   0. Clinic profile (name, NPI, timezone)
//   1. Data residency region (Canadian data centre | US-hosted, HIPAA-aligned region)
//   2. EHR connection (SFTP credentials or "manual" skip)
//   3. First encounter (drop an 837P file or "skipped")
//   4. Complete (lock region, dispatch welcome email, redirect to /dashboard)
//
// State is mirrored from the server's WizardState at mount. Each step
// POSTs to the matching /api/onboarding/* route and updates local
// state from the response. The page's Server Component will fetch
// fresh state on the next render (force-dynamic), so a refresh always
// lands on the right step.

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toUserFacingError } from "@/lib/ui-error";
import styles from "./onboarding.module.css";

interface WizardState {
  tenantId: string;
  step: number;
  completed: boolean;
  completedAt: Date | null;
  clinicName: string | null;
  clinicNpi: string | null;
  clinicTimezone: string | null;
  dataResidencyRegion: string | null;
  residencyRegionLocked: boolean;
  ehrConnectionMode: string | null;
  firstEncounterUploadMode: string | null;
  firstEncounterFileName: string | null;
  sessionId: string;
  alreadyClaimed: boolean;
}

interface Props {
  initialState: WizardState;
  sessionId: string;
}

const STEP_LABELS = [
  "Clinic profile",
  "Residency",
  "EHR connection",
  "First encounter",
  "Done",
] as const;

export default function OnboardingWizard({ initialState, sessionId }: Props) {
  const router = useRouter();
  const [state, setState] = useState<WizardState>(initialState);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [magicLink, setMagicLink] = useState<string | null>(null);
  const [emailMock, setEmailMock] = useState(false);

  // Step 0 form state (clinic profile).
  const [clinicName, setClinicName] = useState(initialState.clinicName ?? "");
  const [clinicNpi, setClinicNpi] = useState(initialState.clinicNpi ?? "");
  const [clinicTimezone, setClinicTimezone] = useState(
    initialState.clinicTimezone ?? "",
  );

  // Step 1 (region).
  const [region, setRegion] = useState<string>(
    initialState.dataResidencyRegion ?? "",
  );

  // Step 2 (EHR). Default to "sftp" on first visit.
  const [ehrMode, setEhrMode] = useState<"sftp" | "manual">(
    initialState.ehrConnectionMode === "manual" ? "manual" : "sftp",
  );
  const [ehrHost, setEhrHost] = useState("");
  const [ehrPort, setEhrPort] = useState("22");
  const [ehrUsername, setEhrUsername] = useState("");
  const [ehrPassword, setEhrPassword] = useState("");

  // Step 3 (first encounter).
  const [encounterFile, setEncounterFile] = useState<File | null>(null);
  const [encounterFilePath, setEncounterFilePath] = useState<string | null>(null);
  const [encounterSkip, setEncounterSkip] = useState(false);
  const encounterFileInputRef = useRef<HTMLInputElement | null>(null);

  const effectiveStep = useMemo(() => {
    if (state.completed) return 4;
    return Math.min(state.step, 3);
  }, [state]);

  // ----- Already complete: render the success state immediately. -----
  if (state.completed && !completing && !magicLink) {
    return (
      <div className={styles.completed}>
        <div className={styles.bigCheck} aria-hidden="true">✓</div>
        <h2>You're all set</h2>
        <p>
          Your clinic is fully onboarded. Jump to your dashboard to upload
          encounters and start auditing.
        </p>
        <div className={styles.actions}>
          <a className={styles.btn} href="/dashboard">Go to dashboard</a>
        </div>
      </div>
    );
  }

  // ----- Step transitions -----

  async function postJson<T = unknown>(url: string, body: Record<string, unknown>): Promise<T> {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => ({}))) as {
      error?: string;
      message?: string;
    } & T;
    if (!res.ok) {
      throw new Error((data as { message?: string }).message ?? (data as { error?: string }).error ?? `HTTP ${res.status}`);
    }
    return data as T;
  }

  async function submitClinicProfile(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const data = await postJson<{ onboardingStep?: number }>(
        "/api/onboarding/clinic-profile",
        {
          tenantId: state.tenantId,
          clinicName: clinicName.trim(),
          clinicNpi: clinicNpi.trim(),
          clinicTimezone: clinicTimezone.trim(),
        },
      );
      setState((s) => ({
        ...s,
        step: data.onboardingStep ?? Math.max(s.step, 2),
        clinicName: clinicName.trim() || s.clinicName,
        clinicNpi: clinicNpi.trim() || s.clinicNpi,
        clinicTimezone: clinicTimezone.trim() || s.clinicTimezone,
      }));
    } catch (err) {
      setError(toUserFacingError(err, "Could not save clinic profile"));
    } finally {
      setBusy(false);
    }
  }

  async function submitRegion(e: React.FormEvent) {
    e.preventDefault();
    if (!region) {
      setError("Pick a data residency region");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const data = await postJson<{ onboardingStep?: number; region?: string }>(
        "/api/onboarding/region",
        {
          tenantId: state.tenantId,
          region,
        },
      );
      setState((s) => ({
        ...s,
        step: data.onboardingStep ?? Math.max(s.step, 3),
        dataResidencyRegion: data.region ?? region,
      }));
    } catch (err) {
      setError(toUserFacingError(err, "Could not save region"));
    } finally {
      setBusy(false);
    }
  }

  async function submitEhr(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const data = await postJson<{ onboardingStep?: number; mode: "sftp" | "manual" }>(
        "/api/onboarding/ehr",
        {
          tenantId: state.tenantId,
          mode: ehrMode,
          host: ehrMode === "sftp" ? ehrHost.trim() : undefined,
          port: ehrMode === "sftp" ? Number.parseInt(ehrPort, 10) || 22 : undefined,
          username: ehrMode === "sftp" ? ehrUsername.trim() : undefined,
          password: ehrMode === "sftp" ? ehrPassword : undefined,
        },
      );
      setState((s) => ({
        ...s,
        step: data.onboardingStep ?? Math.max(s.step, 4),
        ehrConnectionMode: data.mode,
      }));
    } catch (err) {
      setError(toUserFacingError(err, "Could not save EHR connection"));
    } finally {
      setBusy(false);
    }
  }

  async function uploadEncounterFile() {
    if (!encounterFile) return null;
    const fd = new FormData();
    fd.set("file", encounterFile);
    fd.set("tenantId", state.tenantId);
    const res = await fetch("/api/onboarding/upload", {
      method: "POST",
      body: fd,
    });
    const data = (await res.json().catch(() => ({}))) as {
      error?: string;
      message?: string;
      filePath?: string;
      fileName?: string;
    };
    if (!res.ok) {
      throw new Error(data.message ?? data.error ?? `HTTP ${res.status}`);
    }
    return data;
  }

  async function submitFirstEncounter(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      let filePath: string | null = null;
      let fileName: string | null = null;

      if (!encounterSkip) {
        if (!encounterFile) {
          setError("Pick a file or check the 'skip for now' box.");
          setBusy(false);
          return;
        }
        const upload = await uploadEncounterFile();
        if (!upload) {
          setError("File upload failed");
          setBusy(false);
          return;
        }
        filePath = upload.filePath ?? null;
        fileName = upload.fileName ?? encounterFile.name;
      }

      const data = await postJson<{
        onboardingStep?: number;
        mode: "uploaded" | "skipped";
      }>("/api/onboarding/first-encounter", {
        tenantId: state.tenantId,
        mode: encounterSkip ? "skipped" : "uploaded",
        filePath,
        fileName,
      });
      setState((s) => ({
        ...s,
        step: data.onboardingStep ?? Math.max(s.step, 5),
        firstEncounterUploadMode: data.mode,
        firstEncounterFileName: fileName ?? s.firstEncounterFileName,
      }));
    } catch (err) {
      setError(toUserFacingError(err, "Could not save first encounter"));
    } finally {
      setBusy(false);
    }
  }

  async function completeWizard() {
    setError(null);
    setCompleting(true);
    setBusy(true);
    try {
      const data = (await postJson("/api/onboarding/complete", {
        tenantId: state.tenantId,
      })) as {
        tenant: { id: string; name: string; onboardingCompletedAt: string };
        magicLink: string;
        emailSent: boolean;
        emailMock: boolean;
      };
      setMagicLink(data.magicLink);
      setEmailMock(Boolean(data.emailMock));
      setState((s) => ({
        ...s,
        completed: true,
        completedAt: new Date(data.tenant.onboardingCompletedAt),
        residencyRegionLocked: true,
      }));
    } catch (err) {
      setError(toUserFacingError(err, "Could not complete wizard"));
      setCompleting(false);
    } finally {
      setBusy(false);
    }
  }

  // ----- Render -----

  return (
    <>
      <ol className={styles.steps} aria-label="Onboarding steps">
        {STEP_LABELS.slice(0, 4).map((label, idx) => {
          const isActive = idx === effectiveStep && !state.completed;
          const isDone =
            idx < effectiveStep || state.completed || (state.step > idx && !state.completed);
          return (
            <li
              key={label}
              className={
                isActive ? styles.active : isDone ? styles.done : undefined
              }
            >
              <span className={styles.stepDot}>{isDone ? "✓" : idx + 1}</span>
              <span>{label}</span>
            </li>
          );
        })}
      </ol>

      {error && <div className={styles.errorBanner} role="alert">{error}</div>}

      {effectiveStep === 0 && (
        <form onSubmit={submitClinicProfile} className={styles.stepBody}>
          <h2>Clinic profile</h2>
          <p className={styles.helpText}>
            Optional — fill in what you have. You can update these later from Settings.
          </p>

          <label htmlFor="clinicName">Clinic name</label>
          <input
            id="clinicName"
            type="text"
            value={clinicName}
            placeholder="e.g. Maple Leaf Family Practice"
            onChange={(e) => setClinicName(e.target.value)}
            maxLength={120}
          />

          <label htmlFor="clinicNpi">Billing NPI</label>
          <input
            id="clinicNpi"
            type="text"
            value={clinicNpi}
            placeholder="10-digit NPI, or leave blank"
            onChange={(e) => setClinicNpi(e.target.value)}
            maxLength={15}
          />

          <label htmlFor="clinicTimezone">Timezone</label>
          <input
            id="clinicTimezone"
            type="text"
            value={clinicTimezone}
            placeholder="America/Toronto"
            onChange={(e) => setClinicTimezone(e.target.value)}
            maxLength={64}
          />
          <p className={styles.helpText}>
            IANA timezone name (e.g. America/Toronto, America/Los_Angeles).
          </p>

          <div className={styles.navRow}>
            <span />
            <button type="submit" className={styles.btn} disabled={busy}>
              {busy ? "Saving…" : "Continue →"}
            </button>
          </div>
        </form>
      )}

      {effectiveStep === 1 && (
        <form onSubmit={submitRegion} className={styles.stepBody}>
          <h2>Data residency</h2>
          <p className={styles.helpText}>
            Where do you want your data to live? This choice is
            <strong> locked</strong> once you finish the wizard.
          </p>

          <div className={styles.regionRow}>
            <label
              className={`${styles.regionOption} ${
                region === "ca-central-1" ? styles.selected : ""
              }`}
            >
              <input
                type="radio"
                name="region"
                value="ca-central-1"
                checked={region === "ca-central-1"}
                onChange={() => setRegion("ca-central-1")}
              />
              <strong>Canada (Canadian data centre)</strong>
              <span>Region confirmed in the BAA. PIPEDA-aligned.</span>
            </label>
            <label
              className={`${styles.regionOption} ${
                region === "us-east-1" ? styles.selected : ""
              }`}
            >
              <input
                type="radio"
                name="region"
                value="us-east-1"
                checked={region === "us-east-1"}
                onChange={() => setRegion("us-east-1")}
              />
              <strong>United States (US-hosted, HIPAA-aligned)</strong>
              <span>Region confirmed in the BAA. HIPAA-aligned.</span>
            </label>
          </div>

          <div className={styles.navRow}>
            <button
              type="button"
              className={styles.btnGhost}
              onClick={() => setState((s) => ({ ...s, step: 1 }))}
              disabled={busy}
            >
              ← Back
            </button>
            <button type="submit" className={styles.btn} disabled={busy || !region}>
              {busy ? "Saving…" : "Continue →"}
            </button>
          </div>
        </form>
      )}

      {effectiveStep === 2 && (
        <form onSubmit={submitEhr} className={styles.stepBody}>
          <h2>EHR connection</h2>
          <p className={styles.helpText}>
            Connect your EHR via SFTP for automated file delivery, or skip
            and upload 837P files manually on the next step.
          </p>

          <div className={styles.skipRow}>
            <label>
              <input
                type="radio"
                name="ehrMode"
                checked={ehrMode === "sftp"}
                onChange={() => setEhrMode("sftp")}
              />{" "}
              Connect via SFTP
            </label>
            <label>
              <input
                type="radio"
                name="ehrMode"
                checked={ehrMode === "manual"}
                onChange={() => setEhrMode("manual")}
              />{" "}
              Skip — I'll upload files manually
            </label>
          </div>

          {ehrMode === "sftp" && (
            <>
              <label htmlFor="ehrHost">SFTP host</label>
              <input
                id="ehrHost"
                type="text"
                value={ehrHost}
                placeholder="sftp.example.com"
                onChange={(e) => setEhrHost(e.target.value)}
                required
              />

              <label htmlFor="ehrPort">Port</label>
              <input
                id="ehrPort"
                type="number"
                value={ehrPort}
                onChange={(e) => setEhrPort(e.target.value)}
                min={1}
                max={65535}
                required
              />

              <label htmlFor="ehrUsername">Username</label>
              <input
                id="ehrUsername"
                type="text"
                value={ehrUsername}
                onChange={(e) => setEhrUsername(e.target.value)}
                required
              />

              <label htmlFor="ehrPassword">Password / key passphrase</label>
              <input
                id="ehrPassword"
                type="password"
                value={ehrPassword}
                onChange={(e) => setEhrPassword(e.target.value)}
                required
                autoComplete="new-password"
              />
              <p className={styles.helpText}>
                Stored encrypted. Used by the audit pipeline to pull 837P
                files on a schedule.
              </p>
            </>
          )}

          <div className={styles.navRow}>
            <button
              type="button"
              className={styles.btnGhost}
              onClick={() => setState((s) => ({ ...s, step: 2 }))}
              disabled={busy}
            >
              ← Back
            </button>
            <button type="submit" className={styles.btn} disabled={busy}>
              {busy ? "Saving…" : "Continue →"}
            </button>
          </div>
        </form>
      )}

      {effectiveStep === 3 && (
        <form onSubmit={submitFirstEncounter} className={styles.stepBody}>
          <h2>First encounter (optional)</h2>
          <p className={styles.helpText}>
            Drop a single 837P file to get your first audit running, or skip
            and upload later from the Encounters page.
          </p>

          <div
            className={`${styles.dropZone} ${
              encounterFile ? styles.hasFile : ""
            }`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files?.[0];
              if (f) {
                setEncounterFile(f);
                setEncounterSkip(false);
              }
            }}
          >
            {encounterFile ? (
              <div>
                <strong>{encounterFile.name}</strong>
                <div className={styles.helpText}>
                  {(encounterFile.size / 1024).toFixed(1)} KB — ready to upload
                </div>
              </div>
            ) : (
              <div>
                Drag a 837P file here, or
                <br />
                <input
                  ref={encounterFileInputRef}
                  type="file"
                  accept=".837,.txt,.edi,text/plain,application/octet-stream"
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    setEncounterFile(f);
                    if (f) setEncounterSkip(false);
                  }}
                />
              </div>
            )}
          </div>

          <label className={styles.skipRow}>
            <input
              type="checkbox"
              checked={encounterSkip}
              onChange={(e) => {
                setEncounterSkip(e.target.checked);
                if (e.target.checked) setEncounterFile(null);
              }}
            />
            Skip for now — I'll upload encounters later
          </label>

          <div className={styles.navRow}>
            <button
              type="button"
              className={styles.btnGhost}
              onClick={() => setState((s) => ({ ...s, step: 3 }))}
              disabled={busy}
            >
              ← Back
            </button>
            <button type="submit" className={styles.btn} disabled={busy}>
              {busy ? "Uploading…" : "Continue →"}
            </button>
          </div>
        </form>
      )}

      {effectiveStep === 4 && !state.completed && (
        <div className={styles.stepBody}>
          <h2>All set — finish setup</h2>
          <p>
            Lock your data residency, send yourself a magic-link welcome
            email, and unlock the dashboard.
          </p>
          <ul>
            <li>
              Clinic: <strong>{state.clinicName || "—"}</strong>
            </li>
            <li>
              NPI: <strong>{state.clinicNpi || "—"}</strong>
            </li>
            <li>
              Timezone: <strong>{state.clinicTimezone || "—"}</strong>
            </li>
            <li>
              Residency: <strong>{state.dataResidencyRegion || "—"}</strong>
            </li>
            <li>
              EHR:{" "}
              <strong>
                {state.ehrConnectionMode === "sftp"
                  ? "SFTP"
                  : state.ehrConnectionMode === "manual"
                    ? "Manual upload"
                    : "—"}
              </strong>
            </li>
            <li>
              First encounter:{" "}
              <strong>
                {state.firstEncounterUploadMode === "uploaded"
                  ? state.firstEncounterFileName ?? "File uploaded"
                  : state.firstEncounterUploadMode === "skipped"
                    ? "Skipped"
                    : "—"}
              </strong>
            </li>
          </ul>
          <div className={styles.navRow}>
            <span />
            <button
              type="button"
              className={styles.btn}
              onClick={completeWizard}
              disabled={busy}
            >
              {busy ? "Finishing…" : "Finish setup →"}
            </button>
          </div>
        </div>
      )}

      {state.completed && magicLink && (
        <div className={styles.completed}>
          <div className={styles.bigCheck} aria-hidden="true">✓</div>
          <h2>Welcome aboard</h2>
          <p>
            Your residency region is locked. We've sent a magic-link sign-in
            email to the address on your account.
          </p>
          {emailMock && (
            <p className={styles.helpText}>
              (Dev mode: no Resend key configured, so the email was logged
              to the server console instead of dispatched.)
            </p>
          )}
          <div className={styles.signInRow}>
            <a href={magicLink} className={styles.btn}>
              Open the portal →
            </a>
            <p className={styles.helpText}>
              The link works once and expires in 24 hours.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
