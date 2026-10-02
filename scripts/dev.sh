#!/usr/bin/env bash
# Starts the whole local stack: Postgres + Redis (Docker), migrations, API and web.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Missing .env. Copy .env.example to .env and fill it in (see PROJECT_GUIDE.md)."; exit 1; }
set -a; . ./.env; set +a

docker compose up -d --wait
(cd apps/api && .venv/bin/alembic upgrade head)

trap 'kill 0' EXIT
(cd apps/api && .venv/bin/uvicorn app.main:app --reload --port "${API_PORT:-8010}") &
pnpm --filter @fleettms/web dev &
wait
