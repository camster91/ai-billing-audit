CREATE TABLE "ClientEngagement" (
    "id" TEXT NOT NULL,
    "leadId" TEXT NOT NULL,
    "tenantId" TEXT,
    "clinicName" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pilot_planning',
    "ownerUserId" TEXT,
    "offerReference" TEXT,
    "privacyApprovalStatus" TEXT NOT NULL DEFAULT 'pending',
    "pilotStartAt" TIMESTAMP(3),
    "pilotEndAt" TIMESTAMP(3),
    "firstValueAt" TIMESTAMP(3),
    "healthStatus" TEXT NOT NULL DEFAULT 'unknown',
    "version" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "ClientEngagement_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "ClientEngagement_leadId_key" ON "ClientEngagement"("leadId");
CREATE UNIQUE INDEX "ClientEngagement_tenantId_key" ON "ClientEngagement"("tenantId");
CREATE INDEX "ClientEngagement_status_pilotStartAt_idx" ON "ClientEngagement"("status", "pilotStartAt");
CREATE INDEX "ClientEngagement_ownerUserId_status_idx" ON "ClientEngagement"("ownerUserId", "status");
CREATE INDEX "ClientEngagement_healthStatus_status_idx" ON "ClientEngagement"("healthStatus", "status");

CREATE TABLE "CompanyTask" (
    "id" TEXT NOT NULL,
    "engagementId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'todo',
    "priority" TEXT NOT NULL DEFAULT 'normal',
    "ownerUserId" TEXT,
    "dueAt" TIMESTAMP(3),
    "evidenceReference" TEXT,
    "completedAt" TIMESTAMP(3),
    "version" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "CompanyTask_pkey" PRIMARY KEY ("id")
);

CREATE INDEX "CompanyTask_engagementId_status_dueAt_idx" ON "CompanyTask"("engagementId", "status", "dueAt");
CREATE INDEX "CompanyTask_ownerUserId_status_dueAt_idx" ON "CompanyTask"("ownerUserId", "status", "dueAt");

ALTER TABLE "ClientEngagement" ADD CONSTRAINT "ClientEngagement_leadId_fkey" FOREIGN KEY ("leadId") REFERENCES "Lead"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "ClientEngagement" ADD CONSTRAINT "ClientEngagement_tenantId_fkey" FOREIGN KEY ("tenantId") REFERENCES "Tenant"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "ClientEngagement" ADD CONSTRAINT "ClientEngagement_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "CompanyTask" ADD CONSTRAINT "CompanyTask_engagementId_fkey" FOREIGN KEY ("engagementId") REFERENCES "ClientEngagement"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "CompanyTask" ADD CONSTRAINT "CompanyTask_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
