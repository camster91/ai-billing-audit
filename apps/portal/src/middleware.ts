// Tenant-scoped middleware. Pinned to Next.js 15.x (15.5.19) instead of
// 16.x because Next 16 has a known bug where proxy.ts is not detected as
// middleware (the new filename is preferred but the detection code does
// not register it). At 15.x, this file's name (middleware.ts) is the
// canonical convention. When the detection bug is fixed upstream we can
// switch to 16.x and rename proxy.ts <-> middleware.ts in one move.
//
// Responsibilities:
//
//   1. Auth gate (COOKIE-PRESENCE ONLY, no auth() call): redirect
//      unauthenticated users away from protected routes to /login.
//      We deliberately do NOT call auth() here — that's a Node-runtime
//      helper that pulls in Prisma + node:url imports, which can't run
//      in the Edge Runtime where this middleware executes. A
//      cookie-presence check is the lowest-fidelity "is the user
//      authenticated" probe we can run Edge-side; downstream route
//      handlers do the real auth() check before touching tenant data.
//
//   2. Tenant-attach header forwarding (skipped — see below): the
//      earlier version of this file forwarded `x-active-tenant-id` to
//      route handlers so they could skip a second DB call. We skip it
//      here because decoding the tenant ID requires reading the JWT /
//      session row, which doesn't work in Edge. Route handlers already
//      call `getActiveTenant()` themselves; the optimization is lost
//      but the auth gate works.
//
// Match everything except static assets and the favicon.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// NextAuth.js (Auth.js v5) session cookie. Two variants: the
// HTTPS-scoped version (`__Secure-`) on production (Cloudflare +
// Traefik force HTTPS), the plain version on localhost dev. Edge-safe
// to read from request.cookies — no Node import chain.
const SESSION_COOKIE_SECURE = "__Secure-authjs.session-token";
const SESSION_COOKIE_PLAIN = "authjs.session-token";

// Routes that don't require auth — magic-link signin, the verification
// callback, the session probe, CSRF, static assets, public marketing
// pages, public demo routes. Everything else under the matcher
// requires a valid session.
//
// The pricing + billing surface is intentionally public: anonymous
// clinic operators must be able to view /pricing, start a Stripe
// Checkout Session, and reach the post-purchase /portal/onboarding
// landing without an account. Auth comes later, inside the portal,
// not at the marketing front door.
const PUBLIC_PREFIXES = [
  "/api/auth",
  "/api/billing",   // checkout + webhook + tiers + portal are public
  "/api/leads",     // public contact-form endpoint (t_fa2149e1) — pre-account visitors only
  "/api/onboarding", // first-run wizard — Stripe success_url lands here, must work w/o auth
  "/api/team/accept", // invite magic-link — works pre-session; the token IS the auth (t_23bfd49c)
  "/login",
  "/",              // marketing landing page, public (t_fa2149e1)
  "/pricing",       // marketing page, public
  "/how-it-works",  // marketing page, public (3-step explainer + Loom + CTA)
  "/security",      // marketing page, public (HIA/PHIPA/HIPAA/AKS explainer + compliance matrix)
  "/security.pdf",  // one-pager download, public (linked from /security CTA)
  "/contact",       // marketing contact form, public (t_fa2149e1)
  "/what-zorva-finds", // marketing findings gallery, public
  "/pilot",         // pilot program page, public
  "/trust",         // consumer-grade data-safety explainer, public
  "/compare",       // Zorva vs manual/LLM/EHR/outsourced comparison, public
  "/status",        // status/uptime page, public
  "/changelog",     // public release notes for privacy officers + admins
  "/careers",       // careers landing page, public
  "/about",         // public about page (team + story), public (kanban t_df7045d8)
  "/blog",          // public blog / resources stub, public (kanban t_7492f223)
  "/demo-request",  // demo-request landing page, public (kanban t_c091d2b5)
  "/try",           // /try public demo page, public (P0 roadmap W1.1, gap G9) — synthetic-data demo, no PHI, no signup
  "/press",         // press / in the news page, public
  "/technical",     // technical buyer (privacy officer, IT lead) page, public
  "/glossary",      // billing terms glossary for non-billers, public
  "/case-studies",  // anonymized worked examples, public
  "/portal/onboarding", // Stripe success_url lands here, must work w/o auth
  "/portal/billing",   // manage-billing entry from onboarding, public
  "/_next",
  "/favicon.ico",
  "/robots.txt",       // dynamic robots from app/robots.ts
  "/sitemap.xml",      // future sitemap route
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/") || pathname === p,
  );
}

/** Edge-runtime-safe "is the user signed in?" probe. Returns true if
 *  either cookie variant is present, false otherwise. Does NOT verify
 *  JWT contents — that's deferred to route handlers via auth(). */
function hasSessionCookie(request: NextRequest): boolean {
  return (
    request.cookies.has(SESSION_COOKIE_SECURE) ||
    request.cookies.has(SESSION_COOKIE_PLAIN)
  );
}

export default function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Public path → no auth check, no redirects.
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // No session cookie → redirect to /login (or 401 for API routes).
  if (!hasSessionCookie(request)) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json(
        { error: "unauthenticated" },
        { status: 401 },
      );
    }
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("callbackUrl", pathname + request.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  // Cookie present → let through. Tenant forwarding is dropped from
  // middleware (Edge-Runtime can't decode the session JWT); route
  // handlers re-read activeTenantId via getActiveTenant().
  return NextResponse.next();
}

// Match everything except static assets and the favicon. We DO match
// /api/* so the auth gate applies — the API routes are the
// tenant-scoped endpoints we want to protect.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js)$).*)",
  ],
};