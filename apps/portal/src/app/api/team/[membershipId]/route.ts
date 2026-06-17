// PATCH /api/team/[membershipId]
//   Body: { role: "owner" | "auditor" | "viewer" }
//
// Authorization: caller must have the `team` capability.
//
// Behavior:
//   - Load the target membership, scoped to the caller's active tenant.
//   - Reject self-demotion of the last active owner (would lock
//     the tenant out of admin — see edge case in
//     docs/TEAM_MANAGEMENT.md, added in a follow-up doc task).
//   - Update the role.
//   - Return the updated row in the same shape GET /api/team uses.
//
// DELETE /api/team/[membershipId]
//
// Authorization: caller must have the `team` capability.
//
// Behavior:
//   - Soft-disable: set status=inactive (we do NOT hard-delete
//     because Encounter / Finding audit chains reference the
//     membership via the userIdentifier — the audit chain must
//     remain valid).
//   - Revoke the bound User's active Session rows for THIS tenant
//     (Session.activeTenantId == tenantId). Note: we cannot
//     safely delete sessions globally because the user may have
//     other tenants; clearing activeTenantId forces the next
//     request to re-resolve.
//   - Refuse to disable the last active owner (same reason as
//     above).
//
// Both verbs return JSON. Errors are 400 / 401 / 403 / 404 / 409.

import { NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { requireTenantRole } from "@/lib/roles";
import { isInvitableRole } from "@/lib/tenant";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface RouteContext {
  params: Promise<{ membershipId: string }>;
}

const patchBodySchema = z.object({
  role: z.string().refine(isInvitableRole, {
    message: "role must be one of: owner, auditor, viewer",
  }),
});

async function loadTarget(
  membershipId: string,
  tenantId: string,
) {
  return prisma.membership.findFirst({
    where: { id: membershipId, tenantId },
  });
}

/**
 * Returns true when disabling or demoting `target` would leave
 * the tenant with zero active owners. Callers should refuse
 * the operation when this is true.
 */
async function wouldOrphanTenant(
  tenantId: string,
  excludeMembershipId: string,
): Promise<boolean> {
  const activeOwners = await prisma.membership.count({
    where: {
      tenantId,
      role: { in: ["owner", "admin"] },
      status: "active",
      NOT: { id: excludeMembershipId },
    },
  });
  return activeOwners === 0;
}

export async function PATCH(
  request: Request,
  context: RouteContext,
) {
  const auth = await requireTenantRole("team");
  if (!auth.ok) return auth.response;
  const { membershipId } = await context.params;

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return NextResponse.json(
      { error: "invalid_input", detail: "Body must be JSON" },
      { status: 400 },
    );
  }
  const parsed = patchBodySchema.safeParse(raw);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }
  const { role } = parsed.data;

  const target = await loadTarget(membershipId, auth.request.tenantId);
  if (!target) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  // Demoting-from-owner safety: if the target is currently the
  // last active owner AND we're moving them to a non-owner role,
  // refuse. Admins are treated as owners for the "currently"
  // check (a legacy data shape), but the patch schema only
  // accepts the "owner" value for promotions, so "staying" only
  // needs to compare against "owner".
  const isCurrentlyOwnerLike =
    target.role === "owner" || target.role === "admin";
  const isStayingOwnerLike = role === "owner";
  if (
    target.status === "active" &&
    isCurrentlyOwnerLike &&
    !isStayingOwnerLike &&
    (await wouldOrphanTenant(auth.request.tenantId, target.id))
  ) {
    return NextResponse.json(
      {
        error: "would_orphan_tenant",
        detail:
          "Refusing to demote the last active owner. Promote another member to owner first.",
      },
      { status: 409 },
    );
  }

  const updated = await prisma.membership.update({
    where: { id: target.id },
    data: { role },
    include: {
      user: { select: { id: true, email: true, name: true } },
    },
  });

  return NextResponse.json({
    ok: true,
    membership: {
      id: updated.id,
      email: updated.email,
      role: updated.role,
      status: updated.status,
      invitedAt: updated.invitedAt,
      activatedAt: updated.activatedAt,
      createdAt: updated.createdAt,
      user: updated.user
        ? { id: updated.user.id, email: updated.user.email, name: updated.user.name }
        : null,
    },
  });
}

export async function DELETE(
  _request: Request,
  context: RouteContext,
) {
  const auth = await requireTenantRole("team");
  if (!auth.ok) return auth.response;
  const { membershipId } = await context.params;

  const target = await loadTarget(membershipId, auth.request.tenantId);
  if (!target) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  if (target.status === "inactive") {
    // Idempotent: disabling an already-disabled member returns 200
    // with the current row, no session churn.
    return NextResponse.json({ ok: true, membership: { id: target.id, status: target.status } });
  }

  // Last-owner safety: refuse to disable the last active owner.
  const isCurrentlyOwnerLike =
    target.role === "owner" || target.role === "admin";
  if (
    target.status === "active" &&
    isCurrentlyOwnerLike &&
    (await wouldOrphanTenant(auth.request.tenantId, target.id))
  ) {
    return NextResponse.json(
      {
        error: "would_orphan_tenant",
        detail:
          "Refusing to disable the last active owner. Promote another member to owner first.",
      },
      { status: 409 },
    );
  }

  // Disable: flip status, clear the invite token (defense-in-depth,
  // even though the row is no longer "pending" the spec says
  // revoked tokens are no longer valid), and revoke active sessions
  // for this (user, tenant) pair.
  const updated = await prisma.$transaction(async (tx) => {
    const row = await tx.membership.update({
      where: { id: target.id },
      data: {
        status: "inactive",
        inviteToken: null,
      },
    });

    if (target.userId) {
      // Force the next request to re-resolve the active tenant.
      // The user is NOT globally signed out — they keep their
      // session cookie and can re-resolve to any other tenant
      // they still belong to.
      await tx.session.updateMany({
        where: {
          userId: target.userId,
          activeTenantId: auth.request.tenantId,
        },
        data: { activeTenantId: null },
      });
    }

    return row;
  });

  return NextResponse.json({
    ok: true,
    membership: {
      id: updated.id,
      email: updated.email,
      role: updated.role,
      status: updated.status,
      invitedAt: updated.invitedAt,
      activatedAt: updated.activatedAt,
    },
  });
}
