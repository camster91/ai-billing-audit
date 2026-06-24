// Team-invite email template.
//
// Fired when a tenant owner invites a new member through
// /api/team/invite. Contains a one-time magic link bound to the
// Membership.inviteToken. Clicking the link as an existing user
// activates the membership without creating a duplicate account;
// clicking as a new user signs them up (Resend magic link under
// the hood) and then activates the membership.
//
// Template kind: "transactional". The user has not yet
// opted in to any marketing stream, and the email is part of the
// security/operational loop ("you've been invited to a clinic
// account"). No List-Unsubscribe header.
//
// We deliberately do NOT use the existing Resend magic-link
// provider here — that one only signs the recipient into a
// global session, not a tenant-scoped membership. The accept
// route is a custom handler that does both.

import { sendTemplate, escapeHtml } from "@/lib/email";

const BASE_URL = process.env["BASE_URL"] ?? "http://localhost:3000";

export interface TeamInviteInput {
  to: string;
  inviterEmail: string | null;
  inviterName: string | null;
  tenantName: string;
  tenantId: string;
  role: string;
  inviteToken: string;
}

export async function sendTeamInviteEmail(
  input: TeamInviteInput,
): Promise<
  | { sent: true; id: string }
  | { sent: false; mock: boolean; reason?: string; error?: string }
> {
  const acceptUrl =
    `${BASE_URL.replace(/\/$/, "")}/api/team/accept` +
    `?token=${encodeURIComponent(input.inviteToken)}`;

  const inviter = input.inviterName?.trim() || input.inviterEmail || "Someone";
  const subject = `You've been invited to ${input.tenantName} on AI Billing Portal`;

  const text = [
    `${inviter} has invited you to join ${input.tenantName} on the`,
    "AI Billing Portal.",
    "",
    `Your role: ${input.role}`,
    "",
    "Accept the invite by opening this link:",
    acceptUrl,
    "",
    "If you didn't expect this email you can ignore it — the",
    "invite expires when the tenant owner revokes it.",
    "",
    "— The AI Billing Portal team",
  ].join("\n");

  const html = [
    "<p>",
    escapeHtml(inviter),
    " has invited you to join <strong>",
    escapeHtml(input.tenantName),
    "</strong> on the AI Billing Portal.</p>",
    `<p>Your role: <strong>${escapeHtml(input.role)}</strong></p>`,
    '<p><a href="',
    escapeHtml(acceptUrl),
    '">Accept invite</a></p>',
    "<p>If you didn't expect this email you can ignore it — the",
    " invite expires when the tenant owner revokes it.</p>",
    "<p>— The AI Billing Portal team</p>",
  ].join("");

  const result = await sendTemplate({
    to: input.to,
    templateId: "team_invite",
    kind: "transactional",
    subject,
    text,
    html,
    tenantId: input.tenantId,
    metadata: {
      role: input.role,
      // Don't put the token in headers — that goes through
      // intermediate SMTP relays. It's only in the body, which is
      // HTTPS-only on the receiving end.
    },
  });

  if (result.sent) return { sent: true, id: result.id };
  if ("suppressed" in result && result.suppressed) {
    return { sent: false, mock: false, reason: result.reason };
  }
  if ("error" in result) {
    return { sent: false, mock: false, error: result.error };
  }
  return { sent: false, mock: result.mock };
}
