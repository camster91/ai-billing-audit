// Anchor resolution for the audit-log-export self-logging row.
//
// Every successful /api/audit/export call appends one `audit_log_export`
// row to the tenant's chain so the privacy officer can see who pulled
// what, when. `AuditTrailEntry` carries two non-null FKs — `findingId`
// and `encounterId` — but an export is not bound to any single finding.
// Rather than widen those columns (which would change the shared table
// shape and the Python/SQL chain contract), the export row borrows the
// tenant's oldest finding's (findingId, encounterId) pair as a stable
// anchor and records the truthful export metadata in `dataElements`.
//
// Note the chain payload's `patientHash` comes from the anchor
// *encounter*, not the finding — `patientHash` lives on `Encounter`
// (see prisma/schema.prisma), and the finding reaches it through its
// own `encounter` relation.
//
// The anchor is resolved server-side and cached per tenant so a privacy
// officer pulling a year of activity does not pay for a lookup on every
// call.

import { prisma } from "@/lib/prisma";

export interface AuditExportAnchor {
  findingId: string;
  encounterId: string;
  patientHash: string;
}

// Keyed by tenantId. Bounded in practice by the number of tenants that
// ever export; the value is a single small object.
const anchorCache = new Map<string, AuditExportAnchor>();

/**
 * The synthetic finding id used, together with the anchor encounter, to
 * label a self-logging export row. Kept stable so downstream filters can
 * recognise an export row without parsing `dataElements`.
 *
 * NOT a real finding id: it is never used as a foreign key. The row's
 * FKs always point at the resolved anchor pair.
 */
export const AUDIT_EXPORT_FINDING_ID = "__audit_export__";

export class NoAuditExportAnchorError extends Error {
  constructor(tenantId: string) {
    super(
      `tenant ${tenantId} has no finding to anchor the audit-export ` +
        `self-logging row to`,
    );
    this.name = "NoAuditExportAnchorError";
  }
}

/**
 * Resolve (and cache) the anchor triple for a tenant.
 *
 * Throws {@link NoAuditExportAnchorError} when the tenant has no findings
 * at all — in that case there is nothing in the chain to anchor to and
 * the caller must decide how to record the export.
 */
export async function resolveAuditExportAnchor(
  tenantId: string,
): Promise<AuditExportAnchor> {
  const cached = anchorCache.get(tenantId);
  if (cached) return cached;

  // Oldest finding on the tenant's oldest encounter — deterministic, so
  // every export row for a tenant anchors to the same real pair and the
  // chain walk stays reproducible. Selects only the three fields the
  // chain row needs (patientHash comes off the related encounter).
  const finding = await prisma.finding.findFirst({
    where: { encounter: { tenantId } },
    orderBy: [{ encounterId: "asc" }, { id: "asc" }],
    select: {
      id: true,
      encounterId: true,
      encounter: { select: { patientHash: true } },
    },
  });

  if (!finding) {
    throw new NoAuditExportAnchorError(tenantId);
  }

  const anchor: AuditExportAnchor = {
    findingId: finding.id,
    encounterId: finding.encounterId,
    patientHash: finding.encounter.patientHash,
  };
  anchorCache.set(tenantId, anchor);
  return anchor;
}

/** Test/ops hook — drop the cached anchor for one tenant or all of them. */
export function clearAuditExportAnchorCache(tenantId?: string): void {
  if (tenantId === undefined) {
    anchorCache.clear();
  } else {
    anchorCache.delete(tenantId);
  }
}
