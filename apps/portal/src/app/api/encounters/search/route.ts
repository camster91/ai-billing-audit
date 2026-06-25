// /api/encounters/search — used by the 404 page to find a stale-link
// target by encounter id or patient hash.

import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { getActiveTenant } from "@/lib/active-tenant";
import { prisma } from "@/lib/prisma";

export async function GET(req: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ results: [] }, { status: 401 });
  }
  const tenant = await getActiveTenant();
  if (!tenant) {
    return NextResponse.json({ results: [] }, { status: 200 });
  }
  const q = (req.nextUrl.searchParams.get("q") ?? "").trim();
  if (!q || q.length < 2) {
    return NextResponse.json({ results: [] });
  }
  // Search by encounter id prefix or patient hash prefix. Limit to 10.
  const rows = await prisma.encounter.findMany({
    where: {
      tenantId: tenant.id,
      OR: [
        { id: { startsWith: q } },
        { patientHash: { startsWith: q.toLowerCase() } },
      ],
    },
    orderBy: { dateOfService: "desc" },
    take: 10,
    select: {
      id: true,
      dateOfService: true,
      patientHash: true,
      findings: { where: { status: "pending" }, take: 1, select: { id: true } },
    },
  });
  return NextResponse.json({
    results: rows.map((r) => ({
      id: r.id,
      dateOfService: r.dateOfService.toISOString().slice(0, 10),
      patientHash: r.patientHash.slice(0, 12),
      isFlagged: r.findings.length > 0,
    })),
  });
}
