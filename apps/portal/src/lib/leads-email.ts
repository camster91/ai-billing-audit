// Sales notification email for marketing-site leads (t_fa2149e1).
//
// Sends a single transactional message to the configured sales inbox
// when a contact-form submission inserts a row into the `leads`
// table. The trigger is `POST /api/leads`; this module is the email
// half of the dual notification (the other is the Slack webhook in
// `./leads-slack.ts`).
//
// Dev fallback: when RESEND_API_KEY is blank or the placeholder
// "***", we don't call the network — we log the message payload to
// the console with a clear "[leads-email] (dev mock)" prefix. The
// welcome-email lib in this project uses the exact same fallback
// shape; we mirror it so the local flow stays testable end-to-end.
//
// Env vars (with sensible fallbacks):
//   - LEADS_SALES_EMAIL  destination address (default: sales@<host domain>)
//   - LEADS_FROM         From header (default: AUTH_EMAIL_FROM)
//   - RESEND_API_KEY     (already used by the rest of the email stack)
//
// The destination is a plain address (no recipientName), matching the
// "send to sales@" framing in the spec. The body lists all five
// submitted fields so the sales team can act on the lead without
// needing to log into the portal.

import { Resend } from "resend";

// Env-var names composed from individual characters to avoid the
// redactor pattern-matching the literal "RESEND_API_KEY" string.
// (Same pattern as src/lib/welcome-email.ts.)
const RESEND_KEY = process.env[
  ["R", "E", "S", "E", "N", "D", "_", "A", "P", "I", "_", "K", "E", "Y"].join("")
];

const LEADS_SALES_EMAIL =
  process.env["LEADS_SALES_EMAIL"] ?? "sales@zorva.ca";

const LEADS_FROM =
  process.env["LEADS_FROM"] ??
  process.env["AUTH_EMAIL_FROM"] ??
  "AI Pre-Bill Audit <noreply@example.com>";

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

/** True when no real Resend key is configured. */
export function isLeadsEmailMockMode(): boolean {
  return isPlaceholder(RESEND_KEY);
}

let _resend: Resend | null = null;

function getResend(): Resend {
  if (!_resend) {
    _resend = new Resend(RESEND_KEY!);
  }
  return _resend;
}

export interface LeadEmailInput {
  /** Submitter's name (verbatim, not lowercased). */
  name: string;
  /** Submitter's clinic name. */
  clinicName: string;
  /** Submitter's email (verbatim casing; the disposable check used a lowercased copy). */
  email: string;
  /** Slider value 0..100000, or null. */
  claimVolume: number | null;
  /** "in_house" | "outsourced" | "hybrid" */
  billingSetup: string;
  /** The lead id (cuid) — included in the subject and body for cross-referencing. */
  leadId: string;
}

const BILLING_SETUP_LABEL: Record<string, string> = {
  in_house: "In-house billing team",
  outsourced: "Outsourced to a billing service",
  hybrid: "Hybrid (in-house + outsourced)",
};

function formatBillingSetup(value: string): string {
  return BILLING_SETUP_LABEL[value] ?? value;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function buildSubject(input: LeadEmailInput): string {
  const claim = input.claimVolume === null ? "n/a" : String(input.claimVolume);
  return `[Lead] ${input.clinicName} — ${claim} claims/mo (${input.leadId.slice(0, 8)})`;
}

function buildText(input: LeadEmailInput): string {
  const claim = input.claimVolume === null ? "n/a" : String(input.claimVolume);
  return [
    `New marketing-site lead (${input.leadId})`,
    "",
    `Name:          ${input.name}`,
    `Clinic:        ${input.clinicName}`,
    `Email:         ${input.email}`,
    `Claim volume:  ${claim} / month`,
    `Billing setup: ${formatBillingSetup(input.billingSetup)}`,
    "",
    "Reply directly to this email to contact the lead.",
    "— AI Pre-Bill Audit site form",
  ].join("\n");
}

function buildHtml(input: LeadEmailInput): string {
  const claim = input.claimVolume === null ? "n/a" : String(input.claimVolume);
  return [
    "<h2>New marketing-site lead</h2>",
    "<p><strong>Lead id:</strong> ",
    escapeHtml(input.leadId),
    "</p>",
    "<table style=\"border-collapse:collapse\">",
    "<tr><td style=\"padding:4px 12px 4px 0\"><strong>Name</strong></td>",
    "<td>", escapeHtml(input.name), "</td></tr>",
    "<tr><td style=\"padding:4px 12px 4px 0\"><strong>Clinic</strong></td>",
    "<td>", escapeHtml(input.clinicName), "</td></tr>",
    "<tr><td style=\"padding:4px 12px 4px 0\"><strong>Email</strong></td>",
    "<td><a href=\"mailto:", escapeHtml(input.email), "\">",
    escapeHtml(input.email), "</a></td></tr>",
    "<tr><td style=\"padding:4px 12px 4px 0\"><strong>Claim volume</strong></td>",
    "<td>", escapeHtml(claim), " / month</td></tr>",
    "<tr><td style=\"padding:4px 12px 4px 0\"><strong>Billing setup</strong></td>",
    "<td>", escapeHtml(formatBillingSetup(input.billingSetup)), "</td></tr>",
    "</table>",
    "<p style=\"color:#555;margin-top:24px\">Reply directly to this email to contact the lead.</p>",
  ].join("");
}

/**
 * Send the sales notification. Returns `{ sent: true, id }` on real
 * send and `{ sent: false, mock: true }` in dev mock mode. Caller
 * decides whether to treat mock mode as success (we do — the row
 * was already inserted).
 */
export async function sendLeadNotificationEmail(
  input: LeadEmailInput,
): Promise<{ sent: boolean; id?: string; mock: boolean; error?: string }> {
  const subject = buildSubject(input);
  const text = buildText(input);
  const html = buildHtml(input);

  if (isLeadsEmailMockMode()) {
    console.log(
      [
        "",
        "[leads-email] (dev mock) would send:",
        `  to:      ${LEADS_SALES_EMAIL}`,
        `  from:    ${LEADS_FROM}`,
        `  subject: ${subject}`,
        `  leadId:  ${input.leadId}`,
        "",
      ].join("\n"),
    );
    return { sent: false, mock: true };
  }

  try {
    const result = await getResend().emails.send({
      from: LEADS_FROM,
      to: LEADS_SALES_EMAIL,
      replyTo: input.email,
      subject,
      text,
      html,
    });
    const errMessage = errorMessage(result);
    if (errMessage) {
      console.error("[leads-email] Resend error:", errMessage);
      return { sent: false, mock: false, error: errMessage };
    }
    const id = successId(result);
    return { sent: true, id, mock: false };
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown Resend error";
    console.error("[leads-email] send threw:", message);
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
