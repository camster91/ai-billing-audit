-- Company-wide authorization is separate from tenant Membership roles.
CREATE TABLE "PlatformUserRole" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "userId" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "grantedBy" TEXT NOT NULL,
    "grantedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "revokedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "PlatformUserRole_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "PlatformUserRole_userId_key" ON "PlatformUserRole"("userId");
CREATE INDEX "PlatformUserRole_role_active_idx" ON "PlatformUserRole"("role", "active");

-- Non-clinical append-only operator audit record. Application code provides
-- unique request ids so repeated writes fail rather than silently duplicate.
CREATE TABLE "PlatformAuditEvent" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "actorUserId" TEXT,
    "actorRole" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "targetType" TEXT NOT NULL,
    "targetId" TEXT,
    "requestId" TEXT NOT NULL,
    "metadataJson" TEXT,
    "occurredAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PlatformAuditEvent_actorUserId_fkey" FOREIGN KEY ("actorUserId") REFERENCES "User" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "PlatformAuditEvent_requestId_key" ON "PlatformAuditEvent"("requestId");
CREATE INDEX "PlatformAuditEvent_actorUserId_occurredAt_idx" ON "PlatformAuditEvent"("actorUserId", "occurredAt");
CREATE INDEX "PlatformAuditEvent_targetType_targetId_occurredAt_idx" ON "PlatformAuditEvent"("targetType", "targetId", "occurredAt");
CREATE INDEX "PlatformAuditEvent_action_occurredAt_idx" ON "PlatformAuditEvent"("action", "occurredAt");
