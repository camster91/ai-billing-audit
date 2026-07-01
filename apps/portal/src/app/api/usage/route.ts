// GET /api/usage
//
// Returns the current month's audit usage + quota for the active
// tenant. Source of truth is the Tenant.auditQuotaUsed /
// auditQuotaLimit columns (kept up to date by the audit engine;
// reset on the 1st of the month by the cron that the t_0d6f44ae
// task will own).
//
// Authorization (t_23bfd49c): any active member of the tenant
// with the `read` capability — that includes viewer / auditor /
// owner / admin. Disabled members and non-members get 403.
//
// Response shape (200):
//   {
//     used: number,
//     quota: number,
//     percent: number,           // 0..100, 1 dp
//     periodStart: "YYYY-MM-DD", // UTC
//     resetsAt:    "YYYY-MM-DD"  // UTC
//     state: "ok" | "warn" | "blocked",
//     blocked: boolean,          // convenience mirror of state === "blocked"
//     warningSentThisPeriod: boolean,
//     upgradeUrl: string         // present when state === "blocked"
//   }
//
// Errors:
//   401 — not signed in
//   403 — no active tenant, not a member, or membership inactive
//   500 — unexpected DB error

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { loadUsageSnapshot } from "@/lib/billing-page";
import { buildUpgradeUrl, loadQuotaSnapshot } from "@/lib/audit-quota";
import { assertMembershipCapability } from "@/lib/membership-gate";
import { internalErrorResponse } from "@/lib/api-errors";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
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
  // Role gate (t_23bfd49c): read capability covers every active
  // member role. Disabled members and non-members are rejected.
  const gate = await assertMembershipCapability(
    session.user.id,
    tenant.id,
    "read",
  );
  if (!gate.ok) {
    return NextResponse.json(
      { error: gate.error ?? "forbidden" },
      { status: 403 },
    );
  }
  try {
    const snapshot = await loadUsageSnapshot(tenant.id);
    const quota = await loadQuotaSnapshot(tenant.id);
    const upgradeUrl = quota.blocked
      ? buildUpgradeUrl(request.headers.get("origin"))
      : null;
    return NextResponse.json(
      {
        ...snapshot,
        state: quota.state,
        blocked: quota.blocked,
        warningSentThisPeriod: quota.warningSentThisPeriod,
        ...(upgradeUrl ? { upgradeUrl } : {}),
      },
      {
        headers: {
          // Usage is per-user, per-tenant — never share between users.
          "Cache-Control": "private, no-store",
        },
      },
    );
  } catch (e) {
    return internalErrorResponse(request, e, "/api/usage", {
      hint: "usage snapshot failed",
    });
  }
}
