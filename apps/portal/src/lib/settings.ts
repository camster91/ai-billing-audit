// Settings library — the server-side heart of the post-onboarding
// /settings page (task t_1bab62b6).
//
// The /settings page is the long-lived surface for clinic-level
// preferences; the /portal/onboarding wizard handles the first-run
// experience. Both write to the same Tenant columns, so the schemas
// here intentionally mirror the wizard's clinicProfileSchema and
// residencyRegionSchema shapes — a value that validates at the
// wizard's `clinic-profile` step also validates here. (We don't
// share the schemas via import because the wizard wraps them in a
// step-gate that /settings doesn't need.)
//
// Three exported functions back the API routes:
//   saveClinicProfileSettings({ tenantId, input })
//     Persists the four clinic-profile fields. Re-validation runs
//     on every save (the wizard might have skipped them or the
//     user might want to edit later).
//
//   saveResidencyRegionSettings({ tenantId, input })
//     Persists the data residency region. Rejects once the region
//     is locked — either explicitly via `residencyRegionLocked`
//     (set on wizard completion) OR implicitly by the existence
//     of an Encounter row for the tenant (per the spec, the region
//     becomes immutable after the first audit has been recorded).
//
//   savePhiRedactionSettings({ tenantId, redact })
//     Persists the redactPatientNamesInExports flag. The default
//     is true; the user can flip it from the /settings UI.
//
// Plus a typed error class (SettingsError) for the routes to map.

import { prisma } from "@/lib/prisma";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Mirrors src/lib/onboarding.ts. Kept in sync with the wizard's region
 * list so the two surfaces stay in lockstep. */
export const RESIDENCY_REGIONS = ["ca-central-1", "us-east-1"] as const;
export type ResidencyRegion = (typeof RESIDENCY_REGIONS)[number];

/** Loose IANA tz shape — same regex as the wizard. The portal doesn't
 * gate on a full IANA list server-side. */
const TIMEZONE_RE = /^[A-Za-z][A-Za-z0-9+_\-/]{1,40}$/;

/** 10-digit NPI for US; looser 6–15 char alphanumeric for non-US
 * clinics (e.g. Canadian provincial IDs). */
const NPI_RE = /^[A-Za-z0-9]{6,15}$/;

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

/** The four clinic-profile fields, all optional. The user can blank
 * a field by sending an empty string; we persist null in that case
 * (so the UI shows a placeholder rather than a stale value). */
export const clinicProfileSettingsSchema = z.object({
  clinicName: z
    .string()
    .trim()
    .max(120, "clinic name must be 120 characters or fewer")
    .optional()
    .or(z.literal("")),
  clinicAddress: z
    .string()
    .trim()
    .max(500, "clinic address must be 500 characters or fewer")
    .optional()
    .or(z.literal("")),
  clinicNpi: z
    .string()
    .trim()
    .max(15)
    .regex(NPI_RE, "clinic NPI must be 6–15 letters or digits")
    .optional()
    .or(z.literal("")),
  clinicTimezone: z
    .string()
    .trim()
    .max(64)
    .regex(TIMEZONE_RE, "clinic timezone must look like an IANA name")
    .optional()
    .or(z.literal("")),
});

export const residencyRegionSettingsSchema = z.object({
  region: z.enum(RESIDENCY_REGIONS),
});

export const phiRedactionSettingsSchema = z.object({
  redact: z.boolean(),
});

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ClinicProfileSettingsInput {
  clinicName?: string;
  clinicAddress?: string;
  clinicNpi?: string;
  clinicTimezone?: string;
}

export interface ResidencySettingsInput {
  region: ResidencyRegion;
}

// ---------------------------------------------------------------------------
// Audit-count helper
// ---------------------------------------------------------------------------

/**
 * True when any Encounter row exists for the tenant. The /settings
 * spec uses this as the trigger for locking the data-residency
 * selector: once the first audit has been recorded, the region is
 * immutable. We also re-check `residencyRegionLocked` (the legacy
 * wizard-completion flag) for backward-compat with tenants that
 * completed the wizard but never ran an audit.
 */
export async function tenantHasAudit(tenantId: string): Promise<boolean> {
  const row = await prisma.encounter.findFirst({
    where: { tenantId },
    select: { id: true },
  });
  return row !== null;
}

