import { z } from "zod";
import type { Prisma } from "@/generated/prisma/client";
import { prisma } from "@/lib/prisma";
import type { PlatformRequest } from "@/lib/platform-auth";
import { CLAIM_EVIDENCE_TYPES, CLAIM_STATUSES, CONTENT_ASSET_TYPES, CONTENT_CHANNELS, CONTENT_STATUSES, MARKETING_SURFACES } from "@/lib/marketing-rules";

const prohibitedSensitiveContent = /\b(patient|date of birth|dob|personal health number|phn|medical record|clinical note)\b/i;
const optionalText = (max: number) => z.string().trim().max(max).nullable().transform((value) => value || null);
const safeText = (min: number, max: number) => z.string().trim().min(min).max(max).refine((value) => !prohibitedSensitiveContent.test(value), { message: "Do not include patient or clinical-record information." });

export const createClaimSchema = z.object({
  mutationId: z.string().uuid(), exactClaim: safeText(5, 500), evidenceType: z.enum(CLAIM_EVIDENCE_TYPES),
  evidenceReference: optionalText(240), customerPermissionReference: optionalText(240),
  allowedSurfaces: z.array(z.enum(MARKETING_SURFACES)).max(MARKETING_SURFACES.length),
  reviewAt: z.string().datetime().nullable(), expiresAt: z.string().datetime().nullable(), replacesClaimId: optionalText(128),
}).strict();

export const claimMutationSchema = createClaimSchema.omit({ mutationId: true }).extend({
  expectedVersion: z.number().int().nonnegative(), mutationId: z.string().uuid(), status: z.enum(CLAIM_STATUSES),
}).strict();

export const createContentAssetSchema = z.object({
  mutationId: z.string().uuid(), title: safeText(3, 160), assetType: z.enum(CONTENT_ASSET_TYPES), targetSegment: safeText(3, 160),
  channel: z.enum(CONTENT_CHANNELS), containsMarketingClaim: z.boolean(), claimApprovalId: optionalText(128),
  artifactReference: optionalText(240), ownerUserId: optionalText(128), plannedAt: z.string().datetime().nullable(), reviewAt: z.string().datetime().nullable(),
}).strict();

export const contentAssetMutationSchema = createContentAssetSchema.omit({ mutationId: true }).extend({
  expectedVersion: z.number().int().nonnegative(), mutationId: z.string().uuid(), status: z.enum(CONTENT_STATUSES),
}).strict();

type ClaimCreate = z.infer<typeof createClaimSchema>; type ClaimMutation = z.infer<typeof claimMutationSchema>;
type AssetCreate = z.infer<typeof createContentAssetSchema>; type AssetMutation = z.infer<typeof contentAssetMutationSchema>;

export class MarketingRegistryError extends Error {
  constructor(public readonly code: "record_not_found" | "invalid_owner" | "invalid_replacement" | "approval_requires_evidence" | "approval_requires_owner" | "claim_not_approved" | "surface_not_approved" | "no_changes" | "version_conflict" | "idempotency_conflict", message: string) { super(message); }
}

async function replay(mutationId: string, action: string, targetType: string) {
  const audit = await prisma.platformAuditEvent.findUnique({ where: { requestId: mutationId }, select: { action: true, targetType: true, targetId: true } });
  if (!audit) return null;
  if (audit.action !== action || audit.targetType !== targetType || !audit.targetId) throw new MarketingRegistryError("idempotency_conflict", "Mutation id belongs to another operation.");
  return audit.targetId;
}

async function assertMarketingOwner(ownerUserId: string | null) {
  if (!ownerUserId) return;
  const role = await prisma.platformUserRole.findFirst({ where: { userId: ownerUserId, active: true, role: { in: ["owner", "marketing"] } }, select: { id: true } });
  if (!role) throw new MarketingRegistryError("invalid_owner", "Asset owner must be an active owner or marketing operator.");
}

