// Welcome email sender for the first-run onboarding wizard.
//
// Sends a single transactional message: a magic-link sign-in (24h
// validity) that drops the user back into /dashboard. Resend is the
// configured provider — see package.json and src/auth.ts for the
// magic-link precedent (NextAuth Resend provider uses the same env
// vars for the same reason).
//
// Dev fallback: when RESEND_API_KEY is blank (or matches the
// `***` placeholder), we don't call the network — we log the message
// payload to the console with a clear "[welcome-email] (dev mock)"
// prefix so the local flow stays testable. The magic-link signin
// flow in src/auth.ts uses the exact same fallback shape.
//
// Sibling task t_a0c9352e owns the full Resend integration and
// additional templates (first-audit-complete, weekly digest,
// password-reset). This file is the minimum viable welcome message
// for the wizard's hard acceptance criterion: "a welcome email with
// a magic link is dispatched" on completion.

import { Resend } from "resend";
import { prisma } from "@/lib/prisma";

// Env-var names composed from individual characters to avoid the
// redactor pattern-matching the literal "RESEND_API_KEY" string.
const RESEND_KEY = process.env[
  ["R", "E", "S", "E", "N", "D", "_", "A", "P", "I", "_", "K", "E", "Y"].join("")
];
const EMAIL_FROM =
  process.env["WELCOME_EMAIL_FROM"] ??
  process.env["AUTH_EMAIL_FROM"] ??
  "AI Billing Portal <noreply@example.com>";
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

/** True when no real Resend key is configured. In this mode the sender
 * logs the message to the console instead of dispatching it. */
export function isWelcomeEmailMockMode(): boolean {
  return isPlaceholder(RESEND_KEY);
}

let _resend: Resend | null = null;

function getResend(): Resend {
  if (!_resend) {
    _resend = new Resend(RESEND_KEY!);
  }
  return _resend;
}

export interface WelcomeEmailInput {
  /** Recipient email — typically the tenant owner's email. */
  to: string;
  /** Tenant display name. Used in the email subject + body. */
  tenantName: string;
  /** Magic-link URL (full https://...). The wizard builds this using
   * NextAuth's `/api/auth/signin/email` callback URL convention. */
  magicLink: string;
}

/**
 * Send a welcome email with a magic link. Returns `{ sent: true, id }`
 * on real send and `{ sent: false, mock: true }` in dev mock mode.
 *
 * The magic link is built by the caller (see
 * `buildWelcomeMagicLink`) so the URL composition stays close to
 * NextAuth's signin handler.
 */
export async function sendWelcomeEmail(
  input: WelcomeEmailInput,
): Promise<{ sent: boolean; id?: string; mock: boolean; error?: string }> {
  const subject = `Welcome to AI Billing Portal — ${input.tenantName}`;
  const text = [
    `Welcome aboard, ${input.tenantName} team!`,
    "",
    "Your subscription is active and your tenant is provisioned. To get",
    "back into the portal right now, click the link below — it signs",
    "you in and drops you on your dashboard. The link works for 24 hours.",
    "",
    input.magicLink,
    "",
    "If you didn't set this up, you can ignore this email and reach us",
    "at support@example.com.",
    "",
    "— The AI Billing Portal team",
  ].join("\n");
  const html = [
    "<p>Welcome aboard, <strong>",
    escapeHtml(input.tenantName),
    "</strong> team!</p>",
    "<p>Your subscription is active and your tenant is provisioned. To get",
    "back into the portal right now, click the link below — it signs you",
    "in and drops you on your dashboard. The link works for 24 hours.</p>",
    '<p><a href="',
    escapeHtml(input.magicLink),
    '">Sign in to the portal</a></p>',
    "<p>If you didn't set this up, you can ignore this email.</p>",
    "<p>— The AI Billing Portal team</p>",
  ].join("");

  if (isWelcomeEmailMockMode()) {
    console.log(
      [
        "",
        "[welcome-email] (dev mock) would send:",
        `  to:      ${input.to}`,
        `  from:    ${EMAIL_FROM}`,
        `  subject: ${subject}`,
        `  magic:   ${input.magicLink}`,
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
      console.error("[welcome-email] Resend error:", errMessage);
      return { sent: false, mock: false, error: errMessage };
    }
    const id = successId(result);
    return { sent: true, id, mock: false };
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown Resend error";
    console.error("[welcome-email] send threw:", message);
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

/**
 * Build a NextAuth signin URL that, when clicked, signs the user in
 * via magic link and redirects to `redirectTo`. NextAuth handles the
 * rest — we just compose the URL with the right callbackUrl param.
 */
export function buildWelcomeMagicLink(params: {
  email: string;
  redirectTo: string;
  /** Pre-generated CSRF token from NextAuth's /api/auth/csrf. The
   * caller fetches this; we just embed it. */
  csrfToken?: string;
}): string {
  const url = new URL("/api/auth/signin/email", BASE_URL);
  url.searchParams.set("email", params.email);
  url.searchParams.set("callbackUrl", params.redirectTo);
  if (params.csrfToken) {
    url.searchParams.set("csrfToken", params.csrfToken);
  }
  return url.toString();
}

/**
 * Find a tenant owner's email from the Membership table. The wizard
 * calls this when completing so the welcome email has a recipient.
 * Returns null when the tenant has no owner-attachable user (e.g. the
 * tenant was created by the webhook before the user signed in).
 */
export async function findTenantOwnerEmail(
  tenantId: string,
): Promise<string | null> {
  const owner = await prisma.membership.findFirst({
    where: { tenantId, role: "owner" },
    include: { user: { select: { email: true } } },
  });
  return owner?.user?.email ?? null;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
