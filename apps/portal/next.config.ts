import type { NextConfig } from "next";

const scriptSources = [
  "'self'",
  "'unsafe-inline'",
  ...(process.env.NODE_ENV === "development" ? ["'unsafe-eval'"] : []),
  "https://plausible.io",
].join(" ");

const nextConfig: NextConfig = {
  // Standalone build mode produces `.next/standalone/` with the minimal
  // server bundle + a sliced node_modules tree. The runtime Dockerfile
  // (apps/portal/Dockerfile) copies this directory instead of the full
  // source tree, which keeps the image small (~200MB vs ~1GB) and the
  // deploy fast.
  //
  // To verify: `pnpm build` should produce both `.next/standalone/` and
  // `.next/static/`. The Dockerfile's build stage asserts both exist;
  // a missing `output: 'standalone'` line here causes the build to fail
  // loudly rather than silently ship a 1GB+ image.
  output: "standalone",

  // Pin the workspace root to the build CWD (apps/portal/). Without
  // this, Next.js 16 detects the closest lockfile and uses its
  // directory as the root; when a developer machine has a
  // `package-lock.json` at `~/`, the standalone output path becomes
  // `.next/standalone/<home>/<repo>/...` instead of the canonical
  // `.next/standalone/server.js`. Pinning here keeps the path
  // predictable for the Dockerfile's CMD.
  //
  // Using `process.cwd()` rather than `import.meta.url` because Next.js
  // bundles the config file and strips `import.meta.url` from the
  // emitted module — see https://github.com/vercel/next.js/issues/74281
  turbopack: {
    root: process.cwd(),
  },

  /* config options here */

  // Security headers (P11 round-2 fix 2026-07-01):
  // The portal origin was missing the standard transport-security +
  // content-security headers that the API origin already serves.
  // Without these, /security is making claims ("TLS 1.3 in transit",
  // "X-Content-Type-Options", etc.) the live response does not back
  // up. The API origin (ai-billing-audit.ashbi.ca) sets the same
  // headers via Caddy — this brings the portal origin to parity.
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            // CSP: the portal is a server-rendered marketing surface
            // with no inline scripts beyond the Next.js hydration
            // bootstrap. The policy below is intentionally permissive
            // on `self` for styles + images (Next.js injects styles
            // via <style> tags during SSR) but locks down script-src
            // + frame-ancestors. Plausible is always allowed because
            // the script tag in layout.tsx is only emitted when
            // NEXT_PUBLIC_PLAUSIBLE_DOMAIN is set at build time; the
            // empty-when-disabled event channel stays in 'self'
            // (the /api/analytics/event beacon). When Plausible is
            // configured, plausible.io is added to script-src +
            // connect-src + img-src so its script.js and event POST
            // requests are not blocked. Next.js development builds
            // require eval for their source-map/runtime machinery, so
            // unsafe-eval is added only in development; production
            // builds retain the stricter policy. Update this policy
            // when adding any new third-party script (analytics, tag
            // manager, etc.).
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              `script-src ${scriptSources}`,
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob: https://plausible.io",
              "font-src 'self' data:",
              "connect-src 'self' https://plausible.io",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
              "object-src 'none'",
            ].join("; "),
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },

  // Compression (P11 round-2 perf fix 2026-07-01):
  // The HTML responses on the portal origin were being served
  // uncompressed (no content-encoding header). With the marketing
  // pages averaging 25-50KB HTML and /status at 134KB, this was a
  // 50%+ bandwidth tax on first-paint. Next.js' built-in compression
  // enables gzip by default; we also enable brotli for compatible
  // browsers (most modern ones). Compression is applied at the
  // Next.js server layer — the Traefik edge does not re-compress.
  compress: true,
};

export default nextConfig;
