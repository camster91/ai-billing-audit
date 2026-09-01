import { z } from "zod";
import { prisma } from "@/lib/prisma";
import type { PlatformRequest } from "@/lib/platform-auth";
import { SUPPORT_CATEGORIES, SUPPORT_SEVERITIES, SUPPORT_STATUSES } from "@/lib/support-case-rules";

const prohibitedSensitiveContent =
  /\b(patient|diagnos(?:is|es)|date of birth|dob|personal health number|phn|medical record|clinical note|encounter|claim|procedure|medication)\b/i;
const optionalText = (max: number) => z.string().trim().max(max).nullable().transform((value) => value || null);
const safeSummary = z.string().trim().min(5).max(500).refine((value) => !prohibitedSensitiveContent.test(value), {
  message: "Describe the operating issue without patient, claim, or clinical information.",
});

export const createSupportCaseSchema = z.object({
  mutationId: z.string().uuid(),
  engagementId: z.string().trim().min(1).max(128),
  category: z.enum(SUPPORT_CATEGORIES),
  severity: z.enum(SUPPORT_SEVERITIES),
  safeSummary,
  ownerUserId: optionalText(128),
  dueAt: z.string().datetime().nullable(),
}).strict();

export const supportCaseMutationSchema = z.object({
  expectedVersion: z.number().int().nonnegative(),
  mutationId: z.string().uuid(),
  category: z.enum(SUPPORT_CATEGORIES),
  severity: z.enum(SUPPORT_SEVERITIES),
  status: z.enum(SUPPORT_STATUSES),
  safeSummary,
  ownerUserId: optionalText(128),
  dueAt: z.string().datetime().nullable(),
  linkedIssueReference: optionalText(180),
}).strict().superRefine((value, context) => {
  if (value.linkedIssueReference && prohibitedSensitiveContent.test(value.linkedIssueReference)) {
    context.addIssue({ code: "custom", path: ["linkedIssueReference"], message: "Link only a no-PHI product or company issue." });
  }
});

export type CreateSupportCaseInput = z.infer<typeof createSupportCaseSchema>;
export type SupportCaseMutationInput = z.infer<typeof supportCaseMutationSchema>;

export class SupportCaseError extends Error {
  constructor(
    public readonly code: "engagement_not_found" | "case_not_found" | "invalid_owner" | "no_changes" | "version_conflict" | "idempotency_conflict",
    message: string,
  ) {
    super(message);
  }
}

async function assertSupportOwner(ownerUserId: string | null) {
  if (!ownerUserId) return;
  const owner = await prisma.platformUserRole.findFirst({
    where: { userId: ownerUserId, active: true, role: { in: ["owner", "client_success", "support"] } },
    select: { id: true },
  });
  if (!owner) throw new SupportCaseError("invalid_owner", "Case owner must be an active owner, client-success, or support operator.");
}

function dateValue(value: Date | null): string | null {
  return value?.toISOString() ?? null;
}

export async function createSupportCase(input: CreateSupportCaseInput, operator: PlatformRequest) {
  const existingAudit = await prisma.platformAuditEvent.findUnique({
    where: { requestId: input.mutationId },
    select: { action: true, targetType: true, targetId: true },
  });
  if (existingAudit) {
    if (existingAudit.action !== "support_case_created" || existingAudit.targetType !== "support_case" || !existingAudit.targetId) {
      throw new SupportCaseError("idempotency_conflict", "Mutation id belongs to another operation.");
    }
    return prisma.supportCase.findUniqueOrThrow({ where: { id: existingAudit.targetId } });
  }
  if (!(await prisma.clientEngagement.findUnique({ where: { id: input.engagementId }, select: { id: true } }))) {
    throw new SupportCaseError("engagement_not_found", "Client engagement not found.");
  }
  await assertSupportOwner(input.ownerUserId);

  return prisma.$transaction(async (tx) => {
    const supportCase = await tx.supportCase.create({
      data: {
        engagementId: input.engagementId,
        category: input.category,
        severity: input.severity,
        safeSummary: input.safeSummary,
        ownerUserId: input.ownerUserId,
        dueAt: input.dueAt ? new Date(input.dueAt) : null,
      },
    });
    await tx.supportActivity.create({
      data: { caseId: supportCase.id, actorUserId: operator.userId, actorRole: operator.role, kind: "created", mutationId: input.mutationId, changesJson: JSON.stringify({ changedFields: ["category", "severity", "safeSummary", "owner", "dueAt"] }) },
    });
    await tx.platformAuditEvent.create({
      data: { actorUserId: operator.userId, actorRole: operator.role, action: "support_case_created", targetType: "support_case", targetId: supportCase.id, requestId: input.mutationId, metadataJson: JSON.stringify({ engagementId: input.engagementId }) },
    });
    return supportCase;
  });
}

