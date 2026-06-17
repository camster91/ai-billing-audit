// POST /api/audit/run
//
// Server-side gate for every audit submission. Atomically increments
// `Tenant.auditQuotaUsed`; at 80% of cap sends a one-time warning
// email to the owner; at 100% rejects the request with HTTP 402 and
// an `upgrade_url` pointing at the billing/plan-change page.
//
// Body:
//   { encounterId?: string }   — currently informational. The audit
//                                engine reads this on the back end;
//                                the quota gate is per-tenant, not
//                                per-encounter, so encounterId is
//                                optional and only logged.
//
// Response shapes:
//
//   200 — audit allowed
//     { allowed: true, state: "ok" | "warn", used, quota, percent,
//       warnedNow?: boolean, upgradeUrl: string }
//
//   402 — quota exhausted
//     { allowed: false, state: "blocked", used, quota, percent,
//       upgradeUrl: string }
//
//   401 — not signed in
//   403 — no active tenant, or caller lacks the `write` capability
//         (viewers cannot run audits; t_23bfd49c)
//
// The hard cap is server-side authoritative. There is no client flag
// that can bypass the check; the only way to call this route is via
// the live, signed-in session, and the counter lives on the tenant
// row that's read at request time.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import {
  buildUpgradeUrl,
  consumeAuditQuota,
  type ConsumeResult,
} from "@/lib/audit-quota";
import { assertMembershipCapability } from "@/lib/membership-gate";

export const runtime = "nodejs";
// Audit runs are not cacheable — the quota is per-request, per-tenant.
export const dynamic = "force-dynamic";

interface AuditRunBody {
  encounterId?: string;
}

function isAuditRunBody(value: unknown): value is AuditRunBody {
  if (value === null || value === undefined) return true;
  if (typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  if (v.encounterId !== undefined && typeof v.encounterId !== "string") {
    return false;
  }
  return true;
}

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json(
      { error: "no_tenant" },
      { status: 403 },
    );
  }
  // Role gate (t_23bfd49c): running an audit is a write
  // action. Viewers and disabled members are rejected.
  const gate = await assertMembershipCapability(
    session.user.id,
    tenant.id,
    "write",
  );
  if (!gate.ok) {
    return NextResponse.json(
      { error: gate.error ?? "forbidden" },
      { status: 403 },
    );
  }
  // Parse the body. We don't require one — the gate is per-tenant.
  let body: unknown = null;
  try {
    const text = await request.text();
    if (text.length > 0) body = JSON.parse(text);
  } catch {
    return NextResponse.json(
      { error: "invalid_json" },
      { status: 400 },
    );
  }
  if (!isAuditRunBody(body)) {
    return NextResponse.json(
      { error: "invalid_body" },
      { status: 400 },
    );
  }
  const origin = request.headers.get("origin");
  const result: ConsumeResult = await consumeAuditQuota({
    tenantId: tenant.id,
    origin,
  });
  // Log the audit-run decision so a missing row in the future can
  // be traced back through the event log.
  console.log(
    `[/api/audit/run] tenant=${tenant.id} encounterId=${(body as AuditRunBody | null)?.encounterId ?? "-"} kind=${result.kind} used=${result.used} quota=${result.quota} percent=${result.percent}`,
  );
  if (result.kind === "blocked") {
    // 402 Payment Required — the body includes `upgrade_url` so a
    // thin client (the FastAPI audit engine, a future mobile app)
    // can hand the owner a clickable link without re-deriving it.
    return NextResponse.json(
      {
        allowed: false,
        state: "blocked",
        used: result.used,
        quota: result.quota,
        percent: result.percent,
        upgradeUrl: result.upgradeUrl,
        error: "quota_exceeded",
      },
      { status: 402 },
    );
  }
  return NextResponse.json(
    {
      allowed: true,
      state: result.kind,
      used: result.used,
      quota: result.quota,
      percent: result.percent,
      upgradeUrl: buildUpgradeUrl(origin),
      ...(result.kind === "warn" ? { warnedNow: result.warnedNow } : {}),
    },
    {
      status: 200,
      headers: { "Cache-Control": "private, no-store" },
    },
  );
}
