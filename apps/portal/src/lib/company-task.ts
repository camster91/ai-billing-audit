import { z } from "zod";
import { prisma } from "@/lib/prisma";
import type { PlatformRequest } from "@/lib/platform-auth";
import { COMPANY_TASK_PRIORITIES, COMPANY_TASK_STATUSES } from "@/lib/company-task-rules";

const prohibitedSensitiveContent =
  /\b(patient|diagnos(?:is|es)|date of birth|dob|personal health number|phn|medical record|clinical note|encounter|claim|procedure|medication)\b/i;
const optionalText = (max: number) =>
  z.string().trim().max(max).nullable().transform((value) => value || null);

export const companyTaskMutationSchema = z
  .object({
    expectedVersion: z.number().int().nonnegative(),
    mutationId: z.string().uuid(),
    status: z.enum(COMPANY_TASK_STATUSES),
    priority: z.enum(COMPANY_TASK_PRIORITIES),
    ownerUserId: optionalText(128),
    dueAt: z.string().datetime().nullable(),
    evidenceReference: optionalText(180),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.evidenceReference && prohibitedSensitiveContent.test(value.evidenceReference)) {
      context.addIssue({
        code: "custom",
        path: ["evidenceReference"],
        message: "Reference business evidence only; do not enter clinical information.",
      });
    }
  });

export type CompanyTaskMutationInput = z.infer<typeof companyTaskMutationSchema>;

export const createCompanyTaskSchema = z
  .object({
    mutationId: z.string().uuid(),
    title: z.string().trim().min(3).max(120),
    priority: z.enum(COMPANY_TASK_PRIORITIES),
    ownerUserId: optionalText(128),
    dueAt: z.string().datetime().nullable(),
  })
  .strict()
  .superRefine((value, context) => {
    if (prohibitedSensitiveContent.test(value.title)) {
      context.addIssue({
        code: "custom",
        path: ["title"],
        message: "Describe company work only; do not enter clinical information.",
      });
    }
  });

export type CreateCompanyTaskInput = z.infer<typeof createCompanyTaskSchema>;

export class CompanyTaskError extends Error {
  constructor(
    public readonly code: "engagement_not_found" | "task_not_found" | "invalid_owner" | "no_changes" | "version_conflict" | "idempotency_conflict",
    message: string,
  ) {
    super(message);
  }
}

async function assertTaskOwner(ownerUserId: string | null) {
  if (!ownerUserId) return;
  const owner = await prisma.platformUserRole.findFirst({
    where: { userId: ownerUserId, active: true, role: { in: ["owner", "client_success"] } },
    select: { id: true },
  });
  if (!owner) throw new CompanyTaskError("invalid_owner", "Task owner must be an active owner or client-success operator.");
}

export async function createCompanyTask(
  engagementId: string,
  input: CreateCompanyTaskInput,
  operator: PlatformRequest,
) {
  const existingAudit = await prisma.platformAuditEvent.findUnique({
    where: { requestId: input.mutationId },
    select: { action: true, targetType: true, targetId: true },
  });
  if (existingAudit) {
    if (
      existingAudit.action !== "company_task_created" ||
      existingAudit.targetType !== "company_task" ||
      !existingAudit.targetId
    ) {
      throw new CompanyTaskError("idempotency_conflict", "Mutation id belongs to another operation.");
    }
    const task = await prisma.companyTask.findFirst({ where: { id: existingAudit.targetId, engagementId } });
    if (!task) throw new CompanyTaskError("idempotency_conflict", "Mutation id belongs to another engagement.");
    return task;
  }
  if (!(await prisma.clientEngagement.findUnique({ where: { id: engagementId }, select: { id: true } }))) {
    throw new CompanyTaskError("engagement_not_found", "Client engagement not found.");
  }
  await assertTaskOwner(input.ownerUserId);

  return prisma.$transaction(async (tx) => {
    const task = await tx.companyTask.create({
      data: {
        engagementId,
        title: input.title,
        priority: input.priority,
        ownerUserId: input.ownerUserId,
        dueAt: input.dueAt ? new Date(input.dueAt) : null,
      },
    });
    await tx.platformAuditEvent.create({
      data: {
        actorUserId: operator.userId,
        actorRole: operator.role,
        action: "company_task_created",
        targetType: "company_task",
        targetId: task.id,
        requestId: input.mutationId,
        metadataJson: JSON.stringify({ engagementId }),
      },
    });
    return task;
  });
}

function dateValue(value: Date | null): string | null {
  return value?.toISOString() ?? null;
}

export async function updateCompanyTask(
  engagementId: string,
  taskId: string,
  input: CompanyTaskMutationInput,
  operator: PlatformRequest,
  now = new Date(),
) {
  const existingAudit = await prisma.platformAuditEvent.findUnique({
    where: { requestId: input.mutationId },
    select: { action: true, targetType: true, targetId: true },
  });
  if (existingAudit) {
    if (existingAudit.action !== "company_task_updated" || existingAudit.targetType !== "company_task" || existingAudit.targetId !== taskId) {
      throw new CompanyTaskError("idempotency_conflict", "Mutation id belongs to another operation.");
    }
    const replayTask = await prisma.companyTask.findFirst({ where: { id: taskId, engagementId } });
    if (!replayTask) {
      throw new CompanyTaskError("idempotency_conflict", "Mutation id belongs to another engagement.");
    }
    return replayTask;
  }

  const prior = await prisma.companyTask.findFirst({ where: { id: taskId, engagementId } });
  if (!prior) throw new CompanyTaskError("task_not_found", "Company task not found.");
  await assertTaskOwner(input.ownerUserId);

  const dueAt = input.dueAt ? new Date(input.dueAt) : null;
  const changes = {
    status: prior.status !== input.status,
    priority: prior.priority !== input.priority,
    owner: prior.ownerUserId !== input.ownerUserId,
    dueAt: dateValue(prior.dueAt) !== dateValue(dueAt),
    evidenceReference: prior.evidenceReference !== input.evidenceReference,
  };
  const changedFields = Object.entries(changes).filter(([, changed]) => changed).map(([field]) => field);
  if (changedFields.length === 0) throw new CompanyTaskError("no_changes", "No company-task changes were supplied.");

  return prisma.$transaction(async (tx) => {
    const updated = await tx.companyTask.updateMany({
      where: { id: taskId, engagementId, version: input.expectedVersion },
      data: {
        status: input.status,
        priority: input.priority,
        ownerUserId: input.ownerUserId,
        dueAt,
        evidenceReference: input.evidenceReference,
        completedAt: input.status === "done" ? prior.completedAt ?? now : null,
        version: { increment: 1 },
      },
    });
    if (updated.count !== 1) throw new CompanyTaskError("version_conflict", "Task changed after this form was loaded.");
    await tx.platformAuditEvent.create({
      data: {
        actorUserId: operator.userId,
        actorRole: operator.role,
        action: "company_task_updated",
        targetType: "company_task",
        targetId: taskId,
        requestId: input.mutationId,
        metadataJson: JSON.stringify({ engagementId, changedFields }),
      },
    });
    return tx.companyTask.findUniqueOrThrow({ where: { id: taskId } });
  });
}
