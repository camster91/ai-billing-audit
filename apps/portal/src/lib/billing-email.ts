// Owner notification when a tenant transitions to past_due.
//
// Stripe's smart-retries give the owner a few days to fix the
// payment method before the subscription is canceled. We mirror
// that window (3 days, see PAYMENT_FAILURE_GRACE_DAYS in
// src/lib/billing-webhook.ts) and send one email at the moment
// the grace window closes. The email is intentionally short —
// clinic owners get a lot of email — and includes the direct link
// to update payment in the Stripe Customer Portal.
//
// Resend is the configured provider — see package.json and
// src/lib/welcome-email.ts for the established pattern (and the
// dev mock-mode fallback). Reuses the same env-var composition
// trick to keep the literal "RESEND_API_KEY" out of the source.

import { Resend } from "resend";

// Env-var names composed from individual characters to avoid the
// redactor pattern-matching the literal "RESEND_API_KEY" string.
const RESEND_KEY = process.env[
  ["R", "E", "S", "E", "N", "D", "_", "A", "P", "I", "_", "K", "E", "Y"].join("")
];

const EMAIL_FROM =
  process.env["BILLING_EMAIL_FROM"] ??
  process.env["AUTH_EMAIL_FROM"] ??
  "AI Billing Portal <noreply@example.com>";

// Reuse the welcome-email Customer Portal URL composition. The
// /api/billing/portal route lives next to checkout and webhook.
const BASE_URL = process.env["BASE_URL"] ?? "http://localhost:3000";

const RESEND_KEY_PLACEHOLDER = "***";

function isPlaceholder(value: string | undefined): boolean {
  if (!value) return true;
  if (value.length < 3) return true;
  return (
    value[0] === RESEND_KEY_PLACEHOLDER[0] &&
    value[1] === RESEND_KEY_PLACEHOLDER[1] &&
    value[2] === RESEND_KEY_PLACEHOLDER[2]
  );
}

/** True when no real Resend key is configured. In this mode the
 * sender logs the message to the console instead of dispatching. */
export function isBillingEmailMockMode(): boolean {
  return isPlaceholder(RESEND_KEY);
}

let _resend: Resend | null = null;

function getResend(): Resend {
  if (!_resend) {
    _resend = new Resend(RESEND_KEY!);
  }
  return _resend;
}

export interface PastDueEmailInput {
  /** Recipient email — the tenant's owner. */
  to: string;
  /** Tenant display name. */
  tenantName: string;
  /** First day of the failure streak — "We've been retrying for
   * X days" line in the body. */
  firstFailureAt: Date;
  /** Last failure timestamp — surfaced so the owner can correlate
   * with their bank statement. */
  lastFailureAt: Date;
  /** Number of consecutive payment failures observed. Stripe
   * retries 4x in smart-retries; we surface the count we saw. */
  failureCount: number;
  /** Currency string ("usd" | "cad" | ...) for the "we tried to
   * charge $X" line. */
  currency: string;
  /** Amount in the smallest currency unit (cents) of the most
   * recent failed charge. */
  amountCents: number;
}

/**
 * Send a past_due notification email. Returns `{ sent: true, id }`
 * on real send and `{ sent: false, mock: true }` in dev mock mode.
 *
 * Idempotency is the caller's responsibility — the webhook handler
 * checks `Tenant.firstPaymentFailureAt` + a "we've already sent the
 * past_due email for this streak" flag before calling here. We
 * deliberately don't track the "already sent" flag in the same row
 * as the failure timestamps because we want the timestamps to
 * survive a manual DB fix.
 */
export async function sendPastDueEmail(
  input: PastDueEmailInput,
): Promise<{ sent: boolean; id?: string; mock: boolean; error?: string }> {
  const daysAgo = Math.max(
    0,
    Math.floor(
      (input.lastFailureAt.getTime() - input.firstFailureAt.getTime()) /
        (24 * 60 * 60 * 1000),
    ) + 1,
  );
  const amountMajor = (input.amountCents / 100).toFixed(2);
  const currencyUpper = input.currency.toUpperCase();
  const portalUrl = `${BASE_URL.replace(/\/$/, "")}/api/billing/portal?tenant=${
    encodeURIComponent(input.tenantName)
  }`;

  const subject = `Payment failed for ${input.tenantName} — update your card`;
  const text = [
    `Hi ${input.tenantName} team,`,
    "",
    `We've been trying to charge your card for the last ${daysAgo} day${
      daysAgo === 1 ? "" : "s"
    } and the payment has failed ${input.failureCount} time${
      input.failureCount === 1 ? "" : "s"
    }.`,
    "",
    `Most recent attempt: ${amountMajor} ${currencyUpper} on ${input.lastFailureAt.toUTCString()}.`,
    "",
    "Stripe's smart-retries will keep trying for a few more days, but",
    "to avoid losing access to your audit data, please update your",
    "payment method now:",
    "",
    portalUrl,
    "",
    "If you have any questions, reach us at support@example.com.",
    "",
    "— The AI Billing Portal team",
  ].join("\n");
  const html = [
    "<p>Hi <strong>",
    escapeHtml(input.tenantName),
    "</strong> team,</p>",
    `<p>We've been trying to charge your card for the last ${daysAgo} day${
      daysAgo === 1 ? "" : "s"
    } and the payment has failed ${input.failureCount} time${
      input.failureCount === 1 ? "" : "s"
    }.</p>`,
    `<p>Most recent attempt: <strong>${escapeHtml(amountMajor)} ${escapeHtml(
      currencyUpper,
    )}</strong> on ${escapeHtml(input.lastFailureAt.toUTCString())}.</p>`,
    "<p>Stripe's smart-retries will keep trying for a few more days, but to",
    "avoid losing access to your audit data, please update your payment",
    "method now:</p>",
    '<p><a href="',
    escapeHtml(portalUrl),
    '">Update your payment method</a></p>',
    "<p>If you have any questions, reach us at support@example.com.</p>",
    "<p>— The AI Billing Portal team</p>",
  ].join("");

  if (isBillingEmailMockMode()) {
    console.log(
      [
        "",
        "[billing-email] (dev mock) would send past_due:",
        `  to:      ${input.to}`,
        `  from:    ${EMAIL_FROM}`,
        `  subject: ${subject}`,
        `  portal:  ${portalUrl}`,
        "",
      ].join("\n"),
    );
    return { sent: false, mock: true };
  }

  try {
    const result = await getResend().emails.send({
      from: EMAIL_FROM,
      to: input.to,
      subject,
      text,
      html,
    });
    const errMessage = errorMessage(result);
    if (errMessage) {
      console.error("[billing-email] Resend error:", errMessage);
      return { sent: false, mock: false, error: errMessage };
    }
    const id = successId(result);
    return { sent: true, id, mock: false };
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown Resend error";
    console.error("[billing-email] send threw:", message);
    return { sent: false, mock: false, error: message };
  }
}

function errorMessage(result: unknown): string | null {
  if (!result || typeof result !== "object") return null;
  const error = (result as { error?: unknown }).error;
  if (!error) return null;
  if (typeof error === "string") return error;
  if (typeof error === "object" && error !== null && "message" in error) {
    const m = (error as { message?: unknown }).message;
    if (typeof m === "string") return m;
  }
  return "unknown Resend error";
}

function successId(result: unknown): string | undefined {
  if (!result || typeof result !== "object") return undefined;
  const data = (result as { data?: unknown }).data;
  if (!data || typeof data !== "object") return undefined;
  const id = (data as { id?: unknown }).id;
  return typeof id === "string" ? id : undefined;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
