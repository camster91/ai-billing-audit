-- Add CalibrationSignal table for per-(tenant, ruleId) accept/dismiss
-- counts. See apps/portal/src/lib/calibration.ts for the read path
-- and docs/SPECIALTY_TUNING.md for the FastAPI-side counterpart.
--
-- Scaffold intentionally narrow: counts + last-signal timestamp only.
-- Source of truth for free-text + per-finding detail remains the
-- Finding + AuditTrail tables.

-- 1. Add Finding.ruleId (nullable — older findings pre-2026-06-27 don't
--    have it). Indexed for the per-clinic aggregation query.
ALTER TABLE "Finding" ADD COLUMN "ruleId" TEXT;
CREATE INDEX "Finding_ruleId_idx" ON "Finding"("ruleId");

-- 2. Create the CalibrationSignal table.
CREATE TABLE "CalibrationSignal" (
    "id"           TEXT NOT NULL,
    "tenantId"     TEXT NOT NULL,
    "ruleId"       TEXT NOT NULL,
    "acceptCount"  INTEGER NOT NULL DEFAULT 0,
    "dismissCount" INTEGER NOT NULL DEFAULT 0,
    "lastSignalAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "createdAt"    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt"    DATETIME NOT NULL,
    CONSTRAINT "CalibrationSignal_pkey" PRIMARY KEY ("id")
);

-- Unique per (tenant, rule) — one signal row per rule per clinic.
CREATE UNIQUE INDEX "CalibrationSignal_tenantId_ruleId_key" ON "CalibrationSignal"("tenantId", "ruleId");
CREATE INDEX "CalibrationSignal_tenantId_idx" ON "CalibrationSignal"("tenantId");
CREATE INDEX "CalibrationSignal_ruleId_idx" ON "CalibrationSignal"("ruleId");
-- Drives the staleness check in calibration.ts (last_signal > 30 days = stale).
CREATE INDEX "CalibrationSignal_tenantId_lastSignalAt_idx" ON "CalibrationSignal"("tenantId", "lastSignalAt");