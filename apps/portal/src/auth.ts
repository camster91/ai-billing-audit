// NextAuth.js (Auth.js v5) configuration.
//
// Exports: { handlers, auth, signIn, signOut }
//   - handlers:  GET/POST route handlers for /api/auth/*
//   - auth():    server-side helper — call in server components, route
//                handlers, and server actions to read the current session
//   - signIn:    server action helper to start a magic-link flow
//   - signOut:   server action helper
//
// Magic-link flow: Resend provider, user enters email, /api/auth/signin
// POST, Resend sends a one-time link, user clicks, /api/auth/callback/email
// verifies the token, session cookie is set, redirect to /dashboard.
//
// Dev fallback: when AUTH_RESEND_KEY is blank we override
// sendVerificationRequest to log the link to the terminal. This keeps
// the magic-link flow fully exercisable in local dev / CI without a
// Resend account.

import NextAuth, { type NextAuthConfig } from "next-auth";
import Resend from "next-auth/providers/resend";
import { PrismaAdapter } from "@auth/prisma-adapter";
import { prisma } from "@/lib/prisma";

// Resolve the active tenant for a user — used by the session callback.
//
// Selection rule:
//   1. If the session row has activeTenantId set, use that one (subject
//      to a still-valid membership).
//   2. Otherwise, fall back to the user's first membership (oldest by
//      createdAt). The /api/auth/select-tenant route lets the user
//      override this and write back to Session.activeTenantId.
async function loadUserTenants(userId: string, activeTenantId: string | null) {
  const memberships = await prisma.membership.findMany({
    where: { userId },
    orderBy: { createdAt: "asc" },
    select: {
      role: true,
      tenant: {
        select: {
          id: true,
          name: true,
          slug: true,
          tier: true,
          subscriptionStatus: true,
        },
      },
    },
  });

  if (memberships.length === 0) {
    return { tenants: [], activeTenantId: null };
  }

  const tenants = memberships.map((m) => ({
    id: m.tenant.id,
    name: m.tenant.name,
    slug: m.tenant.slug,
    tier: m.tenant.tier,
    subscriptionStatus: m.tenant.subscriptionStatus,
    role: m.role,
  }));

  const validActive = activeTenantId
    ? memberships.find((m) => m.tenant.id === activeTenantId)
    : null;
  const resolvedActiveId = validActive
    ? validActive.tenant.id
    : tenants[0]?.id ?? null;

  return {
    tenants,
    activeTenantId: resolvedActiveId,
  };
}

const useResendMock =
  !process.env.AUTH_RESEND_KEY || process.env.AUTH_RESEND_KEY.length === 0;

// P11 bug-sweep fix (2026-06-30): the previous version of this module
// had three critical security issues:
//   1. ``debugNormalizer`` logged the raw email bytes (PII) and a
//      hex-encoded copy to stdout — every signin attempt printed the
//      user's email to logs. PHI / PII leak.
//   2. ``sendVerificationRequest`` in the dev-mock branch printed the
//      FULL MAGIC-LINK URL to stdout — anyone with log access (CI
//      runner, accidental stdout dump, log aggregator without
//      scrubbing) gets a one-shot account-takeover token. CRITICAL.
//   3. ``signIn`` callback logged the full user object (including id,
//      email, name) on every signin.
//
// All three are now gated behind ``NODE_ENV !== "production"`` AND
// the magic-link URL is NEVER logged — only the (non-PII) presence of
// a pending signin is recorded in dev, and only the email's sha256
// prefix (first 8 hex chars, not the address) is shown so multiple
// devs can correlate logs without leaking the address itself.

function isDev(): boolean {
  return process.env.NODE_ENV !== "production";
}

