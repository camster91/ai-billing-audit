import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

import { decryptPortalBuffer, encryptPortalString } from "@/lib/data-encryption";
import {
  previewPortal837P,
  type Portal837Preview,
} from "@/lib/fastapi";
import type { FastApiPrincipal } from "@/lib/fastapi-principal";
import { hashPatientId } from "@/lib/patient-hash";
import { prisma } from "@/lib/prisma";

const inputSchema = z.object({
  tenantId: z.string().min(1).max(128),
  filePath: z.string().regex(/^uploads\/[A-Za-z0-9._-]+$/),
  fileName: z.string().min(1).max(255),
  clinicalNote: z.string().trim().min(20).max(100_000),
  specialty: z.string().trim().min(2).max(80),
});

export class FirstEncounterIngestionError extends Error {
  constructor(
    public readonly code:
      | "invalid_input"
      | "upload_unavailable"
      | "parser_unavailable"
      | "claim_invalid"
      | "claim_count_invalid",
    message: string,
  ) {
    super(message);
    this.name = "FirstEncounterIngestionError";
  }
}

type Preview = typeof previewPortal837P;

export async function ingestFirstEncounter(params: {
  input: z.input<typeof inputSchema>;
  principal: FastApiPrincipal;
  preview?: Preview;
}): Promise<{ encounterId: string; created: boolean }> {
  const parsed = inputSchema.safeParse(params.input);
  if (!parsed.success) {
    throw new FirstEncounterIngestionError(
      "invalid_input",
      parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; "),
    );
  }
  const input = parsed.data;
  const uploadRoot = path.resolve(process.cwd(), "uploads");
  const absolutePath = path.resolve(process.cwd(), input.filePath);
  if (!absolutePath.startsWith(`${uploadRoot}${path.sep}`)) {
    throw new FirstEncounterIngestionError("invalid_input", "filePath is outside the upload directory");
  }

  let plaintext: Buffer;
  try {
    plaintext = decryptPortalBuffer(await readFile(absolutePath));
  } catch {
    throw new FirstEncounterIngestionError(
      "upload_unavailable",
      "The encrypted upload could not be read. Upload the 837P again.",
    );
  }
  const digest = createHash("sha256")
    .update(`${input.tenantId}\0`, "utf8")
    .update(plaintext)
    .digest("hex");
  const existing = await prisma.encounter.findUnique({
    where: { sourceUploadDigest: digest },
    select: { id: true, tenantId: true },
  });
  if (existing) {
    if (existing.tenantId !== input.tenantId) {
      throw new FirstEncounterIngestionError("claim_invalid", "Upload digest tenant mismatch");
    }
    return { encounterId: existing.id, created: false };
  }

  const preview = await (params.preview ?? previewPortal837P)(
    input.fileName,
    plaintext,
    params.principal,
  );
  if (preview.kind !== "ok") {
    throw new FirstEncounterIngestionError(
      "parser_unavailable",
      "The claim parser is temporarily unavailable. Try again without re-uploading.",
    );
  }
  const row = requireSingleValidClaim(preview.data);
  const dateOfService = new Date(`${row.date_of_service}T00:00:00.000Z`);
  if (Number.isNaN(dateOfService.valueOf())) {
    throw new FirstEncounterIngestionError("claim_invalid", "The 837P date of service is invalid");
  }
  const lines = row.CPT_codes.map((value) => {
    const [code, modifier] = value.split("-", 2);
    return { code, ...(modifier ? { modifier } : {}) };
  });
  const tenant = await prisma.tenant.findUnique({
    where: { id: input.tenantId },
    select: { clinicName: true, name: true },
  });
  if (!tenant) {
    throw new FirstEncounterIngestionError("invalid_input", "Tenant does not exist");
  }
  const claimPayload = {
    lines,
    diagnosisCodes: row.diagnosis_codes,
    totalCents: 0,
    payer: "AHCIP",
    providerNpi: row.NPI!,
    providerName: tenant.clinicName || tenant.name,
    dateOfService: row.date_of_service!,
  };

  try {
    const encounter = await prisma.$transaction(async (tx) => {
      const claim = await tx.encounterClaim.create({
        data: {
          payer: claimPayload.payer,
          providerNpi: claimPayload.providerNpi,
          providerName: claimPayload.providerName,
          cptCodesJson: JSON.stringify(claimPayload),
          billedCents: claimPayload.totalCents,
        },
      });
      return tx.encounter.create({
        data: {
          tenantId: input.tenantId,
          sourceUploadDigest: digest,
          patientHash: hashPatientId(row.patient_id!),
          dateOfService,
          specialty: input.specialty,
          clinicalNote: encryptPortalString(input.clinicalNote),
          claimId: claim.id,
          status: "pending",
        },
        select: { id: true },
      });
    });
    return { encounterId: encounter.id, created: true };
  } catch (error) {
    const raced = await prisma.encounter.findUnique({
      where: { sourceUploadDigest: digest },
      select: { id: true, tenantId: true },
    });
    if (raced?.tenantId === input.tenantId) {
      return { encounterId: raced.id, created: false };
    }
    throw error;
  }
}

function requireSingleValidClaim(preview: Portal837Preview) {
  if (preview.error) {
    throw new FirstEncounterIngestionError("claim_invalid", preview.error);
  }
  if (preview.rows.length !== 1) {
    throw new FirstEncounterIngestionError(
      "claim_count_invalid",
      `The first-audit upload must contain exactly one claim; parsed ${preview.rows.length}.`,
    );
  }
  const row = preview.rows[0]!;
  if (row.errors.length > 0) {
    throw new FirstEncounterIngestionError("claim_invalid", row.errors.join("; "));
  }
  if (
    !row.patient_id ||
    !row.NPI ||
    !row.date_of_service ||
    row.CPT_codes.length === 0
  ) {
    throw new FirstEncounterIngestionError(
      "claim_invalid",
      "The 837P claim is missing patient, provider, date, or service-code data.",
    );
  }
  return row;
}
