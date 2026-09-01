ALTER TABLE "Lead" ADD COLUMN "dedupeKey" TEXT;
ALTER TABLE "Lead" ADD COLUMN "submissionCount" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE "Lead" ADD COLUMN "lastSubmittedAt" TIMESTAMP(3);
ALTER TABLE "Lead" ADD COLUMN "qualificationStatus" TEXT NOT NULL DEFAULT 'unreviewed';
ALTER TABLE "Lead" ADD COLUMN "qualificationReason" TEXT;
ALTER TABLE "Lead" ADD COLUMN "qualificationEvidenceRef" TEXT;
ALTER TABLE "Lead" ADD COLUMN "qualificationReviewedAt" TIMESTAMP(3);

UPDATE "Lead" SET "lastSubmittedAt" = "createdAt";

WITH ranked AS (
  SELECT "id", lower(trim("email")) AS normalized_email,
         row_number() OVER (
           PARTITION BY lower(trim("email"))
           ORDER BY "createdAt" ASC, "id" ASC
         ) AS position
  FROM "Lead"
)
UPDATE "Lead" AS lead
SET "dedupeKey" = ranked.normalized_email
FROM ranked
WHERE lead."id" = ranked."id" AND ranked.position = 1;

CREATE UNIQUE INDEX "Lead_dedupeKey_key" ON "Lead"("dedupeKey");
