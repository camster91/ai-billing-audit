import { z } from "zod";
import { prisma } from "@/lib/prisma";
import type { PlatformRequest } from "@/lib/platform-auth";
import {
  canTransitionLead,
  LEAD_QUALIFICATION_STATUSES,
  LEAD_STAGES,
} from "@/lib/lead-workflow-rules";

const prohibitedClinicalContent =
  /\b(patient|diagnos(?:is|es)|date of birth|dob|personal health number|clinical note|medical record|encounter id)\b/i;

const optionalText = (max: number) =>
  z
    .string()
    .trim()
    .max(max)
    .nullable()
    .transform((value) => (value && value.length > 0 ? value : null));

export const leadMutationSchema = z
  .object({
    expectedVersion: z.number().int().nonnegative(),
    mutationId: z.string().uuid(),
    status: z.enum(LEAD_STAGES),
    ownerUserId: optionalText(128),
    nextAction: optionalText(240),
    nextActionAt: z.string().datetime().nullable(),
    lostReason: optionalText(300),
    qualificationStatus: z.enum(LEAD_QUALIFICATION_STATUSES),
    qualificationReason: optionalText(500),
    qualificationEvidenceRef: optionalText(500),
    logContactNow: z.boolean().default(false),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.nextAction && prohibitedClinicalContent.test(value.nextAction)) {
      context.addIssue({
        code: "custom",
        path: ["nextAction"],
        message: "Use commercial next steps only; do not enter clinical or patient information.",
      });
    }
    if (value.qualificationReason && prohibitedClinicalContent.test(value.qualificationReason)) {
      context.addIssue({
        code: "custom",
        path: ["qualificationReason"],
        message: "Use commercial qualification context only; do not enter clinical or patient information.",
      });
    }
    if (value.qualificationEvidenceRef && prohibitedClinicalContent.test(value.qualificationEvidenceRef)) {
      context.addIssue({
        code: "custom",
        path: ["qualificationEvidenceRef"],
        message: "Use a business evidence reference only; do not enter clinical or patient information.",
      });
    }
    if (value.qualificationStatus === "unreviewed" && (value.qualificationReason || value.qualificationEvidenceRef)) {
      context.addIssue({
        code: "custom",
        path: ["qualificationStatus"],
        message: "Unreviewed leads cannot have a qualification decision.",
      });
    }
    if (value.qualificationStatus !== "unreviewed" && !value.qualificationReason) {
      context.addIssue({
        code: "custom",
        path: ["qualificationReason"],
        message: "Record a commercial rationale for the qualification decision.",
      });
    }
    if (value.status === "lost" && !value.lostReason) {
      context.addIssue({ code: "custom", path: ["lostReason"], message: "A loss reason is required." });
    }
    if (value.status !== "lost" && value.lostReason) {
      context.addIssue({ code: "custom", path: ["lostReason"], message: "Loss reason is only valid for lost leads." });
    }
    if ((value.status === "lost" || value.status === "pilot_signed") && (value.nextAction || value.nextActionAt)) {
      context.addIssue({ code: "custom", path: ["nextAction"], message: "Closed lead stages cannot have a next action." });
    }
    if (Boolean(value.nextAction) !== Boolean(value.nextActionAt)) {
      context.addIssue({ code: "custom", path: ["nextActionAt"], message: "Next action and due date must be set or cleared together." });
    }
  });

export type LeadMutationInput = z.infer<typeof leadMutationSchema>;

export class LeadWorkflowError extends Error {
  constructor(
    public readonly code: "lead_not_found" | "invalid_transition" | "invalid_owner" | "no_changes" | "version_conflict" | "idempotency_conflict",
    message: string,
  ) {
    super(message);
  }
}

function dateValue(value: Date | null): string | null {
  return value?.toISOString() ?? null;
}

