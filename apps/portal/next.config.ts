import type { NextConfig } from "next";

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
};

export default nextConfig;
