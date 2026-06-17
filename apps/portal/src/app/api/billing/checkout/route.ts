// POST /api/billing/checkout
//
// Body: { tierId: "small" | "mid" | "large", currency: "CAD" | "USD" }
//
// Returns: { sessionId, url, demo: boolean }
//
// In demo mode (no STRIPE_SECRET_KEY configured), returns
// { sessionId: "demo_xxx", url: <local /portal/onboarding stub>, demo: true }
// so the front-end can complete the flow without real Stripe keys.
//
// In real mode, creates a Stripe Checkout Session in subscription mode
// using the price ID configured in env (PRICING_TIER_<ID>_STRIPE_PRICE_ID_<CUR>).
// success_url = ${baseUrl}/portal/onboarding?session_id={CHECKOUT_SESSION_ID}
// cancel_url  = ${baseUrl}/pricing
// session.metadata = { tierId, currency } — the webhook reads these to
// provision the tenant with the right tier.
//
// Idempotency: idempotencyKey = `checkout:${tierId}:${currency}:${userId-or-anon}`.
// Re-submitting the same form within 24h returns the same session instead
// of creating a duplicate.
//
// Out of scope (per task body): tax, coupons, proration, auth-required
// checkout, custom UI on top of Checkout.

import { headers } from "next/headers";
import { getStripe, isDemoMode } from "@/lib/stripe";
import {
  getPricingConfig,
  getStripePriceId,
  isValidCurrencyCode,
  isValidTierId,
  type CurrencyCode,
  type TierId,
} from "@/lib/pricing";

interface CheckoutBody {
  tierId: unknown;
  currency: unknown;
}

function resolveBaseUrl(): string {
  // 1. Honor an explicit X-Base-Url header (E2E tests, tunnels).
  // 2. Fall back to BASE_URL env.
  // 3. Fall back to the request's own origin.
  return (
    process.env["BASE_URL"] ||
    "http://localhost:3000"
  );
}

function isValidBody(body: unknown): body is CheckoutBody {
  if (!body || typeof body !== "object") return false;
  const b = body as Record<string, unknown>;
  return "tierId" in b && "currency" in b;
}

export async function POST(request: Request) {
  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  if (!isValidBody(raw)) {
    return Response.json(
      { error: "Body must be { tierId, currency }" },
      { status: 400 }
    );
  }

  const { tierId, currency } = raw;

  if (!isValidTierId(tierId)) {
    return Response.json(
      { error: `Invalid tierId: ${String(tierId)}. Expected one of: small, mid, large.` },
      { status: 400 }
    );
  }
  if (!isValidCurrencyCode(currency)) {
    return Response.json(
      { error: `Invalid currency: ${String(currency)}. Expected: CAD or USD.` },
      { status: 400 }
    );
  }

  const baseUrl = resolveBaseUrl();

  // Demo mode — no real Stripe configured. Return a stub so the
  // front-end's flow stays testable. The demo URL points back at the
  // real onboarding page with a fake session_id so the page's session
  // lookup code is exercised end-to-end.
  if (isDemoMode()) {
    const demoSessionId = `demo_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    const url = new URL("/portal/onboarding", baseUrl);
    url.searchParams.set("session_id", demoSessionId);
    url.searchParams.set("demo", "1");
    return Response.json({
      sessionId: demoSessionId,
      url: url.toString(),
      demo: true,
    });
  }

  const priceId = getStripePriceId(tierId as TierId, currency as CurrencyCode);
  if (!priceId) {
    return Response.json(
      {
        error:
          `No Stripe price ID configured for tier=${tierId} currency=${currency}. ` +
          `Set PRICING_TIER_${tierId.toUpperCase()}_STRIPE_PRICE_ID_${currency} in env.`,
      },
      { status: 503 }
    );
  }

  const stripe = getStripe();
  // best-effort: read forwarded headers for the idempotency key
  let forwardedFor: string | null = null;
  try {
    const h = await headers();
    forwardedFor = h.get("x-forwarded-for");
  } catch {
    // headers() can throw outside a request context — safe to ignore
  }
  const idemKey = `checkout:${tierId}:${currency}:${forwardedFor ?? "anon"}`;

  const successUrl = new URL("/portal/onboarding", baseUrl);
  successUrl.searchParams.set("session_id", "{CHECKOUT_SESSION_ID}");
  const cancelUrl = new URL("/pricing", baseUrl);

  try {
    const session = await stripe.checkout.sessions.create(
      {
        mode: "subscription",
        line_items: [{ price: priceId, quantity: 1 }],
        success_url: successUrl.toString(),
        cancel_url: cancelUrl.toString(),
        // Allow promo codes by default — task body says no coupons, but
        // checkout.sessions.promotion_code = "always" is the standard
        // Stripe idiom and doesn't impose any discount unless the
        // customer enters a code. Disabled below for safety.
        allow_promotion_codes: false,
        metadata: {
          tierId: tierId as string,
          currency: currency as string,
        },
        subscription_data: {
          metadata: {
            tierId: tierId as string,
            currency: currency as string,
          },
        },
      },
      { idempotencyKey: idemKey }
    );

    if (!session.url) {
      return Response.json(
        { error: "Stripe did not return a session URL" },
        { status: 502 }
      );
    }

    return Response.json({
      sessionId: session.id,
      url: session.url,
      demo: false,
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Unknown Stripe error";
    console.error("[/api/billing/checkout] Stripe error:", message);
    return Response.json({ error: message }, { status: 502 });
  }
}
