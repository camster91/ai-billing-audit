// GET /api/billing/tiers
//
// Returns the three pricing tiers as JSON. Source of truth is
// src/lib/pricing.ts (env-driven). The pricing page renders this on
// the server side; the response is also consumable by any external client.
//
// Cached for 60s with stale-while-revalidate — pricing data changes
// rarely, and we want the page to be fast and not hit env-reads on
// every request.
//
// PUT /api/billing/tiers
//
// Updates the audit-quota cap for one or more tiers. Platform-admin
// only — gated by PLATFORM_ADMIN_EMAILS (comma-separated allowlist).
// Any signed-in tenant user MUST NOT be able to mutate platform-wide
// quota defaults.
//
// Body:
//   { caps: { small?: number, mid?: number, large?: number } }
//
// Each value must be a positive integer. Negative or zero values
// return 400. Unknown tier keys return 400. The cap floor is 1 —
// we don't accept 0 (that's the "no audits at all" sentinel which
// we don't expose to operators).
//
// Response (200):
//   { ok: true, caps: { small, mid, large } }
//
// Errors:
//   400 — invalid body or non-positive cap
//   401 — not signed in
//   403 — caller email is not in PLATFORM_ADMIN_EMAILS
//   503 — PLATFORM_ADMIN_EMAILS is unset (fail closed)

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { getPricingConfig, isValidTierId, type TierId } from "@/lib/pricing";
import {
  TIER_AUDIT_QUOTA,
  effectiveAuditQuotaLimit,
} from "@/lib/audit-quota";

export const dynamic = "force-dynamic";

export async function GET() {
  const config = getPricingConfig();
  // Return only the public shape — drop internal-only fields if any are
  // added later. The "stripePriceId" fields are intentionally exposed
  // because they appear in the response so the client can confirm
  // which Stripe price will be used at checkout.
  return Response.json(config, {
    headers: {
      "Cache-Control": "public, max-age=60, s-maxage=60, stale-while-revalidate=300",
    },
  });
}

interface TiersPutBody {
  caps?: Record<string, unknown>;
}

function isPositiveInt(n: unknown): n is number {
  return typeof n === "number" && Number.isInteger(n) && n >= 1;
}

/** Parse PLATFORM_ADMIN_EMAILS into a lowercase Set. Empty → deny all. */
function platformAdminEmails(): Set<string> {
  const raw = process.env.PLATFORM_ADMIN_EMAILS ?? "";
  return new Set(
    raw
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean),
  );
}

export async function PUT(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const admins = platformAdminEmails();
  if (admins.size === 0) {
    // Fail closed: without an allowlist this route is a platform-wide
    // quota mutator and must not be reachable by arbitrary tenants.
    console.error(
      "[/api/billing/tiers] PLATFORM_ADMIN_EMAILS unset; refusing PUT",
    );
    return NextResponse.json(
      { error: "platform_admin_not_configured" },
      { status: 503 },
    );
  }
  const email = (session.user.email ?? "").trim().toLowerCase();
  if (!email || !admins.has(email)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  let body: TiersPutBody;
  try {
    body = (await request.json()) as TiersPutBody;
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }
  if (!body || typeof body !== "object" || !body.caps || typeof body.caps !== "object") {
    return NextResponse.json(
      { error: "invalid_body" },
      { status: 400 },
    );
  }
  const requested = body.caps as Record<string, unknown>;
  // Build the merged caps map. Start from the canonical defaults and
  // overlay any keys the caller provided. We always return the full
  // { small, mid, large } shape so the client doesn't have to track
  // which keys it omitted.
  const merged: Record<TierId, number> = { ...TIER_AUDIT_QUOTA };
  for (const key of Object.keys(requested)) {
    if (!isValidTierId(key)) {
      return NextResponse.json(
        { error: "unknown_tier", tier: key },
        { status: 400 },
      );
    }
    if (!isPositiveInt(requested[key])) {
      return NextResponse.json(
        { error: "invalid_cap", tier: key, value: requested[key] },
        { status: 400 },
      );
    }
    merged[key] = requested[key] as number;
  }
  // Update every tenant whose `auditQuotaLimit` still matches the
  // PRE-update default for its tier. This is a "best-effort" sweep:
  // if an operator manually set a per-tenant override, the override
  // is preserved. The sweep is keyed on (tier, auditQuotaLimit) so
  // a tenant whose cap was bumped individually is left alone.
  for (const tier of ["small", "mid", "large"] as TierId[]) {
    const previousDefault = TIER_AUDIT_QUOTA[tier];
    const nextDefault = merged[tier];
    if (previousDefault === nextDefault) continue;
    await prisma.tenant.updateMany({
      where: { tier, auditQuotaLimit: previousDefault },
      data: { auditQuotaLimit: nextDefault },
    });
  }
  // Mutate the in-memory defaults so the very next call to
  // `getPricingConfig` (and the audit-quota lib's
  // `effectiveAuditQuotaLimit`) sees the new numbers. The
  // `getPricingConfig` reader takes its numbers from env + the
  // in-process TIER_AUDIT_QUOTA — we update the lib's source
  // directly because env-var round-trips are out of scope for
  // this task (the spec says "configurable", and a runtime
  // override is the most useful form for a paying team).
  (TIER_AUDIT_QUOTA as Record<TierId, number>).small = merged.small;
  (TIER_AUDIT_QUOTA as Record<TierId, number>).mid = merged.mid;
  (TIER_AUDIT_QUOTA as Record<TierId, number>).large = merged.large;
  // Sanity-check the call we just made: log what the effective
  // cap would be for a hypothetical fresh "small" tenant so a
  // future debugger can see the chain end-to-end.
  console.log(
    `[/api/billing/tiers] caps updated by ${email}: small=${merged.small} mid=${merged.mid} large=${merged.large}; effective(small)=${effectiveAuditQuotaLimit({ tier: "small", auditQuotaLimit: merged.small })}`,
  );
  return NextResponse.json({ ok: true, caps: merged });
}
