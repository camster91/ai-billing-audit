// Pricing tier configuration for Zorva 3-tier model.
//
// Source of truth: environment variables. The /api/billing/tiers route
// reads this module, never the component. To change prices or swap Stripe
// price IDs, edit .env / .env.example and restart the dev server — no
// code change required.
//
// Variable naming convention:
//   PRICING_TIER_<id>_<FIELD>_<CURRENCY>
// Examples:
//   PRICING_TIER_SMALL_PRICE_CAD=499
//   PRICING_TIER_SMALL_STRIPE_PRICE_ID_CAD=price_1ABC...
//   PRICING_TIER_SMALL_STRIPE_PRICE_ID_USD=price_1DEF...
//
// Audit caps are also env-configurable so the "Up to N audits/month" line
// can be tuned without a redeploy.
//
// Out of scope (per task body): tax, coupons, proration, real-time FX.

export type TierId = "small" | "mid" | "large";
export type CurrencyCode = "CAD" | "USD";

export interface Tier {
  id: TierId;
  name: string;
  auditCap: number;
  auditCapLabel: string;
  priceCAD: number;
  priceUSD: number;
  stripePriceIdCAD: string | null;
  stripePriceIdUSD: string | null;
  features: string[];
}

export interface PricingConfig {
  currency: { primary: CurrencyCode; secondary: CurrencyCode };
  compliance: {
    framework: string;
    specReference: string;
    rejectedModels: string[];
  };
  tiers: Tier[];
}

const FEATURES: Record<TierId, string[]> = {
  small: [
    "Up to 500 encounter audits / month",
    "LLM-agnostic audit engine (any provider, your keys)",
    "Deterministic runs: seed pinned, temperature=0",
    "PHIPA-aligned audit trail with hash-chain",
    "Email support, weekly digest",
  ],
  mid: [
    "Up to 2,000 encounter audits / month",
    "LLM-agnostic audit engine (any provider, your keys)",
    "Deterministic runs: seed pinned, temperature=0",
    "PHIPA-aligned audit trail with hash-chain",
    "Priority email support, daily digest",
    "Multi-user access (up to 5 seats)",
  ],
  large: [
    "Up to 5,000 encounter audits / month",
    "LLM-agnostic audit engine (any provider, your keys)",
    "Deterministic runs: seed pinned, temperature=0",
    "PHIPA-aligned audit trail with hash-chain",
    "Priority support with same-day response SLA",
    "Multi-user access (unlimited seats)",
    "Quarterly billing-rules tuning session",
  ],
};

const TIER_NAMES: Record<TierId, string> = {
  small: "Small practice",
  mid: "Mid clinic",
  large: "Large practice",
};

const TIER_CAPS: Record<TierId, number> = {
  small: 500,
  mid: 2_000,
  large: 5_000,
};

function envInt(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
}

function envStr(name: string, fallback: string | null): string | null {
  const raw = process.env[name];
  if (raw && raw.trim().length > 0) return raw.trim();
  return fallback;
}

/**
 * Build a Tier from env vars. Falls back to canonical Zorva defaults
 * (499 / 1499 / 2999 CAD, 369 / 1109 / 2219 USD) when env is not set —
 * dev never breaks on a missing env file.
 */
function buildTier(id: TierId): Tier {
  const upper = id.toUpperCase();
  return {
    id,
    name: envStr(`PRICING_TIER_${upper}_NAME`, TIER_NAMES[id]) ?? TIER_NAMES[id],
    auditCap: envInt(`PRICING_TIER_${upper}_AUDIT_CAP`, TIER_CAPS[id]),
    auditCapLabel: `Up to ${TIER_CAPS[id].toLocaleString("en-US")} audits / month`,
    priceCAD: envInt(`PRICING_TIER_${upper}_PRICE_CAD`, id === "small" ? 499 : id === "mid" ? 1_499 : 2_999),
    priceUSD: envInt(`PRICING_TIER_${upper}_PRICE_USD`, id === "small" ? 369 : id === "mid" ? 1_109 : 2_219),
    stripePriceIdCAD: envStr(`PRICING_TIER_${upper}_STRIPE_PRICE_ID_CAD`, null),
    stripePriceIdUSD: envStr(`PRICING_TIER_${upper}_STRIPE_PRICE_ID_USD`, null),
    features: FEATURES[id],
  };
}

/**
 * Public pricing config. Reads env on every call — keep cheap; called
 * once per /pricing render (server-side) and once per /api/billing/tiers
 * request.
 */
export function getPricingConfig(): PricingConfig {
  return {
    currency: {
      primary: (envStr("PRICING_CURRENCY_PRIMARY", "CAD") as CurrencyCode) ?? "CAD",
      secondary: (envStr("PRICING_CURRENCY_SECONDARY", "USD") as CurrencyCode) ?? "USD",
    },
    compliance: {
      framework: "AKS_Stark_safe_harbor",
      specReference: "Zorva §11",
      rejectedModels: ["percentage_of_revenue", "percentage_of_collected", "per_dollar_pricing"],
    },
    tiers: [buildTier("small"), buildTier("mid"), buildTier("large")],
  };
}

/**
 * Resolve the Stripe price ID for a tier + currency. Returns null if no
 * Stripe price ID is configured for that combination (the caller should
 * surface a config error rather than attempt checkout).
 */
export function getStripePriceId(tierId: TierId, currency: CurrencyCode): string | null {
  const tier = getPricingConfig().tiers.find((t) => t.id === tierId);
  if (!tier) return null;
  return currency === "CAD" ? tier.stripePriceIdCAD : tier.stripePriceIdUSD;
}

export function isValidTierId(value: unknown): value is TierId {
  return value === "small" || value === "mid" || value === "large";
}

export function isValidCurrencyCode(value: unknown): value is CurrencyCode {
  return value === "CAD" || value === "USD";
}
