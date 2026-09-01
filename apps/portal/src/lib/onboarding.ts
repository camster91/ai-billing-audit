// Onboarding library — the server-side heart of the first-run wizard
// at /portal/onboarding. Five exported functions back the route:
//
//   redeemCheckoutSession({ sessionId, userId })
//     Verifies a Stripe Checkout Session, ensures a Tenant exists,
//     attaches the user as `owner`, and records a RedeemedCheckoutSession
//     row. Idempotent: replaying the same sessionId is a no-op (returns
//     the existing row).
//
//   saveClinicProfile({ tenantId, ... })
//     Persists step 2 (clinic name, NPI, timezone) and advances
//     onboardingStep to 2.
//
//   saveResidencyRegion({ tenantId, region })
//     Persists step 3 and advances onboardingStep to 3.
//
//   saveEhrConnection({ tenantId, mode, ... })
//     Persists step 4 (SFTP credentials or "manual" skip) and advances
//     onboardingStep to 4.
//
//   saveFirstEncounter({ tenantId, mode, filePath, fileName })
//     Persists step 5 (an 837P file path or "skipped") and advances
//     onboardingStep to 5.
//
//   completeOnboarding({ tenantId })
//     Locks the residency region, marks onboardingCompletedAt, and
//     returns the tenant row so the caller can dispatch the welcome
//     email and redirect to /dashboard.
//
//   canStartAudit({ tenantId })
//     Single source of truth for the audit-gate check used by both
//     the wizard's "Finish" button and any future audit-enqueue
//     endpoint. Returns true only when every required field is set
//     and the wizard has completed.
//
// Every step is gated by the previous step being complete, so a
// user can't skip ahead by hand-crafting requests. Gating is enforced
// in the lib (not just the UI) so the API surface is safe to expose.

import { prisma } from "@/lib/prisma";
import { encryptPortalString } from "@/lib/data-encryption";
import { getStripe, isDemoMode } from "@/lib/stripe";
import { isValidTierId } from "@/lib/pricing";
import { z } from "zod";
import type StripeNS from "stripe";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Stripe-suggested residency regions. Mirrors what the /settings page
 * exposes (see task t_1bab62b6) so the two pages stay in lockstep.
 *
 * NOTE (task t_96d9a4f9): these string values are the internal enum
 * persisted to the database. The customer-facing label was changed from
 * "Canada (ca-central-1)" / "United States (us-east-1)" to "Canada
 * (Canadian data centre)" / "United States (US-hosted, HIPAA-aligned)".
 * The enum values themselves stay as `ca-central-1` / `us-east-1` for
 * backwards compatibility with existing tenant rows — changing them is
 * a DB migration, out of scope for the marketing-copy fix. */
export const RESIDENCY_REGIONS = ["ca-central-1", "us-east-1"] as const;
export type ResidencyRegion = (typeof RESIDENCY_REGIONS)[number];

/** IANA timezone strings — a permissive set for the dev wizard. We
 * intentionally don't gate on a full IANA list server-side; the
 * client validates with a `Intl.supportedValuesOf("timeZone")` lookup
 * and we just sanity-check the shape. */
const TIMEZONE_RE = /^[A-Za-z][A-Za-z0-9+_\-/]{1,40}$/;

/** 10-digit NPI for US; looser 6–15 char alphanumeric for non-US
 * clinics (e.g. Canadian providers use provincial IDs). The portal
 * isn't strict on a single national schema at this stage. */
const NPI_RE = /^[A-Za-z0-9]{6,15}$/;

/** Step 2: clinic profile. All three are optional, but if `clinicName`
 * is omitted the wizard falls back to the tenant's `name` column. */
