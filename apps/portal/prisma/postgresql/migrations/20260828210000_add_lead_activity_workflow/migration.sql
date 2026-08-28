ALTER TABLE "Lead" ADD COLUMN "version" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Lead" ADD COLUMN "nextAction" TEXT;
ALTER TABLE "Lead" ADD COLUMN "nextActionAt" TIMESTAMP(3);
ALTER TABLE "Lead" ADD COLUMN "lostReason" TEXT;

CREATE INDEX "Lead_ownerUserId_nextActionAt_idx" ON "Lead"("ownerUserId", "nextActionAt");

CREATE TABLE "LeadActivity" (
    "id" TEXT NOT NULL,
    "leadId" TEXT NOT NULL,
    "actorUserId" TEXT,
    "actorRole" TEXT NOT NULL,
    "kind" TEXT NOT NULL,
    "fromValue" TEXT,
    "toValue" TEXT,
    "mutationId" TEXT NOT NULL,
    "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "LeadActivity_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "LeadActivity_mutationId_kind_key" ON "LeadActivity"("mutationId", "kind");
CREATE INDEX "LeadActivity_leadId_occurredAt_idx" ON "LeadActivity"("leadId", "occurredAt");
CREATE INDEX "LeadActivity_actorUserId_occurredAt_idx" ON "LeadActivity"("actorUserId", "occurredAt");

ALTER TABLE "LeadActivity" ADD CONSTRAINT "LeadActivity_leadId_fkey" FOREIGN KEY ("leadId") REFERENCES "Lead"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "LeadActivity" ADD CONSTRAINT "LeadActivity_actorUserId_fkey" FOREIGN KEY ("actorUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