async function validateClaimApproval(input: ClaimCreate | ClaimMutation, status: string, operator: PlatformRequest) {
  if (input.replacesClaimId && !(await prisma.claimApproval.findUnique({ where: { id: input.replacesClaimId }, select: { id: true } }))) throw new MarketingRegistryError("invalid_replacement", "Replacement claim not found.");
  if (status !== "approved") return;
  if (operator.role !== "owner") throw new MarketingRegistryError("approval_requires_owner", "Only the accountable owner can approve a marketing claim.");
  if (!input.evidenceReference || input.allowedSurfaces.length === 0) throw new MarketingRegistryError("approval_requires_evidence", "Approved claims require evidence and at least one allowed surface.");
  if (input.evidenceType === "customer_permission" && !input.customerPermissionReference) throw new MarketingRegistryError("approval_requires_evidence", "Customer-derived claims require a written permission reference.");
}

async function writeHistory(tx: Prisma.TransactionClient, args: { recordType: string; recordId: string; action: string; mutationId: string; changedFields: string[]; operator: PlatformRequest }) {
  await tx.marketingActivity.create({ data: { recordType: args.recordType, recordId: args.recordId, actorUserId: args.operator.userId, actorRole: args.operator.role, kind: args.action, mutationId: args.mutationId, changesJson: JSON.stringify({ changedFields: args.changedFields }) } });
  await tx.platformAuditEvent.create({ data: { actorUserId: args.operator.userId, actorRole: args.operator.role, action: args.action, targetType: args.recordType, targetId: args.recordId, requestId: args.mutationId, metadataJson: JSON.stringify({ changedFields: args.changedFields }) } });
}

export async function createClaim(input: ClaimCreate, operator: PlatformRequest) {
  const replayId = await replay(input.mutationId, "marketing_claim_created", "marketing_claim"); if (replayId) return prisma.claimApproval.findUniqueOrThrow({ where: { id: replayId } });
  await validateClaimApproval(input, "draft", operator);
  return prisma.$transaction(async (tx) => {
    const claim = await tx.claimApproval.create({ data: { exactClaim: input.exactClaim, evidenceType: input.evidenceType, evidenceReference: input.evidenceReference, customerPermissionReference: input.customerPermissionReference, allowedSurfacesJson: JSON.stringify(input.allowedSurfaces), reviewAt: input.reviewAt ? new Date(input.reviewAt) : null, expiresAt: input.expiresAt ? new Date(input.expiresAt) : null, replacesClaimId: input.replacesClaimId } });
    await writeHistory(tx, { recordType: "marketing_claim", recordId: claim.id, action: "marketing_claim_created", mutationId: input.mutationId, changedFields: ["exactClaim", "evidence", "allowedSurfaces", "reviewAt", "expiresAt", "replacement"], operator }); return claim;
  });
}

export async function updateClaim(id: string, input: ClaimMutation, operator: PlatformRequest, now = new Date()) {
  const replayId = await replay(input.mutationId, "marketing_claim_updated", "marketing_claim"); if (replayId) { if (replayId !== id) throw new MarketingRegistryError("idempotency_conflict", "Mutation id belongs to another claim."); return prisma.claimApproval.findUniqueOrThrow({ where: { id } }); }
  const prior = await prisma.claimApproval.findUnique({ where: { id } }); if (!prior) throw new MarketingRegistryError("record_not_found", "Marketing claim not found.");
  await validateClaimApproval(input, input.status, operator);
  const next = { exactClaim: input.exactClaim, evidenceType: input.evidenceType, evidenceReference: input.evidenceReference, customerPermissionReference: input.customerPermissionReference, allowedSurfacesJson: JSON.stringify(input.allowedSurfaces), status: input.status, reviewAt: input.reviewAt ? new Date(input.reviewAt) : null, expiresAt: input.expiresAt ? new Date(input.expiresAt) : null, replacesClaimId: input.replacesClaimId };
  const changedFields = Object.keys(next).filter((key) => String(prior[key as keyof typeof prior] ?? "") !== String(next[key as keyof typeof next] ?? "")); if (!changedFields.length) throw new MarketingRegistryError("no_changes", "No claim changes were supplied.");
  return prisma.$transaction(async (tx) => { const result = await tx.claimApproval.updateMany({ where: { id, version: input.expectedVersion }, data: { ...next, approverUserId: input.status === "approved" ? operator.userId : null, approvedAt: input.status === "approved" ? prior.approvedAt ?? now : null, version: { increment: 1 } } }); if (result.count !== 1) throw new MarketingRegistryError("version_conflict", "Claim changed after this form was loaded."); await writeHistory(tx, { recordType: "marketing_claim", recordId: id, action: "marketing_claim_updated", mutationId: input.mutationId, changedFields, operator }); return tx.claimApproval.findUniqueOrThrow({ where: { id } }); });
}

