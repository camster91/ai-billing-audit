// POST /api/team/invite
//
// Body: { email: string, role: "owner" | "auditor" | "viewer" }
//
// Authorization: caller must have the `team` capability (i.e. be
// an owner or admin of the active tenant). The route enforces
// the role check via requireTenantRole before doing any work.
//
// Behavior:
//   1. Validate the email + role at the boundary (Zod).
//   2. Lower-case the email; reject empty / over-long values.
//   3. Look up the tenant. (Auth helper has already confirmed
//      membership.)
//   4. Reject the invite if a Membership for that email already
//      exists in the active or pending state for the same tenant
//      — prevents accidental duplicate invites. Inactive rows
//      are reused (re-invite flips status back to "pending" with
//      a fresh token).
//   5. Generate a one-time invite token (32-byte hex).
//   6. Create the Membership row in "pending" status, send the
//      invite email through the shared dispatcher.
//   7. Return { membership: { id, email, role, status, invitedAt } }.
//
// Errors:
//   - 400 invalid_input on bad body
//   - 401 unauthenticated, 403 no_tenant (handled by helper)
//   - 409 already_a_member when an active/pending membership
//     already exists for that email
//   - 500 invite_send_failed when the email dispatch itself
//     errors (the DB row is rolled back)

import { NextResponse } from "next/server";
import { z } from "zod";
import { randomBytes } from "node:crypto";
import { prisma } from "@/lib/prisma";
import { requireTenantRole } from "@/lib/roles";
import { isInvitableRole } from "@/lib/tenant";
import { sendTeamInviteEmail } from "@/lib/emails/team-invite";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const inviteBodySchema = z.object({
  email: z.string().trim().toLowerCase().email().max(254),
  role: z.string().refine(isInvitableRole, {
    message: "role must be one of: owner, auditor, viewer",
  }),
});

function generateInviteToken(): string {
  return randomBytes(32).toString("hex");
}

export async function POST(request: Request) {
  const auth = await requireTenantRole("team");
  if (!auth.ok) return auth.response;

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return NextResponse.json(
      { error: "invalid_input", detail: "Body must be JSON" },
      { status: 400 },
    );
  }
  const parsed = inviteBodySchema.safeParse(raw);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid_input", details: parsed.error.flatten() },
      { status: 400 },
    );
  }
  const { email, role } = parsed.data;

  // Defensive: even after Zod's .email() check, skip addresses
  // that look like a header-injection attempt. We allow only the
  // canonical address shape.
  if (email.includes("\n") || email.includes("\r")) {
    return NextResponse.json(
      { error: "invalid_input", detail: "Invalid email" },
      { status: 400 },
    );
  }

  // Look up an existing membership for this (email, tenant) pair.
  // We treat `active` and `pending` as already-a-member and
  // refuse to issue a duplicate invite. Inactive rows can be
  // re-invited (the spec calls for "have role-based access
  // enforced"; soft-disabling + re-enabling is a valid flow).
  const existing = await prisma.membership.findFirst({
    where: {
      tenantId: auth.request.tenantId,
      email,
      status: { in: ["active", "pending"] },
    },
    select: { id: true, status: true, role: true },
  });
  if (existing) {
    return NextResponse.json(
      {
        error: "already_a_member",
        detail: `An ${existing.status} membership for ${email} already exists (role=${existing.role}).`,
      },
      { status: 409 },
    );
  }

  const inviteToken = generateInviteToken();
  let membershipId: string;
  try {
    // We don't have a stable (email, tenant) unique key in
    // the schema, so look up the inactive row first to decide
    // between create and update. We already checked for an
    // active/pending row above, so a `findFirst` here is
    // limited to the inactive case.
    const inactive = await prisma.membership.findFirst({
      where: {
        tenantId: auth.request.tenantId,
        email,
        status: "inactive",
      },
      select: { id: true },
    });

    if (inactive) {
      const row = await prisma.membership.update({
        where: { id: inactive.id },
        data: {
          role,
          status: "pending",
          inviteToken,
          invitedAt: new Date(),
          // userId is preserved on re-invite; activatedAt is
          // reset so the audit shows a fresh activation when
          // the user accepts the new token.
          activatedAt: null,
        },
      });
      membershipId = row.id;
    } else {
      const row = await prisma.membership.create({
        data: {
          tenantId: auth.request.tenantId,
          email,
          role,
          status: "pending",
          inviteToken,
          invitedAt: new Date(),
        },
      });
      membershipId = row.id;
    }
  } catch (err) {
    console.error("[team/invite] DB write failed", err);
    return NextResponse.json(
      { error: "db_write_failed" },
      { status: 500 },
    );
  }

  // Send the invite email. In dev/mock mode the dispatcher logs
  // to the console; we still return success to the UI so the
  // owner can copy the link manually.
  const sendResult = await sendTeamInviteEmail({
    to: email,
    inviterEmail: auth.request.userEmail,
    inviterName: null,
    tenantName: auth.request.tenantName,
    tenantId: auth.request.tenantId,
    role,
    inviteToken,
  });

  return NextResponse.json(
    {
      ok: true,
      membership: {
        id: membershipId,
        email,
        role,
        status: "pending",
        invitedAt: new Date().toISOString(),
      },
      // Surface the mock-mode flag so the UI can show the link.
      emailDispatch: sendResult.sent
        ? { sent: true, id: (sendResult as { id: string }).id }
        : { sent: false, mock: (sendResult as { mock?: boolean }).mock === true },
    },
    { status: 201 },
  );
}
