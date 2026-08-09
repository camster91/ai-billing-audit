// POST /api/onboarding/upload
//
// multipart/form-data with field `file` (a single 837P file, up to
// 20MB). Returns { filePath, fileName, size }.
//
// The file is encrypted and staged under a server-local directory for a
// future audit-engine handoff. We never trust the client filename for storage
// — we generate a uuid-based path and remember the original name for
// display purposes only.
//
// In production this would write to S3 (or the equivalent
// residency-region bucket per the wizard's dataResidencyRegion
// setting). For the dev/staging build we just write to a
// project-local `uploads/` directory.

import { NextResponse } from "next/server";
import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { requireOnboardingAuth } from "@/lib/onboarding-auth";
import { OnboardingError } from "@/lib/onboarding";
import { encryptPortalBuffer } from "@/lib/data-encryption";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BYTES = 20 * 1024 * 1024; // 20 MB
const UPLOAD_DIR = path.join(process.cwd(), "uploads");

export async function POST(request: Request) {
  let tenantId = "";
  let file: File | null = null;

  try {
    const form = await request.formData();
    const raw = form.get("file");
    const tid = form.get("tenantId");
    if (typeof tid === "string") tenantId = tid;
    if (raw instanceof File) file = raw;
  } catch {
    return NextResponse.json(
      { error: "invalid_form", message: "Expected multipart/form-data" },
      { status: 400 },
    );
  }

  if (!file) {
    return NextResponse.json(
      { error: "missing_file", message: "Field 'file' is required" },
      { status: 400 },
    );
  }
  if (file.size === 0) {
    return NextResponse.json(
      { error: "empty_file", message: "file is empty" },
      { status: 400 },
    );
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json(
      {
        error: "file_too_large",
        message: `file exceeds ${MAX_BYTES / 1024 / 1024}MB limit`,
      },
      { status: 413 },
    );
  }

  try {
    await requireOnboardingAuth(tenantId);
  } catch (e) {
    return mapAuthError(e);
  }

  const safeOriginal = file.name
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .slice(0, 200) || "encounter.837";
  const id = randomUUID();
  const storedName = `${id}__${safeOriginal}`;
  await mkdir(UPLOAD_DIR, { recursive: true });
  const storedPath = path.join(UPLOAD_DIR, storedName);
  const buffer = Buffer.from(await file.arrayBuffer());
  await writeFile(storedPath, encryptPortalBuffer(buffer), { flag: "wx" });

  return NextResponse.json(
    {
      filePath: `uploads/${storedName}`,
      fileName: file.name,
      size: file.size,
      encryptedAtRest: true,
    },
    { status: 200 },
  );
}

function mapAuthError(e: unknown): NextResponse {
  if (e instanceof OnboardingError) {
    const status =
      e.code === "unauthenticated"
        ? 401
        : e.code === "forbidden"
          ? 403
          : 400;
    return NextResponse.json(
      { error: e.code, message: e.message },
      { status },
    );
  }
  const message = e instanceof Error ? e.message : "unknown error";
  console.error("[/api/onboarding/upload] error:", message);
  return NextResponse.json({ error: "internal_error" }, { status: 500 });
}
