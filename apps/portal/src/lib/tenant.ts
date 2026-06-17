// Tenant type definitions and validation helpers.
//
// In dev we use SQLite (no native enum support), so the `tier`,
// `subscriptionStatus`, and `role` columns are plain strings. The
// allowed values live here as const arrays + derived union types so
// TypeScript still catches invalid usage at the boundary. When the
// production datasource moves to PostgreSQL, swap these for real
// Prisma enums; the rest of the app shouldn't need to change.

export const TENANT_TIERS = ["small", "mid", "large"] as const;
export type TenantTier = (typeof TENANT_TIERS)[number];

export const SUBSCRIPTION_STATUSES = [
  "active",
  "past_due",
  "canceled",
] as const;
export type SubscriptionStatus = (typeof SUBSCRIPTION_STATUSES)[number];

export const TENANT_ROLES = [
  "owner",
  "admin",
  "auditor",
  "viewer",
] as const;
export type TenantRole = (typeof TENANT_ROLES)[number];

export function isTenantTier(value: string): value is TenantTier {
  return (TENANT_TIERS as readonly string[]).includes(value);
}

export function isSubscriptionStatus(
  value: string,
): value is SubscriptionStatus {
  return (SUBSCRIPTION_STATUSES as readonly string[]).includes(value);
}

export function isTenantRole(value: string): value is TenantRole {
  return (TENANT_ROLES as readonly string[]).includes(value);
}

// Default audit quota per tier — small clinics get 100 claim reviews/mo,
// mid-tier 1000, large 10000. Tuned to the $1,200/mo/provider pricing in
// the ai-billing-audit board spec.
export function defaultAuditQuotaLimit(tier: TenantTier): number {
  switch (tier) {
    case "small":
      return 100;
    case "mid":
      return 1000;
    case "large":
      return 10000;
  }
}
