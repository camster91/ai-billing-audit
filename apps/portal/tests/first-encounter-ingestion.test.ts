import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { mkdir, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { encryptPortalBuffer, decryptPortalString } from "../src/lib/data-encryption";
import { ingestFirstEncounter } from "../src/lib/first-encounter-ingestion";
import { parsePortalDiagnosisCodes } from "../src/lib/audit-submission";
import { prisma } from "../src/lib/prisma";

process.env.ZORVA_PHI_ENCRYPTION_KEY ??= randomBytes(32).toString("base64url");
process.env.PATIENT_HASH_PEPPER ??= randomBytes(32).toString("hex");

test("encrypted 837P plus note becomes one idempotent tenant encounter", async () => {
  const tag = randomUUID();
  const tenant = await prisma.tenant.create({
    data: { name: `Ingestion ${tag}`, slug: `ingestion-${tag}` },
  });
  const storedName = `${tag}__claim.edi`;
  const relativePath = `uploads/${storedName}`;
  const absolutePath = path.join(process.cwd(), relativePath);
  await mkdir(path.dirname(absolutePath), { recursive: true });
  await writeFile(absolutePath, encryptPortalBuffer(Buffer.from("837P fixture bytes")));
  const preview = async () => ({
    kind: "ok" as const,
    data: {
      filename: "claim.edi",
      rows: [{
        encounter_id: "ENC-1",
        patient_id: "PHN-123",
        NPI: "1234567893",
        date_of_service: "2026-08-31",
        CPT_codes: ["99214-25"],
        diagnosis_codes: ["I10"],
        source_filename: "claim.edi",
        errors: [],
      }],
    },
  });
  let encounterId = "";
  try {
    const first = await ingestFirstEncounter({
      input: {
        tenantId: tenant.id,
        filePath: relativePath,
        fileName: "claim.edi",
        clinicalNote: "Assessment and plan documented for hypertension follow-up.",
        specialty: "family_medicine",
      },
      principal: { subject: "user-1", tenantId: tenant.id, portalRole: "owner" },
      preview,
    });
    encounterId = first.encounterId;
    assert.equal(first.created, true);
    const replay = await ingestFirstEncounter({
      input: {
        tenantId: tenant.id,
        filePath: relativePath,
        fileName: "claim.edi",
        clinicalNote: "Assessment and plan documented for hypertension follow-up.",
        specialty: "family_medicine",
      },
      principal: { subject: "user-1", tenantId: tenant.id, portalRole: "owner" },
      preview,
    });
    assert.deepEqual(replay, { encounterId, created: false });

    const stored = await prisma.encounter.findUnique({
      where: { id: encounterId },
      include: { claim: true },
    });
    assert.ok(stored);
    assert.equal(stored.status, "pending");
    assert.equal(stored.specialty, "family_medicine");
    assert.match(stored.patientHash, /^[a-f0-9]{64}$/);
    assert.equal(
      decryptPortalString(stored.clinicalNote),
      "Assessment and plan documented for hypertension follow-up.",
    );
    assert.deepEqual(parsePortalDiagnosisCodes(stored.claim.cptCodesJson), ["I10"]);
  } finally {
    if (encounterId) await prisma.encounter.delete({ where: { id: encounterId } }).catch(() => {});
    await prisma.encounterClaim.deleteMany({ where: { encounter: null } }).catch(() => {});
    await prisma.tenant.delete({ where: { id: tenant.id } }).catch(() => {});
    await unlink(absolutePath).catch(() => {});
  }
});
