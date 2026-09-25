// Mint a session cookie for UX polish manual testing.
import { randomBytes } from "node:crypto";
import { prisma } from "../src/lib/prisma";

async function main() {
  const email = process.env.UX_USER_EMAIL || "ux.polish@zorva.test";
  const slug = process.env.UX_TENANT_SLUG || "e2e-clinic";
  const user = await prisma.user.findUnique({ where: { email } });
  const tenant = await prisma.tenant.findUnique({ where: { slug } });
  if (!user || !tenant) {
    throw new Error(`missing user/tenant for ${email} / ${slug}`);
  }

  const existing = await prisma.membership.findFirst({
    where: { userId: user.id, tenantId: tenant.id },
  });
  if (!existing) {
    await prisma.membership.create({
      data: {
        id: randomBytes(12).toString("hex"),
        userId: user.id,
        tenantId: tenant.id,
        role: "owner",
        status: "active",
        invitedAt: new Date(),
        activatedAt: new Date(),
        email: user.email!,
      },
    });
  }

  await prisma.session.deleteMany({ where: { userId: user.id } });
  const sessionToken = randomBytes(32).toString("hex");
  await prisma.session.create({
    data: {
      id: `ux_${randomBytes(8).toString("hex")}`,
      sessionToken,
      userId: user.id,
      expires: new Date(Date.now() + 30 * 24 * 3600 * 1000),
      activeTenantId: tenant.id,
    },
  });

  console.log(
    JSON.stringify(
      {
        cookieName: "authjs.session-token",
        cookieValue: sessionToken,
        tenantId: tenant.id,
        userId: user.id,
        userEmail: user.email,
      },
      null,
      2,
    ),
  );
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
