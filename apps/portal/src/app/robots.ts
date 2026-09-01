// Dynamic robots.txt for the Zorva portal.
//
// Only the reviewed core routes (/, /how-it-works, and /contact) are served
// as indexable marketing pages. Deferred marketing URLs remain crawlable long
// enough for search engines to observe their temporary noindex redirect; only
// authenticated routes are disallowed here.
//
// Note: robots.txt is a HINT, not a security control. The portal
// routes are also gated by the next-auth middleware in middleware.ts
// (or src/proxy.ts in this app) — robots.txt is the SEO layer on
// top of that, not a substitute for it.
import type { MetadataRoute } from "next";
// Routes that are NOT indexable. Prefix entries also cover nested paths
// (for example, /portal/ covers /portal/onboarding).
//
// Marketing URLs intentionally stay out of this list: their middleware
// response must be crawlable for a noindex redirect to be observed.
const DISALLOWED_ROUTES = [
  "/portal/",
  "/encounters/",
  "/findings/",
  "/billing/",
  "/dashboard/",
  "/settings/",
  "/team/",
  "/onboarding/",
  "/hq/",
  "/login",
  "/api/",
] as const;

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [...DISALLOWED_ROUTES],
      },
      // Tighten Google's crawler specifically — it actually reads
      // robots.txt reliably, so we mirror the wildcard rules here.
      // If we ever want different rules per UA (e.g. allowing a
      // specific preview bot), add them here.
      {
        userAgent: "Googlebot",
        allow: "/",
        disallow: [...DISALLOWED_ROUTES],
      },
    ],
    // The App Router sitemap is implemented in sitemap.ts. Keep this
    // fallback aligned with the live portal host when build-time env is absent.
    sitemap: `${process.env.NEXT_PUBLIC_SITE_URL ?? "https://zorva.ashbi.ca"}/sitemap.xml`,
  };
}
