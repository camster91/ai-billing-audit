ALTER TABLE "Encounter" ADD COLUMN "sourceUploadDigest" TEXT;
ALTER TABLE "Tenant" ADD COLUMN "firstEncounterEncounterId" TEXT;

CREATE UNIQUE INDEX "Encounter_sourceUploadDigest_key"
ON "Encounter"("sourceUploadDigest");
