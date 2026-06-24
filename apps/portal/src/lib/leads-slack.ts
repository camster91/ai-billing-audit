// Slack notification for marketing-site leads (t_fa2149e1).
//
// Posts a simple text message to a Slack incoming-webhook URL when a
// contact-form submission inserts a row into the `leads` table.
// The trigger is `POST /api/leads`; this module is the Slack half of
// the dual notification (the other is the email in
// `./leads-email.ts`).
//
// Slack incoming-webhook URLs are POSTed with a `text` body and an
// optional `blocks` array for richer formatting. We send both — a
// fallback `text` for Slack clients that ignore blocks, and a small
// blocks payload that surfaces the lead's clinic + claim volume up
// front. No `attachments` (legacy) and no `username` / `icon_emoji`
// override — keeps the message attributable to the default
// webhook owner.
//
// Dev fallback: when LEADS_SLACK_WEBHOOK_URL is blank or matches the
// "***" placeholder, we don't call the network — we log the payload
// to the console with a clear "[leads-slack] (dev mock)" prefix.
// The email lib in this project uses the exact same fallback shape
// so the local flow stays testable end-to-end.
//
// Security: the webhook URL is server-side only. It is never
// returned to the client. If a future task needs to validate the
// URL shape, do it at config time (e.g. on first call) — this
// module trusts whatever is in process.env.

const WEBHOOK_URL = process.env["LEADS_SLACK_WEBHOOK_URL"];

const PLACEHOLDER = "***";

function isPlaceholder(value: string | undefined): boolean {
  if (!value) return true;
  if (value.length < 3) return true;
  return (
    value[0] === PLACEHOLDER[0] &&
    value[1] === PLACEHOLDER[1] &&
    value[2] === PLACEHOLDER[2]
  );
}

/** True when no real webhook URL is configured. */
export function isLeadsSlackMockMode(): boolean {
  return isPlaceholder(WEBHOOK_URL);
}

export interface LeadSlackInput {
  /** Submitter's name. */
  name: string;
  /** Submitter's clinic name. */
  clinicName: string;
  /** Submitter's email. */
  email: string;
  /** Slider value 0..100000, or null. */
  claimVolume: number | null;
  /** "in_house" | "outsourced" | "hybrid" */
  billingSetup: string;
  /** The lead id (cuid). */
  leadId: string;
}

const BILLING_SETUP_LABEL: Record<string, string> = {
  in_house: "In-house",
  outsourced: "Outsourced",
  hybrid: "Hybrid",
};

function buildText(input: LeadSlackInput): string {
  const claim = input.claimVolume === null ? "n/a" : `${input.claimVolume}/mo`;
  const setup = BILLING_SETUP_LABEL[input.billingSetup] ?? input.billingSetup;
  return `:incoming_envelope: New lead — ${input.clinicName} (${input.name}) — ${claim}, ${setup} — ${input.email}`;
}

function buildPayload(input: LeadSlackInput): unknown {
  const claim = input.claimVolume === null ? "n/a" : `${input.claimVolume} / month`;
  const setup = BILLING_SETUP_LABEL[input.billingSetup] ?? input.billingSetup;
  return {
    text: buildText(input),
    blocks: [
      {
        type: "header",
        text: {
          type: "plain_text",
          text: `New lead — ${input.clinicName}`,
          emoji: false,
        },
      },
      {
        type: "section",
        fields: [
          { type: "mrkdwn", text: `*Name:*\n${input.name}` },
          { type: "mrkdwn", text: `*Clinic:*\n${input.clinicName}` },
          { type: "mrkdwn", text: `*Email:*\n${input.email}` },
          { type: "mrkdwn", text: `*Claim volume:*\n${claim}` },
        ],
      },
      {
        type: "context",
        elements: [
          {
            type: "mrkdwn",
            text: `Billing setup: *${setup}* • Lead id: \`${input.leadId}\``,
          },
        ],
      },
    ],
  };
}

/**
 * Post the lead notification to Slack. Returns `{ sent: true }` on
 * a 2xx response and `{ sent: false, mock: true }` in dev mock mode.
 * The endpoint is fire-and-forget from the API route's perspective —
 * failures are logged but do NOT cause the form submit to fail (the
 * row was already inserted; sales can still see it via the email
 * side or by querying the leads table directly).
 */
export async function postLeadNotificationToSlack(
  input: LeadSlackInput,
): Promise<{ sent: boolean; mock: boolean; status?: number; error?: string }> {
  const payload = buildPayload(input);

  if (isLeadsSlackMockMode()) {
    console.log(
      [
        "",
        "[leads-slack] (dev mock) would post:",
        `  leadId: ${input.leadId}`,
        `  text:   ${buildText(input)}`,
        "",
      ].join("\n"),
    );
    return { sent: false, mock: true };
  }

  try {
    const response = await fetch(WEBHOOK_URL!, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const body = await response.text().catch(() => "");
      const message = `slack webhook responded ${response.status}: ${body.slice(0, 200)}`;
      console.error("[leads-slack] non-2xx:", message);
      return { sent: false, mock: false, status: response.status, error: message };
    }
    return { sent: true, mock: false, status: response.status };
  } catch (e) {
    const message = e instanceof Error ? e.message : "unknown Slack webhook error";
    console.error("[leads-slack] fetch threw:", message);
    return { sent: false, mock: false, error: message };
  }
}
