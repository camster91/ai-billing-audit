// /api/maintenance — public (no auth) endpoint reporting maintenance status.
// Used by the site-wide banner. Toggled via env var so we can flip it
// during a deploy without a code change.
//
// ZORVA_MAINTENANCE=1     → active, info severity, generic message
// ZORVA_MAINTENANCE_MESSAGE="..."   → custom message
// ZORVA_MAINTENANCE_SEVERITY=info|warn|critical  → severity
// ZORVA_MAINTENANCE_FORCE=1         → banner cannot be dismissed

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const active = process.env.ZORVA_MAINTENANCE === "1";
  if (!active) {
    return NextResponse.json({ active: false });
  }
  return NextResponse.json({
    active: true,
    message:
      process.env.ZORVA_MAINTENANCE_MESSAGE ??
      "Zorva is undergoing scheduled maintenance. Findings may be slower than usual.",
    severity: process.env.ZORVA_MAINTENANCE_SEVERITY ?? "info",
    force: process.env.ZORVA_MAINTENANCE_FORCE === "1",
  });
}
