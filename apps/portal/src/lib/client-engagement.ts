import { z } from "zod";
import { prisma } from "@/lib/prisma";
import type { PlatformRequest } from "@/lib/platform-auth";
import {
  CLIENT_ENGAGEMENT_STATUSES,
  CLIENT_HEALTH_STATUSES,
  PRIVACY_APPROVAL_STATUSES,
} from "@/lib/client-engagement-rules";

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

export const clientEngagementMutationSchema = z
  .object({
    expectedVersion: z.number().int().nonnegative(),
    mutationId: z.string().uuid(),
    status: z.enum(CLIENT_ENGAGEMENT_STATUSES),
    privacyApprovalStatus: z.enum(PRIVACY_APPROVAL_STATUSES),
    firstValueAt: z.string().datetime().nullable(),
    healthStatus: z.enum(CLIENT_HEALTH_STATUSES),
  })
  .strict();

export type ClientEngagementMutationInput = z.infer<typeof clientEngagementMutationSchema>;

export class ClientEngagementError extends Error {
  constructor(
    public readonly code:
      | "lead_not_found"
      | "lead_not_approved"
      | "invalid_owner"
      | "engagement_exists"
      | "engagement_not_found"
      | "no_changes"
      | "version_conflict"
      | "idempotency_conflict",
    message: string,
  ) {
    super(message);
  }
}

function dateValue(value: Date | null): string | null {
  return value?.toISOString() ?? null;
}

export async function updateClientEngagement(
  engagementId: string,
  input: ClientEngagementMutationInput,
  operator: PlatformRequest,
) {
  const existingAudit = await prisma.platformAuditEvent.findUnique({
    where: { requestId: input.mutationId },
    select: { action: true, targetType: true, targetId: true },
  });
  if (existingAudit) {
    if (
      existingAudit.action !== "client_engagement_updated" ||
      existingAudit.targetType !== "client_engagement" ||
      existingAudit.targetId !== engagementId
    ) {
      throw new ClientEngagementError("idempotency_conflict", "Mutation id belongs to another operation.");
    }
    return prisma.clientEngagement.findUniqueOrThrow({ where: { id: engagementId } });
  }

  const prior = await prisma.clientEngagement.findUnique({ where: { id: engagementId } });
  if (!prior) throw new ClientEngagementError("engagement_not_found", "Client engagement not found.");
  const firstValueAt = input.firstValueAt ? new Date(input.firstValueAt) : null;
  const changes = {
    status: prior.status !== input.status,
    privacyApprovalStatus: prior.privacyApprovalStatus !== input.privacyApprovalStatus,
    firstValueAt: dateValue(prior.firstValueAt) !== dateValue(firstValueAt),
    healthStatus: prior.healthStatus !== input.healthStatus,
  };
  const changedFields = Object.entries(changes).filter(([, changed]) => changed).map(([field]) => field);
  if (changedFields.length === 0) {
    throw new ClientEngagementError("no_changes", "No engagement milestone changes were supplied.");
  }

  return prisma.$transaction(async (tx) => {
    const updated = await tx.clientEngagement.updateMany({
      where: { id: engagementId, version: input.expectedVersion },
      data: {
        status: input.status,
        privacyApprovalStatus: input.privacyApprovalStatus,
        firstValueAt,
        healthStatus: input.healthStatus,
        version: { increment: 1 },
      },
    });
    if (updated.count !== 1) {
      throw new ClientEngagementError("version_conflict", "Engagement changed after this form was loaded.");
    }
    await tx.platformAuditEvent.create({
      data: {
        actorUserId: operator.userId,
        actorRole: operator.role,
        action: "client_engagement_updated",
        targetType: "client_engagement",
        targetId: engagementId,
        requestId: input.mutationId,
        metadataJson: JSON.stringify({ changedFields }),
      },
    });
    return tx.clientEngagement.findUniqueOrThrow({ where: { id: engagementId } });
  });
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
