// GET /api/email/unsubscribe
//
// One-click unsubscribe endpoint (RFC 8058). The List-Unsubscribe
// header in marketing-adjacent emails points here so a Gmail /
// Outlook user can stop the weekly digest with a single click —
// no login required, no email confirmation round-trip.
//
// Auth: requires a signed `token` query param (HMAC of email +
// template + expiry). Raw `?email=` is rejected — anyone who knew
// an address could previously suppress it without proof of inbox
// access.
//
// Semantics:
//   - "unsubscribe" reason goes into SuppressListEntry; future
//     sends of marketing-adjacent templates (welcome, weekly_digest)
//     are blocked. Operational templates (password-reset,
//     first-audit-complete) are NOT blocked — the user only opted
//     out of marketing.
//   - We always respond with a tiny HTML confirmation page so the
//     user sees "you've been unsubscribed" in their browser when
//     the one-click flow opens a tab. Mailbox clients that POST
//     to the URL with List-Unsubscribe-Post expect a 2xx; we send
//     200 either way.
//   - The endpoint also accepts POST (with the same query params)
//     for clients that use the List-Unsubscribe-Post header shape.
//
// We intentionally do NOT require a CSRF token here. The endpoint
// is idempotent and the signed token IS the authorization.

import type { NextRequest } from "next/server";
import { prisma } from "@/lib/prisma";
import { verifyUnsubscribeToken } from "@/lib/email";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const CONFIRMATION_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Unsubscribed</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body { font: 16px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1a1a1a; max-width: 560px; margin: 60px auto; padding: 0 20px; }
  h1 { font-size: 22px; margin: 0 0 12px; }
  p { margin: 0 0 12px; }
  a { color: #2b5fff; }
</style>
</head>
<body>
  <h1>You're unsubscribed</h1>
  <p>You won't receive the weekly digest from AI Billing Portal anymore.</p>
  <p>You'll still get security and operational emails (like password resets and audit notifications). Reach out to support if you need those stopped too.</p>
  <p><a href="/dashboard">Back to the portal</a></p>
</body>
</html>`;

const ALREADY_HTML = CONFIRMATION_HTML.replace(
  "<h1>You're unsubscribed</h1>",
  "<h1>Already unsubscribed</h1>",
);

const ERROR_HTML = `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Unsubscribe failed</title></head>
<body style="font: 16px/1.45 -apple-system, sans-serif; max-width: 560px; margin: 60px auto; padding: 0 20px;">
  <h1>Unsubscribe failed</h1>
  <p>The unsubscribe link is missing, expired, or malformed. Please reply to the original email and we'll handle it manually.</p>
</body>
</html>`;

async function handle(req: NextRequest): Promise<Response> {
  const url = new URL(req.url);
  const token = url.searchParams.get("token");
  const verified = token ? verifyUnsubscribeToken(token) : null;
  if (!verified) {
    return new Response(ERROR_HTML, {
      status: 400,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }
  const normalized = verified.email;
  const template = verified.templateId;
  // Idempotent: if the address is already suppressed, we still
  // return 200 with the "already unsubscribed" page so the user
  // sees confirmation.
  const existing = await prisma.suppressListEntry.findUnique({
    where: { email: normalized },
    select: { reason: true },
  });
  if (existing && (existing.reason === "complaint" || existing.reason === "bounce")) {
    // Hard-suppressed (bounce / complaint) — they shouldn't have
    // been receiving the marketing email in the first place. Show
    // a generic "you're unsubscribed" page anyway; we don't expose
    // the underlying reason.
    return new Response(CONFIRMATION_HTML, {
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }
  if (existing && existing.reason === "unsubscribe") {
    return new Response(ALREADY_HTML, {
      status: 200,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }
  await prisma.$transaction([
    prisma.suppressListEntry.create({
      data: {
        email: normalized,
        reason: "unsubscribe",
        sourceEventId: `oneclick:${crypto.randomUUID()}`,
        sourceDetail: `template=${template}`,
      },
    }),
    prisma.suppressionEvent.create({
      data: {
        email: normalized,
        reason: "unsubscribe",
        sourceEventId: `oneclick:local`,
        sourceDetail: `template=${template} via=${req.headers.get("user-agent") ?? "unknown"}`,
        payloadJson: JSON.stringify({
          email: normalized,
          template,
          userAgent: req.headers.get("user-agent"),
          ts: new Date().toISOString(),
        }),
      },
    }),
  ]);
  return new Response(CONFIRMATION_HTML, {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}

export async function GET(req: NextRequest): Promise<Response> {
  return handle(req);
}

export async function POST(req: NextRequest): Promise<Response> {
  return handle(req);
}
