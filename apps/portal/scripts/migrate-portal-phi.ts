import path from "node:path";

import { prisma } from "../src/lib/prisma";
import {
  migrateAuditTextFields,
  migratePortalCredential,
  migratePortalUploadDirectory,
} from "../src/lib/portal-phi-migration";
import {
  computeSignature,
  GENESIS_PREVIOUS_SIGNATURE,
  type ChainRow,
} from "../src/lib/audit-chain";
import { verifyTenantChain } from "../src/lib/audit-write";

async function main(): Promise<void> {
  const uploadDir = path.resolve(process.env.PORTAL_UPLOAD_DIR ?? "uploads");
  const uploads = await migratePortalUploadDirectory(uploadDir);

  const tenants = await prisma.tenant.findMany({
    where: { ehrSftpPasswordCiphertext: { not: null } },
    select: { id: true, ehrSftpPasswordCiphertext: true },
  });
  let credentialsMigrated = 0;
  for (const tenant of tenants) {
    const current = tenant.ehrSftpPasswordCiphertext;
    if (!current) continue;
    const migrated = migratePortalCredential(current);
    if (!migrated.migrated) continue;
    await prisma.tenant.update({
      where: { id: tenant.id },
      data: { ehrSftpPasswordCiphertext: migrated.value },
    });
    credentialsMigrated += 1;
  }

  let encountersMigrated = 0;
  const encounters = await prisma.encounter.findMany({
    select: { id: true, clinicalNote: true },
  });
  for (const encounter of encounters) {
    const migrated = migratePortalCredential(encounter.clinicalNote);
    if (!migrated.migrated) continue;
    await prisma.encounter.update({
      where: { id: encounter.id },
      data: { clinicalNote: migrated.value },
    });
    encountersMigrated += 1;
  }

  let findingsMigrated = 0;
  const findings = await prisma.finding.findMany({
    select: { id: true, evidenceQuote: true, dismissText: true },
  });
  for (const finding of findings) {
    const evidence = migratePortalCredential(finding.evidenceQuote);
    const dismiss = finding.dismissText
      ? migratePortalCredential(finding.dismissText)
      : { value: null, migrated: false };
    if (!evidence.migrated && !dismiss.migrated) continue;
    await prisma.finding.update({
      where: { id: finding.id },
      data: {
        evidenceQuote: evidence.value,
        dismissText: dismiss.value,
      },
    });
    findingsMigrated += 1;
  }

  let auditRowsMigrated = 0;
  const auditTenants = await prisma.auditTrailEntry.groupBy({ by: ["tenantId"] });
  for (const { tenantId } of auditTenants) {
    const brokenAt = await verifyTenantChain(tenantId);
    if (brokenAt !== null) {
      throw new Error(`audit chain for tenant ${tenantId} is broken at row ${brokenAt}`);
    }
    const rows = await prisma.auditTrailEntry.findMany({
      where: { tenantId },
      orderBy: [{ timestamp: "asc" }, { eventId: "asc" }],
    });
    const transformed = rows.map((row) => ({
      row,
      text: migrateAuditTextFields(row.reasonText, row.dataElements),
    }));
    if (!transformed.some(({ text }) => text.migrated)) continue;

    await prisma.$transaction(async (tx) => {
      let previousSignature = GENESIS_PREVIOUS_SIGNATURE;
      for (const { row, text } of transformed) {
        const chainRow: ChainRow = {
          eventId: row.eventId,
          timestamp: row.timestamp.toISOString(),
          userIdentifier: row.userIdentifier,
          action: row.action,
          patientHash: row.patientHash,
          dataElements: text.dataElements,
          modelRunId: row.modelRunId,
          previousSignature,
          cryptographicSignature: "",
        };
        const cryptographicSignature = computeSignature(previousSignature, chainRow);
        await tx.auditTrailEntry.update({
          where: { id: row.id },
          data: {
            reasonText: text.reasonText,
            dataElements: text.dataElements,
            previousSignature,
            cryptographicSignature,
          },
        });
        previousSignature = cryptographicSignature;
        if (text.migrated) auditRowsMigrated += 1;
      }
    });
    const brokenAfter = await verifyTenantChain(tenantId);
    if (brokenAfter !== null) {
      throw new Error(
        `audit chain for tenant ${tenantId} failed verification after migration at row ${brokenAfter}`,
      );
    }
  }

  console.log(
    JSON.stringify({
      uploads,
      credentialsMigrated,
      encountersMigrated,
      findingsMigrated,
      auditRowsMigrated,
    }),
  );
}

main()
  .catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
