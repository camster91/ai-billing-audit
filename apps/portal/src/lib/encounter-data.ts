// Server-side data access for the encounter review surface.
//
// Every query here is tenant-scoped: the caller's `tenantId` is
// resolved from the active session and added to the WHERE clause.
// There is no helper that fetches an encounter by id without the
// tenant filter — that's a deliberate footgun-prevention measure for
// future contributors. If you need cross-tenant access, write a
// separate `loadEncounterForAdmin` and gate it behind the admin role.

import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import type { ClaimPayload } from "@/lib/encounter-types";
import { parseClaimPayload } from "@/lib/encounter-format";
import {
  decryptPortalNullableString,
  decryptPortalString,
} from "@/lib/data-encryption";

export interface EncounterDetail {
  id: string;
  tenantId: string;
  patientHash: string;
  dateOfService: Date;
  specialty: string;
  clinicalNote: string;
  status: string;
  auditDispatch: {
    status: string;
    engineJobId: string | null;
  } | null;
  claim: {
    id: string;
    payer: string;
    providerNpi: string;
    providerName: string;
    cptCodesJson: string;
    billedCents: number;
    /** Parsed claim payload; null when the JSON is malformed. */
    parsed: ClaimPayload | null;
  };
  findings: FindingDetail[];
}

export interface FindingDetail {
  id: string;
  encounterId: string;
  category: string;
  billingRuleReference: string;
  currentCode: string | null;
  suggestedCode: string | null;
  evidenceQuote: string;
  estFinancialImpactCents: number;
  status: string;
  dismissReason: string | null;
  dismissText: string | null;
  actionedByUserId: string | null;
  actionedAt: Date | null;
  createdAt: Date;
}

/**
 * Load an encounter and its findings for the /encounters/[id] page.
 * Tenant-scoped — returns null when the encounter doesn't exist OR
 * when the encounter belongs to a different tenant (the caller can't
 * tell the difference, which is the right behavior).
 */
export async function loadEncounterDetail(
  encounterId: string,
  tenantId: string,
): Promise<EncounterDetail | null> {
  const row = await prisma.encounter.findFirst({
    where: { id: encounterId, tenantId },
    include: {
      claim: true,
      findings: {
        orderBy: [{ status: "asc" }, { createdAt: "asc" }],
      },
      auditDispatch: {
        select: { status: true, engineJobId: true },
      },
    },
  });
  if (!row) return null;

  return {
    id: row.id,
    tenantId: row.tenantId,
    patientHash: row.patientHash,
    dateOfService: row.dateOfService,
    specialty: row.specialty,
    clinicalNote: decryptPortalString(row.clinicalNote),
    status: row.status,
    auditDispatch: row.auditDispatch,
    claim: {
      id: row.claim.id,
      payer: row.claim.payer,
      providerNpi: row.claim.providerNpi,
      providerName: row.claim.providerName,
      cptCodesJson: row.claim.cptCodesJson,
      billedCents: row.claim.billedCents,
      parsed: parseClaimPayload(row.claim.cptCodesJson),
    },
    findings: row.findings.map((f) => ({
      id: f.id,
      encounterId: f.encounterId,
      category: f.category,
      billingRuleReference: f.billingRuleReference,
      currentCode: f.currentCode,
      suggestedCode: f.suggestedCode,
      evidenceQuote: decryptPortalString(f.evidenceQuote),
      estFinancialImpactCents: f.estFinancialImpactCents,
      status: f.status,
      dismissReason: f.dismissReason,
      dismissText: decryptPortalNullableString(f.dismissText),
      actionedByUserId: f.actionedByUserId,
      actionedAt: f.actionedAt,
      createdAt: f.createdAt,
    })),
  };
}

/**
 * Resolve an encounter id, looking it up by tenant scope. Throws via
 * Next's `notFound()` when the encounter doesn't exist (or belongs to
 * another tenant) — this is the page-level helper.
 */
export async function requireEncounter(
  encounterId: string,
  tenantId: string,
): Promise<EncounterDetail> {
  const detail = await loadEncounterDetail(encounterId, tenantId);
  if (!detail) notFound();
  return detail;
}
