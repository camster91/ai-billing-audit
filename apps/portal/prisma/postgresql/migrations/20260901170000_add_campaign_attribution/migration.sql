CREATE TABLE "Campaign" (
  "id" TEXT NOT NULL, "name" TEXT NOT NULL, "sourceKey" TEXT NOT NULL, "objective" TEXT NOT NULL,
  "targetSegment" TEXT NOT NULL, "channel" TEXT NOT NULL, "status" TEXT NOT NULL DEFAULT 'planning',
  "ownerUserId" TEXT, "contentAssetId" TEXT, "landingPath" TEXT, "utmSource" TEXT, "utmMedium" TEXT, "utmCampaign" TEXT,
  "plannedStartAt" TIMESTAMP(3), "plannedEndAt" TIMESTAMP(3), "reviewAt" TIMESTAMP(3), "externalApprovalReference" TEXT,
  "budgetApprovalReference" TEXT, "approvedBudgetCents" INTEGER, "recordedSpendCents" INTEGER,
  "version" INTEGER NOT NULL DEFAULT 0, "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP, "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "Campaign_pkey" PRIMARY KEY ("id")
);
CREATE TABLE "CampaignAttributionSnapshot" (
  "id" TEXT NOT NULL, "campaignId" TEXT NOT NULL, "mutationId" TEXT NOT NULL, "sourceReference" TEXT NOT NULL,
  "periodStartAt" TIMESTAMP(3) NOT NULL, "periodEndAt" TIMESTAMP(3) NOT NULL, "visitCount" INTEGER, "leadCount" INTEGER,
  "qualifiedCount" INTEGER, "demoCount" INTEGER, "pilotCount" INTEGER, "clientCount" INTEGER, "revenueCents" INTEGER,
  "currency" TEXT NOT NULL DEFAULT 'CAD', "notes" TEXT, "recordedByUserId" TEXT, "recordedByRole" TEXT NOT NULL, "recordedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "CampaignAttributionSnapshot_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "Campaign_sourceKey_key" ON "Campaign"("sourceKey");
CREATE INDEX "Campaign_status_channel_plannedStartAt_idx" ON "Campaign"("status", "channel", "plannedStartAt");
CREATE INDEX "Campaign_ownerUserId_status_reviewAt_idx" ON "Campaign"("ownerUserId", "status", "reviewAt");
CREATE INDEX "Campaign_contentAssetId_idx" ON "Campaign"("contentAssetId");
CREATE UNIQUE INDEX "CampaignAttributionSnapshot_mutationId_key" ON "CampaignAttributionSnapshot"("mutationId");
CREATE INDEX "CampaignAttributionSnapshot_campaignId_periodEndAt_idx" ON "CampaignAttributionSnapshot"("campaignId", "periodEndAt");
CREATE INDEX "CampaignAttributionSnapshot_recordedByUserId_recordedAt_idx" ON "CampaignAttributionSnapshot"("recordedByUserId", "recordedAt");
ALTER TABLE "Campaign" ADD CONSTRAINT "Campaign_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "Campaign" ADD CONSTRAINT "Campaign_contentAssetId_fkey" FOREIGN KEY ("contentAssetId") REFERENCES "ContentAsset"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "CampaignAttributionSnapshot" ADD CONSTRAINT "CampaignAttributionSnapshot_campaignId_fkey" FOREIGN KEY ("campaignId") REFERENCES "Campaign"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "CampaignAttributionSnapshot" ADD CONSTRAINT "CampaignAttributionSnapshot_recordedByUserId_fkey" FOREIGN KEY ("recordedByUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
CREATE TRIGGER "CampaignAttributionSnapshot_immutable" BEFORE UPDATE OR DELETE ON "CampaignAttributionSnapshot" FOR EACH ROW EXECUTE FUNCTION "deny_hq_history_mutation"();
