// severity.tsx — visual encoding for finding severity that uses BOTH
// color and an icon, plus a text label, so the finding is distinguishable
// without color (kanban t_e9812a38, WCAG 1.4.1).
//
// Severity values: "info" | "low" | "medium" | "high" | "critical".
// Per kanban t_41e846ef, this is the canonical severity ordering in the
// Finding model (see apps/portal/src/lib/encounter-types.ts).

import type { ReactNode } from "react";
import styles from "./severity.module.css";

export type Severity = "info" | "low" | "medium" | "high" | "critical";

const SEVERITY_ORDER: Severity[] = ["info", "low", "medium", "high", "critical"];

export function severityRank(s: Severity): number {
  return SEVERITY_ORDER.indexOf(s);
}

const ICONS: Record<Severity, string> = {
  // Glyphs chosen for high distinctness without color. ✓ ⓘ ⚠ ⛔ ✕
  info: "ⓘ",
  low: "✓",
  medium: "⚠",
  high: "⛔",
  critical: "✕",
};

const LABELS: Record<Severity, string> = {
  info: "Info",
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export function SeverityBadge({
  severity,
  size = "md",
}: {
  severity: Severity;
  size?: "sm" | "md";
}) {
  return (
    <span
      className={`${styles.badge} ${styles[severity]} ${size === "sm" ? styles.sm : ""}`}
      role="img"
      aria-label={`Severity: ${LABELS[severity]}`}
      title={LABELS[severity]}
    >
      <span aria-hidden="true" className={styles.icon}>
        {ICONS[severity]}
      </span>
      <span className={styles.label}>{LABELS[severity]}</span>
    </span>
  );
}

/**
 * Visual-only (color) treatment without the icon, for places where the
 * icon is already shown by the parent (e.g. a finding card that puts
 * the icon in the corner and wants the row tinted by severity).
 */
export function severityClass(severity: Severity): string {
  return styles[severity] ?? "";
}

/** All severity keys, in order. */
export const ALL_SEVERITIES = SEVERITY_ORDER;

/** Maps the existing severity string to the canonical order. */
export function coerceSeverity(s: string | null | undefined): Severity {
  switch ((s ?? "").toLowerCase()) {
    case "info": return "info";
    case "low": return "low";
    case "medium":
    case "med": return "medium";
    case "high": return "high";
    case "critical":
    case "crit": return "critical";
    default: return "info";
  }
}

/**
 * Returns a screen-reader-friendly summary of a finding's severity +
 * category, suitable for the finding card's `aria-label`.
 */
export function severitySummary(s: Severity, categoryLabel: string): ReactNode {
  return `${LABELS[s]} severity, ${categoryLabel}`;
}