async function validateAsset(input: AssetCreate | AssetMutation, status: string) {
  await assertMarketingOwner(input.ownerUserId);
  if (!input.containsMarketingClaim) return;
  if (!input.claimApprovalId) throw new MarketingRegistryError("claim_not_approved", "Claim-bearing assets require a linked claim record.");
  const claim = await prisma.claimApproval.findUnique({ where: { id: input.claimApprovalId }, select: { status: true, allowedSurfacesJson: true, expiresAt: true } });
  if (!claim) throw new MarketingRegistryError("claim_not_approved", "The linked claim record does not exist.");
  if (status !== "approved") return;
  if (claim.status !== "approved" || (claim.expiresAt && claim.expiresAt <= new Date())) throw new MarketingRegistryError("claim_not_approved", "The linked claim is not currently approved.");
  const surfaces = JSON.parse(claim.allowedSurfacesJson) as unknown;
  if (!Array.isArray(surfaces) || !surfaces.includes(input.channel)) throw new MarketingRegistryError("surface_not_approved", "The claim is not approved for this channel.");
}

export async function createContentAsset(input: AssetCreate, operator: PlatformRequest) {
  const replayId = await replay(input.mutationId, "content_asset_created", "content_asset"); if (replayId) return prisma.contentAsset.findUniqueOrThrow({ where: { id: replayId } }); await validateAsset(input, "draft");
  return prisma.$transaction(async (tx) => { const asset = await tx.contentAsset.create({ data: { title: input.title, assetType: input.assetType, targetSegment: input.targetSegment, channel: input.channel, containsMarketingClaim: input.containsMarketingClaim, claimApprovalId: input.claimApprovalId, artifactReference: input.artifactReference, ownerUserId: input.ownerUserId, plannedAt: input.plannedAt ? new Date(input.plannedAt) : null, reviewAt: input.reviewAt ? new Date(input.reviewAt) : null } }); await writeHistory(tx, { recordType: "content_asset", recordId: asset.id, action: "content_asset_created", mutationId: input.mutationId, changedFields: ["title", "assetType", "targetSegment", "channel", "claim", "artifact", "owner", "plannedAt", "reviewAt"], operator }); return asset; });
}

export async function updateContentAsset(id: string, input: AssetMutation, operator: PlatformRequest) {
  const replayId = await replay(input.mutationId, "content_asset_updated", "content_asset"); if (replayId) { if (replayId !== id) throw new MarketingRegistryError("idempotency_conflict", "Mutation id belongs to another asset."); return prisma.contentAsset.findUniqueOrThrow({ where: { id } }); }
  const prior = await prisma.contentAsset.findUnique({ where: { id } }); if (!prior) throw new MarketingRegistryError("record_not_found", "Content asset not found."); await validateAsset(input, input.status);
  const next = { title: input.title, assetType: input.assetType, targetSegment: input.targetSegment, channel: input.channel, status: input.status, containsMarketingClaim: input.containsMarketingClaim, claimApprovalId: input.claimApprovalId, artifactReference: input.artifactReference, ownerUserId: input.ownerUserId, plannedAt: input.plannedAt ? new Date(input.plannedAt) : null, reviewAt: input.reviewAt ? new Date(input.reviewAt) : null };
  const changedFields = Object.keys(next).filter((key) => String(prior[key as keyof typeof prior] ?? "") !== String(next[key as keyof typeof next] ?? "")); if (!changedFields.length) throw new MarketingRegistryError("no_changes", "No content changes were supplied.");
  return prisma.$transaction(async (tx) => { const result = await tx.contentAsset.updateMany({ where: { id, version: input.expectedVersion }, data: { ...next, version: { increment: 1 } } }); if (result.count !== 1) throw new MarketingRegistryError("version_conflict", "Content asset changed after this form was loaded."); await writeHistory(tx, { recordType: "content_asset", recordId: id, action: "content_asset_updated", mutationId: input.mutationId, changedFields, operator }); return tx.contentAsset.findUniqueOrThrow({ where: { id } }); });
}
