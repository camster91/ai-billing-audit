"use client";

// Per-finding card with Accept / Dismiss actions.
//
// Accept: POSTs to /api/encounters/[id]/findings/[findingId]/accept
// with an empty body, then refreshes the page on success.
//
// Dismiss: opens an inline reason picker with the four reasons from
// the task body. Selecting "other_with_text" reveals a free-text
// field that is required before submit. POSTs to the dismiss route
// and refreshes the page on success.
//
// On any error the card surfaces a banner explaining what went wrong;
// the user can retry without losing the panel state.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { formatCents } from "@/lib/encounter-format";
import {
  DISMISS_REASONS,
  DISMISS_REASON_LABEL,
  type DismissReason,
  type FindingCategory,
  type FindingStatus,
} from "@/lib/encounter-types";
import styles from "./split-review.module.css";

interface FindingCardProps {
  findingId: string;
  encounterId: string;
  category: FindingCategory | string;
  billingRuleReference: string;
  currentCode: string | null;
  suggestedCode: string | null;
  evidenceQuote: string;
  estFinancialImpactCents: number;
  status: FindingStatus | string;
  dismissReason: DismissReason | null;
  dismissText: string | null;
}

const CATEGORY_LABELS: Record<string, string> = {
  em_level: "E/M level",
  documentation: "Documentation",
  medical_necessity: "Medical necessity",
  modifier: "Modifier",
  code_mismatch: "Code mismatch",
  payer_policy: "Payer policy",
  other: "Other",
};

