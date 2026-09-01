import { z } from "zod";
import { prisma } from "@/lib/prisma";
import type { PlatformRequest } from "@/lib/platform-auth";

const prohibitedSensitiveContent =
  /\b(patient|diagnos(?:is|es)|date of birth|dob|personal health number|phn|medical record|clinical note|encounter|claim|procedure|medication)\b/i;

const optionalBusinessText = (max: number) =>
  z.string().trim().max(max).nullable().transform((value) => value || null);

export const createClientEngagementSchema = z
  .object({
    mutationId: z.string().uuid(),
    ownerUserId: optionalBusinessText(128),
    offerReference: optionalBusinessText(120),
    pilotStartAt: z.string().datetime().nullable(),
    pilotEndAt: z.string().datetime().nullable(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.offerReference && prohibitedSensitiveContent.test(value.offerReference)) {
      context.addIssue({
        code: "custom",
        path: ["offerReference"],
        message: "Use an approved commercial artifact reference only; do not enter clinical information.",
      });
    }
    if (value.pilotStartAt && value.pilotEndAt && value.pilotEndAt <= value.pilotStartAt) {
      context.addIssue({
        code: "custom",
        path: ["pilotEndAt"],
        message: "Pilot end must be after pilot start.",
      });
    }
  });

export type CreateClientEngagementInput = z.infer<typeof createClientEngagementSchema>;

export class ClientEngagementError extends Error {
  constructor(
    public readonly code:
      | "lead_not_found"
      | "lead_not_approved"
      | "invalid_owner"
      | "engagement_exists"
      | "idempotency_conflict",
    message: string,
  ) {
    super(message);
  }
}

const DEFAULT_ONBOARDING_TASKS = [
  "Confirm approved pilot offer",
  "Record privacy and data approvals",
  "Confirm onboarding owner and timeline",
  "Verify first reviewed audit milestone",
] as const;

export async function createClientEngagement(
  leadId: string,
  input: CreateClientEngagementInput,
  operator: PlatformRequest,
) {
  const existingAudit = await prisma.platformAuditEvent.findUnique({
    where: { requestId: input.mutationId },
    select: { action: true, targetType: true, targetId: true },
  });
  if (existingAudit) {
    if (
      existingAudit.action !== "client_engagement_created" ||
      existingAudit.targetType !== "client_engagement" ||
      !existingAudit.targetId
    ) {
      throw new ClientEngagementError("idempotency_conflict", "Mutation id belongs to another operation.");
    }
    return prisma.clientEngagement.findUniqueOrThrow({
      where: { id: existingAudit.targetId },
      include: { tasks: { orderBy: { createdAt: "asc" } } },
    });
  }

  const lead = await prisma.lead.findUnique({
    where: { id: leadId },
    select: { id: true, clinicName: true, status: true, engagement: { select: { id: true } } },
  });
  if (!lead) throw new ClientEngagementError("lead_not_found", "Lead not found.");
  if (lead.engagement) throw new ClientEngagementError("engagement_exists", "Lead already has a client engagement.");
  if (lead.status !== "pilot_signed") {
    throw new ClientEngagementError("lead_not_approved", "Only a pilot-signed lead can become a client engagement.");
  }

  if (input.ownerUserId) {
    const owner = await prisma.platformUserRole.findFirst({
      where: { userId: input.ownerUserId, active: true, role: { in: ["owner", "client_success"] } },
      select: { id: true },
    });
    if (!owner) {
      throw new ClientEngagementError("invalid_owner", "Client owner must be an active owner or client-success operator.");
    }
  }

  return prisma.$transaction(async (tx) => {
    const engagement = await tx.clientEngagement.create({
      data: {
        leadId,
        clinicName: lead.clinicName,
        ownerUserId: input.ownerUserId,
        offerReference: input.offerReference,
        pilotStartAt: input.pilotStartAt ? new Date(input.pilotStartAt) : null,
        pilotEndAt: input.pilotEndAt ? new Date(input.pilotEndAt) : null,
        tasks: {
          create: DEFAULT_ONBOARDING_TASKS.map((title) => ({ title })),
        },
      },
    });
    await tx.platformAuditEvent.create({
      data: {
        actorUserId: operator.userId,
        actorRole: operator.role,
        action: "client_engagement_created",
        targetType: "client_engagement",
        targetId: engagement.id,
        requestId: input.mutationId,
        metadataJson: JSON.stringify({ leadId, taskCount: DEFAULT_ONBOARDING_TASKS.length }),
      },
    });
    return tx.clientEngagement.findUniqueOrThrow({
      where: { id: engagement.id },
      include: { tasks: { orderBy: { createdAt: "asc" } } },
    });
  });
}
