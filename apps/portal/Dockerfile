# apps/portal/Dockerfile
#
# Multi-stage build for the Zorva marketing portal (Next.js 15 + React 19).
# Outputs the standalone bundle from `next build --standalone` (configured in
# next.config.ts via `output: 'standalone'`), so the runtime image carries
# only the compiled server + the static asset bundles — not node_modules.
#
# Build context: this directory (apps/portal/). The repo-root .gitignore
# does NOT exclude apps/portal/.next, so the .dockerignore here must drop
# .next and node_modules before the COPY.
#
# Why pnpm: pnpm-lock.yaml pins exact dep versions; the portal uses pnpm
# overrides in package.json (`@hono/node-server`, `postcss`) that npm does
# not honor. npm install would silently drift.
#
# Runtime port: 3020. The api stack runs on 8000 + Caddy; this container
# is exposed to the Traefik reverse proxy via the `ai-billing-audit_net`
# docker network and the `portal.ashbi.ca` Host() router.

# ---- Stage 1: deps -----------------------------------------------------
FROM node:22-slim AS deps

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pnpm via corepack (Node 22 ships corepack). Faster + reproducible.
# Pin to the same version the lockfile was generated with (9.15.9 as
# of 2026-06-26; the lockfile rejects frozen-lockfile installs when
# the active pnpm's overrides-handling differs).
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate

WORKDIR /app

# Copy lockfile + manifest first so the dep install is cached when only
# source files change.
COPY package.json pnpm-lock.yaml ./

# `--frozen-lockfile` fails the build if package.json would change
# pnpm-lock.yaml — the canonical way to enforce "lockfile is the source
# of truth" in CI.
# `--prod=false` because we need devDeps (typescript, prisma) for the
# `prisma generate` step in the build stage.
RUN pnpm install --frozen-lockfile --prod=false

# ---- Stage 2: migrations ------------------------------------------------
FROM deps AS migrate

COPY prisma ./prisma
COPY prisma.config.ts prisma.postgresql.config.ts ./
COPY scripts/prepare-postgresql-schema.mjs ./scripts/prepare-postgresql-schema.mjs

CMD ["pnpm", "prisma:migrate:deploy:postgresql"]

# ---- Stage 3: build -----------------------------------------------------
FROM node:22-slim AS build

RUN corepack enable && corepack prepare pnpm@9.15.9 --activate

WORKDIR /app

# Pull the installed node_modules from the deps stage so we don't
# reinstall.
COPY --from=deps /app/node_modules ./node_modules
COPY package.json pnpm-lock.yaml ./
COPY next.config.ts next-env.d.ts tsconfig.json prisma.config.ts prisma.postgresql.config.ts ./
COPY src ./src
COPY prisma ./prisma
COPY scripts/prepare-postgresql-schema.mjs ./scripts/prepare-postgresql-schema.mjs
COPY public ./public

# Prisma client is generated into src/generated/prisma (per
# prisma/schema.prisma `generator { output = "../src/generated/prisma" }`).
# This MUST happen before `pnpm build` because src/lib/prisma.ts and
# many route files import from `@/generated/prisma/client`; without
# the generated client the bundler fails with "module not found."
# Locally this happened implicitly from prior `pnpm dev` runs; the
# Dockerfile build is a clean checkout so we must generate explicitly.
RUN pnpm prisma:generate

# `next build` with `output: 'standalone'` in next.config.ts produces
# `.next/standalone/` with the minimal server + .next/static with the
# hashed asset bundles.
ENV NEXT_TELEMETRY_DISABLED=1
ENV DATABASE_URL=postgresql://build:build@127.0.0.1:9/build
RUN pnpm build

# Prisma client is generated into src/generated/prisma (per
# prisma/schema.prisma `generator { output = "../src/generated/prisma" }`).
# After build, the standalone server needs to find it. The standalone
# bundle copies node_modules recursively by default; we verify below.
RUN test -d .next/standalone || (echo "ERROR: standalone output missing — check next.config.ts output: 'standalone'" && exit 1)
RUN test -d .next/static || (echo "ERROR: .next/static missing" && exit 1)


# ---- Stage 4: runtime ---------------------------------------------------
FROM node:22-slim AS runtime

# pnpm not needed at runtime — the standalone server is plain Node.
WORKDIR /app

# Non-root user. Node 22-slim ships with a `node` user (uid 1000).
# Prisma needs the runtime binary (libssl, libgcc) for some Postgres
# TLS configurations — install just the openssl package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Switch to non-root.
USER node

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3020

# Copy the standalone server, the static asset bundles, and the public
# directory (favicon, og images, etc.). Standalone copies the relevant
# node_modules slice automatically.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/prisma ./prisma

EXPOSE 3020

# Healthcheck: a noop that confirms the Node process is up. The portal
# has no `/healthz` route today — a future card adds one. For now we
# just verify the process is alive and listening on 3020.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:'+process.env.PORT+'/login', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
