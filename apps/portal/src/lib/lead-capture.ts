import { prisma } from "@/lib/prisma";

export interface PublicLeadCaptureInput {
  name: string;
  clinicName: string;
  email: string;
  claimVolume: number | null;
  billingSetup: string;
}

export function normalizeLeadIdentity(email: string): string {
  return email.trim().toLowerCase();
}

/**
 * Capture a public request against one canonical contact record. A repeated
 * submission never rewrites the operator-managed pipeline or qualification
 * decision; it only records that demand recurred and when it happened.
 */
export async function capturePublicLead(input: PublicLeadCaptureInput, now = new Date()) {
  const dedupeKey = normalizeLeadIdentity(input.email);
  const lead = await prisma.lead.upsert({
    where: { dedupeKey },
    create: {
      name: input.name,
      clinicName: input.clinicName,
      email: dedupeKey,
      dedupeKey,
      submissionCount: 1,
      lastSubmittedAt: now,
      claimVolume: input.claimVolume,
      billingSetup: input.billingSetup,
    },
    update: {
      submissionCount: { increment: 1 },
      lastSubmittedAt: now,
    },
    select: { id: true, submissionCount: true },
  });
  return { ...lead, deduplicated: lead.submissionCount > 1 };
}
