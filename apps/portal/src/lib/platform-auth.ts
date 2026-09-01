import { randomUUID } from "node:crypto";
import { notFound, redirect } from "next/navigation";
import { NextResponse } from "next/server";
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

async function resolvePlatformRequest(
  capability: PlatformCapability,
): Promise<
  | { ok: true; request: PlatformRequest }
  | { ok: false; reason: "unauthenticated" | "forbidden" }
> {
  const session = await auth();
  if (!session?.user?.id) return { ok: false, reason: "unauthenticated" };

  const platformRole = await prisma.platformUserRole.findUnique({
    where: { userId: session.user.id },
    select: { role: true, active: true },
  });
  if (
    !platformRole ||
    !hasPlatformCapability(platformRole.role, platformRole.active, capability) ||
    !isPlatformRole(platformRole.role)
  ) {
    return { ok: false, reason: "forbidden" };
  }
  return {
    ok: true,
    request: {
      userId: session.user.id,
      userEmail: session.user.email ?? null,
      role: platformRole.role,
    },
  };
}

/**
 * Authorize a server-rendered HQ entry point and write an operator-access event.
 * Tenant membership is deliberately not consulted: clinic roles never imply
 * company-wide access. Denied users receive a 404 to avoid disclosing HQ.
 */
export async function requirePlatformPage(
  capability: PlatformCapability,
  targetType: "hq_dashboard" | "hq_leads" | "hq_lead_detail" | "hq_clients" | "hq_client_detail",
): Promise<PlatformRequest> {
  const result = await resolvePlatformRequest(capability);
  if (!result.ok && result.reason === "unauthenticated") {
    const callbackUrl = targetType === "hq_dashboard"
      ? "/hq"
      : targetType === "hq_clients" || targetType === "hq_client_detail"
        ? "/hq/clients"
        : "/hq/leads";
    redirect(`/login?callbackUrl=${callbackUrl}`);
  }
  if (!result.ok) notFound();

  const requestId = randomUUID();
  await prisma.platformAuditEvent.create({
    data: {
      actorUserId: result.request.userId,
      actorRole: result.request.role,
      action: "read",
      targetType,
      requestId,
      metadataJson: JSON.stringify({ capability }),
    },
  });

  return result.request;
}

export async function requirePlatformApi(
  capability: PlatformCapability,
): Promise<
  | { ok: true; request: PlatformRequest }
  | { ok: false; response: NextResponse }
> {
  const result = await resolvePlatformRequest(capability);
  if (result.ok) return result;
  return {
    ok: false,
    response: NextResponse.json(
      { error: result.reason },
      { status: result.reason === "unauthenticated" ? 401 : 403 },
    ),
  };
}