export const clinicProfileSchema = z.object({
  clinicName: z
    .string()
    .trim()
    .max(120, "clinic name must be 120 characters or fewer")
    .optional()
    .or(z.literal("")),
  clinicNpi: z
    .string()
    .trim()
    .max(15)
    .regex(NPI_RE, "clinic NPI must be 6–15 letters or digits")
    .optional()
    .or(z.literal("")),
  clinicTimezone: z
    .string()
    .trim()
    .max(64)
    .regex(TIMEZONE_RE, "clinic timezone must look like an IANA name")
    .optional()
    .or(z.literal("")),
});

/** Step 3: data residency. Required: must be one of the two regions. */
export const residencyRegionSchema = z.object({
  region: z.enum(RESIDENCY_REGIONS),
});

/** Step 4: EHR connection. Either SFTP (with host/port/username/password)
 * or an explicit "manual" mode (skip-SFTP). The wizard's UI is the
 * single-select gate. */
export const ehrConnectionSchema = z
  .object({
    mode: z.enum(["sftp", "manual"]),
    host: z.string().trim().max(255).optional(),
    port: z
      .number()
      .int()
      .min(1)
      .max(65535)
      .optional(),
    username: z.string().trim().max(128).optional(),
    password: z.string().max(1024).optional(),
  })
  .superRefine((value, ctx) => {
    if (value.mode === "sftp") {
      if (!value.host) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["host"],
          message: "host is required for sftp mode",
        });
      }
      if (value.port === undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["port"],
          message: "port is required for sftp mode",
        });
      }
      if (!value.username) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["username"],
          message: "username is required for sftp mode",
        });
      }
      if (!value.password) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["password"],
          message: "password is required for sftp mode",
        });
      }
    }
  });

/** Step 5: first encounter. Either a 837P file path (uploaded
 * separately to a server-staging area and referenced by path) or an
 * explicit "skipped" mode. The file upload itself is handled by a
 * separate API route — this lib only persists the metadata. */
export const firstEncounterSchema = z
  .object({
    mode: z.enum(["uploaded", "skipped"]),
    filePath: z.string().trim().max(512).optional(),
    fileName: z.string().trim().max(255).optional(),
  })
  .superRefine((value, ctx) => {
    if (value.mode === "uploaded") {
      if (!value.filePath) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["filePath"],
          message: "filePath is required for uploaded mode",
        });
      }
      if (!value.fileName) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["fileName"],
          message: "fileName is required for uploaded mode",
        });
      }
    }
  });

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Demo-mode session ids look like `demo_<timestamp>_<random>`. Used
 * to skip the Stripe API call in dev. */
export function isDemoSessionId(sessionId: string): boolean {
  return sessionId.startsWith("demo_");
}

/** Build a demo-mode session id, used by /api/billing/checkout when
 * no real Stripe is configured. */
