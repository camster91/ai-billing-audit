// GET /api/team
//
// List the current tenant's memberships. Returns each row with
// its role, status, email, invited/activated timestamps, and the
// bound user's name/email if any.
//
// Authorization: any active member of the tenant can read the
// list. The /settings/team page is the primary caller; admin
// tooling and the smoke tests also hit it.
//
// Response shape:
//   { memberships: Array<{ id, email, role, status, invitedAt,
//                          activatedAt, createdAt, user:
//                          { id, email, name } | null }> }
//
// Inactive members are INCLUDED in the list (the team page
// surfaces them as "Disabled") but the request handler filters
// them by their own status query parameter when present.

import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireTenantRole } from "@/lib/roles";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  const auth = await requireTenantRole("read");
  if (!auth.ok) return auth.response;

  const url = new URL(request.url);
  const statusFilter = url.searchParams.get("status");
  // Whitelist the values; ignore anything else to keep the
  // response shape stable.
  const validStatuses = new Set(["pending", "active", "inactive", "all"]);
  const whereStatus =
    statusFilter && validStatuses.has(statusFilter) && statusFilter !== "all"
      ? statusFilter
      : null;

  const memberships = await prisma.membership.findMany({
    where: {
      tenantId: auth.request.tenantId,
      ...(whereStatus ? { status: whereStatus } : {}),
    },
    orderBy: [{ status: "asc" }, { createdAt: "asc" }],
    include: {
      user: { select: { id: true, email: true, name: true } },
    },
  });

  return NextResponse.json({
    memberships: memberships.map((m) => ({
      id: m.id,
      email: m.email,
      role: m.role,
      status: m.status,
      invitedAt: m.invitedAt,
      activatedAt: m.activatedAt,
      createdAt: m.createdAt,
      // null when the invite has not been accepted yet
      user: m.user
        ? { id: m.user.id, email: m.user.email, name: m.user.name }
        : null,
    })),
    viewerRole: auth.request.role,
    viewerUserId: auth.request.userId,
  });
}
