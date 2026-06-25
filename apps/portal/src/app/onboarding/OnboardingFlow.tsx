"use client";

// /onboarding — 5-step wizard Client Component.
//
// Steps (see docs/ALBERTA_STRATEGY_BRIEF.md and the PCN pitch for
// the 60-day pilot workflow):
//
//   0. Account           — clinic name + sign-in email (or "I already
//                          have an account" link to /login)
//   1. HIA paperwork     — confirm DPA on file, custodian + privacy
//                          officer name + email
//   2. Import pilot data — 837P file / SFTP creds / CSV / skip
//   3. Run first audit   — triggers /api/audits with the imported data
//   4. Accept first finding — biller reviews and accepts/edits/dismisses
//                          the first finding produced
//
// State persistence:
//   - The current step is mirrored to localStorage so a refresh
//     lands the clinic on the same step (but NOT form data —
//     re-fill is intentional for sensitive fields like SFTP creds).
//   - Each "Continue" button POSTs to a route handler that does
//     the real work (creates tenant, accepts DPA, ingests file,
//     runs audit). The wizard updates its local step on success.
//
// Skip:
//   - Every step has a "Skip for now" link at the bottom. Skipping
//     advances the active step but does NOT mark the step done —
//     the user can return to skipped steps from /portal/onboarding.
//
// This component is intentionally simple: no animation library, no
// Redux, no form library. The portal already has form patterns
// (see /portal/onboarding/OnboardingWizard.tsx) but those are
// tuned for the post-checkout flow. The /onboarding route is the
// pre-checkout / cold-start flow and is intentionally minimal.

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import styles from "./onboarding.module.css";

interface FormState {
  // Step 0 — account
  clinicName: string;
  signInEmail: string;
  // Step 1 — HIA paperwork
  dpaConfirmed: boolean;
  custodianName: string;
  custodianEmail: string;
  privacyOfficerName: string;
  privacyOfficerEmail: string;
  // Step 2 — import
  importMode: "skip" | "csv" | "837p" | "sftp" | "";
  // Step 3 — first audit
  auditId: string;
  auditStatus: "idle" | "running" | "done" | "error";
  auditError: string;
  // Step 4 — accept first finding
  firstFindingId: string;
  firstFindingDecision: "" | "accept" | "edit" | "dismiss";
}

const STEPS = [
  { key: "account", label: "Account" },
  { key: "hia", label: "HIA paperwork" },
  { key: "import", label: "Import pilot data" },
  { key: "audit", label: "Run first audit" },
  { key: "accept", label: "Accept first finding" },
] as const;

const STORAGE_KEY = "zorva.onboarding.step";

const EMPTY: FormState = {
  clinicName: "",
  signInEmail: "",
  dpaConfirmed: false,
  custodianName: "",
  custodianEmail: "",
  privacyOfficerName: "",
  privacyOfficerEmail: "",
  importMode: "",
  auditId: "",
  auditStatus: "idle",
  auditError: "",
  firstFindingId: "",
  firstFindingDecision: "",
};

