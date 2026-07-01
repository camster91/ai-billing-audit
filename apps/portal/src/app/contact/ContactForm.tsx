"use client";

// /contact — client-side form component.
//
// Posts the lead payload to POST /api/leads (server route, no auth).
// The route validates, rejects disposable emails, inserts a row, and
// fires email + Slack. We mirror that error contract on the client so
// the user sees the same reasons for rejection they'd see in curl:
//
//   { error: "invalid_input", details: { fieldErrors, formErrors } }
//     -> render a top-level "Please fix the errors below" banner plus
//        per-field messages from the fieldErrors map.
//   { error: "disposable_email" }
//     -> inline message on the email field; one of the most common
//        reasons a real submission gets rejected, so we keep it tight.
//   anything else
//     -> top-level "Something went wrong — try again" message; the row
//        was either inserted or not, we can't tell from the client.
//
// State machine (kept tiny on purpose — the spec only requires
// rendering, validation, and submit):
//   idle    -> idle (after a failed submit), submissionError: string
//   busy    -> button disabled, fields disabled
//   success -> the form is replaced by a confirmation panel; the only
//              way out is to refresh the page (or click "Send another"
//              which resets to idle)
//
// We keep the form values in React state (not refs) so React-driven
// validation can run on change and the slider's numeric value stays in
// sync with the visible label.
//
// PII: the form mirrors the server schema exactly. No analytics, no
// marketing-pixel firing on submit, no IP/UA capture. The server route
// is the single place where data crosses the trust boundary.

import { useState } from "react";
import styles from "./contact.module.css";

type Status = "idle" | "busy" | "success";

type FieldErrors = Partial<Record<
  "name" | "clinicName" | "email" | "claimVolume" | "billingSetup",
  string[]
>>;

interface Props {
  // Optional pre-fill (the spec doesn't need it; a "contact us from a
  // pricing CTA" deep-link might pass ?name= later, but YAGNI for v1).
  defaults?: {
    name?: string;
    clinicName?: string;
    email?: string;
  };
}

const BILLING_SETUPS = [
  { value: "", label: "Pick one…" },
  { value: "in_house", label: "In-house billing team" },
  { value: "outsourced", label: "Outsourced to a billing service" },
  { value: "hybrid", label: "Hybrid (in-house + outsourced)" },
] as const;

function formatClaimVolume(n: number): string {
  if (n === 0) return "0 / month (just starting)";
  if (n >= 1000) {
    // Render big numbers as 1.2k / 12.5k for readability in the slider label.
    const k = (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1);
    return `${k}k / month`;
  }
  return `${n.toLocaleString("en-US")} / month`;
}

