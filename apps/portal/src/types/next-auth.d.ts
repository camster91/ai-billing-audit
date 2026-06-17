// Extend the default NextAuth types with our tenant-related fields.
// Without this, TypeScript only knows about session.user.{name,email,image}
// and our session callback assignment fails to typecheck.
import type { DefaultSession } from "next-auth";
import type { SubscriptionStatus, TenantRole, TenantTier } from "@/lib/tenant";

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      tenants: Array<{
        id: string;
        name: string;
        slug: string;
        tier: string;
        subscriptionStatus: string;
        role: string;
      }>;
      activeTenantId: string | null;
    } & DefaultSession["user"];
  }
}

export {};