// ---------------------------------------------------------------------------
// Save functions
// ---------------------------------------------------------------------------

export async function saveClinicProfileSettings(params: {
  tenantId: string;
  input: ClinicProfileSettingsInput;
}): Promise<{
  tenantId: string;
  clinicName: string | null;
  clinicAddress: string | null;
  clinicNpi: string | null;
  clinicTimezone: string | null;
}> {
  const parsed = clinicProfileSettingsSchema.safeParse(params.input);
  if (!parsed.success) {
    throw new SettingsError(
      "invalid_input",
      parsed.error.issues
        .map((i) => `${i.path.join(".")}: ${i.message}`)
        .join("; "),
    );
  }

  const existing = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
    select: { id: true },
  });
  if (!existing) {
    throw new SettingsError("not_found", "Tenant not found");
  }

  // Empty strings from the form mean "clear the field" → persist null.
  const updated = await prisma.tenant.update({
    where: { id: params.tenantId },
    data: {
      clinicName: parsed.data.clinicName
        ? parsed.data.clinicName
        : null,
      clinicAddress: parsed.data.clinicAddress
        ? parsed.data.clinicAddress
        : null,
      clinicNpi: parsed.data.clinicNpi ? parsed.data.clinicNpi : null,
      clinicTimezone: parsed.data.clinicTimezone
        ? parsed.data.clinicTimezone
        : null,
    },
    select: {
      clinicName: true,
      clinicAddress: true,
      clinicNpi: true,
      clinicTimezone: true,
    },
  });

  return {
    tenantId: params.tenantId,
    clinicName: updated.clinicName,
    clinicAddress: updated.clinicAddress,
    clinicNpi: updated.clinicNpi,
    clinicTimezone: updated.clinicTimezone,
  };
}

export async function saveResidencyRegionSettings(params: {
  tenantId: string;
  input: ResidencySettingsInput;
}): Promise<{ tenantId: string; region: ResidencyRegion }> {
  const parsed = residencyRegionSettingsSchema.safeParse(params.input);
  if (!parsed.success) {
    throw new SettingsError(
      "invalid_input",
      parsed.error.issues
        .map((i) => `${i.path.join(".")}: ${i.message}`)
        .join("; "),
    );
  }

  const existing = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
    select: { id: true, residencyRegionLocked: true },
  });
  if (!existing) {
    throw new SettingsError("not_found", "Tenant not found");
  }

  // The region is immutable once any of these is true:
  //   - the wizard set residencyRegionLocked on completion
  //   - the tenant has at least one Encounter row (first audit landed)
  // The spec's acceptance criterion is the second condition; we also
  // honor the first for tenants that completed the wizard but never
  // ran an audit.
  if (existing.residencyRegionLocked) {
    throw new SettingsError(
      "region_locked",
      "Data residency region is locked. It cannot be changed after the wizard completed.",
    );
  }
  if (await tenantHasAudit(params.tenantId)) {
    throw new SettingsError(
      "region_locked",
      "Data residency region is locked. It cannot be changed after the first audit has been recorded.",
    );
  }

  const updated = await prisma.tenant.update({
    where: { id: params.tenantId },
    data: { dataResidencyRegion: parsed.data.region },
    select: { dataResidencyRegion: true },
  });

  return {
    tenantId: params.tenantId,
    region: updated.dataResidencyRegion as ResidencyRegion,
  };
}

export async function savePhiRedactionSettings(params: {
  tenantId: string;
  redact: boolean;
}): Promise<{ tenantId: string; redact: boolean }> {
  const parsed = phiRedactionSettingsSchema.safeParse({
    redact: params.redact,
  });
  if (!parsed.success) {
    throw new SettingsError(
      "invalid_input",
      parsed.error.issues
        .map((i) => `${i.path.join(".")}: ${i.message}`)
        .join("; "),
    );
  }

  const existing = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
    select: { id: true },
  });
  if (!existing) {
    throw new SettingsError("not_found", "Tenant not found");
  }

  await prisma.tenant.update({
    where: { id: params.tenantId },
    data: { redactPatientNamesInExports: parsed.data.redact },
  });

  return { tenantId: params.tenantId, redact: parsed.data.redact };
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/** Typed error for /settings write failures. Mapped to HTTP status by
 * the API route layer. */
export class SettingsError extends Error {
  public readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "SettingsError";
    this.code = code;
  }
}
