// GET /api/billing/tiers
//
// Returns the three pricing tiers as JSON. Source of truth is
// src/lib/pricing.ts (env-driven). The pricing page renders this on the
// server side; the response is also consumable by any external client.
//
// Cached for 60s with stale-while-revalidate — pricing data changes
// rarely, and we want the page to be fast and not hit env-reads on
// every request.

import { getPricingConfig } from "@/lib/pricing";

export const dynamic = "force-static";
export const revalidate = 60;

export async function GET() {
  const config = getPricingConfig();
  // Return only the public shape — drop internal-only fields if any are
  // added later. The "stripePriceId" fields are intentionally exposed
  // because they appear in the response so the client can confirm
  // which Stripe price will be used at checkout.
  return Response.json(config, {
    headers: {
      "Cache-Control": "public, max-age=60, s-maxage=60, stale-while-revalidate=300",
    },
  });
}
