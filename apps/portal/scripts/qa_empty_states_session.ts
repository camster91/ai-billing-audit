// QA helper: mint a session cookie for the freshly-seeded QA empty
// user. We can't intercept the dev server's magic-link stdout (it was
// not redirected to a log file when launched), so we write a Session
// row directly. The NextAuth cookie name is `authjs.session-token`
// (HTTPS would append __Secure-). We print the cookie value so the
// QA script can use it as `Cookie: authjs.session-token=<value>`.
//
// The dev server will rebuild the session on the next request and
// call our `session` callback (auth.ts:125), which will load the
// user's memberships and active tenant. The PrismaAdapter uses the
// `sessionToken` as the lookup key — same as the cookie value.
//
// Run from apps/portal:
//   pnpm exec tsx scripts/qa_empty_states_session.ts

import { randomBytes, createHash } from "node:crypto";
import { prisma } from "../src/lib/prisma";

function randomToken(): string {
  return randomBytes(32).toString("hex");
}

async function main() {
  const tenant = await prisma.tenant.findFirst({
    where: { slug: { startsWith: "qa-empty-" } },
    orderBy: { createdAt: "desc" },
  });
  if (!tenant) {
    throw new Error("No qa-empty-* tenant found. Run qa_empty_states_seed.ts first.");
  }

  const user = await prisma.user.findFirst({
    where: { email: { startsWith: "qa-empty-" } },
    orderBy: { createdAt: "desc" },
  });
  if (!user) {
    throw new Error("No qa-empty-* user found. Run qa_empty_states_seed.ts first.");
  }

  // Wipe any prior QA session for this user so we get a fresh token.
  await prisma.session.deleteMany({ where: { userId: user.id } });

  const sessionToken = randomToken();
  const expires = new Date(Date.now() + 1000 * 60 * 60 * 24 * 30); // 30 days
  await prisma.session.create({
    data: {
      id: `qa_${randomToken().slice(0, 16)}`,
      sessionToken,
      userId: user.id,
      expires,
      // Pin the active tenant so the dashboard does not have to
      // fall back to "first membership" — the seed only created
      // one but being explicit avoids surprises.
      activeTenantId: tenant.id,
    },
  });

  console.log(
    JSON.stringify(
      {
        cookieName: "authjs.session-token",
        cookieValue: sessionToken,
        tenantId: tenant.id,
        tenantSlug: tenant.slug,
        userId: user.id,
        userEmail: user.email,
        expires: expires.toISOString(),
      },
      null,
      2,
    ),
  );
}

main()
  .catch((e) => {
    console.error("[qa-empty-session] failed:", e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
