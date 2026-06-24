// GET /api/team/accept?token=<inviteToken>
//
// Magic-link accept endpoint. Three things happen in order:
//   1. Look up the Membership row by its invite token. If the
//      row is missing, the token is unknown / already used /
//      already revoked — return a 404 page that explains.
//   2. The spec says "clicking the link as a new user signs them
//      up" — we honor that by:
//        a) If the invitee's email matches an existing User, we
//           attach the membership to that User.
//        b) If not, we render a small sign-in page that triggers
//           the Resend magic-link signin flow with callbackUrl
//           back to this same /api/team/accept?token=... URL.
//           When the user clicks the signin link, the resulting
//           session will have user.email == invite.email and
//           step (3) will bind the membership.
//   3. Bind the membership to the current session's user, flip
//      status to "active", set activatedAt = now, clear
//      inviteToken (defense in depth), and redirect to /team so
//      the user can see they're now a member.
//
// Authorization: the accept flow is intentionally open — the
// invite token IS the authorization. Once consumed, the token
// is cleared. A pre-flight check verifies the membership is
// still in "pending" status.
//
// Public route: this is intentionally NOT in the auth gate's
// PUBLIC_PREFIXES because the user may arrive here from the
// email link with no active session. The handler itself is
// permission-gated by the invite token, not the session cookie.

import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BASE_URL = process.env["BASE_URL"] ?? "http://localhost:3000";

function acceptPageHtml(args: {
  title: string;
  body: string;
  ctaHref?: string;
  ctaLabel?: string;
}): string {
  const cta = args.ctaHref
    ? `<p style="margin-top:24px"><a href="${args.ctaHref}" style="background:#4f46e5;color:white;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600">${args.ctaLabel ?? "Continue"}</a></p>`
    : "";
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${args.title}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0b1020; color: #e6e9f2; margin: 0; padding: 0; }
  main { max-width: 520px; margin: 80px auto; padding: 32px; background: #131a30; border: 1px solid #28324f; border-radius: 12px; }
  h1 { font-size: 22px; margin: 0 0 12px; }
  p { line-height: 1.55; color: #b8c0d8; }
  code { background: #0b1020; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
</style>
</head>
<body>
  <main>
    <h1>${args.title}</h1>
    ${args.body}
    ${cta}
  </main>
</body>
</html>`;
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const token = url.searchParams.get("token");
  if (!token || token.length < 16) {
    return new NextResponse(
      acceptPageHtml({
        title: "Invalid invite link",
        body: "<p>This invite link is missing or malformed. Ask the team owner to send a fresh invite.</p>",
      }),
      { status: 400, headers: { "content-type": "text/html; charset=utf-8" } },
    );
  }

  // Find the membership by invite token. The schema enforces
  // uniqueness on the token, so this returns at most one row.
  const membership = await prisma.membership.findUnique({
    where: { inviteToken: token },
    include: {
      tenant: { select: { id: true, name: true } },
    },
  });

  if (!membership) {
    return new NextResponse(
      acceptPageHtml({
        title: "Invite link not found",
        body: "<p>This invite link has been used, revoked, or never existed. Ask the team owner to send a fresh invite.</p>",
      }),
      { status: 404, headers: { "content-type": "text/html; charset=utf-8" } },
    );
  }

  if (membership.status === "inactive") {
    return new NextResponse(
      acceptPageHtml({
        title: "Invite revoked",
        body: `<p>The invite for <code>${membership.email}</code> on <strong>${membership.tenant.name}</strong> has been revoked. Ask the team owner to send a fresh invite.</p>`,
      }),
      { status: 410, headers: { "content-type": "text/html; charset=utf-8" } },
    );
  }

  if (membership.status === "active") {
    // Idempotent: a member who clicks their own accept link
    // again lands on /team.
    return NextResponse.redirect(`${BASE_URL}/team`);
  }

  // membership.status === "pending" — proceed to bind.
  // We need an authenticated user whose email matches the
  // membership's email. If the user already has a session and
  // their email matches, bind immediately. Otherwise, send
  // them through the auth flow with a callbackUrl back here.
  const session = await auth();

  if (session?.user?.id) {
    if (session.user.email?.toLowerCase() !== membership.email.toLowerCase()) {
      // The signed-in user is not the invitee. Refuse — we
      // don't want to silently rebind the membership to a
      // different account.
      return new NextResponse(
        acceptPageHtml({
          title: "Wrong account",
          body: `<p>You're signed in as <code>${session.user.email ?? "(unknown)"}</code>, but this invite is for <code>${membership.email}</code>.</p>
                 <p>Sign out and click the invite link from the original email, or ask the team owner to re-send it.</p>`,
        }),
        { status: 403, headers: { "content-type": "text/html; charset=utf-8" } },
      );
    }

    // Bind: set userId, status=active, activatedAt, clear token.
    await prisma.membership.update({
      where: { id: membership.id },
      data: {
        userId: session.user.id,
        status: "active",
        activatedAt: new Date(),
        inviteToken: null,
      },
    });

    return NextResponse.redirect(`${BASE_URL}/team`);
  }

  // No session — render a signin page. We pass the original
  // acceptUrl as the callbackUrl so the user lands back here
  // after the magic-link signin completes. The `prefill_email`
  // query param is a hint to the /login page so the user
  // doesn't have to retype the address.
  const acceptUrl = `${BASE_URL}/api/team/accept?token=${encodeURIComponent(token)}`;
  const loginUrl = `/login?callbackUrl=${encodeURIComponent(acceptUrl)}&email=${encodeURIComponent(membership.email)}`;

  return new NextResponse(
    acceptPageHtml({
      title: `Join ${membership.tenant.name}`,
      body: `<p>You've been invited to <strong>${membership.tenant.name}</strong> on the AI Billing Portal as <code>${membership.email}</code>.</p>
             <p>Sign in to accept the invite. If you don't have an account yet, we'll create one with the email above.</p>`,
      ctaHref: loginUrl,
      ctaLabel: "Sign in to accept",
    }),
    { status: 200, headers: { "content-type": "text/html; charset=utf-8" } },
  );
}
