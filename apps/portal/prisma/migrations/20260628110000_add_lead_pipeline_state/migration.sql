-- Add pipeline-state columns to the Lead model (research/P0-PRODUCT-ROADMAP.md
-- W1.2). All four columns are nullable / have safe defaults so the migration
-- is non-blocking on existing 41 fixture rows.
--
-- Columns:
--   status           STRING  default 'new'   ('new' | 'contacted' | 'engaged' |
--                                           'demo_scheduled' | 'pilot_signed' |
--                                           'lost')
--   source           STRING  nullable         (channel of origin)
--   ownerUserId      STRING  nullable         (FK id, but no @relation — Lead
--                                           is user-scoped not tenant-scoped)
--   lastContactedAt  DATETIME nullable       (for "stale pipeline" alerts)
--
-- Indexes: composite (status, lastContactedAt) drives the pipeline
-- dashboard's primary query; (source) for "where did our leads come
-- from this quarter" tracking.

ALTER TABLE "Lead" ADD COLUMN "status" TEXT NOT NULL DEFAULT 'new';
ALTER TABLE "Lead" ADD COLUMN "source" TEXT;
ALTER TABLE "Lead" ADD COLUMN "ownerUserId" TEXT;
ALTER TABLE "Lead" ADD COLUMN "lastContactedAt" DATETIME;

CREATE INDEX "Lead_status_lastContactedAt_idx" ON "Lead"("status", "lastContactedAt");
CREATE INDEX "Lead_source_idx" ON "Lead"("source");