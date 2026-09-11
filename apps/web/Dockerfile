# syntax=docker/dockerfile:1
#
# Alppy web. Multi-stage: the final image carries the standalone Next.js output
# and nothing else — no pnpm store, no source, no dev dependencies.

# Pinned by digest, not by tag (D18) — see apps/api/Dockerfile for why.
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable

# --- dependencies -----------------------------------------------------------
FROM base AS deps
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* .npmrc ./
COPY apps/web/package.json apps/web/
COPY packages/ui/package.json packages/ui/
COPY packages/shared/package.json packages/shared/
# No `|| pnpm install` fallback: the lockfile is committed, CI installs with
# `--frozen-lockfile` everywhere else, and a fallback that quietly resolves
# fresh versions is how two builds a week apart stop being the same image
# (D17). Out-of-date lockfile means fix the lockfile, not ship a different one.
RUN pnpm install --frozen-lockfile

# --- build ------------------------------------------------------------------
FROM base AS build
WORKDIR /repo
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
COPY --from=deps /repo/packages/ui/node_modules ./packages/ui/node_modules
COPY . .
# Next inlines NEXT_PUBLIC_* into the client bundle at build time, so this has
# to be a build arg: setting it only at runtime leaves the browser calling a
# same-origin /api/v1 that this container does not serve.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
# Empty by default, which is what keeps the session gate on: the middleware
# only stands aside for the literal "1".
ARG NEXT_PUBLIC_ALPPY_DEMO_MODE=
ENV NEXT_PUBLIC_ALPPY_DEMO_MODE=$NEXT_PUBLIC_ALPPY_DEMO_MODE
ENV NEXT_TELEMETRY_DISABLED=1 ALPPY_STANDALONE=1
# @alppy/ui resolves through ./dist, and .dockerignore excludes every dist/ —
# correctly, since a stale one from the host is worse than none. So it has to
# be compiled here, before Next can resolve the import. Without this the build
# fails with "Module not found: Can't resolve '@alppy/ui'".
RUN pnpm --filter @alppy/ui build
RUN pnpm --filter @alppy/web build

# --- runtime ----------------------------------------------------------------
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000

RUN addgroup -g 10001 -S alppy && adduser -u 10001 -S alppy -G alppy

COPY --from=build --chown=alppy:alppy /repo/apps/web/.next/standalone ./
COPY --from=build --chown=alppy:alppy /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=alppy:alppy /repo/apps/web/public ./apps/web/public

USER alppy
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
