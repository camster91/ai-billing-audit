// Reusable empty-state block with a primary CTA and an optional
// secondary link. Used by /dashboard, /encounters, and /findings
// when the tenant has zero rows so a fresh user knows what to do
// next instead of staring at a "no results" table.
//
// Server-component compatible: no client hooks, no event handlers.
// The CTA href is a plain <a> so it works in SSR'd HTML and
// without JS.
//
// Variants:
//   - `variant="block"`    (default) — full-width dashed card, used
//                            when the empty state IS the page (e.g.
//                            when there is no other UI to show).
//   - `variant="inline"`   — left-aligned in-flow strip with a CTA
//                            on the right, used when the page has
//                            other controls (filters, table) and the
//                            empty state should not visually outweigh
//                            them.
//
// `data-testid` is exposed for E2E smoke + the QA empty-state doc.

import type { ReactNode } from "react";
import styles from "@/app/shell.module.css";

export interface EmptyStateCTAProps {
  /** Heading — keep under 6 words. */
  title: string;
  /** 1-2 sentence explanation. No markdown. */
  description: string;
  /** Primary CTA — required, must be a real destination. */
  primaryAction: { label: string; href: string; testId?: string };
  /** Optional secondary action (e.g. "Learn how it works"). */
  secondaryAction?: { label: string; href: string; testId?: string };
  /**
   * "block"   — full-width centred card (default)
   * "inline"  — left-aligned in-flow strip (for pages with other UI)
   */
  variant?: "block" | "inline";
  /** testid for the wrapper — used by E2E selectors. */
  testId?: string;
}

export function EmptyStateCTA({
  title,
  description,
  primaryAction,
  secondaryAction,
  variant = "block",
  testId,
}: EmptyStateCTAProps): ReactNode {
  if (variant === "inline") {
    return (
      <section
        className={styles.emptyInline}
        data-testid={testId ?? "empty-state-cta"}
        data-variant="inline"
      >
        <div className={styles.emptyInlineBody}>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <div className={styles.emptyInlineActions}>
          <a
            className={styles.ctaPrimary}
            href={primaryAction.href}
            data-testid={primaryAction.testId ?? "empty-state-cta-primary"}
          >
            {primaryAction.label}
          </a>
          {secondaryAction ? (
            <a
              className={styles.ctaSecondary}
              href={secondaryAction.href}
              data-testid={secondaryAction.testId ?? "empty-state-cta-secondary"}
            >
              {secondaryAction.label}
            </a>
          ) : null}
        </div>
      </section>
    );
  }

  return (
    <section
      className={styles.empty}
      data-testid={testId ?? "empty-state-cta"}
      data-variant="block"
    >
      <h2>{title}</h2>
      <p>{description}</p>
      <div
        className={styles.emptyInlineActions}
        style={{ justifyContent: "center", marginTop: 20 }}
      >
        <a
          className={styles.ctaPrimary}
          href={primaryAction.href}
          data-testid={primaryAction.testId ?? "empty-state-cta-primary"}
        >
          {primaryAction.label}
        </a>
        {secondaryAction ? (
          <a
            className={styles.ctaSecondary}
            href={secondaryAction.href}
            data-testid={secondaryAction.testId ?? "empty-state-cta-secondary"}
          >
            {secondaryAction.label}
          </a>
        ) : null}
      </div>
    </section>
  );
}

/**
 * Build the onboarding-wizard URL for a given user. Used by the
 * empty-state CTAs to point a brand-new user at the wizard that
 * collects clinic profile + EHR + first encounter.
 *
 * The wizard's demo branch is keyed off a synthetic session id of
 * the form `demo_<timestamp>_<rand>`. The redeem route recognizes
 * the `demo_` prefix and synthesizes a Stripe Checkout Session
 * shape so the rest of the wizard can run without a real Stripe
 * call.
 */
export function onboardingWizardHref(seed?: number): string {
  const ts = seed ?? Date.now();
  const rand = Math.random().toString(36).slice(2, 10);
  return `/portal/onboarding?session_id=demo_${ts}_${rand}`;
}
