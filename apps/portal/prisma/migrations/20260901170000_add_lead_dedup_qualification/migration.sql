ALTER TABLE "Lead" ADD COLUMN "dedupeKey" TEXT;
ALTER TABLE "Lead" ADD COLUMN "submissionCount" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE "Lead" ADD COLUMN "lastSubmittedAt" DATETIME;
ALTER TABLE "Lead" ADD COLUMN "qualificationStatus" TEXT NOT NULL DEFAULT 'unreviewed';
ALTER TABLE "Lead" ADD COLUMN "qualificationReason" TEXT;
ALTER TABLE "Lead" ADD COLUMN "qualificationEvidenceRef" TEXT;
ALTER TABLE "Lead" ADD COLUMN "qualificationReviewedAt" DATETIME;

UPDATE "Lead" SET "lastSubmittedAt" = "createdAt";

-- Preserve every historical row. The oldest row for a normalized email becomes
-- the canonical public-capture record; older duplicates remain queryable with a
-- null key and are never silently deleted or merged.
UPDATE "Lead" AS candidate
SET "dedupeKey" = lower(trim(candidate."email"))
WHERE candidate."id" = (
  SELECT canonical."id"
  FROM "Lead" AS canonical
  WHERE lower(trim(canonical."email")) = lower(trim(candidate."email"))
  ORDER BY canonical."createdAt" ASC, canonical."id" ASC
  LIMIT 1
);

CREATE UNIQUE INDEX "Lead_dedupeKey_key" ON "Lead"("dedupeKey");
