// Tenant-scoped proxy (renamed from middleware in Next.js 16).
//
// Two responsibilities:
//   1. Auth gate: redirect unauthenticated users away from protected
//      routes to /login. Allow /api/auth/* through so the magic-link
//      callback can complete and set the session cookie.
//   2. Tenant attach: for authenticated requests to API routes, the
//      session callback in src/auth.ts already populates
//      `session.user.activeTenantId`. We pass that value downstream via
//      a request header (x-tenant-id) so route handlers can read it
//      without re-querying the DB.
//
// Why a header and not just `auth()` in the route: most route handlers
// will still call `auth()` themselves to read the full user, but the
// header makes tenant-scoped DB queries a one-liner and keeps the
// tenant resolution consistent.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";

// Routes that don't require auth — magic-link signin, the verification
// callback, the session probe, CSRF, static assets. Everything else
// under the matcher requires a valid session.
//
// The pricing + billing surface is intentionally public: anonymous
// clinic operators must be able to view /pricing, start a Stripe
// Checkout Session, and reach the post-purchase /portal/onboarding
// landing without an account. Auth comes later, inside the portal,
// not at the marketing front door.
const PUBLIC_PREFIXES = [
  "/api/auth",
  "/api/billing",   // checkout + webhook + tiers + portal are public
  "/api/onboarding", // first-run wizard — Stripe success_url lands here, must work w/o auth
  "/login",
  "/pricing",       // marketing page, public
  "/how-it-works",  // marketing page, public (3-step explainer + Loom + CTA)
  "/portal/onboarding", // Stripe success_url lands here, must work w/o auth
  "/portal/billing",   // manage-billing entry from onboarding, public
  "/_next",
  "/favicon.ico",
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/") || pathname === p);
}

export default async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const session = await auth();

  if (!session?.user?.id) {
    // API routes: respond 401 (not a redirect) so the client knows to
    // refresh the session rather than chasing a redirect loop.
    if (pathname.startsWith("/api/")) {
      return NextResponse.json(
        { error: "unauthenticated" },
        { status: 401 },
      );
    }

    // Page routes: redirect to /login with a callbackUrl so we can come
    // back here after the magic-link flow completes.
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("callbackUrl", pathname + request.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  // Authenticated. If the user has memberships and an active tenant,
  // forward that tenant id as a request header so downstream route
  // handlers / server components can read it without a second DB call.
  const requestHeaders = new Headers(request.headers);
  const activeTenantId = session.user.activeTenantId;
  if (activeTenantId) {
    requestHeaders.set("x-tenant-id", activeTenantId);
  }

  // If the user is authenticated but has no memberships (e.g. just
  // signed up via magic link, hasn't been invited to a clinic yet),
  // routes that REQUIRE a tenant scope should fail. Pages render a
  // "no tenant" empty state. API routes get 403.
  if (!activeTenantId && pathname.startsWith("/api/") && !pathname.startsWith("/api/auth/")) {
    return NextResponse.json(
      { error: "no_tenant" },
      { status: 403 },
    );
  }

  return NextResponse.next({ request: { headers: requestHeaders } });
}

// Match everything except static assets and the favicon. We DO match
// /api/* so the auth gate applies — the API routes are the
// tenant-scoped endpoints we want to protect.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js)$).*)",
  ],
};