// Dev-only identifier redactor: emit the first 8 hex chars of a
// sha256 of the email so logs can still correlate "is this the same
// person retrying?" without printing the address. Production returns
// "[redacted]" because dev-redaction isn't appropriate in prod logs
// either — those should go to a structured logger, not console.log.
function devRedactEmail(email: string | null | undefined): string {
  if (!isDev()) return "[redacted]";
  if (!email) return "(none)";
  try {
    // Lazy import so this never lands in the production bundle's
    // module-resolution graph.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { createHash } = require("node:crypto") as typeof import("node:crypto");
    return "sha256:" + createHash("sha256").update(email.toLowerCase()).digest("hex").slice(0, 8);
  } catch {
    return "(unparseable)";
  }
}

// Normalize the email the way Resend's defaultNormalizer does. The
// dev-only debug log uses devRedactEmail so we never print the raw
// address in any environment.
function debugNormalizer(email: string): string {
  if (isDev()) {
    console.log(
      `[auth-debug] normalize identifier=${devRedactEmail(email)} useResendMock=${useResendMock}`,
    );
  }
  // Replicate defaultNormalizer
  if (!email) throw new Error("Missing email from request body.");
  const trimmedEmail = email.toLowerCase().trim();
  if (trimmedEmail.includes('"')) {
    throw new Error("Invalid email address format.");
  }
  const [local, rawDomain] = trimmedEmail.split("@");
  let domain = rawDomain;
  if (!local || !domain || trimmedEmail.split("@").length !== 2) {
    throw new Error("Invalid email address format.");
  }
  domain = domain.split(",")[0];
  if (!domain) throw new Error("Invalid email address format.");
  return `${local}@${domain}`;
}

export const authConfig: NextAuthConfig = {
  adapter: PrismaAdapter(prisma),

  providers: [
    Resend({
      apiKey: process.env.AUTH_RESEND_KEY ?? "dev",
      from:
        process.env.AUTH_EMAIL_FROM ??
        "AI Billing Portal <noreply@example.com>",
      normalizeIdentifier: debugNormalizer,
      ...(useResendMock
        ? {
            async sendVerificationRequest({ identifier }) {
              // CRITICAL: never log the magic-link URL — it contains the
              // one-shot token. We log only the redacted identifier
              // (sha256 prefix) and the fact that a link was generated.
              if (isDev()) {
                console.log(
                  `[auth-debug] sendVerificationRequest identifier=${devRedactEmail(identifier)} useResendMock=${useResendMock} (link suppressed — paste the URL from the request handler's return to test signin in dev)`,
                );
              }
            },
          }
        : {}),
    }),
  ],

  pages: {
    signIn: "/login",
    verifyRequest: "/verify-request",
    error: "/auth/error",
  },

  callbacks: {
    async signIn({ user }) {
      // Dev-only log: redacted identifier + user id presence. Never
      // log the full user object (it carries email, name, image).
      if (isDev()) {
        console.log(
          `[auth-debug] signIn callback identifier=${devRedactEmail(user?.email ?? null)} hasUserId=${Boolean(user?.id)}`,
        );
      }
      return true;
    },
    // With PrismaAdapter (database session strategy), the `user` parameter
    // is the AdapterUser — the row from the User table. We use its id to
    // look up the active session and the user's memberships.
    async session({ session, user }) {
      if (!user?.id) {
        return session;
      }

      const sessionRow = await prisma.session.findFirst({
        where: { userId: user.id },
        orderBy: { expires: "desc" },
        select: { activeTenantId: true },
      });

      const { tenants, activeTenantId } = await loadUserTenants(
        user.id,
        sessionRow?.activeTenantId ?? null,
      );

      return {
        ...session,
        user: {
          ...session.user,
          id: user.id,
          tenants,
          activeTenantId,
        },
      };
    },
  },

  // Production: require AUTH_URL so callback URLs are pinned to the
  // canonical host behind Traefik. trustHost:true would accept any
  // Host / X-Forwarded-Host and is only safe for local/dev.
  trustHost: process.env.NODE_ENV !== "production",
};

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
