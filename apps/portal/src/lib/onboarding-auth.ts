// Per-route auth + tenant-ownership guard for /api/onboarding/*.
//
// Even though the proxy lists /api/onboarding as public (so the
// initial redeem can run before sign-in), every step-save endpoint
// from step 2 onward must verify the caller is signed in AND is a
// member of the tenant being mutated. Without this guard, anyone
// with a guessed tenantId could rewrite a clinic's profile.
//
// Onboarding routes that need this guard call `requireOnboardingAuth`
// which:
//   - throws 401-style OnboardingError when the user is not signed in
//   - throws 403-style OnboardingError when the user has no
//     membership for the supplied tenantId
//   - returns the userId and the membership role otherwise
//
// The redeem route is the only onboarding route that should NOT
// call this — its first hit can be unauthenticated (the user is the
// buyer who just came back from Stripe).

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { OnboardingError } from "@/lib/onboarding";

export interface OnboardingAuth {
  userId: string;
  tenantId: string;
  role: string;
}

/**
 * Authenticate the caller AND verify they are a member of `tenantId`.
 * Returns the userId + role on success; throws OnboardingError on
 * either failure (mapped to 401/403 by the route layer).
 */
export async function requireOnboardingAuth(
  tenantId: string,
): Promise<OnboardingAuth> {
  if (!tenantId || typeof tenantId !== "string") {
    throw new OnboardingError("invalid_input", "tenantId is required");
  }
  const session = await auth();
  const userId = session?.user?.id;
  if (!userId) {
    throw new OnboardingError(
      "unauthenticated",
      "Sign in to continue the wizard. Use the magic-link signin page.",
    );
  }
  const membership = await prisma.membership.findUnique({
    where: { userId_tenantId: { userId, tenantId } },
    select: { role: true },
  });
  if (!membership) {
    throw new OnboardingError(
      "forbidden",
      "You are not a member of this tenant. Sign in with the email you used at checkout.",
    );
  }
  return { userId, tenantId, role: membership.role };
}

/**
 * Like requireOnboardingAuth but only succeeds for owner-role
 * callers. Used by the wizard's complete step so non-owners can't
 * mark a tenant as "fully onboarded".
 */
export async function requireOnboardingOwner(
  tenantId: string,
): Promise<OnboardingAuth> {
  const auth_ = await requireOnboardingAuth(tenantId);
  if (auth_.role !== "owner") {
    throw new OnboardingError(
      "forbidden",
      "Only the tenant owner can complete the wizard.",
    );
  }
  return auth_;
}

/**
 * Optional-auth variant for the redeem route. Returns the userId
 * when signed in, or null when the caller is anonymous. The redeem
 * endpoint then redirects to the signin page when null (carrying
 * the session_id through as the callback).
 */
export async function getOptionalOnboardingUser(): Promise<string | null> {
  const session = await auth();
  return session?.user?.id ?? null;
}
