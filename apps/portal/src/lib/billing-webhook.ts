// Stripe subscription lifecycle helpers.
//
// Centralized so the webhook route, the past_due email sender, and the
// 30-day purge script can all reach the same primitives without
// duplicating tier-resolution or status-normalization logic.
//
// Sibling task t_c12cf722 owns the full webhook implementation. This
// file is the small, testable subset: tier lookup from a Stripe
// subscription, subscription-status mapping, retention-window
// constants, and the past-due grace-day constant.

import type StripeNS from "stripe";
import { getPricingConfig, isValidTierId, type TierId } from "@/lib/pricing";
import {
  isSubscriptionStatus,
  type SubscriptionStatus,
} from "@/lib/tenant";

/** Grace window (days) between the first consecutive payment failure
 * and the past_due status transition. Stripe's smart-retries also use
 * a multi-day window; we match it so the portal and Stripe agree on
 * when "dunning failed" is final. */
export const PAYMENT_FAILURE_GRACE_DAYS = 3;

/** Retention window (days) between customer.subscription.deleted and
 * the hard-delete purge. The owner can still sign in during this
 * window and re-subscribe without re-onboarding. */
export const CANCELED_TENANT_RETENTION_DAYS = 30;

/** Default audit quota per tier — used by the subscription.created
 * handler when it provisions a new tenant, and as the upper-bound
 * floor when an upgrade lands. Mirrors the values in src/lib/tenant.ts
 * to avoid a circular import (tenant.ts is the canonical home, but
 * the webhook handler is the canonical writer of these caps from
 * Stripe so we keep the numbers here). */
export const TIER_AUDIT_QUOTA: Record<TierId, number> = {
  small: 500,
  mid: 2_000,
  large: 5_000,
};

/**
 * Resolve a Stripe Subscription to our tier id ("small" | "mid" |
 * "large"). Walks every line item on the subscription and matches
 * the configured Stripe price id back to a tier + currency. Returns
 * null when nothing matches (the configuration is incomplete, or
 * the price was deleted in the dashboard). The caller should fall
 * back to the tenant's existing tier rather than overwriting with
 * null.
 */
export function resolveTierFromSubscription(
  sub: StripeNS.Subscription,
): TierId | null {
  const config = getPricingConfig();
  // Build a set of every price id we know about, paired with its tier.
  const priceToTier = new Map<string, TierId>();
  for (const tier of config.tiers) {
    if (tier.stripePriceIdCAD) priceToTier.set(tier.stripePriceIdCAD, tier.id);
    if (tier.stripePriceIdUSD) priceToTier.set(tier.stripePriceIdUSD, tier.id);
  }
  for (const item of sub.items?.data ?? []) {
    const priceId = item.price?.id;
    if (typeof priceId === "string") {
      const tier = priceToTier.get(priceId);
      if (tier && isValidTierId(tier)) return tier;
    }
  }
  return null;
}

/**
 * Map a Stripe subscription status string to our domain enum.
 * We only persist a known-good value; anything Stripe sends that
 * isn't in SUBSCRIPTION_STATUSES falls back to "active" so a
 * never-before-seen status (e.g. "incomplete_expired" or a new
 * Stripe value) doesn't crash the handler.
 */
export function mapSubscriptionStatus(
  stripeStatus: string | null | undefined,
): SubscriptionStatus {
  if (stripeStatus && isSubscriptionStatus(stripeStatus)) {
    return stripeStatus;
  }
  return "active";
}

/**
 * Human-readable subscription status for the owner email. Mirrors
 * the mapping Stripe's own dashboard uses so the email reads
 * naturally to a clinic owner who's also looking at the Stripe
 * portal.
 */
export function humanSubscriptionStatus(
  status: SubscriptionStatus,
): string {
  switch (status) {
    case "active":
      return "active";
    case "past_due":
      return "past due (payment failed)";
    case "canceled":
      return "canceled";
  }
}

/**
 * Decide whether a past_due email should fire for this payment
 * failure event. The 3-day grace window starts on the FIRST
 * consecutive failure; subsequent failures within the streak do
 * not re-send (the email is one per dunning cycle, not one per
 * retry). Returns `true` on the FIRST day the streak crosses the
 * grace boundary.
 */
export function shouldSendPastDueEmail(args: {
  /** Timestamp of the first failure in the current streak. */
  firstFailureAt: Date;
  /** Whether we've already sent the past_due email for this streak. */
  alreadyNotified: boolean;
  /** now() — accepted as a parameter so unit tests can pin it. */
  now: Date;
}): boolean {
  if (args.alreadyNotified) return false;
  const ageMs = args.now.getTime() - args.firstFailureAt.getTime();
  const graceMs = PAYMENT_FAILURE_GRACE_DAYS * 24 * 60 * 60 * 1000;
  return ageMs >= graceMs;
}

/**
 * Build a slug from a base string. Same shape as the private helper
 * in the webhook route — exported so a future tenant-rename UI can
 * use the same logic. Bounded loop to avoid pathological inputs
 * DoS'ing the unique check.
 */
export async function uniqueSlug(
  base: string,
  isSlugTaken: (slug: string) => Promise<boolean>,
): Promise<string> {
  const normalized = base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 48) || "clinic";
  let candidate = normalized;
  let n = 1;
  while (n < 50) {
    if (!(await isSlugTaken(candidate))) return candidate;
    n += 1;
    candidate = `${normalized}-${n}`;
  }
  return `${normalized}-${Date.now()}`;
}
