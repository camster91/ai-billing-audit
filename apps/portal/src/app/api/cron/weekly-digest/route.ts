// POST /api/cron/weekly-digest
//
// Server-to-server cron endpoint hit by the VPS cron once a week
// (Monday 13:00 UTC, after the prior Mon→Sun window closes).
// Auth: `Authorization: Bearer ${CRON_SECRET}` header — set in
// the portal's .env. Returns 401 on missing/wrong token so a
// public curl probe doesn't leak the dispatch.
//
// Why an HTTP endpoint, not a node script in the cron line: the
// portal is the only process that owns the Prisma client, the
// Resend client, and the SuppressList gate. Spawning a separate
// process for the cron duplicates all three. Hitting the endpoint
// keeps the work in the running app and gives us a free health
// check (a 200 response means the portal can talk to both Postgres
// and Resend).
//
// Idempotency: runWeeklyDigest is per-tenant and the suppress-list
// gate stops repeat sends, but the cron can still double-fire if
// the schedule is changed mid-week. A second dispatch within the
// same window is a real failure mode we accept — the cost is one
// duplicate digest per affected tenant, not a billing event. If
// that becomes a problem later, the right fix is a per-tenant
// `weeklyDigestSentAt` column on Tenant; we don't add it now
// because the cron is expected to fire at most once per week.

import { NextResponse } from "next/server";
import { runWeeklyDigest } from "@/lib/emails/weekly-digest";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const expected = process.env["CRON_SECRET"];
  if (!expected) {
    console.error(
      "[cron/weekly-digest] CRON_SECRET not configured; refusing request",
    );
    return NextResponse.json(
      { error: "cron not configured" },
      { status: 503 },
    );
  }
  const auth = request.headers.get("authorization") ?? "";
  const match = /^Bearer\s+(.+)$/i.exec(auth);
  const provided = match?.[1] ?? "";
  if (!provided || !timingSafeEqual(provided, expected)) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const startedAt = new Date();
  const result = await runWeeklyDigest(startedAt);
  return NextResponse.json(
    {
      ok: true,
      startedAt: startedAt.toISOString(),
      sent: result.sent,
      skipped: result.skipped,
      errors: result.errors,
      // Per-tenant breakdown is included in dev / on first run for
      // forensic visibility; once we have confidence the cron
      // works this can be elided.
      results: result.results,
    },
    { status: 200 },
  );
}

// GET is also accepted for `curl`-style health probes — the
// auth check still runs so the endpoint doesn't leak.
export async function GET(request: Request) {
  return POST(request);
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}
