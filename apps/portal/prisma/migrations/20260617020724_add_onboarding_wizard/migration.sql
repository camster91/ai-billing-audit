-- CreateTable
CREATE TABLE "RedeemedCheckoutSession" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "sessionId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "tenantId" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "RedeemedCheckoutSession_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "RedeemedCheckoutSession_tenantId_fkey" FOREIGN KEY ("tenantId") REFERENCES "Tenant" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_Tenant" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "tier" TEXT NOT NULL DEFAULT 'small',
    "subscriptionStatus" TEXT NOT NULL DEFAULT 'active',
    "stripeCustomerId" TEXT,
    "stripeSubscriptionId" TEXT,
    "auditQuotaUsed" INTEGER NOT NULL DEFAULT 0,
    "auditQuotaLimit" INTEGER NOT NULL DEFAULT 100,
    "clinicName" TEXT,
    "clinicNpi" TEXT,
    "clinicTimezone" TEXT,
    "dataResidencyRegion" TEXT,
    "residencyRegionLocked" BOOLEAN NOT NULL DEFAULT false,
    "ehrConnectionMode" TEXT,
    "ehrSftpHost" TEXT,
    "ehrSftpPort" INTEGER,
    "ehrSftpUsername" TEXT,
    "ehrSftpPasswordCiphertext" TEXT,
    "firstEncounterUploadMode" TEXT,
    "firstEncounterFilePath" TEXT,
    "firstEncounterFileName" TEXT,
    "firstEncounterUploadedAt" DATETIME,
    "onboardingStep" INTEGER NOT NULL DEFAULT 0,
    "onboardingCompletedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);
INSERT INTO "new_Tenant" ("auditQuotaLimit", "auditQuotaUsed", "createdAt", "id", "name", "slug", "stripeCustomerId", "stripeSubscriptionId", "subscriptionStatus", "tier", "updatedAt") SELECT "auditQuotaLimit", "auditQuotaUsed", "createdAt", "id", "name", "slug", "stripeCustomerId", "stripeSubscriptionId", "subscriptionStatus", "tier", "updatedAt" FROM "Tenant";
DROP TABLE "Tenant";
ALTER TABLE "new_Tenant" RENAME TO "Tenant";
CREATE UNIQUE INDEX "Tenant_slug_key" ON "Tenant"("slug");
CREATE UNIQUE INDEX "Tenant_stripeCustomerId_key" ON "Tenant"("stripeCustomerId");
CREATE UNIQUE INDEX "Tenant_stripeSubscriptionId_key" ON "Tenant"("stripeSubscriptionId");
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;

-- CreateIndex
CREATE UNIQUE INDEX "RedeemedCheckoutSession_sessionId_key" ON "RedeemedCheckoutSession"("sessionId");

-- CreateIndex
CREATE INDEX "RedeemedCheckoutSession_userId_idx" ON "RedeemedCheckoutSession"("userId");

-- CreateIndex
CREATE INDEX "RedeemedCheckoutSession_tenantId_idx" ON "RedeemedCheckoutSession"("tenantId");
