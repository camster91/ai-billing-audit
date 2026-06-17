-- CreateTable
CREATE TABLE "SuppressListEntry" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "email" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "sourceEventId" TEXT,
    "sourceDetail" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lastEventAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "SuppressionEvent" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "email" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "sourceEventId" TEXT,
    "sourceDetail" TEXT,
    "payloadJson" TEXT NOT NULL,
    "receivedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateIndex
CREATE UNIQUE INDEX "SuppressListEntry_email_key" ON "SuppressListEntry"("email");

-- CreateIndex
CREATE INDEX "SuppressionEvent_email_receivedAt_idx" ON "SuppressionEvent"("email", "receivedAt");

-- CreateIndex
CREATE INDEX "SuppressionEvent_reason_receivedAt_idx" ON "SuppressionEvent"("reason", "receivedAt");
