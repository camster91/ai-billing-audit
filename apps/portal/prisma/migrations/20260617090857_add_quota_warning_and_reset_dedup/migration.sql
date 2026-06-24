-- AlterTable
ALTER TABLE "Tenant" ADD COLUMN "lastQuotaResetPeriodStart" DATETIME;
ALTER TABLE "Tenant" ADD COLUMN "quotaWarningSentAt" DATETIME;
