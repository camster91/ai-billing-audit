// POST /api/audit/run
// Tenant-scoped bridge from a persisted portal encounter to the audit engine.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import {
  finalizeAuditDispatch,
  releaseAuditDispatchReservation,
  reserveAuditDispatch,
} from "@/lib/audit-quota";
import { decryptPortalString } from "@/lib/data-encryption";
import { parsePortalClaimLines } from "@/lib/audit-submission";
import { submitPortalAudit } from "@/lib/fastapi";
import { assertMembershipCapability } from "@/lib/membership-gate";
import { prisma } from "@/lib/prisma";
import { z } from "zod";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const auditRunBodySchema = z.object({
  encounterId: z.string().min(1).max(128),
}).strict();
const noStoreHeaders = { "Cache-Control": "private, no-store" };

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json({ error: "no_tenant" }, { status: 403 });
  }
  const gate = await assertMembershipCapability(session.user.id, tenant.id, "write");
  if (!gate.ok) {
    return NextResponse.json({ error: gate.error ?? "forbidden" }, { status: 403 });
  }

  let input: z.infer<typeof auditRunBodySchema>;
  try {
    input = auditRunBodySchema.parse(await request.json());
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const reservation = await reserveAuditDispatch({
    tenantId: tenant.id,
    encounterId: input.encounterId,
    origin: new URL(request.url).origin,
  });
  if (reservation.kind === "not_found") {
    return NextResponse.json({ error: "encounter_not_found" }, { status: 404 });
  }
  if (reservation.kind === "blocked") {
    return NextResponse.json(
      {
        error: "audit_quota_exhausted",
        used: reservation.used,
        reserved: reservation.reserved,
        quota: reservation.quota,
        upgradeUrl: reservation.upgradeUrl,
      },
      { status: 402, headers: noStoreHeaders },
    );
  }
  if (reservation.kind === "existing") {
    return NextResponse.json(
      {
        queued: true,
        existing: true,
        jobId: reservation.engineJobId,
        statusUrl: reservation.engineStatusUrl,
      },
      { status: 202, headers: noStoreHeaders },
    );
  }

  const encounter = await prisma.encounter.findFirst({
    where: { id: input.encounterId, tenantId: tenant.id },
    include: { claim: true },
  });
  if (!encounter) {
    await releaseAuditDispatchReservation({
      tenantId: tenant.id,
      encounterId: input.encounterId,
      reason: "encounter_not_found",
    });
    return NextResponse.json({ error: "encounter_not_found" }, { status: 404 });
  }

  let clinicalNote: string;
  let lines: ReturnType<typeof parsePortalClaimLines>;
  try {
    clinicalNote = decryptPortalString(encounter.clinicalNote);
    lines = parsePortalClaimLines(encounter.claim.cptCodesJson);
  } catch {
    await releaseAuditDispatchReservation({
      tenantId: tenant.id,
      encounterId: encounter.id,
      reason: "encounter_data_unavailable",
    });
    return NextResponse.json(
      { error: "encounter_data_unavailable" },
      { status: 500, headers: noStoreHeaders },
    );
  }

  let submitted: Awaited<ReturnType<typeof submitPortalAudit>>;
  try {
    submitted = await submitPortalAudit(
      {
        encounterId: encounter.id,
        patientHash: encounter.patientHash,
        providerNpi: encounter.claim.providerNpi,
        dateOfService: encounter.dateOfService.toISOString().slice(0, 10),
        cptCodes: lines.map((line) =>
          line.modifier ? `${line.code}-${line.modifier}` : line.code,
        ),
        diagnosisCodes: [],
        clinicalNote,
      },
      {
        subject: session.user.id,
        tenantId: tenant.id,
        portalRole: tenant.role,
      },
    );
  } catch {
    return NextResponse.json(
      { error: "audit_engine_unavailable" },
      { status: 503, headers: noStoreHeaders },
    );
  }
  if (submitted.kind === "error") {
    return NextResponse.json(
      { error: "audit_engine_rejected", engineStatus: submitted.status },
      { status: 502, headers: noStoreHeaders },
    );
  }

  const finalized = await finalizeAuditDispatch({
    tenantId: tenant.id,
    encounterId: encounter.id,
    engineJobId: submitted.jobId,
    engineStatusUrl: submitted.statusUrl,
  });
  if (finalized.kind !== "queued") {
    return NextResponse.json(
      { error: "audit_dispatch_finalize_failed" },
      { status: 500, headers: noStoreHeaders },
    );
  }
  return NextResponse.json(
    {
      queued: true,
      existing: finalized.alreadyFinalized,
      jobId: submitted.jobId,
      statusUrl: submitted.statusUrl,
      used: finalized.used,
      quota: finalized.quota,
    },
    { status: 202, headers: noStoreHeaders },
  );
}
