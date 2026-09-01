CREATE TABLE "Campaign" (
  "id" TEXT NOT NULL PRIMARY KEY, "name" TEXT NOT NULL, "sourceKey" TEXT NOT NULL, "objective" TEXT NOT NULL,
  "targetSegment" TEXT NOT NULL, "channel" TEXT NOT NULL, "status" TEXT NOT NULL DEFAULT 'planning',
  "ownerUserId" TEXT, "contentAssetId" TEXT, "landingPath" TEXT, "utmSource" TEXT, "utmMedium" TEXT, "utmCampaign" TEXT,
  "plannedStartAt" DATETIME, "plannedEndAt" DATETIME, "reviewAt" DATETIME, "externalApprovalReference" TEXT,
  "budgetApprovalReference" TEXT, "approvedBudgetCents" INTEGER, "recordedSpendCents" INTEGER,
  "version" INTEGER NOT NULL DEFAULT 0, "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "updatedAt" DATETIME NOT NULL,
  CONSTRAINT "Campaign_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "User" ("id") ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT "Campaign_contentAssetId_fkey" FOREIGN KEY ("contentAssetId") REFERENCES "ContentAsset" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE TABLE "CampaignAttributionSnapshot" (
  "id" TEXT NOT NULL PRIMARY KEY, "campaignId" TEXT NOT NULL, "mutationId" TEXT NOT NULL, "sourceReference" TEXT NOT NULL,
  "periodStartAt" DATETIME NOT NULL, "periodEndAt" DATETIME NOT NULL, "visitCount" INTEGER, "leadCount" INTEGER,
  "qualifiedCount" INTEGER, "demoCount" INTEGER, "pilotCount" INTEGER, "clientCount" INTEGER, "revenueCents" INTEGER,
  "currency" TEXT NOT NULL DEFAULT 'CAD', "notes" TEXT, "recordedByUserId" TEXT, "recordedByRole" TEXT NOT NULL, "recordedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "CampaignAttributionSnapshot_campaignId_fkey" FOREIGN KEY ("campaignId") REFERENCES "Campaign" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT "CampaignAttributionSnapshot_recordedByUserId_fkey" FOREIGN KEY ("recordedByUserId") REFERENCES "User" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE UNIQUE INDEX "Campaign_sourceKey_key" ON "Campaign"("sourceKey");
CREATE INDEX "Campaign_status_channel_plannedStartAt_idx" ON "Campaign"("status", "channel", "plannedStartAt");
CREATE INDEX "Campaign_ownerUserId_status_reviewAt_idx" ON "Campaign"("ownerUserId", "status", "reviewAt");
CREATE INDEX "Campaign_contentAssetId_idx" ON "Campaign"("contentAssetId");
CREATE UNIQUE INDEX "CampaignAttributionSnapshot_mutationId_key" ON "CampaignAttributionSnapshot"("mutationId");
CREATE INDEX "CampaignAttributionSnapshot_campaignId_periodEndAt_idx" ON "CampaignAttributionSnapshot"("campaignId", "periodEndAt");
CREATE INDEX "CampaignAttributionSnapshot_recordedByUserId_recordedAt_idx" ON "CampaignAttributionSnapshot"("recordedByUserId", "recordedAt");
CREATE TRIGGER "CampaignAttributionSnapshot_immutable_update" BEFORE UPDATE ON "CampaignAttributionSnapshot" BEGIN SELECT RAISE(ABORT, 'CampaignAttributionSnapshot is append-only'); END;
CREATE TRIGGER "CampaignAttributionSnapshot_immutable_delete" BEFORE DELETE ON "CampaignAttributionSnapshot" BEGIN SELECT RAISE(ABORT, 'CampaignAttributionSnapshot is append-only'); END;
