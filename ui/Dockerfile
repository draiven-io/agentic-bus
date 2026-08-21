# Agentic Bus admin dashboard (Next.js 16).
#
# Server-side, the dashboard proxies /api/admin/* to the coordinator's REST
# API via a Next.js rewrite, so AGBUS_API_URL is read at container start.
#
# The browser talks to the LIP WebSocket directly, and NEXT_PUBLIC_* values
# are inlined at build time — hence NEXT_PUBLIC_WS_URL is a build argument.
# Its default suits `docker compose up` on a workstation, where the browser
# reaches the published port on localhost rather than the compose network.

FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:20-slim AS builder
WORKDIR /app

ARG NEXT_PUBLIC_WS_URL=ws://localhost:8765
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build


FROM node:20-slim AS runtime

LABEL org.opencontainers.image.title="Agentic Bus dashboard" \
      org.opencontainers.image.source="https://github.com/draiven-io/agentic-bus" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# `output: "standalone"` emits server.js plus only the node_modules it needs.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

USER node
EXPOSE 3000

CMD ["node", "server.js"]
