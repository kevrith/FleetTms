# The web app, served (and the API reverse-proxied) by Caddy, which also gets and renews the TLS certificates by itself.
# Build from the repository root:  docker build -f deploy/web.Dockerfile --build-arg VITE_API_URL=https://api.example.com -t fleettms-edge .
FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc tsconfig.base.json ./
COPY packages ./packages
COPY apps/web ./apps/web
RUN pnpm install --frozen-lockfile --filter "@fleettms/web..."
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN pnpm --filter @fleettms/web build

FROM caddy:2-alpine
COPY --from=build /repo/apps/web/dist /srv/app
COPY deploy/Caddyfile /etc/caddy/Caddyfile