export default function ContactForm({ defaults }: Props) {
  const [name, setName] = useState(defaults?.name ?? "");
  const [clinicName, setClinicName] = useState(defaults?.clinicName ?? "");
  const [email, setEmail] = useState(defaults?.email ?? "");
  const [claimVolume, setClaimVolume] = useState<number>(2000);
  const [billingSetup, setBillingSetup] =
    useState<string>("");

  const [status, setStatus] = useState<Status>("idle");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [topError, setTopError] = useState<string | null>(null);
  const [submittedEmail, setSubmittedEmail] = useState<string>("");

  function clearErrors(): void {
    setFieldErrors({});
    setTopError(null);
  }

  function clientValidate(): FieldErrors {
    const errs: FieldErrors = {};
    if (!name.trim()) errs.name = ["Name is required"];
    else if (name.trim().length > 200) errs.name = ["Name is too long"];

    if (!clinicName.trim()) errs.clinicName = ["Clinic name is required"];
    else if (clinicName.trim().length > 200)
      errs.clinicName = ["Clinic name is too long"];

    if (!email.trim()) errs.email = ["Email is required"];
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      errs.email = ["Enter a valid email address"];

    if (claimVolume < 0 || claimVolume > 100000)
      errs.claimVolume = ["Claim volume must be between 0 and 100,000"];

    if (
      billingSetup !== "in_house" &&
      billingSetup !== "outsourced" &&
      billingSetup !== "hybrid"
    )
      errs.billingSetup = ["Pick a billing setup"];

    return errs;
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    clearErrors();

    const clientErrs = clientValidate();
    if (Object.keys(clientErrs).length > 0) {
      setFieldErrors(clientErrs);
      setTopError("Please fix the errors below and resubmit.");
      return;
    }

    setStatus("busy");
    try {
      const res = await fetch("/api/leads", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          clinicName: clinicName.trim(),
          email: email.trim(),
          claimVolume,
          billingSetup,
        }),
      });

      if (res.ok) {
        setSubmittedEmail(email.trim());
        setStatus("success");
        return;
      }

      const body = (await res.json().catch(() => ({}))) as {
        error?: string;
        details?: { fieldErrors?: FieldErrors; formErrors?: string[] };
      };

      if (body.error === "disposable_email") {
        setFieldErrors({
          email: [
            "That email is on a disposable-email blocklist. Use your work address so we can reply.",
          ],
        });
        setTopError(null);
        setStatus("idle");
        return;
      }

      if (body.error === "invalid_input" && body.details) {
        setFieldErrors(body.details.fieldErrors ?? {});
        const formErrs = body.details.formErrors ?? [];
        setTopError(
          formErrs.length > 0
            ? formErrs.join(". ")
            : "Please fix the errors below and resubmit.",
        );
        setStatus("idle");
        return;
      }

      setTopError(
        "Something went wrong submitting the form. Please try again, or email us directly at sales@ashbi.ca.",
      );
      setStatus("idle");
    } catch {
      setTopError("Network error. Please try again.");
      setStatus("idle");
    }
  }

  function reset(): void {
    setName(defaults?.name ?? "");
    setClinicName(defaults?.clinicName ?? "");
    setEmail(defaults?.email ?? "");
    setClaimVolume(2000);
    setBillingSetup("");
    clearErrors();
    setStatus("idle");
  }

  if (status === "success") {
    return (
      <div className={styles.card} role="status" aria-live="polite">
        <h2 className={styles.successHeading}>Thanks — we got it.</h2>
        <p className={styles.successBody}>
          A sales lead has been created for <strong>{submittedEmail}</strong>.
          We&apos;ll be in touch within one business day with next steps and
          a link to book a 20-minute walkthrough.
        </p>
        <p className={styles.successBody}>
          In the meantime, the{" "}
          <a href="/how-it-works" className={styles.link}>
            how-it-works
          </a>{" "}
          page walks through the audit loop in plain English, and the{" "}
          <a href="/security" className={styles.link}>
            security
          </a>{" "}
          page has the HIA / PHIPA / HIPAA explainer you can forward to
          your privacy officer.
        </p>
        <button
          type="button"
          onClick={reset}
          className={styles.secondaryButton}
        >
          Send another message
        </button>
      </div>
    );
  }

  const disabled = status === "busy";

  return (
    <form
      className={styles.card}
      onSubmit={handleSubmit}
      noValidate
      aria-describedby={topError ? "contact-top-error" : undefined}
    >
      {topError && (
        <div id="contact-top-error" className={styles.topError} role="alert">
          {topError}
        </div>
      )}

      <Field
        id="name"
        label="Your name"
        required
        value={name}
        onChange={setName}
        disabled={disabled}
        autoComplete="name"
        errors={fieldErrors.name}
      />

      <Field
        id="clinicName"
        label="Clinic name"
        required
        value={clinicName}
        onChange={setClinicName}
        disabled={disabled}
        autoComplete="organization"
        errors={fieldErrors.clinicName}
      />

      <Field
        id="email"
        label="Work email"
        type="email"
        required
        value={email}
        onChange={setEmail}
        disabled={disabled}
        autoComplete="email"
        inputMode="email"
        hint="Use a non-disposable address so we can reply."
        errors={fieldErrors.email}
      />

      <fieldset
        className={styles.fieldset}
        disabled={disabled}
        aria-invalid={Boolean(fieldErrors.claimVolume)}
        aria-describedby={
          fieldErrors.claimVolume ? "claimVolume-error" : "claimVolume-hint"
        }
      >
        <legend className={styles.legend}>
          Monthly claim volume
          <span aria-hidden="true" className={styles.req}>
            *
          </span>
        </legend>
        <div className={styles.sliderRow}>
          <input
            id="claimVolume"
            name="claimVolume"
            type="range"
            min={0}
            max={100000}
            step={100}
            value={claimVolume}
            onChange={(e) => setClaimVolume(Number(e.target.value))}
            className={styles.slider}
            aria-describedby="claimVolume-hint"
          />
          <output
            htmlFor="claimVolume"
            className={styles.sliderValue}
            aria-live="polite"
          >
            {formatClaimVolume(claimVolume)}
          </output>
        </div>
        <p id="claimVolume-hint" className={styles.hint}>
          Drag the slider to roughly match your monthly claim volume. We
          use this to recommend a tier on the call.
        </p>
        {fieldErrors.claimVolume && (
          <p id="claimVolume-error" className={styles.fieldError}>
            {fieldErrors.claimVolume.join(". ")}
          </p>
        )}
      </fieldset>

      <div className={styles.field}>
        <label htmlFor="billingSetup" className={styles.label}>
          Current billing setup
          <span aria-hidden="true" className={styles.req}>
            *
          </span>
        </label>
        <select
          id="billingSetup"
          name="billingSetup"
          required
          value={billingSetup}
          onChange={(e) => setBillingSetup(e.target.value)}
          disabled={disabled}
          className={styles.select}
          aria-invalid={Boolean(fieldErrors.billingSetup)}
          aria-describedby={
            fieldErrors.billingSetup ? "billingSetup-error" : undefined
          }
        >
          {BILLING_SETUPS.map((opt) => (
            <option key={opt.value} value={opt.value} disabled={opt.value === ""}>
              {opt.label}
            </option>
          ))}
        </select>
        {fieldErrors.billingSetup && (
          <p id="billingSetup-error" className={styles.fieldError}>
            {fieldErrors.billingSetup.join(". ")}
          </p>
        )}
      </div>

      <div className={styles.actions}>
        <button
          type="submit"
          className={styles.primaryButton}
          disabled={disabled}
        >
          {disabled ? "Sending…" : "Talk to sales"}
        </button>
        <p className={styles.fineprint}>
          We&apos;ll email you back within one business day. No marketing
          list signup, no automated drip.
        </p>
      </div>
    </form>
  );
}

