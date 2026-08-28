import { randomUUID } from "node:crypto";
import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import {
  hasPlatformCapability,
  isPlatformRole,
  type PlatformCapability,
  type PlatformRole,
} from "@/lib/platform-capabilities";

export interface PlatformRequest {
  userId: string;
  userEmail: string | null;
  role: PlatformRole;
}

/**
 * Authorize a server-rendered HQ entry point and write an operator-access event.
 * Tenant membership is deliberately not consulted: clinic roles never imply
 * company-wide access. Denied users receive a 404 to avoid disclosing HQ.
 */
export async function requirePlatformPage(
  capability: PlatformCapability,
  targetType: "hq_dashboard" | "hq_leads",
): Promise<PlatformRequest> {
  const session = await auth();
  if (!session?.user?.id) {
    redirect(`/login?callbackUrl=${targetType === "hq_dashboard" ? "/hq" : "/hq/leads"}`);
  }

  const platformRole = await prisma.platformUserRole.findUnique({
    where: { userId: session.user.id },
    select: { role: true, active: true },
  });

  if (
    !platformRole ||
    !hasPlatformCapability(platformRole.role, platformRole.active, capability) ||
    !isPlatformRole(platformRole.role)
  ) {
    notFound();
  }

  const requestId = randomUUID();
  await prisma.platformAuditEvent.create({
    data: {
      actorUserId: session.user.id,
      actorRole: platformRole.role,
      action: "read",
      targetType,
      requestId,
      metadataJson: JSON.stringify({ capability }),
    },
  });

  return {
    userId: session.user.id,
    userEmail: session.user.email ?? null,
    role: platformRole.role,
  };
}
