// Helper for the existing finding-mutation routes
// (src/app/api/encounters/.../accept, /dismiss, /findings/bulk/...).
// Centralizes the role check that t_23bfd49c introduced — the
// same set of routes also do their own membership lookup
// (read-only) for the encounter scope, so we keep this thin.
//
// Why not just call requireTenantRole()? The existing routes
// already use getActiveTenant() and the x-tenant-id header
// contract; replacing that with the full helper would force
// a wider refactor. This is the minimal change to enforce the
// new role contract without breaking the existing flow.

import { prisma } from "@/lib/prisma";
import { hasCapability } from "@/lib/roles";

export interface MembershipGateResult {
  ok: boolean;
  /** When !ok, an error code suitable for the JSON body. */
  error?: "forbidden" | "no_tenant" | "unauthenticated";
}

/**
 * Verify the caller has the given capability on the active
 * tenant. Returns { ok: true } on success or { ok: false,
 * error } on the various failure modes. Routes map the error
 * to a status code; this helper is HTTP-agnostic on purpose
 * so the caller can pick 401 vs 403.
 */
export async function assertMembershipCapability(
  userId: string,
  tenantId: string,
  capability:
    | "read"
    | "write"
    | "accept_or_dismiss"
    | "billing"
    | "team",
): Promise<MembershipGateResult> {
  const m = await prisma.membership.findFirst({
    where: { userId, tenantId },
    select: { role: true, status: true },
  });
  if (!m) {
    return { ok: false, error: "forbidden" };
  }
  if (m.status === "inactive") {
    return { ok: false, error: "forbidden" };
  }
  if (!hasCapability(m.role, capability)) {
    return { ok: false, error: "forbidden" };
  }
  return { ok: true };
}
