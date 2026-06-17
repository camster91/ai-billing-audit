-- AlterTable
ALTER TABLE "Tenant" ADD COLUMN "canceledAt" DATETIME;
ALTER TABLE "Tenant" ADD COLUMN "firstPaymentFailureAt" DATETIME;
ALTER TABLE "Tenant" ADD COLUMN "lastPaymentFailureAt" DATETIME;

-- CreateTable
CREATE TABLE "ProcessedStripeEvent" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "eventId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "tenantId" TEXT,
    "receivedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ProcessedStripeEvent_tenantId_fkey" FOREIGN KEY ("tenantId") REFERENCES "Tenant" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Invoice" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "stripeInvoiceId" TEXT NOT NULL,
    "stripeCustomerId" TEXT NOT NULL,
    "tenantId" TEXT NOT NULL,
    "stripeSubscriptionId" TEXT,
    "status" TEXT NOT NULL,
    "amountCents" INTEGER NOT NULL,
    "currency" TEXT NOT NULL,
    "payloadJson" TEXT NOT NULL,
    "createdFromEventId" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "Invoice_tenantId_fkey" FOREIGN KEY ("tenantId") REFERENCES "Tenant" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "ProcessedStripeEvent_eventId_key" ON "ProcessedStripeEvent"("eventId");

-- CreateIndex
CREATE INDEX "ProcessedStripeEvent_tenantId_receivedAt_idx" ON "ProcessedStripeEvent"("tenantId", "receivedAt");

-- CreateIndex
CREATE INDEX "ProcessedStripeEvent_type_receivedAt_idx" ON "ProcessedStripeEvent"("type", "receivedAt");

-- CreateIndex
CREATE UNIQUE INDEX "Invoice_stripeInvoiceId_key" ON "Invoice"("stripeInvoiceId");

-- CreateIndex
CREATE INDEX "Invoice_tenantId_createdAt_idx" ON "Invoice"("tenantId", "createdAt");

-- CreateIndex
CREATE INDEX "Invoice_stripeCustomerId_idx" ON "Invoice"("stripeCustomerId");

-- CreateIndex
CREATE INDEX "Invoice_stripeSubscriptionId_idx" ON "Invoice"("stripeSubscriptionId");
