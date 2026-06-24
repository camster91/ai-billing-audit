// POST /api/email/webhook
//
// Resend webhook receiver. Receives three event types:
//
//   - email.bounced       → add to SuppressListEntry, reason="bounce"
//   - email.complained    → add to SuppressListEntry, reason="complaint"
//   - email.delivered     → ignore (no-op, returned for completeness;
//                            we don't act on successful deliveries)
//
// Signature verification: Resend signs with svix (the same scheme
// they use for the dashboard event stream). The shared secret is
// RESEND_WEBHOOK_SECRET — when blank we refuse to process events
// (this matches the Stripe webhook's posture in
// /api/billing/webhook/route.ts: no secret, no trust).
//
// Idempotency: every accepted event inserts a SuppressionEvent row
// first; the unique index on `sourceEventId` dedupes re-deliveries.
// A duplicate hits the unique constraint and we ack-and-skip — the
// SuppressListEntry upsert is the second step and runs only on the
// first delivery.
//
// The list-unsubscribe one-click flow lives at GET
// /api/email/unsubscribe (separate route, same write target) so
// the click-from-mailbox path doesn't have to deal with svix
// signature verification.

import type { NextRequest } from "next/server";
import { prisma } from "@/lib/prisma";
import {
  type SuppressionReason,
} from "@/lib/email";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface ResendBouncePayload {
  type: "email.bounced";
  created_at: string;
  data: {
    email_id: string;
    to: string[];
    from: string;
    subject: string;
    bounce?: {
      type?: string;
      message?: string;
      subType?: string;
    };
  };
}

interface ResendComplaintPayload {
  type: "email.complained";
  created_at: string;
  data: {
    email_id: string;
    to: string[];
    from: string;
    subject: string;
    complaint?: {
      feedbackType?: string;
      message?: string;
    };
  };
}

interface ResendDeliveryPayload {
  type: "email.delivered";
  created_at: string;
  data: { email_id: string; to: string[]; from: string; subject: string };
}

type ResendPayload =
  | ResendBouncePayload
  | ResendComplaintPayload
  | ResendDeliveryPayload
  | { type: string; created_at?: string; data?: { email_id?: string; to?: string[] } };

// ---------------------------------------------------------------------------
// Signature verification (svix)
//
// Resend uses svix to sign webhooks. The verification is
// deterministic — verifyWebhook(rawBody, headers, secret) returns
// the parsed payload or throws. We avoid the svix SDK dependency
// (extra ~200kB) and run a small HMAC-SHA256 check ourselves. The
// shape of the signed string is documented at:
//   https://docs.resend.com/webhooks/verify-webhooks
// ---------------------------------------------------------------------------

const RESEND_WEBHOOK_SECRET = process.env["RESEND_WEBHOOK_SECRET"];

interface SvixHeaders {
  id: string;
  timestamp: string;
  signature: string;
}

