import type { ReactNode } from "react";
import styles from "./InlineBanner.module.css";

export type InlineBannerTone = "error" | "success" | "info" | "warning";

export interface InlineBannerProps {
  tone?: InlineBannerTone;
  children: ReactNode;
  className?: string;
  /** Defaults to alert for error/warning, status otherwise. */
  role?: "alert" | "status";
}

/**
 * Accessible inline feedback banner for forms and page-level errors.
 * Prefer this over window.alert / ad-hoc colored paragraphs.
 */
export function InlineBanner({
  tone = "error",
  children,
  className,
  role,
}: InlineBannerProps) {
  const resolvedRole =
    role ?? (tone === "error" || tone === "warning" ? "alert" : "status");
  return (
    <div
      className={`${styles.banner} ${styles[tone]} ${className ?? ""}`.trim()}
      role={resolvedRole}
      aria-live={resolvedRole === "alert" ? "assertive" : "polite"}
    >
      {children}
    </div>
  );
}
