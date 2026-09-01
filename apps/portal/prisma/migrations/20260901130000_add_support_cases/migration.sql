CREATE TABLE "SupportCase" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "engagementId" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "severity" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'new',
    "safeSummary" TEXT NOT NULL,
    "ownerUserId" TEXT,
    "dueAt" DATETIME,
    "acknowledgedAt" DATETIME,
    "resolvedAt" DATETIME,
    "linkedIssueReference" TEXT,
    "version" INTEGER NOT NULL DEFAULT 0,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "SupportCase_engagementId_fkey" FOREIGN KEY ("engagementId") REFERENCES "ClientEngagement" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "SupportCase_ownerUserId_fkey" FOREIGN KEY ("ownerUserId") REFERENCES "User" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE "SupportActivity" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "caseId" TEXT NOT NULL,
    "actorUserId" TEXT,
    "actorRole" TEXT NOT NULL,
    "kind" TEXT NOT NULL,
    "mutationId" TEXT NOT NULL,
    "changesJson" TEXT NOT NULL,
    "occurredAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "SupportActivity_caseId_fkey" FOREIGN KEY ("caseId") REFERENCES "SupportCase" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "SupportActivity_actorUserId_fkey" FOREIGN KEY ("actorUserId") REFERENCES "User" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE INDEX "SupportCase_status_severity_dueAt_idx" ON "SupportCase"("status", "severity", "dueAt");
CREATE INDEX "SupportCase_engagementId_status_createdAt_idx" ON "SupportCase"("engagementId", "status", "createdAt");
CREATE INDEX "SupportCase_ownerUserId_status_dueAt_idx" ON "SupportCase"("ownerUserId", "status", "dueAt");
CREATE UNIQUE INDEX "SupportActivity_mutationId_key" ON "SupportActivity"("mutationId");
CREATE INDEX "SupportActivity_caseId_occurredAt_idx" ON "SupportActivity"("caseId", "occurredAt");
CREATE INDEX "SupportActivity_actorUserId_occurredAt_idx" ON "SupportActivity"("actorUserId", "occurredAt");

CREATE TRIGGER "SupportActivity_immutable_update"
BEFORE UPDATE ON "SupportActivity"
BEGIN
  SELECT RAISE(ABORT, 'SupportActivity is append-only');
END;

CREATE TRIGGER "SupportActivity_immutable_delete"
BEFORE DELETE ON "SupportActivity"
BEGIN
  SELECT RAISE(ABORT, 'SupportActivity is append-only');
END;