interface FieldProps {
  id: string;
  label: string;
  type?: "text" | "email";
  required?: boolean;
  value: string;
  onChange: (next: string) => void;
  disabled: boolean;
  autoComplete?: string;
  inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
  hint?: string;
  errors?: string[];
}

function Field(props: FieldProps) {
  const errId = `${props.id}-error`;
  const hintId = `${props.id}-hint`;
  return (
    <div className={styles.field}>
      <label htmlFor={props.id} className={styles.label}>
        {props.label}
        {props.required && (
          <span aria-hidden="true" className={styles.req}>
            *
          </span>
        )}
      </label>
      <input
        id={props.id}
        name={props.id}
        type={props.type ?? "text"}
        required={props.required}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        disabled={props.disabled}
        autoComplete={props.autoComplete}
        inputMode={props.inputMode}
        aria-invalid={Boolean(props.errors && props.errors.length > 0)}
        aria-describedby={
          props.errors && props.errors.length > 0 ? errId : hintId
        }
        className={styles.input}
      />
      {props.hint && !props.errors?.length && (
        <p id={hintId} className={styles.hint}>
          {props.hint}
        </p>
      )}
      {props.errors && props.errors.length > 0 && (
        <p id={errId} className={styles.fieldError}>
          {props.errors.join(". ")}
        </p>
      )}
    </div>
  );
}