export async function updateLeadWorkflow(
  leadId: string,
  input: LeadMutationInput,
  operator: PlatformRequest,
  now = new Date(),
) {
  const existingAudit = await prisma.platformAuditEvent.findUnique({
    where: { requestId: input.mutationId },
    select: { action: true, targetType: true, targetId: true },
  });
  if (existingAudit) {
    if (
      existingAudit.action !== "lead_updated" ||
      existingAudit.targetType !== "lead" ||
      existingAudit.targetId !== leadId
    ) {
      throw new LeadWorkflowError("idempotency_conflict", "Mutation id belongs to another operation.");
    }
    return prisma.lead.findUniqueOrThrow({ where: { id: leadId } });
  }

  const prior = await prisma.lead.findUnique({
    where: { id: leadId },
    select: {
      id: true,
      status: true,
      ownerUserId: true,
      nextAction: true,
      nextActionAt: true,
      lostReason: true,
      qualificationStatus: true,
      qualificationReason: true,
      qualificationEvidenceRef: true,
      qualificationReviewedAt: true,
      lastContactedAt: true,
      version: true,
    },
  });
  if (!prior) throw new LeadWorkflowError("lead_not_found", "Lead not found.");
  if (!canTransitionLead(prior.status, input.status)) {
    throw new LeadWorkflowError("invalid_transition", `Cannot move lead from ${prior.status} to ${input.status}.`);
  }

  if (input.ownerUserId) {
    const owner = await prisma.platformUserRole.findFirst({
      where: { userId: input.ownerUserId, active: true, role: { in: ["owner", "sales"] } },
      select: { id: true },
    });
    if (!owner) throw new LeadWorkflowError("invalid_owner", "Lead owner must be an active owner or sales operator.");
  }

  const nextActionAt = input.nextActionAt ? new Date(input.nextActionAt) : null;
  const changes: Array<{ kind: string; fromValue: string | null; toValue: string | null }> = [];
  if (prior.status !== input.status) changes.push({ kind: "stage_changed", fromValue: prior.status, toValue: input.status });
  if (prior.ownerUserId !== input.ownerUserId) changes.push({ kind: "assignment_changed", fromValue: prior.ownerUserId, toValue: input.ownerUserId });
  if (prior.nextAction !== input.nextAction || dateValue(prior.nextActionAt) !== dateValue(nextActionAt)) {
    changes.push({
      kind: "next_action_changed",
      fromValue: JSON.stringify({ action: prior.nextAction, dueAt: dateValue(prior.nextActionAt) }),
      toValue: JSON.stringify({ action: input.nextAction, dueAt: dateValue(nextActionAt) }),
    });
  }
  if (prior.lostReason !== input.lostReason) changes.push({ kind: "lost_reason_changed", fromValue: prior.lostReason, toValue: input.lostReason });
  const qualificationChanged =
    prior.qualificationStatus !== input.qualificationStatus ||
    prior.qualificationReason !== input.qualificationReason ||
    prior.qualificationEvidenceRef !== input.qualificationEvidenceRef;
  if (qualificationChanged) {
    changes.push({
      kind: "qualification_changed",
      fromValue: JSON.stringify({
        status: prior.qualificationStatus,
        reason: prior.qualificationReason,
        evidenceRef: prior.qualificationEvidenceRef,
      }),
      toValue: JSON.stringify({
        status: input.qualificationStatus,
        reason: input.qualificationReason,
        evidenceRef: input.qualificationEvidenceRef,
      }),
    });
  }
  if (input.logContactNow) changes.push({ kind: "contact_logged", fromValue: dateValue(prior.lastContactedAt), toValue: now.toISOString() });
  if (changes.length === 0) throw new LeadWorkflowError("no_changes", "No lead changes were supplied.");

  return prisma.$transaction(async (tx) => {
    const updated = await tx.lead.updateMany({
      where: { id: leadId, version: input.expectedVersion },
      data: {
        status: input.status,
        ownerUserId: input.ownerUserId,
        nextAction: input.nextAction,
        nextActionAt,
        lostReason: input.lostReason,
        qualificationStatus: input.qualificationStatus,
        qualificationReason: input.qualificationReason,
        qualificationEvidenceRef: input.qualificationEvidenceRef,
        ...(qualificationChanged ? { qualificationReviewedAt: now } : {}),
        ...(input.logContactNow ? { lastContactedAt: now } : {}),
        version: { increment: 1 },
      },
    });
    if (updated.count !== 1) {
      throw new LeadWorkflowError("version_conflict", "Lead changed after this form was loaded.");
    }

    await tx.leadActivity.createMany({
      data: changes.map((change) => ({
        leadId,
        actorUserId: operator.userId,
        actorRole: operator.role,
        mutationId: input.mutationId,
        ...change,
      })),
    });
    await tx.platformAuditEvent.create({
      data: {
        actorUserId: operator.userId,
        actorRole: operator.role,
        action: "lead_updated",
        targetType: "lead",
        targetId: leadId,
        requestId: input.mutationId,
        metadataJson: JSON.stringify({ changedFields: changes.map((change) => change.kind) }),
      },
    });
    return tx.lead.findUniqueOrThrow({ where: { id: leadId } });
  });
}
