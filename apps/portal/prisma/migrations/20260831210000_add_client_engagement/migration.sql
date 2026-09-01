CREATE TABLE "ClientEngagement" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "leadId" TEXT NOT NULL,
    "tenantId" TEXT,
    "clinicName" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pilot_planning',
    "ownerUserId" TEXT,
    "offerReference" TEXT,
    "privacyApprovalStatus" TEXT NOT NULL DEFAULT 'pending',
    "pilotStartAt" DATETIME,
    "pilotEndAt" DATETIME,
    "firstValueAt" DATETIME,
    "healthStatus" TEXT NOT NULL DEFAULT 'unknown',
    "version" INTEGER NOT NULL DEFAULT 0,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "ClientEngagement_leadId_fkey" FOREIGN KEY ("leadId") REFERENCES "Lead" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "ClientEngagement_tenantId_fkey" FOREIGN KEY ("tenantId") REFERENCES "Tenant" ("id") ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT "ClientEngagement_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "User" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "ClientEngagement_leadId_key" ON "ClientEngagement"("leadId");
CREATE UNIQUE INDEX "ClientEngagement_tenantId_key" ON "ClientEngagement"("tenantId");
CREATE INDEX "ClientEngagement_status_pilotStartAt_idx" ON "ClientEngagement"("status", "pilotStartAt");
CREATE INDEX "ClientEngagement_ownerUserId_status_idx" ON "ClientEngagement"("ownerUserId", "status");
CREATE INDEX "ClientEngagement_healthStatus_status_idx" ON "ClientEngagement"("healthStatus", "status");

CREATE TABLE "CompanyTask" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "engagementId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'todo',
    "priority" TEXT NOT NULL DEFAULT 'normal',
    "ownerUserId" TEXT,
    "dueAt" DATETIME,
    "evidenceReference" TEXT,
    "completedAt" DATETIME,
    "version" INTEGER NOT NULL DEFAULT 0,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "CompanyTask_engagementId_fkey" FOREIGN KEY ("engagementId") REFERENCES "ClientEngagement" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "CompanyTask_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "User" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE INDEX "CompanyTask_engagementId_status_dueAt_idx" ON "CompanyTask"("engagementId", "status", "dueAt");
CREATE INDEX "CompanyTask_ownerUserId_status_dueAt_idx" ON "CompanyTask"("ownerUserId", "status", "dueAt");
