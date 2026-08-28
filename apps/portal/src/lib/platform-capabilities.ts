export const PLATFORM_ROLES = [
  "owner",
  "sales",
  "client_success",
  "support",
  "analyst",
] as const;

export type PlatformRole = (typeof PLATFORM_ROLES)[number];
export type PlatformCapability = "hq:read" | "leads:read";

const CAPABILITIES: Record<PlatformRole, ReadonlySet<PlatformCapability>> = {
  owner: new Set(["hq:read", "leads:read"]),
  sales: new Set(["hq:read", "leads:read"]),
  client_success: new Set(["hq:read"]),
  support: new Set(["hq:read"]),
  analyst: new Set(["hq:read"]),
};

export function isPlatformRole(value: string): value is PlatformRole {
  return (PLATFORM_ROLES as readonly string[]).includes(value);
}

export function hasPlatformCapability(
  role: string | null | undefined,
  active: boolean,
  capability: PlatformCapability,
): boolean {
  if (!active || !role || !isPlatformRole(role)) return false;
  return CAPABILITIES[role].has(capability);
}
