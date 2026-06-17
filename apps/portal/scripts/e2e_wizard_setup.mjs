import { prisma } from "../src/lib/prisma.ts";
import { randomBytes } from "node:crypto";

const SESSION = "cs_test_e2e_wizard_" + randomBytes(4).toString("hex");
const EMAIL = "e2e-wizard-" + randomBytes(4).toString("hex") + "@example.com";

// 1. Create a user
const user = await prisma.user.create({
  data: { email: EMAIL, emailVerified: new Date() },
});

// 2. Reset any prior tenant for this SESSION (idempotent)
await prisma.redeemedCheckoutSession.deleteMany({ where: { sessionId: SESSION } });
await prisma.tenant.deleteMany({ where: { stripeSubscriptionId: "sub_test_" + SESSION } });

console.log(JSON.stringify({ userId: user.id, email: EMAIL, session: SESSION }));
