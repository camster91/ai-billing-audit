// Status / category / reason value sets for the encounter review surface.
//
// The Prisma schema (prisma/schema.prisma) stores these as plain `String`
// columns because SQLite has no native ENUM type. These TS unions and
// Zod schemas are the single source of truth — every API route and
// server component imports from here, and the validation error messages
// reference these names verbatim. When the datasource moves to
// PostgreSQL, replace the Zod refinement with a real Prisma enum and
// the call sites don't change.
//
// The values mirror the docstring block at the top of schema.prisma.

import { z } from "zod";

// ---------------------------------------------------------------------------
// Encounters
// ---------------------------------------------------------------------------

export const ENCOUNTER_STATUSES = [
  "pending",
  "auditing",
  "awaiting_review",
  "completed",
] as const;

export type EncounterStatus = (typeof ENCOUNTER_STATUSES)[number];

export const ENCOUNTER_STATUS_SET: ReadonlySet<EncounterStatus> = new Set(
  ENCOUNTER_STATUSES,
);

export const encounterStatusSchema = z.enum(ENCOUNTER_STATUSES);

// ---------------------------------------------------------------------------
// Findings
// ---------------------------------------------------------------------------

export const FINDING_CATEGORIES = [
  "em_level",
  "documentation",
  "medical_necessity",
  "modifier",
  "code_mismatch",
  "payer_policy",
  "other",
] as const;

export type FindingCategory = (typeof FINDING_CATEGORIES)[number];

export const findingCategorySchema = z.enum(FINDING_CATEGORIES);

// Human-readable label used in the split-screen badge. Keep in sync with
// the audit board's category taxonomy (Zorva §3.2).
export const FINDING_CATEGORY_LABEL: Record<FindingCategory, string> = {
  em_level: "E/M level",
  documentation: "Documentation",
  medical_necessity: "Medical necessity",
  modifier: "Modifier",
  code_mismatch: "Code mismatch",
  payer_policy: "Payer policy",
  other: "Other",
};

export const FINDING_STATUSES = ["pending", "accepted", "dismissed"] as const;
export type FindingStatus = (typeof FINDING_STATUSES)[number];

export const findingStatusSchema = z.enum(FINDING_STATUSES);

// ---------------------------------------------------------------------------
// Dismiss reasons
// ---------------------------------------------------------------------------

export const DISMISS_REASONS = [
  "wrong_payer_policy",
  "hallucinated_fact",
  "too_conservative",
  "other_with_text",
] as const;

export type DismissReason = (typeof DISMISS_REASONS)[number];

export const dismissReasonSchema = z.enum(DISMISS_REASONS);

export const DISMISS_REASON_LABEL: Record<DismissReason, string> = {
  wrong_payer_policy: "Wrong payer policy",
  hallucinated_fact: "Hallucinated fact",
  too_conservative: "Too conservative",
  other_with_text: "Other (specify)",
};

// ---------------------------------------------------------------------------
// Audit action verbs
// ---------------------------------------------------------------------------

export const AUDIT_ACTIONS = ["accept", "dismiss"] as const;
export type AuditAction = (typeof AUDIT_ACTIONS)[number];

// ---------------------------------------------------------------------------
// EncounterClaim shape
// ---------------------------------------------------------------------------

export const claimLineSchema = z.object({
  code: z.string().min(1),
  modifier: z.string().nullable().optional(),
  units: z.number().int().nonnegative().optional(),
  description: z.string().optional(),
});

export type ClaimLine = z.infer<typeof claimLineSchema>;

export const claimPayloadSchema = z.object({
  lines: z.array(claimLineSchema).min(1),
  totalCents: z.number().int().nonnegative(),
  payer: z.string().min(1),
  providerNpi: z.string().min(1),
  providerName: z.string().min(1),
  dateOfService: z.string().min(1), // ISO date
});

export type ClaimPayload = z.infer<typeof claimPayloadSchema>;

// ---------------------------------------------------------------------------
// Route input schemas
// ---------------------------------------------------------------------------

// POST /api/encounters/[id]/findings/[findingId]/accept
// Empty body — the user is identified via the auth session.
export const acceptInputSchema = z.object({}).strict();

// POST /api/encounters/[id]/findings/[findingId]/dismiss
// Body: { reason: DismissReason, reasonText?: string }
//
// When reason === "other_with_text", reasonText is required and must
// be a non-empty trimmed string of 1-2000 characters. The 2k cap is
// defensive — the audit log row stores the text verbatim and the
// runbook reviewer (an OIPC auditor) needs to read it offline.
export const dismissInputSchema = z
  .object({
    reason: dismissReasonSchema,
    reasonText: z.string().max(2000).optional(),
  })
  .strict()
  .refine(
    (value) =>
      value.reason !== "other_with_text" ||
      (typeof value.reasonText === "string" &&
        value.reasonText.trim().length > 0 &&
        value.reasonText.trim().length <= 2000),
    {
      message:
        "reasonText is required (1-2000 characters) when reason is other_with_text",
      path: ["reasonText"],
    },
  );

export type DismissInput = z.infer<typeof dismissInputSchema>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Type guard for the encounter status string column. */
export function isEncounterStatus(value: string): value is EncounterStatus {
  return ENCOUNTER_STATUS_SET.has(value as EncounterStatus);
}

/** Type guard for the finding category string column. */
export function isFindingCategory(value: string): value is FindingCategory {
  return (FINDING_CATEGORIES as readonly string[]).includes(value);
}

/** Type guard for the finding status string column. */
export function isFindingStatus(value: string): value is FindingStatus {
  return (FINDING_STATUSES as readonly string[]).includes(value);
}

/** Type guard for the dismiss reason string column. */
export function isDismissReason(value: string | null | undefined): value is DismissReason {
  if (typeof value !== "string") return false;
  return (DISMISS_REASONS as readonly string[]).includes(value);
}
