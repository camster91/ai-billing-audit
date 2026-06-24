// password-reset email template.
//
// Sends a one-time password-reset link valid for 1 hour. Pure
// transactional — the user just asked for the reset, no
// List-Unsubscribe header, an "unsubscribe" suppression does NOT
// block the send (security/operational exemption — see email.ts
// suppress-list rules).
//
// Note: the current NextAuth auth flow uses the Resend provider's
// built-in magic-link signin (no password). This template is the
// "in case we add a password flow later" sibling — it lives in
// the same dispatcher so the next person to wire a password reset
// only needs to call this function with a token. The Resend
// provider's sendVerificationRequest stays the source of truth
// for the magic-link signin.
//
// Token lifetime: 1 hour (3600s) — shorter than the magic-link
// 24h because a password reset is a higher-trust action.

import { sendTemplate, escapeHtml } from "@/lib/email";

const BASE_URL = process.env["BASE_URL"] ?? "http://localhost:3000";

const PASSWORD_RESET_TTL_SECONDS = 60 * 60; // 1 hour

export interface PasswordResetInput {
  to: string;
  tenantName: string;
  /** Plaintext reset token (32+ char random). The caller
   * persists the hash; we only see the plaintext long enough
   * to embed it in the link. */
  token: string;
  /** Optional tenant id (null when the user has no tenant). */
  tenantId?: string | null;
}

export interface PasswordResetLinkParts {
  url: string;
  expiresAt: Date;
  ttlSeconds: number;
}

/** Build the reset URL the email embeds. */
export function buildPasswordResetLink(token: string): PasswordResetLinkParts {
  const url = new URL("/reset-password", BASE_URL);
  url.searchParams.set("token", token);
  const expiresAt = new Date(Date.now() + PASSWORD_RESET_TTL_SECONDS * 1000);
  return { url: url.toString(), expiresAt, ttlSeconds: PASSWORD_RESET_TTL_SECONDS };
}

/**
 * Send the password-reset email. The link embeds a one-time token
 * valid for 1 hour. The reset handler (out of scope for this
 * milestone) is expected to call `verifyPasswordResetToken` to
 * validate the token before allowing a new password.
 */
export async function sendPasswordResetEmail(input: PasswordResetInput) {
  const { url, expiresAt, ttlSeconds } = buildPasswordResetLink(input.token);
  const subject = `Reset your AI Billing Portal password`;

  const text = [
    `Hi ${input.tenantName} team,`,
    "",
    "We received a request to reset the password for your AI Billing",
    "Portal account. Click the link below to choose a new password:",
    "",
    url,
    "",
    `This link expires at ${expiresAt.toUTCString()} (${ttlSeconds / 60} minutes`,
    "from now). If you didn't request this, you can ignore this email",
    "and your password will stay the same.",
    "",
    "— The AI Billing Portal team",
  ].join("\n");

  const html = [
    "<p>Hi <strong>",
    escapeHtml(input.tenantName),
    "</strong> team,</p>",
    "<p>We received a request to reset the password for your AI",
    "Billing Portal account. Click the link below to choose a new",
    "password:</p>",
    '<p><a href="',
    escapeHtml(url),
    '">Reset your password</a></p>',
    `<p style="font-size:small;color:#666">This link expires at ${escapeHtml(
      expiresAt.toUTCString(),
    )} (${ttlSeconds / 60} minutes from now). If you didn't request this, you can ignore this email and your password will stay the same.</p>`,
    "<p>— The AI Billing Portal team</p>",
  ].join("");

  const result = await sendTemplate({
    to: input.to,
    templateId: "password_reset",
    kind: "transactional",
    subject,
    text,
    html,
    tenantId: input.tenantId ?? null,
    metadata: { expiresAt: expiresAt.toISOString() },
  });

  if (result.sent) return { sent: true as const, id: result.id };
  if ("suppressed" in result && result.suppressed) {
    return { sent: false as const, mock: false as const, reason: result.reason };
  }
  if ("error" in result) {
    return { sent: false as const, mock: false as const, error: result.error };
  }
  return { sent: false as const, mock: result.mock };
}
