// POST /api/leads — public marketing-site contact form endpoint.
//
// Captures a single lead submission from the public contact form on
// the marketing site. Validates the payload, runs a disposable-email
// check, inserts one row into the `leads` table, and fires the two
// notifications (email to sales@, Slack to the configured webhook).
//
// Auth: NOT required. The endpoint is public — the contact form is
// the top-of-funnel for pre-account visitors. Rate-limiting is the
// job of the upstream reverse proxy / WAF, not this handler.
//
// PII: exactly the five submitted fields are persisted. We do not
// capture IP, User-Agent, or referrer. createdAt is non-PII
// (timestamp only) and is included so sales can correlate to traffic.
//
// Response shape:
//   200 — { ok: true, leadId: string }
//   400 — { error: "invalid_input", details: ZodFlattenedError }
//   400 — { error: "disposable_email" }  (after passing zod)
//   405 — { error: "method_not_allowed" }
//   500 — { error: "internal_error", message?: string }
//
// Notifications are fire-and-forget after the row is inserted. A
// notification failure is logged but does NOT undo the insert —
// the lead is captured regardless. Sales can still see it in the DB
// even if email/Slack is down. The Promise.all wrapper here just
// parallelises the two side effects; we do not await the result
// before returning 200 to the client (the row is already committed).
//
// Out of scope (per the task body):
//   - CRM sync / lead scoring / marketing automation
//   - Authenticated admin UI for browsing leads
//   - A/B testing or form variants
//   - File uploads or attachments

import { NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { isDisposableEmail } from "@/lib/disposable-email-domains";
import { sendLeadNotificationEmail } from "@/lib/leads-email";
import { postLeadNotificationToSlack } from "@/lib/leads-slack";
import { internalErrorResponse } from "@/lib/api-errors";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const leadInputSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "name is required")
    .max(200, "name is too long"),
  clinicName: z
    .string()
    .trim()
    .min(1, "clinic name is required")
    .max(200, "clinic name is too long"),
  email: z
    .string()
    .trim()
    .min(3, "email is required")
    .max(320, "email is too long")
    // Cheap shape check — the disposable-domain list is the real gate.
    .email("invalid email address"),
  claimVolume: z
    .number()
    .int("claim volume must be a whole number")
    .min(0, "claim volume cannot be negative")
    .max(100000, "claim volume is too large")
    .nullable(),
  billingSetup: z.enum(["in_house", "outsourced", "hybrid"], {
    message: "billing setup must be in_house, outsourced, or hybrid",
  }),
});

type LeadInput = z.infer<typeof leadInputSchema>;

export async function POST(request: Request): Promise<NextResponse> {
  // 1. Parse + validate
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "invalid_input", details: { formErrors: ["body must be valid JSON"], fieldErrors: {} } },
      { status: 400 },
    );
  }

  const parsed = leadInputSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }
  const input: LeadInput = parsed.data;

  // 2. Disposable-email gate (after zod, so the user gets a real
  //    "invalid email" error for malformed addresses and a
  //    "disposable_email" error for known throwaway domains).
  if (isDisposableEmail(input.email)) {
    return NextResponse.json(
      { error: "disposable_email" },
      { status: 400 },
    );
  }

  // 3. Insert. Lowercase the email on the way in to keep the column
  //    consistent for downstream lookups; preserve the user's
  //    casing for name and clinicName (display fields).
  let lead;
  try {
    lead = await prisma.lead.create({
      data: {
        name: input.name,
        clinicName: input.clinicName,
        email: input.email.toLowerCase(),
        claimVolume: input.claimVolume,
        billingSetup: input.billingSetup,
      },
      select: { id: true },
    });
  } catch (e) {
    return internalErrorResponse(request, e, "/api/leads", {
      hint: "lead insert failed",
    });
  }

  // 4. Fire notifications (fire-and-forget; do not block the
  //    response on these). A failure here is logged but the lead
  //    is already persisted — sales can still see it.
  const notificationInput = {
    name: input.name,
    clinicName: input.clinicName,
    email: input.email,
    claimVolume: input.claimVolume,
    billingSetup: input.billingSetup,
    leadId: lead.id,
  };
  void Promise.allSettled([
    sendLeadNotificationEmail(notificationInput).then((r) => {
      if (!r.sent && !r.mock) {
        console.error("[/api/leads] email failed:", r.error);
      }
    }),
    postLeadNotificationToSlack(notificationInput).then((r) => {
      if (!r.sent && !r.mock) {
        console.error("[/api/leads] slack failed:", r.error);
      }
    }),
  ]);

  return NextResponse.json({ ok: true, leadId: lead.id });
}

// Defensive: GET should be a 405, not a 200 with the form HTML.
export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    { error: "method_not_allowed" },
    { status: 405, headers: { Allow: "POST" } },
  );
}
