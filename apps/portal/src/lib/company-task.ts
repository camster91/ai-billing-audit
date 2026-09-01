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

export class CompanyTaskError extends Error {
  constructor(
    public readonly code: "task_not_found" | "invalid_owner" | "no_changes" | "version_conflict" | "idempotency_conflict",
    message: string,
  ) {
    super(message);
  }
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
  if (input.ownerUserId) {
    const owner = await prisma.platformUserRole.findFirst({
      where: { userId: input.ownerUserId, active: true, role: { in: ["owner", "client_success"] } },
      select: { id: true },
    });
    if (!owner) throw new CompanyTaskError("invalid_owner", "Task owner must be an active owner or client-success operator.");
  }

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
