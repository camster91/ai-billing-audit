// Tenant-scoped request helpers.
//
// The portal's middleware (see src/proxy.ts) already resolves the
// current `Tenant` for every authenticated request and stuffs the id
// into the `x-tenant-id` header. This module re-exports the canonical
// `getActiveTenant` helper used by every protected route — it reads
// the header, looks up the `Tenant` row, and returns a fully-typed
// object. Routes that bypass middleware (e.g. a /api/cron handler
// that needs to act on a specific tenant by id) call the lower-level
// `requireTenantById` instead.

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
 * caller is not signed in, has no memberships, or the `x-tenant-id`
 * header is missing/invalid.
 *
 * The middleware guarantees the header is set on every authenticated
 * request — this helper exists so route handlers and server actions
 * can call it without re-implementing the lookup.
 */
export async function getActiveTenant(): Promise<ActiveTenant | null> {
  const session = await auth();
  if (!session?.user?.id) return null;

  const headerStore = await headers();
  const tenantId = headerStore.get("x-tenant-id");
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
