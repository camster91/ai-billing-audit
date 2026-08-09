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
