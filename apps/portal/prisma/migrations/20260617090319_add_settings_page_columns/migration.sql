-- CreateTable
CREATE TABLE "Lead" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "clinicName" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "claimVolume" INTEGER,
    "billingSetup" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    "canceledAt" DATETIME,
    "firstPaymentFailureAt" DATETIME,
    "lastPaymentFailureAt" DATETIME,
    "clinicName" TEXT,
    "clinicAddress" TEXT,
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
    "redactPatientNamesInExports" BOOLEAN NOT NULL DEFAULT true,
    "onboardingStep" INTEGER NOT NULL DEFAULT 0,
    "onboardingCompletedAt" DATETIME,
    "firstAuditEmailSentAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);
INSERT INTO "new_Tenant" ("auditQuotaLimit", "auditQuotaUsed", "canceledAt", "clinicName", "clinicNpi", "clinicTimezone", "createdAt", "dataResidencyRegion", "ehrConnectionMode", "ehrSftpHost", "ehrSftpPasswordCiphertext", "ehrSftpPort", "ehrSftpUsername", "firstAuditEmailSentAt", "firstEncounterFileName", "firstEncounterFilePath", "firstEncounterUploadMode", "firstEncounterUploadedAt", "firstPaymentFailureAt", "id", "lastPaymentFailureAt", "name", "onboardingCompletedAt", "onboardingStep", "residencyRegionLocked", "slug", "stripeCustomerId", "stripeSubscriptionId", "subscriptionStatus", "tier", "updatedAt") SELECT "auditQuotaLimit", "auditQuotaUsed", "canceledAt", "clinicName", "clinicNpi", "clinicTimezone", "createdAt", "dataResidencyRegion", "ehrConnectionMode", "ehrSftpHost", "ehrSftpPasswordCiphertext", "ehrSftpPort", "ehrSftpUsername", "firstAuditEmailSentAt", "firstEncounterFileName", "firstEncounterFilePath", "firstEncounterUploadMode", "firstEncounterUploadedAt", "firstPaymentFailureAt", "id", "lastPaymentFailureAt", "name", "onboardingCompletedAt", "onboardingStep", "residencyRegionLocked", "slug", "stripeCustomerId", "stripeSubscriptionId", "subscriptionStatus", "tier", "updatedAt" FROM "Tenant";
DROP TABLE "Tenant";
ALTER TABLE "new_Tenant" RENAME TO "Tenant";
CREATE UNIQUE INDEX "Tenant_slug_key" ON "Tenant"("slug");
CREATE UNIQUE INDEX "Tenant_stripeCustomerId_key" ON "Tenant"("stripeCustomerId");
CREATE UNIQUE INDEX "Tenant_stripeSubscriptionId_key" ON "Tenant"("stripeSubscriptionId");
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;

-- CreateIndex
CREATE INDEX "Lead_email_createdAt_idx" ON "Lead"("email", "createdAt");

-- CreateIndex
CREATE INDEX "Lead_createdAt_idx" ON "Lead"("createdAt");
