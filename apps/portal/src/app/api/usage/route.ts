// GET /api/usage
//
// Returns the current month's audit usage + quota for the active
// tenant. Source of truth is the Tenant.auditQuotaUsed /
// auditQuotaLimit columns (kept up to date by the audit engine;
// reset on the 1st of the month by the cron that the t_0d6f44ae
// task will own). Auth: any signed-in user with an active tenant.
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
//   403 — no active tenant
//   500 — unexpected DB error

import { NextResponse } from "next/server";
import { getActiveTenant } from "@/lib/active-tenant";
import { loadUsageSnapshot } from "@/lib/billing-page";
import { buildUpgradeUrl, loadQuotaSnapshot } from "@/lib/audit-quota";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json(
      { error: "no_tenant" },
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
    const message = e instanceof Error ? e.message : "unknown";
    console.error("[/api/usage] DB error:", message);
    return NextResponse.json(
      { error: "internal_error", message },
      { status: 500 },
    );
  }
}
