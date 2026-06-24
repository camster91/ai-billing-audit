// Role-based authorization for tenant-scoped routes.
//
// One helper, one source of truth. Every protected API route should
// call `requireTenantRole(...)` (or one of the capability helpers
// below) instead of checking roles inline. The helper:
//
//   1. Confirms the caller is signed in (session.user.id).
//   2. Reads the active tenant from the x-tenant-id header.
//   3. Loads the caller's Membership row for that tenant.
//   4. Verifies the membership exists, is not `inactive`, and has
//      a role that satisfies the requested capability.
//   5. Returns `{ user, tenant, role, membership }` so the caller
//      can avoid a second DB round-trip.
//
// Spec for this milestone (t_23bfd49c):
//   - owner   : full access including billing, team management, and
//               all mutations on tenant data.
//   - auditor : full READ across tenant data + the Accept / Dismiss
//               actions on findings. Cannot mutate anything else.
//   - viewer  : READ only.
//   - admin   : legacy value kept for back-compat. Treated as
//               equivalent to `owner` for capability purposes.
//
// The helper also enforces that an `inactive` membership is NOT a
// member for the purposes of the request. Disabling a member
// therefore revokes access on the next request, even if the JWT
// cookie is still valid (the membership is the source of truth,
// not the cookie).

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { headers } from "next/headers";

export type Capability =
  | "read"            // any GET under /api/* for this tenant
  | "write"           // any non-Accept/Dismiss mutation
  | "accept_or_dismiss" // POST /api/encounters/[id]/findings/[findingId]/{accept,dismiss}
  | "billing"         // Stripe / subscription / tier / cancel endpoints
  | "team";           // /api/team/* (invite, change role, disable)

const ROLE_RANK: Record<string, number> = {
  viewer: 1,
  auditor: 2,
  owner: 3,
  admin: 3, // legacy back-compat
};

/**
 * True if `role` is at least as privileged as `required` per the
 * rank table above. Admin counts as owner for capability purposes.
 */
export function hasCapability(
  role: string | null | undefined,
  required: Capability,
): boolean {
  if (!role) return false;
  const rank = ROLE_RANK[role] ?? 0;
  switch (required) {
    case "read":
      return rank >= 1;
    case "accept_or_dismiss":
      // viewer cannot; auditor + owner + admin can.
      return rank >= 2;
    case "write":
    case "billing":
    case "team":
      // owner / admin only.
      return rank >= 3;
  }
}

export interface AuthorizedRequest {
  userId: string;
  userEmail: string | null;
  tenantId: string;
  tenantName: string;
  role: "owner" | "admin" | "auditor" | "viewer";
  membershipId: string;
  membershipStatus: "pending" | "active" | "inactive";
}

/**
 * Resolve the active tenant and load the caller's Membership row.
 *
 * Returns either:
 *   - `{ ok: true, request }` on success
 *   - `{ ok: false, response }` with a ready-to-return NextResponse
 *     for the 401 / 403 / 404 case
 *
 * The route handler should `return result.response` on the !ok
 * branch; on the ok branch, it can proceed using
 * `result.request.userId` etc.
 *
 * Capability check: the helper requires the membership to be
 * `active` or `pending` (a pending member is still a member of the
 * tenant, just not yet bound to a session). Inactive members are
 * treated as 404 — they should not be able to tell that the
 * tenant still exists.
 */
export async function requireTenantRole(
  capability: Capability,
): Promise<
  | { ok: true; request: AuthorizedRequest }
  | { ok: false; response: NextResponse }
> {
  const session = await auth();
  if (!session?.user?.id) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: "unauthenticated" },
        { status: 401 },
      ),
    };
  }
  const userId = session.user.id;
  const userEmail = session.user.email ?? null;

  const hdr = await headers();
  const tenantId = hdr.get("x-tenant-id");
  if (!tenantId) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: "no_tenant" },
        { status: 403 },
      ),
    };
  }

  const membership = await prisma.membership.findFirst({
    where: { userId, tenantId },
    include: {
      tenant: { select: { id: true, name: true } },
    },
  });

  if (!membership || membership.status === "inactive") {
    // Treat disabled / never-was-a-member identically — the
    // caller should not be able to tell the tenant exists.
    return {
      ok: false,
      response: NextResponse.json(
        { error: "not_a_member" },
        { status: 404 },
      ),
    };
  }

  if (!hasCapability(membership.role, capability)) {
    return {
      ok: false,
      response: NextResponse.json(
        {
          error: "forbidden",
          detail:
            `role '${membership.role}' is not authorized for ` +
            `'${capability}' on tenant ${tenantId}`,
        },
        { status: 403 },
      ),
    };
  }

  return {
    ok: true,
    request: {
      userId,
      userEmail,
      tenantId,
      tenantName: membership.tenant.name,
      role: membership.role as AuthorizedRequest["role"],
      membershipId: membership.id,
      membershipStatus: membership.status as AuthorizedRequest["membershipStatus"],
    },
  };
}

/**
 * Convenience helper: the team-management routes and the user
 * request tests want the raw shape, not the result envelope.
 * Throws on failure (caller is expected to be a route handler that
 * will let the error bubble to a 500, or use the result-envelope
 * variant above).
 */
export async function authorizeOrThrow(
  capability: Capability,
): Promise<AuthorizedRequest> {
  const r = await requireTenantRole(capability);
  if (!r.ok) {
    // Surface the same status code to the caller so route handlers
    // can simply `return result.response`.
    throw new AuthorizeError(r.response);
  }
  return r.request;
}

export class AuthorizeError extends Error {
  readonly response: NextResponse;
  constructor(response: NextResponse) {
    super("authorize_failed");
    this.response = response;
  }
}
