// GET /api/audit/status?encounterId=...
// Poll a tenant-owned engine job and import its terminal result exactly once.

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { importEngineAuditResult } from "@/lib/audit-results";
import { fetchPortalAuditJob } from "@/lib/fastapi";
import { assertMembershipCapability } from "@/lib/membership-gate";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const noStoreHeaders = { "Cache-Control": "private, no-store" };

export async function GET(request: Request) {
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
  const encounterId = new URL(request.url).searchParams.get("encounterId")?.trim();
  if (!encounterId || encounterId.length > 128) {
    return NextResponse.json({ error: "invalid_encounter_id" }, { status: 400 });
  }

  const dispatch = await prisma.auditDispatch.findFirst({
    where: { encounterId, tenantId: tenant.id },
  });
  if (!dispatch) {
    return NextResponse.json({ error: "audit_not_found" }, { status: 404 });
  }
  if (!dispatch.engineJobId) {
    return NextResponse.json(
      { status: "dispatching" },
      { status: 202, headers: noStoreHeaders },
    );
  }
  if (dispatch.resultImportedAt) {
    return NextResponse.json(
      { status: "done", imported: true },
      { headers: noStoreHeaders },
    );
  }

  let result: Awaited<ReturnType<typeof fetchPortalAuditJob>>;
  try {
    result = await fetchPortalAuditJob(dispatch.engineJobId, {
      subject: session.user.id,
      tenantId: tenant.id,
      portalRole: tenant.role,
    });
  } catch {
    return NextResponse.json(
      { error: "audit_engine_unavailable", status: dispatch.status },
      { status: 503, headers: noStoreHeaders },
    );
  }
  if (result.kind === "not_found") {
    return NextResponse.json(
      { error: "engine_job_not_found", status: dispatch.status },
      { status: 502, headers: noStoreHeaders },
    );
  }
  if (result.kind === "error") {
    return NextResponse.json(
      { error: "audit_engine_unavailable", status: dispatch.status },
      { status: 502, headers: noStoreHeaders },
    );
  }

  const { job } = result;
  if (job.status === "failed" || job.status === "canceled") {
    await prisma.$transaction([
      prisma.auditDispatch.update({
        where: { id: dispatch.id },
        data: {
          status: "failed",
          completedAt: new Date(),
          lastError: "engine_job_failed",
        },
      }),
      prisma.encounter.update({
        where: { id: encounterId },
        data: { status: "pending" },
      }),
    ]);
    return NextResponse.json(
      { status: "failed", error: "audit_job_failed" },
      { headers: noStoreHeaders },
    );
  }
  if (job.status === "done") {
    if (!job.result || !Array.isArray(job.result.findings)) {
      return NextResponse.json(
        { error: "engine_result_invalid" },
        { status: 502, headers: noStoreHeaders },
      );
    }
    const imported = await importEngineAuditResult({
      tenantId: tenant.id,
      encounterId,
      engineJobId: dispatch.engineJobId,
      findings: job.result.findings,
    });
    if (imported.kind === "not_found") {
      return NextResponse.json(
        { error: "audit_dispatch_not_found" },
        { status: 404, headers: noStoreHeaders },
      );
    }
    return NextResponse.json(
      { status: "done", imported: true, findings: imported.count },
      { headers: noStoreHeaders },
    );
  }

  await prisma.auditDispatch.update({
    where: { id: dispatch.id },
    data: { status: job.status === "running" ? "running" : "queued" },
  });
  return NextResponse.json(
    { status: job.status },
    { status: 202, headers: noStoreHeaders },
  );
}
