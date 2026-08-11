// Dynamic robots.txt for the Zorva portal.
//
// Split rules: marketing routes (/, /pricing, /pilot, /security,
// /trust, /changelog, /how-it-works, /compare, /case-studies,
// /press, /careers, /team, /glossary, /technical, /status,
// /contact) are ALLOWED. Portal / auth routes (/portal/*,
// /encounters/*, /findings/*, /billing, /dashboard, /settings,
// /login, /api/*) are DISALLOWED so PHI / auth state is never
// accidentally indexed.
//
// The static fallback at apps/portal/public/robots.txt mirrors the
// same rules; this route handler is the authoritative version because
// Next.js serves /robots.txt from app/robots.ts when present.
//
// Note: robots.txt is a HINT, not a security control. The portal
// routes are also gated by the next-auth middleware in middleware.ts
// (or src/proxy.ts in this app) — robots.txt is the SEO layer on
// top of that, not a substitute for it.
import type { MetadataRoute } from "next";

// Routes that are NOT indexable. Each must start with "/" and end
// with "/" so that robots.txt matches every nested path under it
// (e.g. /portal/onboarding matches /portal/).
//
// Keep this list in sync with the per-page `robots: { index: false,
// follow: false }` exports in the corresponding app/<route>/page.tsx
// files. The list below is the *complete* deny list for the live
// site as of 2026-06-24.
const DISALLOWED_ROUTES = [
  "/portal/",
  "/encounters/",
  "/findings/",
  "/billing/",
  "/dashboard/",
  "/settings/",
  "/login",
  "/api/",
  "/about",
  "/calculator",
  "/case-studies",
  "/changelog",
  "/compare",
  "/faq",
  "/for/",
  "/legal/",
  "/pilot",
  "/press",
  "/pricing",
  "/security",
  "/status",
  "/technical",
  "/trust",
  "/what-zorva-finds",
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
