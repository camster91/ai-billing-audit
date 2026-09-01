CREATE TABLE "ClaimApproval" (
    "id" TEXT NOT NULL, "exactClaim" TEXT NOT NULL, "evidenceType" TEXT NOT NULL,
    "evidenceReference" TEXT, "customerPermissionReference" TEXT, "allowedSurfacesJson" TEXT NOT NULL DEFAULT '[]',
    "status" TEXT NOT NULL DEFAULT 'draft', "approverUserId" TEXT, "approvedAt" TIMESTAMP(3),
    "reviewAt" TIMESTAMP(3), "expiresAt" TIMESTAMP(3), "replacesClaimId" TEXT, "version" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP, "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "ClaimApproval_pkey" PRIMARY KEY ("id")
);
CREATE TABLE "ContentAsset" (
    "id" TEXT NOT NULL, "title" TEXT NOT NULL, "assetType" TEXT NOT NULL, "targetSegment" TEXT NOT NULL,
    "channel" TEXT NOT NULL, "status" TEXT NOT NULL DEFAULT 'draft', "containsMarketingClaim" BOOLEAN NOT NULL DEFAULT false,
    "claimApprovalId" TEXT, "artifactReference" TEXT, "ownerUserId" TEXT, "plannedAt" TIMESTAMP(3), "reviewAt" TIMESTAMP(3),
    "version" INTEGER NOT NULL DEFAULT 0, "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP, "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "ContentAsset_pkey" PRIMARY KEY ("id")
);
CREATE TABLE "MarketingActivity" (
    "id" TEXT NOT NULL, "recordType" TEXT NOT NULL, "recordId" TEXT NOT NULL, "actorUserId" TEXT,
    "actorRole" TEXT NOT NULL, "kind" TEXT NOT NULL, "mutationId" TEXT NOT NULL, "changesJson" TEXT NOT NULL,
    "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT "MarketingActivity_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "ClaimApproval_status_reviewAt_idx" ON "ClaimApproval"("status", "reviewAt");
CREATE INDEX "ClaimApproval_approverUserId_status_idx" ON "ClaimApproval"("approverUserId", "status");
CREATE INDEX "ClaimApproval_replacesClaimId_idx" ON "ClaimApproval"("replacesClaimId");
CREATE INDEX "ContentAsset_status_channel_plannedAt_idx" ON "ContentAsset"("status", "channel", "plannedAt");
CREATE INDEX "ContentAsset_ownerUserId_status_reviewAt_idx" ON "ContentAsset"("ownerUserId", "status", "reviewAt");
CREATE INDEX "ContentAsset_claimApprovalId_idx" ON "ContentAsset"("claimApprovalId");
CREATE UNIQUE INDEX "MarketingActivity_mutationId_key" ON "MarketingActivity"("mutationId");
CREATE INDEX "MarketingActivity_recordType_recordId_occurredAt_idx" ON "MarketingActivity"("recordType", "recordId", "occurredAt");
CREATE INDEX "MarketingActivity_actorUserId_occurredAt_idx" ON "MarketingActivity"("actorUserId", "occurredAt");
ALTER TABLE "ClaimApproval" ADD CONSTRAINT "ClaimApproval_approverUserId_fkey" FOREIGN KEY ("approverUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "ClaimApproval" ADD CONSTRAINT "ClaimApproval_replacesClaimId_fkey" FOREIGN KEY ("replacesClaimId") REFERENCES "ClaimApproval"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "ContentAsset" ADD CONSTRAINT "ContentAsset_claimApprovalId_fkey" FOREIGN KEY ("claimApprovalId") REFERENCES "ClaimApproval"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "ContentAsset" ADD CONSTRAINT "ContentAsset_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "MarketingActivity" ADD CONSTRAINT "MarketingActivity_actorUserId_fkey" FOREIGN KEY ("actorUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
CREATE TRIGGER "MarketingActivity_immutable" BEFORE UPDATE OR DELETE ON "MarketingActivity" FOR EACH ROW EXECUTE FUNCTION "deny_hq_history_mutation"();