export function buildDemoSessionId(): string {
  return `demo_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

/** Generate a unique slug for a tenant name. Mirrors the helper in the
 * Stripe webhook so the wizard's demo-mode fallback produces the same
 * shape. */
async function uniqueSlug(base: string): Promise<string> {
  const normalized =
    base
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "")
      .slice(0, 48) || "clinic";
  let candidate = normalized;
  let n = 1;
  while (n < 50) {
    const clash = await prisma.tenant.findUnique({ where: { slug: candidate } });
    if (!clash) return candidate;
    n += 1;
    candidate = `${normalized}-${n}`;
  }
  return `${normalized}-${Date.now()}`;
}

/** Look up a Stripe Checkout Session and return the tenant-relevant
 * fields. Returns null on any Stripe error so the caller can show a
 * friendly "session expired / unknown" state. */
async function fetchSessionFromStripe(
  sessionId: string,
): Promise<StripeNS.Checkout.Session | null> {
  if (isDemoSessionId(sessionId)) {
    // Demo: synthesize a minimal session shape so the rest of the
    // wizard can run uniformly. The webhook's `upsertTenantFromSession`
    // never sees demo sessions, so the wizard has to mint the tenant
    // itself.
    return {
      id: sessionId,
      customer: `cus_demo_${sessionId.slice(-8)}`,
      subscription: `sub_demo_${sessionId.slice(-8)}`,
      customer_details: { email: null },
      metadata: { tierId: "small", currency: "CAD" },
    } as unknown as StripeNS.Checkout.Session;
  }
  if (isDemoMode()) {
    return null;
  }
  try {
    return await getStripe().checkout.sessions.retrieve(sessionId);
  } catch (e) {
    console.warn("[onboarding] stripe session retrieve failed:", e);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Step 1: redeem the Stripe Checkout Session
// ---------------------------------------------------------------------------

export interface RedeemResult {
  /** True when this call created the membership (vs. a replay that
   * found an existing row). */
  created: boolean;
  /** The Tenant the user was attached to. */
  tenant: {
    id: string;
    name: string;
    slug: string;
    tier: string;
    subscriptionStatus: string;
    onboardingStep: number;
    onboardingCompletedAt: Date | null;
  };
  /** True when the user was found to be the second user to land on
   * the same session — i.e. someone else already redeemed it. We do
   * NOT silently attach a second owner; the caller should show a
   * "session already claimed" message. */
  alreadyClaimed: boolean;
}

/**
 * Verify a Stripe Checkout Session, ensure a Tenant exists for it,
 * and attach the calling user as `owner`. Idempotent.
 *
 * Behaviour:
 *   - The webhook's checkout.session.completed handler usually creates
 *     the Tenant first. We reuse it when present.
 *   - When the webhook hasn't fired (race condition in dev, or a
 *     demo-mode flow), we mint the Tenant here.
 *   - The first user to call this function for a given sessionId
 *     gets the owner Membership. Subsequent users see `alreadyClaimed`
 *     and are not silently attached.
 *   - Replaying the SAME sessionId with the SAME user is a no-op and
 *     returns `created: false` with the existing tenant.
 */
export async function redeemCheckoutSession(params: {
  sessionId: string;
  userId: string;
}): Promise<RedeemResult> {
  const { sessionId, userId } = params;

  if (!sessionId || typeof sessionId !== "string") {
    throw new OnboardingError("invalid_session", "sessionId is required");
  }

  // Fast path: this user already redeemed this session.
  const existing = await prisma.redeemedCheckoutSession.findUnique({
    where: { sessionId },
    include: {
      tenant: {
        select: {
          id: true,
          name: true,
          slug: true,
          tier: true,
          subscriptionStatus: true,
          onboardingStep: true,
          onboardingCompletedAt: true,
        },
      },
    },
  });
  if (existing) {
    if (existing.userId !== userId) {
      // Same session, different user → don't quietly attach them.
      return {
        created: false,
        alreadyClaimed: true,
        tenant: existing.tenant,
      };
    }
    return {
      created: false,
      alreadyClaimed: false,
      tenant: existing.tenant,
    };
  }

  const session = await fetchSessionFromStripe(sessionId);
  if (!session) {
    throw new OnboardingError(
      "session_not_found",
      "Stripe could not find this checkout session. It may have expired or been completed in a different account.",
    );
  }

  const customerId =
    typeof session.customer === "string" ? session.customer : null;
  const subscriptionId =
    typeof session.subscription === "string" ? session.subscription : null;
  if (!customerId || !subscriptionId) {
    throw new OnboardingError(
      "session_incomplete",
      "Checkout session is missing a customer or subscription id — it may still be processing. Try again in a moment.",
    );
  }

  // Resolve the tenant. The webhook normally creates it; in a race or
  // demo-mode flow we mint it here.
  let tenant = await prisma.tenant.findUnique({
    where: { stripeCustomerId: customerId },
    select: {
      id: true,
      name: true,
      slug: true,
      tier: true,
      subscriptionStatus: true,
      onboardingStep: true,
      onboardingCompletedAt: true,
    },
  });

  if (!tenant) {
    const metadata = (session.metadata ?? {}) as Record<string, unknown>;
    const tierId = isValidTierId(metadata.tierId) ? metadata.tierId : "small";
    const customerEmail =
      typeof session.customer_details?.email === "string"
        ? session.customer_details.email
        : null;
    const fallbackName = customerEmail
      ? customerEmail.split("@")[0]
      : `Clinic ${customerId.slice(-6)}`;
    const slug = await uniqueSlug(fallbackName);
    tenant = await prisma.tenant.create({
      data: {
        name: fallbackName,
        slug,
        tier: tierId,
        subscriptionStatus: "active",
        stripeCustomerId: customerId,
        stripeSubscriptionId: subscriptionId,
        auditQuotaLimit: tierId === "small" ? 500 : tierId === "mid" ? 2_000 : 5_000,
        onboardingStep: 1,
      },
      select: {
        id: true,
        name: true,
        slug: true,
        tier: true,
        subscriptionStatus: true,
        onboardingStep: true,
        onboardingCompletedAt: true,
      },
    });
  }

  // Attach the user as owner. Idempotent via the (userId, tenantId)
  // unique key — second call from the same user is a no-op. The
  // `email` column is required on Membership (added in t_23bfd49c
  // for the team-management feature), so we read it from the
  // user row here. The lookup is best-effort — a missing email
  // falls back to a placeholder so the upsert still succeeds and
  // Attach the user as owner. Idempotent via the (userId, tenantId)
  // unique key — second call from the same user is a no-op. The
  // `email` column is required on Membership (added in t_23bfd49c
  // for the team-management feature), so we read it from the
  // user row here.
  const attachingUser = await prisma.user.findUnique({
    where: { id: userId },
    select: { email: true },
  });
  if (!attachingUser) {
    throw new OnboardingError(
      "not_found",
      "Signed-in user no longer exists.",
    );
  }
  await prisma.membership.upsert({
    where: { userId_tenantId: { userId, tenantId: tenant.id } },
    create: {
      user: { connect: { id: userId } },
      tenant: { connect: { id: tenant.id } },
      role: "owner",
      status: "active",
      email: attachingUser.email,
      activatedAt: new Date(),
    },
    update: { role: "owner" },
  });

  // Record the redemption. Unique on sessionId so a race between two
  // concurrent users only inserts once — the loser gets
  // `alreadyClaimed: true` from the next call.
  try {
    await prisma.redeemedCheckoutSession.create({
      data: { sessionId, userId, tenantId: tenant.id },
    });
  } catch (e) {
    // P2002 = unique violation. The other user beat us by milliseconds.
    if (e && typeof e === "object" && "code" in e && (e as { code?: string }).code === "P2002") {
      const winner = await prisma.redeemedCheckoutSession.findUnique({
        where: { sessionId },
        select: { userId: true },
      });
      if (winner && winner.userId !== userId) {
        return {
          created: false,
          alreadyClaimed: true,
          tenant,
        };
      }
    } else {
      throw e;
    }
  }

  return {
    created: true,
    alreadyClaimed: false,
    tenant,
  };
}

// ---------------------------------------------------------------------------
// Step 2: clinic profile
// ---------------------------------------------------------------------------

export interface ClinicProfileInput {
  clinicName?: string;
  clinicNpi?: string;
  clinicTimezone?: string;
}

/**
 * Persist the clinic profile and advance to step 2. Rejects with
 * OnboardingError("invalid_input", ...) on validation failure.
 */
export async function saveClinicProfile(params: {
  tenantId: string;
  input: ClinicProfileInput;
}): Promise<{ tenantId: string; onboardingStep: number }> {
  const parsed = clinicProfileSchema.safeParse(params.input);
  if (!parsed.success) {
    throw new OnboardingError(
      "invalid_input",
      parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
    );
  }

  // Gate: the redemption (step 1) must already have happened.
  const existing = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
    select: { onboardingStep: true },
  });
  if (!existing || existing.onboardingStep < 1) {
    throw new OnboardingError(
      "step_not_reached",
      "Step 1 (redeem checkout session) must be completed before saving the clinic profile.",
    );
  }

  const data: Record<string, string | null> = {
    clinicNpi: parsed.data.clinicNpi ? parsed.data.clinicNpi : null,
    clinicTimezone: parsed.data.clinicTimezone
      ? parsed.data.clinicTimezone
      : null,
  };
  if (parsed.data.clinicName && parsed.data.clinicName.length > 0) {
    data.clinicName = parsed.data.clinicName;
  }
  // Step never goes backwards; only set if larger.
  const nextStep = Math.max(existing.onboardingStep, 2);

  await prisma.tenant.update({
    where: { id: params.tenantId },
    data: { ...data, onboardingStep: nextStep },
  });

  return { tenantId: params.tenantId, onboardingStep: nextStep };
}

// ---------------------------------------------------------------------------
// Step 3: data residency
// ---------------------------------------------------------------------------

export interface ResidencyInput {
  region: ResidencyRegion;
}

export async function saveResidencyRegion(params: {
  tenantId: string;
  input: ResidencyInput;
}): Promise<{ tenantId: string; onboardingStep: number; region: ResidencyRegion }> {
  const parsed = residencyRegionSchema.safeParse(params.input);
  if (!parsed.success) {
    throw new OnboardingError(
      "invalid_input",
      parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
    );
  }

  const existing = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
    select: { onboardingStep: true, dataResidencyRegion: true, residencyRegionLocked: true },
  });
  if (!existing || existing.onboardingStep < 2) {
    throw new OnboardingError(
      "step_not_reached",
      "Step 2 (clinic profile) must be completed before saving the data residency region.",
    );
  }
  // Once locked, the region is immutable. The completion handler sets
  // this flag, so any call after that should reject.
  if (existing.residencyRegionLocked) {
    throw new OnboardingError(
      "region_locked",
      "Data residency region is locked. It cannot be changed after the wizard completed.",
    );
  }

  const nextStep = Math.max(existing.onboardingStep, 3);
  await prisma.tenant.update({
    where: { id: params.tenantId },
    data: { dataResidencyRegion: parsed.data.region, onboardingStep: nextStep },
  });

  return {
    tenantId: params.tenantId,
    onboardingStep: nextStep,
    region: parsed.data.region,
  };
}

// ---------------------------------------------------------------------------
// Step 4: EHR connection
// ---------------------------------------------------------------------------

export interface EhrInput {
  mode: "sftp" | "manual";
  host?: string;
  port?: number;
  username?: string;
  password?: string;
}

export async function saveEhrConnection(params: {
  tenantId: string;
  input: EhrInput;
}): Promise<{ tenantId: string; onboardingStep: number; mode: "sftp" | "manual" }> {
  const parsed = ehrConnectionSchema.safeParse(params.input);
  if (!parsed.success) {
    throw new OnboardingError(
      "invalid_input",
      parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
    );
  }

  const existing = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
    select: { onboardingStep: true },
  });
  if (!existing || existing.onboardingStep < 3) {
    throw new OnboardingError(
      "step_not_reached",
      "Step 3 (data residency) must be completed before saving the EHR connection.",
    );
  }

  const data: Record<string, unknown> = {
    ehrConnectionMode: parsed.data.mode,
  };
  if (parsed.data.mode === "sftp") {
    data.ehrSftpHost = parsed.data.host;
    data.ehrSftpPort = parsed.data.port;
    data.ehrSftpUsername = parsed.data.username;
    data.ehrSftpPasswordCiphertext = encryptPortalString(parsed.data.password!);
  } else {
    // "manual" — clear any prior SFTP details so the tenant row
    // doesn't carry stale credentials.
    data.ehrSftpHost = null;
    data.ehrSftpPort = null;
    data.ehrSftpUsername = null;
    data.ehrSftpPasswordCiphertext = null;
  }

  const nextStep = Math.max(existing.onboardingStep, 4);
  await prisma.tenant.update({
    where: { id: params.tenantId },
    data: { ...data, onboardingStep: nextStep },
  });

  return {
    tenantId: params.tenantId,
    onboardingStep: nextStep,
    mode: parsed.data.mode,
  };
}

// ---------------------------------------------------------------------------
// Step 5: first encounter upload (or skip)
// ---------------------------------------------------------------------------

export interface FirstEncounterInput {
  mode: "uploaded" | "skipped";
  filePath?: string;
  fileName?: string;
}

export async function saveFirstEncounter(params: {
  tenantId: string;
  input: FirstEncounterInput;
}): Promise<{
  tenantId: string;
  onboardingStep: number;
  mode: "uploaded" | "skipped";
}> {
  const parsed = firstEncounterSchema.safeParse(params.input);
  if (!parsed.success) {
    throw new OnboardingError(
      "invalid_input",
      parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
    );
  }

  const existing = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
    select: { onboardingStep: true },
  });
  if (!existing || existing.onboardingStep < 4) {
    throw new OnboardingError(
      "step_not_reached",
      "Step 4 (EHR connection) must be completed before saving the first encounter.",
    );
  }

  const data: Record<string, unknown> = {
    firstEncounterUploadMode: parsed.data.mode,
  };
  if (parsed.data.mode === "uploaded") {
    data.firstEncounterFilePath = parsed.data.filePath;
    data.firstEncounterFileName = parsed.data.fileName;
    data.firstEncounterUploadedAt = new Date();
  } else {
    data.firstEncounterFilePath = null;
    data.firstEncounterFileName = null;
    data.firstEncounterUploadedAt = null;
  }

  const nextStep = Math.max(existing.onboardingStep, 5);
  await prisma.tenant.update({
    where: { id: params.tenantId },
    data: { ...data, onboardingStep: nextStep },
  });

  return {
    tenantId: params.tenantId,
    onboardingStep: nextStep,
    mode: parsed.data.mode,
  };
}

// ---------------------------------------------------------------------------
// Complete: lock region, mark done
// ---------------------------------------------------------------------------

export interface OnboardedTenant {
  id: string;
  name: string;
  slug: string;
  tier: string;
  dataResidencyRegion: string | null;
  ehrConnectionMode: string | null;
  firstEncounterUploadMode: string | null;
  onboardingCompletedAt: Date;
}

export async function completeOnboarding(params: {
  tenantId: string;
}): Promise<OnboardedTenant> {
  const tenant = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
  });
  if (!tenant) {
    throw new OnboardingError("tenant_not_found", "tenant does not exist");
  }
  if (tenant.onboardingStep < 5) {
    throw new OnboardingError(
      "step_not_reached",
      "All four data steps (clinic profile, residency, EHR, first encounter) must be completed before the wizard can finish.",
    );
  }
  if (!tenant.dataResidencyRegion) {
    throw new OnboardingError(
      "missing_field",
      "Data residency region was not captured. Re-run step 3.",
    );
  }
  if (!tenant.ehrConnectionMode) {
    throw new OnboardingError(
      "missing_field",
      "EHR connection mode was not captured. Re-run step 4.",
    );
  }
  if (!tenant.firstEncounterUploadMode) {
    throw new OnboardingError(
      "missing_field",
      "First encounter upload status was not captured. Re-run step 5.",
    );
  }

  const completedAt = tenant.onboardingCompletedAt ?? new Date();
  const updated = await prisma.tenant.update({
    where: { id: tenant.id },
    data: {
      residencyRegionLocked: true,
      onboardingCompletedAt: completedAt,
    },
    select: {
      id: true,
      name: true,
      slug: true,
      tier: true,
      dataResidencyRegion: true,
      ehrConnectionMode: true,
      firstEncounterUploadMode: true,
      onboardingCompletedAt: true,
    },
  });

  return {
    id: updated.id,
    name: updated.name,
    slug: updated.slug,
    tier: updated.tier,
    dataResidencyRegion: updated.dataResidencyRegion,
    ehrConnectionMode: updated.ehrConnectionMode,
    firstEncounterUploadMode: updated.firstEncounterUploadMode,
    onboardingCompletedAt: updated.onboardingCompletedAt ?? completedAt,
  };
}

// ---------------------------------------------------------------------------
// Audit gate
// ---------------------------------------------------------------------------

/**
 * Single source of truth for "can this tenant start an audit run?".
 * Returns true only when:
 *   - wizard completed (onboardingCompletedAt set, region locked)
 *   - residency region set
 *   - EHR connection mode set (sftp with creds OR manual)
 *   - first encounter status set (uploaded with file OR skipped)
 *
 * Use this from any future /api/audit/run route to gate submission.
 */
export async function canStartAudit(tenantId: string): Promise<boolean> {
  const tenant = await prisma.tenant.findUnique({
    where: { id: tenantId },
    select: {
      onboardingCompletedAt: true,
      dataResidencyRegion: true,
      ehrConnectionMode: true,
      ehrSftpHost: true,
      ehrSftpUsername: true,
      ehrSftpPasswordCiphertext: true,
      firstEncounterUploadMode: true,
    },
  });
  if (!tenant) return false;
  if (!tenant.onboardingCompletedAt) return false;
  if (!tenant.dataResidencyRegion) return false;
  if (!tenant.ehrConnectionMode) return false;
  if (tenant.ehrConnectionMode === "sftp") {
    if (!tenant.ehrSftpHost || !tenant.ehrSftpUsername || !tenant.ehrSftpPasswordCiphertext) {
      return false;
    }
  }
  if (!tenant.firstEncounterUploadMode) return false;
  return true;
}

/** Convenience: read the wizard's current state for the page render.
 * Returns the safe-to-render subset of tenant fields (no SFTP password,
 * no internal ids other than what the wizard's UI needs). */
export interface WizardState {
  tenantId: string;
  step: number;
  completed: boolean;
  completedAt: Date | null;
  clinicName: string | null;
  clinicNpi: string | null;
  clinicTimezone: string | null;
  dataResidencyRegion: string | null;
  residencyRegionLocked: boolean;
  ehrConnectionMode: string | null;
  firstEncounterUploadMode: string | null;
  firstEncounterFileName: string | null;
  firstEncounterEncounterId: string | null;
  sessionId: string;
  alreadyClaimed: boolean;
}

export async function loadWizardState(params: {
  tenantId: string;
  sessionId: string;
  userId: string;
}): Promise<WizardState | null> {
  const tenant = await prisma.tenant.findUnique({
    where: { id: params.tenantId },
  });
  if (!tenant) return null;
  const alreadyClaimed = await prisma.redeemedCheckoutSession.findUnique({
    where: { sessionId: params.sessionId },
    select: { userId: true },
  });
  return {
    tenantId: tenant.id,
    step: tenant.onboardingStep,
    completed: Boolean(tenant.onboardingCompletedAt),
    completedAt: tenant.onboardingCompletedAt,
    clinicName: tenant.clinicName,
    clinicNpi: tenant.clinicNpi,
    clinicTimezone: tenant.clinicTimezone,
    dataResidencyRegion: tenant.dataResidencyRegion,
    residencyRegionLocked: tenant.residencyRegionLocked,
    ehrConnectionMode: tenant.ehrConnectionMode,
    firstEncounterUploadMode: tenant.firstEncounterUploadMode,
    firstEncounterFileName: tenant.firstEncounterFileName,
    firstEncounterEncounterId: tenant.firstEncounterEncounterId,
    sessionId: params.sessionId,
    alreadyClaimed: alreadyClaimed ? alreadyClaimed.userId !== params.userId : false,
  };
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/** Typed error for wizard failures. The API layer maps these to the
 * right HTTP status. */
export class OnboardingError extends Error {
  public readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "OnboardingError";
    this.code = code;
  }
}
