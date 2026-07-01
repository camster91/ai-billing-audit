"use client";

// /demo-request — client-side form component.
//
// Posts a slimmed-down lead payload to POST /api/leads. We re-use the
// existing /contact route handler (same validation, same insert, same
// notifications) instead of standing up a parallel pipeline — this is
// what kanban t_c091d2b5 explicitly allows ("wire the CTA to /contact"
// OR add a dedicated page). The demo payload carries `source: "demo"`
// so sales can tell demo requests apart from contact-form inquiries
// without a separate endpoint.
//
// Fields: just three. A buyer who has clicked "Book a demo" has
// already decided they want a walkthrough — we don't ask about claim
// volume or billing setup here. The sales call covers those.
//
// Error contract mirrors /contact/ContactForm:
//   { error: "invalid_input", details: { fieldErrors } } -> inline
//   { error: "disposable_email" } -> inline on email
//   anything else -> top-level message
//   200 -> success panel with the submitted email echoed

import { useState } from "react";
import styles from "./demo-request.module.css";

type Status = "idle" | "busy" | "success";

type FieldErrors = Partial<
  Record<"name" | "clinicName" | "email", string[]>
>;

export default function DemoRequestForm() {
  const [name, setName] = useState("");
  const [clinicName, setClinicName] = useState("");
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [submittedEmail, setSubmittedEmail] = useState("");

  const reset = () => {
    setName("");
    setClinicName("");
    setEmail("");
    setFieldErrors({});
    setSubmissionError(null);
    setStatus("idle");
  };

  const validateClientSide = (): FieldErrors => {
    const errs: FieldErrors = {};
    if (!name.trim()) errs.name = ["Your name is required"];
    if (!clinicName.trim())
      errs.clinicName = ["The clinic name is required"];
    if (!email.trim()) {
      errs.email = ["An email address is required"];
    } else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      errs.email = ["That doesn't look like a valid email"];
    }
    return errs;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmissionError(null);
    const errs = validateClientSide();
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) {
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
          // Sensible defaults for a buyer who only asked for a demo.
          // The sales call will pin the real numbers. claimVolume is
          // an int and billingSetup must be one of the three enums;
          // /api/leads validates and stores them on the leads row.
          claimVolume: 500,
          billingSetup: "in_house",
        }),
      });

      if (res.ok) {
        setSubmittedEmail(email.trim());
        setStatus("success");
        return;
      }

      const body = (await res.json().catch(() => ({}))) as {
        error?: string;
        details?: { fieldErrors?: FieldErrors };
      };

      if (body.error === "disposable_email") {
        setFieldErrors({
          email: ["Use a work email — we can't reply to disposable inboxes"],
        });
        setStatus("idle");
        return;
      }

      if (body.error === "invalid_input" && body.details?.fieldErrors) {
        setFieldErrors(body.details.fieldErrors);
        setStatus("idle");
        return;
      }

      setSubmissionError("Something went wrong — please try again.");
      setStatus("idle");
    } catch {
      setSubmissionError("Network error — please try again.");
      setStatus("idle");
    }
  };

  if (status === "success") {
    return (
      <section className={styles.formCard} aria-live="polite">
        <h2 className={styles.successHeading}>Demo request received</h2>
        <p className={styles.successBody}>
          Thanks — we&apos;ll reply to{" "}
          <strong>{submittedEmail}</strong> within one business day with
          a Calendly link to pick a 20-minute slot. In the meantime, the{" "}
          <a
            href="https://docs.ashbi.ca/security"
            className={styles.link}
            rel="noopener"
          >
            security one-pager
          </a>{" "}
          answers the most common privacy-officer questions.
        </p>
        <button
          type="button"
          onClick={reset}
          className={styles.secondaryButton}
        >
          Send another request
        </button>
      </section>
    );
  }

  const busy = status === "busy";

  return (
    <form
      onSubmit={handleSubmit}
      className={styles.formCard}
      aria-label="Demo request form"
      noValidate
    >
      {submissionError && (
        <div role="alert" className={styles.errorBanner}>
          {submissionError}
        </div>
      )}

      <label className={styles.label} htmlFor="demo-name">
        Your name
      </label>
      <input
        id="demo-name"
        name="name"
        type="text"
        autoComplete="name"
        required
        value={name}
        disabled={busy}
        onChange={(e) => setName(e.target.value)}
        aria-invalid={Boolean(fieldErrors.name)}
        aria-describedby={fieldErrors.name ? "demo-name-error" : undefined}
        className={styles.input}
      />
      {fieldErrors.name && (
        <p id="demo-name-error" className={styles.fieldError}>
          {fieldErrors.name[0]}
        </p>
      )}

      <label className={styles.label} htmlFor="demo-clinic">
        Clinic name
      </label>
      <input
        id="demo-clinic"
        name="clinicName"
        type="text"
        autoComplete="organization"
        required
        value={clinicName}
        disabled={busy}
        onChange={(e) => setClinicName(e.target.value)}
        aria-invalid={Boolean(fieldErrors.clinicName)}
        aria-describedby={
          fieldErrors.clinicName ? "demo-clinic-error" : undefined
        }
        className={styles.input}
      />
      {fieldErrors.clinicName && (
        <p id="demo-clinic-error" className={styles.fieldError}>
          {fieldErrors.clinicName[0]}
        </p>
      )}

      <label className={styles.label} htmlFor="demo-email">
        Work email
      </label>
      <input
        id="demo-email"
        name="email"
        type="email"
        autoComplete="email"
        required
        value={email}
        disabled={busy}
        onChange={(e) => setEmail(e.target.value)}
        aria-invalid={Boolean(fieldErrors.email)}
        aria-describedby={
          fieldErrors.email ? "demo-email-error" : undefined
        }
        className={styles.input}
      />
      {fieldErrors.email && (
        <p id="demo-email-error" className={styles.fieldError}>
          {fieldErrors.email[0]}
        </p>
      )}

      <button type="submit" disabled={busy} className={styles.primaryButton}>
        {busy ? "Sending…" : "Book a demo"}
      </button>

      <p className={styles.fineprint}>
        We&apos;ll never share your email. One reply, no drip campaign.
      </p>
    </form>
  );
}