ALTER TABLE "Tenant" ADD COLUMN "auditQuotaReserved" INTEGER NOT NULL DEFAULT 0;

CREATE TABLE "AuditDispatch" (
    "id" TEXT NOT NULL,
    "tenantId" TEXT NOT NULL,
    "encounterId" TEXT NOT NULL,
    "engineJobId" TEXT,
    "engineStatusUrl" TEXT,
    "status" TEXT NOT NULL DEFAULT 'dispatching',
    "quotaReserved" BOOLEAN NOT NULL DEFAULT true,
    "quotaChargedAt" TIMESTAMP(3),
    "dispatchStartedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "submittedAt" TIMESTAMP(3),
    "completedAt" TIMESTAMP(3),
    "resultImportedAt" TIMESTAMP(3),
    "lastError" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "AuditDispatch_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "AuditDispatch_encounterId_key" ON "AuditDispatch"("encounterId");
CREATE UNIQUE INDEX "AuditDispatch_engineJobId_key" ON "AuditDispatch"("engineJobId");
CREATE INDEX "AuditDispatch_tenantId_status_idx" ON "AuditDispatch"("tenantId", "status");
ALTER TABLE "AuditDispatch" ADD CONSTRAINT "AuditDispatch_tenantId_fkey" FOREIGN KEY ("tenantId") REFERENCES "Tenant"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "AuditDispatch" ADD CONSTRAINT "AuditDispatch_encounterId_fkey" FOREIGN KEY ("encounterId") REFERENCES "Encounter"("id") ON DELETE CASCADE ON UPDATE CASCADE;