export async function updateSupportCase(caseId: string, input: SupportCaseMutationInput, operator: PlatformRequest, now = new Date()) {
  const existingAudit = await prisma.platformAuditEvent.findUnique({
    where: { requestId: input.mutationId },
    select: { action: true, targetType: true, targetId: true },
  });
  if (existingAudit) {
    if (existingAudit.action !== "support_case_updated" || existingAudit.targetType !== "support_case" || existingAudit.targetId !== caseId) {
      throw new SupportCaseError("idempotency_conflict", "Mutation id belongs to another operation.");
    }
    return prisma.supportCase.findUniqueOrThrow({ where: { id: caseId } });
  }
  const prior = await prisma.supportCase.findUnique({ where: { id: caseId } });
  if (!prior) throw new SupportCaseError("case_not_found", "Support case not found.");
  await assertSupportOwner(input.ownerUserId);
  const dueAt = input.dueAt ? new Date(input.dueAt) : null;
  const changes = {
    category: prior.category !== input.category,
    severity: prior.severity !== input.severity,
    status: prior.status !== input.status,
    safeSummary: prior.safeSummary !== input.safeSummary,
    owner: prior.ownerUserId !== input.ownerUserId,
    dueAt: dateValue(prior.dueAt) !== dateValue(dueAt),
    linkedIssueReference: prior.linkedIssueReference !== input.linkedIssueReference,
  };
  const changedFields = Object.entries(changes).filter(([, changed]) => changed).map(([field]) => field);
  if (changedFields.length === 0) throw new SupportCaseError("no_changes", "No support-case changes were supplied.");

  return prisma.$transaction(async (tx) => {
    const updated = await tx.supportCase.updateMany({
      where: { id: caseId, version: input.expectedVersion },
      data: {
        category: input.category,
        severity: input.severity,
        status: input.status,
        safeSummary: input.safeSummary,
        ownerUserId: input.ownerUserId,
        dueAt,
        linkedIssueReference: input.linkedIssueReference,
        acknowledgedAt: input.status === "new" ? null : prior.acknowledgedAt ?? now,
        resolvedAt: ["resolved", "closed"].includes(input.status) ? prior.resolvedAt ?? now : null,
        version: { increment: 1 },
      },
    });
    if (updated.count !== 1) throw new SupportCaseError("version_conflict", "Support case changed after this form was loaded.");
    await tx.supportActivity.create({
      data: { caseId, actorUserId: operator.userId, actorRole: operator.role, kind: "updated", mutationId: input.mutationId, changesJson: JSON.stringify({ changedFields }) },
    });
    await tx.platformAuditEvent.create({
      data: { actorUserId: operator.userId, actorRole: operator.role, action: "support_case_updated", targetType: "support_case", targetId: caseId, requestId: input.mutationId, metadataJson: JSON.stringify({ changedFields }) },
    });
    return tx.supportCase.findUniqueOrThrow({ where: { id: caseId } });
  });
}
