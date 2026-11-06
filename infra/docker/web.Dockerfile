# syntax=docker/dockerfile:1
# Next.js standalone image. Build context: repository root (needs packages/shared-contracts).
FROM node:22-alpine AS deps
WORKDIR /repo/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

FROM node:22-alpine AS build
# Rewrites are compiled at build time, so the API address is a build argument.
ARG API_INTERNAL_URL=http://api:8000
ENV NEXT_TELEMETRY_DISABLED=1 API_INTERNAL_URL=${API_INTERNAL_URL}
WORKDIR /repo
COPY packages/shared-contracts ./packages/shared-contracts
COPY apps/web ./apps/web
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
WORKDIR /repo/apps/web
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /repo/apps/web/.next/standalone ./
COPY --from=build --chown=app:app /repo/apps/web/.next/static ./.next/static
USER app
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD wget -qO- http://127.0.0.1:3000/login >/dev/null || exit 1
CMD ["node", "server.js"]