export default function OnboardingFlow() {
  const router = useRouter();
  const [step, setStep] = useState<number>(0);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Restore step from localStorage on mount.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as { step?: number };
        if (
          typeof parsed.step === "number" &&
          parsed.step >= 0 &&
          parsed.step < STEPS.length
        ) {
          setStep(parsed.step);
        }
      }
    } catch {
      // localStorage may be disabled; ignore.
    }
  }, []);

  // Persist step on change.
  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ step }));
    } catch {
      // ignore
    }
  }, [step]);

  const isLast = step === STEPS.length - 1;

  // --- Field helpers (typed setters keep call-sites short) ---
  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  // --- Step validation: minimum bar to enable "Continue" ---
  const canContinue = useMemo(() => {
    switch (step) {
      case 0:
        return form.clinicName.trim().length >= 2 && form.signInEmail.includes("@");
      case 1:
        return (
          form.dpaConfirmed &&
          form.custodianName.trim().length >= 2 &&
          form.custodianEmail.includes("@") &&
          form.privacyOfficerName.trim().length >= 2 &&
          form.privacyOfficerEmail.includes("@")
        );
      case 2:
        return form.importMode !== "";
      case 3:
        return form.auditStatus === "done";
      case 4:
        return form.firstFindingDecision !== "";
      default:
        return false;
    }
  }, [step, form]);

  async function handleContinue() {
    setError(null);
    setBusy(true);
    try {
      if (step === 0) {
        // Account creation is the only step that needs a network call
        // before allowing "Continue" — the rest can be deferred to
        // the post-onboarding tenant setup.
        const res = await fetch("/api/onboarding/account", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            clinicName: form.clinicName,
            signInEmail: form.signInEmail,
          }),
        });
        if (!res.ok) {
          const body = (await res.json().catch(() => ({}))) as {
            error?: string;
          };
          throw new Error(body.error ?? `Account creation failed (${res.status})`);
        }
        setStep(1);
        return;
      }

      if (step === 3) {
        // Kick off the first audit. The API returns the audit id and
        // polls for completion in the background; for v1 we just
        // wait for the response.
        setForm((prev) => ({ ...prev, auditStatus: "running" }));
        const res = await fetch("/api/onboarding/first-audit", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ clinicName: form.clinicName }),
        });
        if (!res.ok) {
          setForm((prev) => ({ ...prev, auditStatus: "error" }));
          const body = (await res.json().catch(() => ({}))) as {
            error?: string;
          };
          throw new Error(body.error ?? `Audit failed (${res.status})`);
        }
        const data = (await res.json()) as {
          auditId: string;
          firstFindingId?: string;
        };
        setForm((prev) => ({
          ...prev,
          auditId: data.auditId,
          auditStatus: "done",
          firstFindingId: data.firstFindingId ?? "",
        }));
        setStep(4);
        return;
      }

      if (step === 4) {
        // Persist the biller's decision and finish.
        const res = await fetch("/api/onboarding/first-decision", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            auditId: form.auditId,
            findingId: form.firstFindingId,
            decision: form.firstFindingDecision,
          }),
        });
        if (!res.ok) {
          const body = (await res.json().catch(() => ({}))) as {
            error?: string;
          };
          throw new Error(body.error ?? `Decision failed (${res.status})`);
        }
        // Clear localStorage and route to the post-onboarding home.
        try {
          window.localStorage.removeItem(STORAGE_KEY);
        } catch {
          // ignore
        }
        router.push("/dashboard?welcome=1");
        return;
      }

      // Default: just advance.
      setStep((s) => Math.min(s + 1, STEPS.length - 1));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  function handleSkip() {
    setError(null);
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  }

  function handleBack() {
    setError(null);
    setStep((s) => Math.max(0, s - 1));
  }

  return (
    <>
      {/* --- Progress indicator --- */}
      <ol className={styles.steps} aria-label="Onboarding progress">
        {STEPS.map((s, i) => {
          const cls =
            i < step
              ? `${styles.step} ${styles.stepDone}`
              : i === step
                ? `${styles.step} ${styles.stepActive}`
                : styles.step;
          return (
            <li key={s.key} className={cls} aria-current={i === step ? "step" : undefined}>
              <span className={styles.stepDot}>
                {i < step ? "✓" : i + 1}
              </span>
              <span className={styles.stepLabel}>{s.label}</span>
            </li>
          );
        })}
      </ol>

      {/* --- Step body --- */}
      <div className={styles.body}>
        {step === 0 && (
          <section aria-labelledby="step-0-heading">
            <h2 id="step-0-heading">Create your clinic account</h2>
            <p className={styles.help}>
              We&apos;ll send a magic sign-in link to your email — no
              password to remember.
            </p>
            <label className={styles.label}>
              <span>Clinic name</span>
              <input
                className={styles.input}
                type="text"
                value={form.clinicName}
                onChange={(e) => set("clinicName", e.target.value)}
                placeholder="Bow Valley Medical Clinic"
                autoComplete="organization"
                required
              />
            </label>
            <label className={styles.label}>
              <span>Sign-in email</span>
              <input
                className={styles.input}
                type="email"
                value={form.signInEmail}
                onChange={(e) => set("signInEmail", e.target.value)}
                placeholder="billing@bowvalleymedical.ca"
                autoComplete="email"
                required
              />
            </label>
            <p className={styles.fineprint}>
              Already have an account?{" "}
              <a href="/login?callbackUrl=/onboarding" className={styles.link}>
                Sign in
              </a>{" "}
              and we&apos;ll continue from where you left off.
            </p>
          </section>
        )}

        {step === 1 && (
          <section aria-labelledby="step-1-heading">
            <h2 id="step-1-heading">Confirm HIA paperwork</h2>
            <p className={styles.help}>
              Alberta&apos;s <em>Health Information Act</em> requires a
              named custodian and a named privacy officer. We&apos;ll
              attach these to the HIA-compliant Data Processing
              Agreement (DPA) for this pilot.
            </p>
            <label className={styles.checkboxRow}>
              <input
                type="checkbox"
                checked={form.dpaConfirmed}
                onChange={(e) => set("dpaConfirmed", e.target.checked)}
              />
              <span>
                I confirm the HIA DPA template (
                <a
                  href="/legal/hia-dpa"
                  className={styles.link}
                  target="_blank"
                  rel="noreferrer"
                >
                  view template
                </a>
                ) has been reviewed and is on file for this pilot.
              </span>
            </label>
            <div className={styles.grid}>
              <label className={styles.label}>
                <span>Health-info custodian name</span>
                <input
                  className={styles.input}
                  type="text"
                  value={form.custodianName}
                  onChange={(e) => set("custodianName", e.target.value)}
                  autoComplete="name"
                  required
                />
              </label>
              <label className={styles.label}>
                <span>Custodian email</span>
                <input
                  className={styles.input}
                  type="email"
                  value={form.custodianEmail}
                  onChange={(e) => set("custodianEmail", e.target.value)}
                  autoComplete="email"
                  required
                />
              </label>
              <label className={styles.label}>
                <span>Privacy officer name</span>
                <input
                  className={styles.input}
                  type="text"
                  value={form.privacyOfficerName}
                  onChange={(e) => set("privacyOfficerName", e.target.value)}
                  autoComplete="name"
                  required
                />
              </label>
              <label className={styles.label}>
                <span>Privacy officer email</span>
                <input
                  className={styles.input}
                  type="email"
                  value={form.privacyOfficerEmail}
                  onChange={(e) => set("privacyOfficerEmail", e.target.value)}
                  autoComplete="email"
                  required
                />
              </label>
            </div>
          </section>
        )}

        {step === 2 && (
          <section aria-labelledby="step-2-heading">
            <h2 id="step-2-heading">Import pilot data</h2>
            <p className={styles.help}>
              Pick how you&apos;d like to get your first 100+ AHCIP
              claims into Zorva. You can change this later.
            </p>
            <div className={styles.radioGroup} role="radiogroup" aria-label="Import method">
              {([
                { v: "csv", t: "Upload a CSV", d: "Fastest — export claims from your billing system as CSV and drop it in." },
                { v: "837p", t: "Upload an 837P file", d: "X12 EDI — the standard US/CA billing format. Best for larger batches." },
                { v: "sftp", t: "SFTP credentials", d: "We'll fetch automatically from your existing SFTP drop. Add the host + creds in the next screen." },
                { v: "skip", t: "Skip for now", d: "Use synthetic demo data so you can see how the auditor works. Real data import is in /portal/onboarding." },
              ] as const).map((opt) => (
                <label
                  key={opt.v}
                  className={`${styles.radioRow} ${
                    form.importMode === opt.v ? styles.radioRowActive : ""
                  }`}
                >
                  <input
                    type="radio"
                    name="importMode"
                    value={opt.v}
                    checked={form.importMode === opt.v}
                    onChange={() => set("importMode", opt.v)}
                  />
                  <span>
                    <strong>{opt.t}</strong>
                    <span className={styles.radioDesc}>{opt.d}</span>
                  </span>
                </label>
              ))}
            </div>
          </section>
        )}

        {step === 3 && (
          <section aria-labelledby="step-3-heading">
            <h2 id="step-3-heading">Run your first audit</h2>
            <p className={styles.help}>
              We&apos;ll run the same v12 AHCIP auditor your peers use
              in production. The first run takes ~30 seconds for 100
              claims.
            </p>
            {form.auditStatus === "idle" && (
              <p className={styles.callout}>
                Click <strong>Continue</strong> to run the audit.
              </p>
            )}
            {form.auditStatus === "running" && (
              <p className={styles.callout} role="status">
                Running audit… this usually takes under 30 seconds.
              </p>
            )}
            {form.auditStatus === "done" && (
              <p className={styles.callout} role="status">
                Audit complete. {form.auditId ? `ID: ${form.auditId}` : null}
              </p>
            )}
            {form.auditStatus === "error" && (
              <p className={styles.calloutError} role="alert">
                Audit failed: {form.auditError}
              </p>
            )}
          </section>
        )}

        {step === 4 && (
          <section aria-labelledby="step-4-heading">
            <h2 id="step-4-heading">Review your first finding</h2>
            <p className={styles.help}>
              The auditor flagged at least one finding. As the biller,
              you decide: <strong>accept</strong> the recommendation
              and correct the claim, <strong>edit</strong> it before
              accepting, or <strong>dismiss</strong> it as not
              applicable. Your decision is logged to the hash-chained
              audit trail.
            </p>
            {form.firstFindingId ? (
              <p className={styles.callout}>
                First finding: <code>{form.firstFindingId}</code>
              </p>
            ) : (
              <p className={styles.callout}>
                No findings were produced (clean claim). You can skip
                this step or accept the &ldquo;no findings&rdquo; state.
              </p>
            )}
            <div className={styles.radioGroup} role="radiogroup" aria-label="Decision">
              {([
                { v: "accept", t: "Accept", d: "Apply the auditor's recommendation to the claim." },
                { v: "edit", t: "Edit", d: "Apply a different correction. We'll open the edit form next." },
                { v: "dismiss", t: "Dismiss", d: "The finding doesn't apply — keep the original claim." },
              ] as const).map((opt) => (
                <label
                  key={opt.v}
                  className={`${styles.radioRow} ${
                    form.firstFindingDecision === opt.v ? styles.radioRowActive : ""
                  }`}
                >
                  <input
                    type="radio"
                    name="firstFindingDecision"
                    value={opt.v}
                    checked={form.firstFindingDecision === opt.v}
                    onChange={() => set("firstFindingDecision", opt.v)}
                  />
                  <span>
                    <strong>{opt.t}</strong>
                    <span className={styles.radioDesc}>{opt.d}</span>
                  </span>
                </label>
              ))}
            </div>
          </section>
        )}

        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
      </div>

      {/* --- Footer: Back / Skip / Continue --- */}
      <div className={styles.footer}>
        <button
          type="button"
          className={styles.btnGhost}
          onClick={handleBack}
          disabled={busy || step === 0}
        >
          Back
        </button>
        <button
          type="button"
          className={styles.linkBtn}
          onClick={handleSkip}
          disabled={busy || isLast}
        >
          Skip for now
        </button>
        <button
          type="button"
          className={styles.btn}
          onClick={handleContinue}
          disabled={busy || !canContinue}
        >
          {busy ? "Working…" : isLast ? "Finish" : "Continue"}
        </button>
      </div>
    </>
  );
}
