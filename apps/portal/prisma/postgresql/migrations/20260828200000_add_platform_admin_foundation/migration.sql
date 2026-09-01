CREATE TABLE "PlatformUserRole" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "grantedBy" TEXT NOT NULL,
    "grantedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "revokedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "PlatformUserRole_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "PlatformAuditEvent" (
    "id" TEXT NOT NULL,
    "actorUserId" TEXT,
    "actorRole" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "targetType" TEXT NOT NULL,
    "targetId" TEXT,
    "requestId" TEXT NOT NULL,
    "metadataJson" TEXT,
    "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PlatformAuditEvent_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "PlatformUserRole_userId_key" ON "PlatformUserRole"("userId");
CREATE INDEX "PlatformUserRole_role_active_idx" ON "PlatformUserRole"("role", "active");
CREATE UNIQUE INDEX "PlatformAuditEvent_requestId_key" ON "PlatformAuditEvent"("requestId");
CREATE INDEX "PlatformAuditEvent_actorUserId_occurredAt_idx" ON "PlatformAuditEvent"("actorUserId", "occurredAt");
CREATE INDEX "PlatformAuditEvent_targetType_targetId_occurredAt_idx" ON "PlatformAuditEvent"("targetType", "targetId", "occurredAt");
CREATE INDEX "PlatformAuditEvent_action_occurredAt_idx" ON "PlatformAuditEvent"("action", "occurredAt");

ALTER TABLE "PlatformUserRole" ADD CONSTRAINT "PlatformUserRole_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "PlatformAuditEvent" ADD CONSTRAINT "PlatformAuditEvent_actorUserId_fkey" FOREIGN KEY ("actorUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
