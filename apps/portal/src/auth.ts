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
    include: { tenant: true },
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

// TEMP DEBUG: log the body that arrives at /api/auth/signin/<provider>
function debugNormalizer(email: string): string {
  console.log(
    "[auth-debug] debugNormalizer called with email=>>>" + email + "<<< typeof=" + typeof email + " length=" + (email ? email.length : "null") + " bytes=" + (email ? Buffer.from(email).toString("hex") : "null") + " useResendMock=" + useResendMock + " key_set=" + (process.env.AUTH_RESEND_KEY ? "yes(" + process.env.AUTH_RESEND_KEY.length + ")" : "no"),
  );
  // Replicate defaultNormalizer
  if (!email) throw new Error("Missing email from request body.");
  const trimmedEmail = email.toLowerCase().trim();
  if (trimmedEmail.includes('"')) {
    throw new Error("Invalid email address format.");
  }
  let [local, domain] = trimmedEmail.split("@");
  if (!local || !domain || trimmedEmail.split("@").length !== 2) {
    throw new Error("Invalid email address format. (local=" + JSON.stringify(local) + " domain=" + JSON.stringify(domain) + " splitLen=" + trimmedEmail.split("@").length + ")");
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
            async sendVerificationRequest({ identifier, url }) {
              console.log(
                "[auth-debug] sendVerificationRequest called identifier=" + JSON.stringify(identifier) + " useResendMock=" + useResendMock + " key_set=" + (process.env.AUTH_RESEND_KEY ? "yes" : "no"),
              );
              console.log(
                "\n[auth] magic link for " + identifier + ":\n  " + url + "\n",
              );
            },
          }
        : {}),
    }),
  ],

  pages: {
    signIn: "/login",
  },

  callbacks: {
    async signIn({ user }) {
      console.log("[auth-debug] signIn callback user=", JSON.stringify(user));
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

  trustHost: true,
};

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
