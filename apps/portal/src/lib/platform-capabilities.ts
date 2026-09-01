export const PLATFORM_ROLES = [
  "owner",
  "sales",
  "client_success",
  "support",
  "analyst",
  "marketing",
] as const;

export type PlatformRole = (typeof PLATFORM_ROLES)[number];
export type PlatformCapability =
  | "hq:read"
  | "leads:read"
  | "leads:write"
  | "clients:read"
  | "clients:write"
  | "support:read"
  | "support:write"
  | "marketing:read"
  | "marketing:write"
  | "reporting:read";

const CAPABILITIES: Record<PlatformRole, ReadonlySet<PlatformCapability>> = {
  owner: new Set(["hq:read", "leads:read", "leads:write", "clients:read", "clients:write", "support:read", "support:write", "marketing:read", "marketing:write", "reporting:read"]),
  sales: new Set(["hq:read", "leads:read", "leads:write", "clients:read", "marketing:read"]),
  client_success: new Set(["hq:read", "leads:read", "clients:read", "clients:write", "support:read", "support:write", "marketing:read"]),
  support: new Set(["hq:read", "support:read", "support:write"]),
  analyst: new Set(["hq:read", "marketing:read", "reporting:read"]),
  marketing: new Set(["hq:read", "marketing:read", "marketing:write"]),
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
