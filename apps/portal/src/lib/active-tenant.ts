// Tenant-scoped request helpers.
//
// The portal's Edge middleware can verify session-cookie presence but cannot
// decode the database session. This module provides the canonical tenant
// resolver used by protected routes: it accepts an explicit `x-tenant-id`
// override or falls back to the active tenant resolved by Auth.js, then
// verifies membership. Routes acting on a known tenant id call the lower-level
// `requireTenantById` helper directly.

import { headers } from "next/headers";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";

export interface ActiveTenant {
  userId: string;
  id: string;
  name: string;
  slug: string;
  tier: string;
  subscriptionStatus: string;
  role: string;
}

/**
 * Resolve the current tenant for a request. Returns null when the
 * caller is not signed in, has no memberships, or neither the optional
 * `x-tenant-id` override nor the verified session has an active tenant.
 *
 * Normal browser navigations use the active tenant resolved by the Auth.js
 * session callback. API clients may override it with `x-tenant-id`; both
 * paths are membership-checked by requireTenantById().
 */
export async function getActiveTenant(): Promise<ActiveTenant | null> {
  const session = await auth();
  if (!session?.user?.id) return null;

  const headerStore = await headers();
  const tenantId = headerStore.get("x-tenant-id") ?? session.user.activeTenantId;
  if (!tenantId) {
    return null;
  }
  return requireTenantById(session.user.id, tenantId);
}

/**
 * Lower-level lookup: verify the user is a member of `tenantId` and
 * return the row. Throws when the membership is missing — callers
 * that can't recover should let the error bubble (the surrounding
 * route handler returns 403).
 */
export async function requireTenantById(
  userId: string,
  tenantId: string,
): Promise<ActiveTenant> {
  const membership = await prisma.membership.findFirst({
    where: { userId, tenantId },
    include: {
      tenant: {
        select: {
          id: true,
          name: true,
          slug: true,
          tier: true,
          subscriptionStatus: true,
        },
      },
    },
  });
  if (!membership) {
    throw new Error(`user ${userId} is not a member of tenant ${tenantId}`);
  }
  return {
    ...membership.tenant,
    userId,
    role: membership.role,
  };
}

/** True if the caller is signed in. Convenience wrapper. */
export async function isSignedIn(): Promise<boolean> {
  const session = await auth();
  return Boolean(session?.user?.id);
}
