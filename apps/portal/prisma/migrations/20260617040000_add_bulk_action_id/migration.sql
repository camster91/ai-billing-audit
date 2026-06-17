-- AlterTable
-- Add bulkActionId to AuditTrailEntry for the /findings inbox bulk
-- action feature. The id is duplicated into `dataElements` (which is
-- part of the chain hash) so the column itself is NOT in the chain
-- payload — it is just the indexed handle for "give me every row
-- from bulk action X" on the billing-team review surface. See
-- apps/portal/src/lib/audit-write.ts writeAuditEntry for the writer
-- and apps/portal/src/lib/audit-chain.ts for the chain payload
-- (bulkActionId is a key on the canonical JSON dataElements object,
-- not a new chain field).
ALTER TABLE "AuditTrailEntry" ADD COLUMN "bulkActionId" TEXT;

-- CreateIndex
CREATE INDEX "AuditTrailEntry_bulkActionId_idx" ON "AuditTrailEntry"("bulkActionId");