export function FindingCard(props: FindingCardProps) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [dismissOpen, setDismissOpen] = useState(false);
  const [dismissReason, setDismissReason] = useState<DismissReason>("wrong_payer_policy");
  const [dismissText, setDismissText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const terminal = props.status === "accepted" || props.status === "dismissed";
  const impactClass =
    props.estFinancialImpactCents > 0
      ? styles.impactPositive
      : props.estFinancialImpactCents < 0
        ? styles.impactNegative
        : styles.impactZero;
  const findingClass = [
    styles.finding,
    props.status === "accepted" && styles.findingAccepted,
    props.status === "dismissed" && styles.findingDismissed,
    // Visual hint for category — match the auditor template.
    props.category === "documentation" && styles.findingWarn,
  ]
    .filter(Boolean)
    .join(" ");

  async function handleAccept() {
    setError(null);
    try {
      const res = await fetch(
        `/api/encounters/${encodeURIComponent(props.encounterId)}/findings/${encodeURIComponent(props.findingId)}/accept`,
        { method: "POST", headers: { "content-type": "application/json" }, body: "{}" },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body && (body.error || body.detail)) || `Accept failed (${res.status})`,
        );
      }
      startTransition(() => {
        router.refresh();
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDismiss() {
    setError(null);
    if (dismissReason === "other_with_text" && dismissText.trim().length === 0) {
      setError("Please describe the reason (1-2000 characters).");
      return;
    }
    if (dismissText.length > 2000) {
      setError("Reason text exceeds 2000 characters.");
      return;
    }
    try {
      const res = await fetch(
        `/api/encounters/${encodeURIComponent(props.encounterId)}/findings/${encodeURIComponent(props.findingId)}/dismiss`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            reason: dismissReason,
            ...(dismissReason === "other_with_text"
              ? { reasonText: dismissText.trim() }
              : {}),
          }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body && (body.error || body.detail)) || `Dismiss failed (${res.status})`,
        );
      }
      setDismissOpen(false);
      startTransition(() => {
        router.refresh();
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function handleQuoteClick() {
    // Scroll the matching evidence mark in the narrative pane into
    // view and pulse its highlight. The clinical-note component owns
    // the actual highlighting (one active mark at a time).
    const root = document.querySelector("." + styles.clinicalNote);
    if (!(root instanceof HTMLElement)) return;
    const mark = root.querySelector(
      `mark.evidence[data-evidence-id="${cssEscape(props.findingId)}"]`,
    );
    if (!(mark instanceof HTMLElement)) return;
    // Clear existing active, then mark this one.
    for (const el of root.querySelectorAll("mark.evidence.is-active")) {
      el.classList.remove("is-active");
    }
    mark.classList.add("is-active");
    mark.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  return (
    <article
      id={`finding-${cssEscape(props.findingId)}`}
      data-finding-id={props.findingId}
      className={findingClass}
    >
      <div className={styles.findingHeader}>
        <span className={styles.findingCategory}>
          {CATEGORY_LABELS[props.category] ?? props.category}
        </span>
        <span
          className={
            props.status === "accepted"
              ? `${styles.findingStatus} ${styles.findingStatusAccepted}`
              : props.status === "dismissed"
                ? `${styles.findingStatus} ${styles.findingStatusDismissed}`
                : styles.findingStatus
          }
        >
          {props.status}
        </span>
      </div>

      {(props.currentCode || props.suggestedCode) && (
        <p className={styles.codeChange}>
          {props.currentCode && (
            <span className={styles.codeCurrent}>{props.currentCode}</span>
          )}
          {props.currentCode && props.suggestedCode && (
            <span className={styles.codeArrow}>→</span>
          )}
          {props.suggestedCode && (
            <span className={styles.codeSuggested}>{props.suggestedCode}</span>
          )}
        </p>
      )}

      <button
        type="button"
        className={styles.quote}
        onClick={handleQuoteClick}
        title="Click to highlight this quote in the clinical note"
      >
        <span className={styles.quoteLabel}>Evidence</span>
        <span className={styles.quoteText}>“{props.evidenceQuote}”</span>
      </button>

      <dl className={styles.meta}>
        <dt>Rule</dt>
        <dd>{props.billingRuleReference}</dd>
        <dt>Impact</dt>
        <dd className={`${styles.impact} ${impactClass}`}>
          {formatCents(props.estFinancialImpactCents)}
        </dd>
      </dl>

      {props.status === "dismissed" && props.dismissReason && (
        <div className={styles.dismissContext}>
          <strong>Dismissed — {DISMISS_REASON_LABEL[props.dismissReason] ?? props.dismissReason}</strong>
          {props.dismissText && <span>{props.dismissText}</span>}
        </div>
      )}

      {!terminal && (
        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnAccept}`}
            onClick={handleAccept}
            disabled={isPending}
          >
            {isPending ? "Working…" : "Accept"}
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnDismiss}`}
            onClick={() => setDismissOpen((v) => !v)}
            disabled={isPending}
            aria-expanded={dismissOpen}
          >
            {dismissOpen ? "Cancel dismiss" : "Dismiss"}
          </button>
        </div>
      )}

      {dismissOpen && !terminal && (
        <div className={styles.dismissPanel}>
          <label htmlFor={`reason-${props.findingId}`}>Reason</label>
          <select
            id={`reason-${props.findingId}`}
            className={styles.reasonSelect}
            value={dismissReason}
            onChange={(event) => setDismissReason(event.target.value as DismissReason)}
          >
            {DISMISS_REASONS.map((reason) => (
              <option key={reason} value={reason}>
                {DISMISS_REASON_LABEL[reason]}
              </option>
            ))}
          </select>

          {dismissReason === "other_with_text" && (
            <>
              <label htmlFor={`reason-text-${props.findingId}`}>
                Describe why (required, 1-2000 chars)
              </label>
              <textarea
                id={`reason-text-${props.findingId}`}
                className={styles.reasonText}
                value={dismissText}
                onChange={(event) => setDismissText(event.target.value)}
                maxLength={2000}
                placeholder="Explain why this finding should be dismissed…"
                required
              />
            </>
          )}

          <div className={styles.dismissPanelActions}>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnDismiss}`}
              onClick={() => {
                setDismissOpen(false);
                setError(null);
                setDismissText("");
              }}
              disabled={isPending}
            >
              Cancel
            </button>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnAccept}`}
              onClick={handleDismiss}
              disabled={isPending}
            >
              {isPending ? "Submitting…" : "Confirm dismiss"}
            </button>
          </div>
        </div>
      )}

      {error && <p className={styles.errorBanner}>{error}</p>}
    </article>
  );
}

/**
 * Minimal CSS.escape polyfill for the data-evidence-id attribute
 * selector. The cuid is alphanumeric so the only metacharacter we
 * realistically need to escape is "-", but we use the standard
 * escape to be safe.
 */
function cssEscape(value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/([^a-zA-Z0-9_-])/g, "\\$1");
}
