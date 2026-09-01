import { z } from "zod";
import {
  claimLineSchema,
  claimPayloadSchema,
  type ClaimLine,
} from "@/lib/encounter-types";

const legacyClaimLinesSchema = z.array(claimLineSchema).min(1);

/** Read both the canonical `{ lines, ... }` claim and pre-migration arrays. */
export function parsePortalClaimLines(json: string): ClaimLine[] {
  const parsed: unknown = JSON.parse(json);
  const canonical = claimPayloadSchema.safeParse(parsed);
  if (canonical.success) return canonical.data.lines;
  return legacyClaimLinesSchema.parse(parsed);
}

/** Diagnosis codes are retained in canonical claims; legacy claims had none. */
export function parsePortalDiagnosisCodes(json: string): string[] {
  const parsed: unknown = JSON.parse(json);
  const canonical = claimPayloadSchema.safeParse(parsed);
  return canonical.success ? canonical.data.diagnosisCodes : [];
}
