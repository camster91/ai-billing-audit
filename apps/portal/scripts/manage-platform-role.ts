import { randomUUID } from "node:crypto";
import { prisma } from "../src/lib/prisma";
import { isPlatformRole } from "../src/lib/platform-capabilities";

interface Options {
  action: "grant" | "revoke";
  email: string;
  role: string | null;
  grantedBy: string;
  confirmed: boolean;
  productionConfirmed: boolean;
}

export function parseOptions(args: string[]): Options {
  const value = (name: string) => {
    const index = args.indexOf(name);
    return index >= 0 ? args[index + 1] ?? "" : "";
  };
  const action = value("--action");
  if (action !== "grant" && action !== "revoke") {
    throw new Error("--action must be grant or revoke");
  }
  const email = value("--email").trim().toLowerCase();
  const grantedBy = value("--granted-by").trim();
  const role = action === "grant" ? value("--role") : null;
  if (!email || !email.includes("@")) throw new Error("--email is required");
  if (!grantedBy) throw new Error("--granted-by is required");
  if (action === "grant" && (!role || !isPlatformRole(role))) {
    throw new Error("--role must be owner, sales, client_success, support, or analyst");
  }
  return {
    action,
    email,
    role,
    grantedBy,
    confirmed: args.includes("--confirm-role-change"),
    productionConfirmed: args.includes("--confirm-production"),
  };
}

function maskedEmail(email: string): string {
  const [local, domain] = email.split("@");
  return `${local?.slice(0, 1) ?? "*"}***@${domain ?? "***"}`;
}

async function main() {
  const options = parseOptions(process.argv.slice(2));
  if (!options.confirmed) {
    throw new Error("Refusing role change without --confirm-role-change");
  }
  if (process.env.NODE_ENV === "production" && !options.productionConfirmed) {
    throw new Error("Refusing production role change without --confirm-production");
  }

  const user = await prisma.user.findUnique({
    where: { email: options.email },
    select: { id: true },
  });
  if (!user) throw new Error("Existing user not found; sign in before granting a platform role");

  if (options.action === "grant") {
    await prisma.$transaction([
      prisma.platformUserRole.upsert({
        where: { userId: user.id },
        create: {
          userId: user.id,
          role: options.role!,
          active: true,
          grantedBy: options.grantedBy,
        },
        update: {
          role: options.role!,
          active: true,
          grantedBy: options.grantedBy,
          grantedAt: new Date(),
          revokedAt: null,
        },
      }),
      prisma.platformAuditEvent.create({
        data: {
          actorRole: "bootstrap_operator",
          action: "platform_role_granted",
          targetType: "user",
          targetId: user.id,
          requestId: randomUUID(),
          metadataJson: JSON.stringify({ role: options.role, grantedBy: options.grantedBy }),
        },
      }),
    ]);
  } else {
    const existing = await prisma.platformUserRole.findUnique({ where: { userId: user.id } });
    if (!existing) throw new Error("No platform role exists for this user");
    await prisma.$transaction([
      prisma.platformUserRole.update({
        where: { userId: user.id },
        data: { active: false, revokedAt: new Date() },
      }),
      prisma.platformAuditEvent.create({
        data: {
          actorRole: "bootstrap_operator",
          action: "platform_role_revoked",
          targetType: "user",
          targetId: user.id,
          requestId: randomUUID(),
          metadataJson: JSON.stringify({ priorRole: existing.role, grantedBy: options.grantedBy }),
        },
      }),
    ]);
  }

  console.log(`${options.action} complete for ${maskedEmail(options.email)}`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main()
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.message : "platform role change failed");
      process.exitCode = 1;
    })
    .finally(async () => prisma.$disconnect());
}