function readSvixHeaders(req: NextRequest): SvixHeaders | null {
  const id = req.headers.get("svix-id");
  const timestamp = req.headers.get("svix-timestamp");
  const signature = req.headers.get("svix-signature");
  if (!id || !timestamp || !signature) return null;
  return { id, timestamp, signature };
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

async function verifySignature(
  rawBody: string,
  headers: SvixHeaders,
  secret: string,
): Promise<boolean> {
  // svix secret format: "whsec_<base64>". The base64 portion is
  // the HMAC key — base64-decode before use.
  const keyB64 = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  const keyBytes = Buffer.from(keyB64, "base64");
  const encoder = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
  const signed = `${headers.id}.${headers.timestamp}.${rawBody}`;
  const mac = await crypto.subtle.sign(
    "HMAC",
    cryptoKey,
    encoder.encode(signed),
  );
  const expected = `v1,${Buffer.from(mac).toString("base64")}`;
  // svix-signature can carry multiple space-separated entries
  // (e.g. "v1,abc v1,def" for secret rotation); we accept any
  // single match.
  return headers.signature
    .split(" ")
    .some((s) => timingSafeEqual(s.trim(), expected));
}

// ---------------------------------------------------------------------------
// Suppress list writes
// ---------------------------------------------------------------------------

async function recordSuppression(args: {
  email: string;
  reason: SuppressionReason;
  sourceEventId: string | null;
  sourceDetail: string | null;
  payloadJson: string;
}): Promise<{ created: boolean; suppressed: boolean }> {
  const normalized = args.email.toLowerCase().trim();
  // 1. History row (idempotent on sourceEventId).
  let created = false;
  if (args.sourceEventId) {
    try {
      await prisma.suppressionEvent.create({
        data: {
          email: normalized,
          reason: args.reason,
          sourceEventId: args.sourceEventId,
          sourceDetail: args.sourceDetail,
          payloadJson: args.payloadJson,
        },
      });
      created = true;
    } catch (e) {
      // Unique violation on (email, sourceEventId) is the dedup
      // signal — the same event was delivered twice.
      if (isUniqueViolation(e)) {
        return { created: false, suppressed: false };
      }
      throw e;
    }
  } else {
    await prisma.suppressionEvent.create({
      data: {
        email: normalized,
        reason: args.reason,
        sourceEventId: null,
        sourceDetail: args.sourceDetail,
        payloadJson: args.payloadJson,
      },
    });
    created = true;
  }

  // 2. Current-state upsert.
  await prisma.suppressListEntry.upsert({
    where: { email: normalized },
    create: {
      email: normalized,
      reason: args.reason,
      sourceEventId: args.sourceEventId,
      sourceDetail: args.sourceDetail,
    },
    update: {
      reason: args.reason,
      sourceEventId: args.sourceEventId ?? undefined,
      sourceDetail: args.sourceDetail ?? undefined,
      lastEventAt: new Date(),
    },
  });
  return { created, suppressed: true };
}

function isUniqueViolation(e: unknown): boolean {
  if (!e || typeof e !== "object") return false;
  // Prisma 7 uses the `P2002` error code; better-sqlite3 surfaces
  // the SQLite UNIQUE constraint message. We accept either.
  const code = (e as { code?: string }).code;
  if (code === "P2002") return true;
  const message = (e as { message?: string }).message ?? "";
  return /UNIQUE constraint failed/i.test(message);
}

// ---------------------------------------------------------------------------
// Route handler
// ---------------------------------------------------------------------------

export async function POST(req: NextRequest) {
  const raw = await req.text();
  const headers = readSvixHeaders(req);
  const secret = RESEND_WEBHOOK_SECRET;

  if (!secret) {
    console.error(
      "[email-webhook] RESEND_WEBHOOK_SECRET not configured; refusing event",
    );
    return Response.json({ error: "webhook not configured" }, { status: 503 });
  }
  if (!headers) {
    return Response.json({ error: "missing svix headers" }, { status: 400 });
  }
  const valid = await verifySignature(raw, headers, secret);
  if (!valid) {
    return Response.json({ error: "invalid signature" }, { status: 401 });
  }

  let payload: ResendPayload;
  try {
    payload = JSON.parse(raw) as ResendPayload;
  } catch {
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }

  const eventId = (payload as { data?: { email_id?: string } }).data?.email_id ?? null;

  if (payload.type === "email.bounced") {
    const data = (payload as ResendBouncePayload).data;
    const to = data.to?.[0];
    if (!to) {
      return Response.json({ ok: true, skipped: "no recipient" });
    }
    const detail = data.bounce
      ? [data.bounce.type, data.bounce.subType, data.bounce.message]
          .filter(Boolean)
          .join(": ")
      : null;
    const res = await recordSuppression({
      email: to,
      reason: "bounce",
      sourceEventId: eventId,
      sourceDetail: detail,
      payloadJson: raw,
    });
    return Response.json({ ok: true, ...res });
  }

  if (payload.type === "email.complained") {
    const data = (payload as ResendComplaintPayload).data;
    const to = data.to?.[0];
    if (!to) {
      return Response.json({ ok: true, skipped: "no recipient" });
    }
    const detail = data.complaint
      ? [data.complaint.feedbackType, data.complaint.message]
          .filter(Boolean)
          .join(": ")
      : null;
    const res = await recordSuppression({
      email: to,
      reason: "complaint",
      sourceEventId: eventId,
      sourceDetail: detail,
      payloadJson: raw,
    });
    return Response.json({ ok: true, ...res });
  }

  if (payload.type === "email.delivered") {
    // No-op — kept here so the route is self-documenting and so a
    // future "track engagement" feature has a hook.
    return Response.json({ ok: true, ignored: payload.type });
  }

  // Unknown event type — accept and ignore.
  return Response.json({ ok: true, ignored: payload.type });
}
