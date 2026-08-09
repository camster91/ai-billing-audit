ALTER TABLE "Tenant" ADD COLUMN "auditQuotaReserved" INTEGER NOT NULL DEFAULT 0;

CREATE TABLE "AuditDispatch" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "tenantId" TEXT NOT NULL,
    "encounterId" TEXT NOT NULL,
    "engineJobId" TEXT,
    "engineStatusUrl" TEXT,
    "status" TEXT NOT NULL DEFAULT 'dispatching',
    "quotaReserved" BOOLEAN NOT NULL DEFAULT true,
    "quotaChargedAt" DATETIME,
    "dispatchStartedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "submittedAt" DATETIME,
    "completedAt" DATETIME,
    "resultImportedAt" DATETIME,
    "lastError" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "AuditDispatch_tenantId_fkey" FOREIGN KEY ("tenantId") REFERENCES "Tenant" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "AuditDispatch_encounterId_fkey" FOREIGN KEY ("encounterId") REFERENCES "Encounter" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "AuditDispatch_encounterId_key" ON "AuditDispatch"("encounterId");
CREATE UNIQUE INDEX "AuditDispatch_engineJobId_key" ON "AuditDispatch"("engineJobId");
CREATE INDEX "AuditDispatch_tenantId_status_idx" ON "AuditDispatch"("tenantId", "status");
