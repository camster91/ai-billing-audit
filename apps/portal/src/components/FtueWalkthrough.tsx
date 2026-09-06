"use client";

// First-time user experience — crisp 3-step product walkthrough.
// Shown once after clinic onboarding (localStorage: zorva.ftue.v1).
// Escape / Skip dismisses; focus is trapped while open.

import { useCallback, useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import styles from "./FtueWalkthrough.module.css";

const STORAGE_KEY = "zorva.ftue.v1";

const STEPS = [
  {
    title: "Review findings",
    body: "Open the Findings inbox to accept or dismiss AI suggestions before claims go out.",
    href: "/findings",
    cta: "Open findings",
  },
  {
    title: "Audit encounters",
    body: "Encounters hold the clinical note and claim lines. Run an audit, then work findings side-by-side.",
    href: "/encounters",
    cta: "View encounters",
  },
  {
    title: "Invite your team",
    body: "Owners can invite auditors and viewers so billing review stays collaborative and auditable.",
    href: "/team",
    cta: "Manage team",
  },
] as const;

export interface FtueWalkthroughProps {
  /** When false, never show (e.g. no tenant / fresh empty signup CTA). */
  enabled?: boolean;
}

export function FtueWalkthrough({ enabled = true }: FtueWalkthroughProps) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    try {
      if (window.localStorage.getItem(STORAGE_KEY) === "done") return;
      setOpen(true);
    } catch {
      // private mode / disabled storage — skip tour
    }
  }, [enabled]);

  const complete = useCallback(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, "done");
    } catch {
      // ignore
    }
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        complete();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
        "a[href], button:not([disabled])",
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, complete]);

  if (!open) return null;

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <div className={styles.overlay} role="presentation">
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
      >
        <div className={styles.top}>
          <p className={styles.eyebrow}>Quick tour · {step + 1} of {STEPS.length}</p>
          <button
            ref={closeRef}
            type="button"
            className={styles.skip}
            onClick={complete}
          >
            Skip
          </button>
        </div>

        <ol className={styles.dots} aria-label="Tour progress">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <button
                type="button"
                className={i === step ? styles.dotActive : styles.dot}
                aria-label={`Step ${i + 1}: ${s.title}`}
                aria-current={i === step ? "step" : undefined}
                onClick={() => setStep(i)}
              />
            </li>
          ))}
        </ol>

        <h2 id={titleId} className={styles.title}>
          {current.title}
        </h2>
        <p id={descId} className={styles.body}>
          {current.body}
        </p>

        <div className={styles.actions}>
          {step > 0 ? (
            <button
              type="button"
              className={styles.secondary}
              onClick={() => setStep((s) => Math.max(0, s - 1))}
            >
              Back
            </button>
          ) : (
            <span />
          )}
          <div className={styles.actionGroup}>
            <Link
              href={current.href}
              className={styles.linkCta}
              onClick={isLast ? complete : undefined}
            >
              {current.cta}
            </Link>
            {isLast ? (
              <button type="button" className={styles.primary} onClick={complete}>
                Got it
              </button>
            ) : (
              <button
                type="button"
                className={styles.primary}
                onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
              >
                Next
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
