// /api/analytics/event — best-effort analytics beacon endpoint.
//
// Today this just logs to stdout (so the deploy can be observed) and
// returns 204. When a real analytics backend is wired (PostHog / Plausible
// / GA4 measurement protocol), this handler is the single place to add
// the server-side forward. The page-side AnalyticsClick component pushes
// to window.dataLayer first, so a GTM tag can pick the same events up
// without a code change.

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: Request) {
  let payload: unknown = null;
  try {
    payload = await req.json();
  } catch {
    payload = { raw: "<unparseable>" };
  }
  // eslint-disable-next-line no-console
  console.log("[analytics-event]", JSON.stringify(payload));
  return new NextResponse(null, { status: 204 });
}
