# Deployment and go-live

How FleetTms runs in production, and the checklist for the day. The files are in `deploy/`; the recovery side is in `docs/disaster-recovery.md`.

## What runs

One machine to begin with, all in Docker Compose (`deploy/docker-compose.prod.yml`):

| Service | What it does |
|---|---|
| `edge` | Caddy: serves the web app, proxies the API, gets and renews TLS certificates by itself, adds security headers, caps request size. The only service with published ports (80 and 443). |
| `api` | The API, four worker processes (`deploy/api.Dockerfile`). Reachable only from `edge`. |
| `worker` | The background jobs: reminders, reports, retention, fraud sweeps, usage counting, heartbeat. Same image. |
| `migrate` | Runs `alembic upgrade head` once before the API and worker start. |
| `db` | PostgreSQL 16 with PostGIS and TimescaleDB, WAL archiving on to `BACKUP_DIR`. |
| `redis` | The job queue, rate-limit counters and usage counts, with a password and persistence. |

Run the uptime checker (`python -m app.uptime_check`) from a different machine.

## Settings

`deploy/.env.production.example` lists every setting. Copy it to `deploy/.env.production` (git-ignored) and fill it in. With `ENVIRONMENT=production` the API **refuses to start** if the JWT secret is short, the CORS origins or public address are not https, plan limits or billing or rate limits are off, the AI test stand-ins are set, or texts would still go to the in-memory stand-in. `/ready` shows whether it is healthy.

## What was checked, and what was not

The images were built and the whole stack was run on a developer machine under its own project name (so it could not touch the development stack), with random throwaway secrets, plain `http://localhost` addresses and `ENVIRONMENT=staging`. It found three real faults, all fixed: the API image lacked `httpx` (it was only in the development requirements), the worker showed as unhealthy (the image's health check asks a web port the worker does not serve), and `/ready` could not see the backups from inside the container (the folder was not mounted).

After the fixes, on that machine:
- the database came up with WAL archiving on, and the migrations ran from empty to the latest;
- the API and worker were healthy, and a real base backup was taken with `scripts/dr/backup.sh` (6.2 MB, one second) and an archived segment appeared;
- `/ready` reported ready with every check green: database, Redis, worker heartbeat, base backup age, WAL archive age;
- the web app and its security headers were served, and a page address (`/help`) fell back to the app as it should;
- a sign-up through the proxy worked, only the web app's address was allowed by CORS, and the sign-in rate limit answered 429 after 20 attempts, through the proxy and a password-protected Redis;
- with `ENVIRONMENT=production` and these settings the API refused to start and named the problems (http addresses, the in-memory text stand-in).

**Not checked:** real DNS and real TLS certificates (Caddy's automatic certificates, ports 80 and 443); a start in production mode with every setting valid; sending a real text or taking a real payment; a second machine or backups going to another disk; restoring from this stack's own backup (the restore drill in `docs/disaster-recovery.md` used a separate database); upgrading a running system; behaviour under load with this layout. The web image was built with CSP and cache headers that have been read, not tested in a browser.

## Go-live checklist

**Accounts and services (yours to arrange)**
- [ ] Hosting chosen (a region in or near Kenya if possible); a server with disk for the database, the media folder and Docker; a separate disk or bucket for `BACKUP_DIR`. Record the provider in `docs/legal/sub-processors.md`.
- [ ] Domain names for `APP_HOST` and `API_HOST` pointing at the server (an `A` record each), ports 80 and 443 open.
- [ ] Africa's Talking account, a registered sender name, credit; `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID` set. Send a real sign-in code to a real phone.
- [ ] Safaricom Daraja: the platform Paybill and passkey for subscriptions (`PLATFORM_SHORTCODE`, `PLATFORM_PASSKEY`) and the consumer key and secret; `PUBLIC_API_URL` reachable by Safaricom. Make one real payment of a small amount and check it marks the invoice paid.
- [ ] KRA eTIMS device registration, if invoicing through it from day one.
- [ ] Email sending (SMTP) and, if wanted, WhatsApp; `ANTHROPIC_API_KEY` if the reading and question features are on; `GOOGLE_MAPS_API_KEY` for route suggestions.
- [ ] Maps: the web map uses OpenStreetMap's public tile server, whose usage policy does not allow heavy commercial use. Choose a tile provider before launch and change `TILES` in `apps/web/src/MapView.tsx` and the policy line in `deploy/Caddyfile`.

**Before opening the doors**
- [ ] `deploy/.env.production` filled in; secrets generated, stored somewhere safe outside the server, and never in the repository.
- [ ] `docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml up -d --build`; `https://API_HOST/ready` answers `{"ready": true}`.
- [ ] Create the first platform admin (a user with `is_platform_admin`, two-step sign-in on) and make your own business a complimentary account.
- [ ] Backups: a daily timer for `scripts/dr/backup.sh` and `scripts/dr/backup-files.sh`; the first base backup taken; **a restore drill run against it** (`docs/disaster-recovery.md`).
- [ ] Uptime checker running elsewhere, with a working alert (send a test).
- [ ] The penetration test done and its critical and high findings fixed (`docs/security-review.md`).
- [ ] Legal documents approved, published, versions bumped; ODPC registration done (`docs/legal/odpc-registration-checklist.md`).
- [ ] Partner and support details set: `SUPPORT_WHATSAPP`, `SUPPORT_EMAIL`, `SUPPORT_HOURS`; first partner approved and a test referral taken through to a payment.
- [ ] Prices and the partner share decided (they are proposals in `plan_rules.py` and `config.py`).
- [ ] The store builds (`docs/release/store-submission.md`).

**Day one**
- [ ] Watch `/ready`, the worker heartbeat, SMS delivery and the first sign-ups. Keep the breach plan to hand.
- [ ] Take a manual base backup after the first real data arrives.

## Updating a running system

`git pull`, then the same `up -d --build`. The `migrate` service runs new migrations before the API restarts. Migrations are written to be additive; take a base backup first. Roll back by restoring the previous image tag; a migration that has run is undone with `alembic downgrade -1` run in the `migrate` image.
