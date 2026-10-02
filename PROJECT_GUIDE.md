# FleetTms Project Guide

Read this at the start of every work session.

## Summary

FleetTms is a fleet and transport management system for Kenyan lorry businesses: visibility, true profit,
fraud detection, discipline and cash control. Multi-tenant SaaS, first tenant is Kelvin's own fleet.
Full spec: [docs/masterplan.md](docs/masterplan.md). Build plan: [docs/sprint-plan.md](docs/sprint-plan.md).

## Stack

Monorepo (pnpm workspaces). React + TypeScript web, Expo mobile, FastAPI backend, PostgreSQL + PostGIS +
TimescaleDB, Redis (arq job queue), S3-compatible storage, Traccar for trackers (later sprints).

## Folder structure

- `apps/web` React + Vite dashboard
- `apps/mobile` Expo app (driver and owner)
- `apps/api` FastAPI backend (`app/`, `migrations/`, `tests/`)
- `packages/types` shared TypeScript types
- `packages/business-rules` shared rules (money, billing, lease, profit, fraud) with tests
- `packages/design-tokens` colours, spacing, typography
- `packages/api-client` shared API client
- `docs/` masterplan and sprint plan; `infra/` deployment config; `scripts/` dev helpers

## Non-negotiable rules

- Every record belongs to a business (tenant); every query is tenant-scoped.
- Every endpoint checks role and permissions (including Lessor and Workshop).
- Create/edit/delete on financial, trip, lease and inspection records writes to the audit log.
- Money is stored in cents (KES). Times stored in UTC, shown in Africa/Nairobi.
- No secrets in code or docs; use environment variables. `.env` is never committed.
- Business rules live in `packages/business-rules`, never duplicated in web and mobile. The role to permission
  matrix is the exception that lives in one place only: `apps/api/app/permissions.py`. Clients read the
  resulting `permissions` list from `GET /auth/me` and never hardcode role checks.
- Personal data handling follows masterplan Section 11.
- No emoji in code or UI; icons come from lucide-react.

## Running things

First time setup:

1. `cp .env.example .env`, then set `POSTGRES_PASSWORD` and put the same value into `DATABASE_URL`
   (`postgresql+asyncpg://fleettms:<password>@localhost:5442/fleettms`).
2. `pnpm install`
3. `cd apps/api && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`

Daily:

- `pnpm dev` starts Docker (db + redis), runs migrations, API (http://localhost:8010) and web (http://localhost:5180).
- `pnpm dev:mobile` starts Expo. On a real phone set `EXPO_PUBLIC_API_URL` to your machine's LAN address.
- Tests: `pnpm test` (JS) and `cd apps/api && set -a && . ../../.env && set +a && .venv/bin/pytest` (needs the Docker db and redis up)
- Lint/typecheck: `pnpm lint`, `pnpm typecheck`, `cd apps/api && .venv/bin/ruff check .`
- Migrations: `cd apps/api && .venv/bin/alembic revision -m "msg"` then `alembic upgrade head`

Ports are non-default (Postgres 5442, API 8010, web 5180) because the usual ones are used by other projects
on the dev machine.

## Patterns (decided in Sprint 1)

- **Tenancy.** A model that holds tenant data mixes in `TenantMixin` (`app/tenancy.py`). Every SELECT, UPDATE and
  DELETE on it is filtered by the current business automatically, new rows are stamped with it, and a query with
  no tenant context raises `TenantContextError` (fails closed). The context is set per request by `load_principal`
  in `app/deps.py`. Login and company switching are the only places that cross tenants, and they opt in with
  `.execution_options(skip_tenant=True)`. Do not add other uses without a reason.
- **Permissions.** Protect endpoints with `Depends(require("some.permission"))`. Add new permissions and role
  mappings in `app/permissions.py` and extend `tests/test_permissions.py` in the same change.
- **Audit.** Call `audit.record(...)` in the same transaction as the change, before `commit()`. The table is
  append-only (database trigger). Never put secrets in the before/after snapshots.
- **Sessions.** Short-lived access JWT plus rotating refresh token. The session row is checked on every request,
  so revoking it or removing a membership cuts access at once. Re-use of an old refresh token ends the session.
- **Two-step verification.** Owner, manager, supervisor and accountant need a second step: an authenticator app
  (TOTP) or an SMS code, never both (`has_two_factor()` in `app/auth_service.py`). Drivers and turnboys sign in
  with phone number plus SMS code only. SMS codes live in `otp_challenges` with a `purpose`, so a code for one
  purpose never works for another.
- **Commits.** Endpoints call `await db.commit()` explicitly.
- **Dev only.** With `ENVIRONMENT=development` the fake SMS sender prints the one-time code to the API console.
- **Web tokens** live in localStorage for now (simple, but exposed to XSS). Revisit in Sprint 16 (httpOnly cookies).
- **Deleting a tenant** will need a privileged purge job: the audit trigger blocks cascading deletes by design.
- **Supervisor vehicle scope** (`Principal.vehicle_scope`) is enforced through `app/vehicle_scope.py`: use
  `scope_vehicles()` on vehicle queries and `require_vehicle_in_scope()` for single records. Out-of-scope
  vehicles return 404, not 403. Every new vehicle-linked endpoint must use these.
- **Crew assignments** are closed, never deleted (history). Partial unique indexes allow one open driver and one
  open turnboy per vehicle, and one open vehicle per person.
- **Document reminders** (`app/reminders.py`) run daily at 07:00 Africa/Nairobi from the arq worker
  (`cd apps/api && .venv/bin/arq app.worker.WorkerSettings`). Each reminder is recorded, so none repeats.
- **Excel import** (`app/routers/imports.py`) is all-or-nothing with per-row savepoints. New importable things
  (clients, suppliers, balances) go in as another `_kind_row` function plus a template.
- **Audit snapshots** go through `audit.snapshot()`, which makes dates, decimals and ids JSON-safe. Do not pass raw
  model fields to `audit.record()`.
- **Demo data:** set `DEMO_OWNER_EMAIL` and `DEMO_OWNER_PASSWORD` in `.env`, then `python -m app.cli seed-demo`.

- **Photos** go through `app/photos.py`: real image, at least 480 px on the short side, not mostly black or white,
  fresh (camera: claimed capture time within 10 minutes; web: the picture's own EXIF time), never seen before in
  the business. Stored by `app/storage.py` (local disk in `media_store/`, git-ignored; S3 later) and viewed only
  through 5-minute signed links from `photo_out()`. A photo backs one record: attach it with `claim_photo()`.
- **Inspections and trips.** Today's inspection (Africa/Nairobi day) must be passed, passed with defects, or
  overridden before `POST /trips/{id}/start`. Only owner and manager hold `inspections.override`. Odometer flags
  (`mismatch`, `backward`, `large_jump`, `no_location`) are stored on the reading and never block; the rules live in
  `app/odometer.py` and `packages/business-rules/src/odometer.ts` (keep them in step).
- **Mobile capture** uses `src/capture.tsx` (live camera only; do not add an image picker). In the Android emulator
  the still camera returns a black frame, so end-to-end photo capture needs a real phone.

## Testing against a real phone/emulator

- API tests use a separate `fleettms_test` database that they create and migrate themselves.
- Android emulator: `emulator -avd Pixel_6`, then `pnpm dev:mobile` and press `a`. The emulator reaches the host
  at `10.0.2.2`. Start the API with `--host 0.0.0.0`.

## Definition of Done

See docs/sprint-plan.md Section 1.3.

## Current sprint

Sprints 0 and 1 are done apart from carry-overs (staging, storage bucket, external applications, advocate
review). Sprint 2 (vehicles, ownership, staff, crews, documents, Excel import) is done: tested, the web was
driven end to end in headless Chrome, and the mobile screens were run on the Android emulator. Sprint 3 (trips, odometer capture, pre-trip inspection)
is built and tested (web driven in headless Chrome; mobile flow checked on the emulator up to the camera). Not yet
built: automatic odometer reading (needs a development build). Next: Sprint 4 (offline sync, fuel, floats, device
integrity).

Create the first platform admin with `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_NAME` and `PLATFORM_ADMIN_PASSWORD`
set in `.env`, then `cd apps/api && .venv/bin/python -m app.cli create-platform-admin`.
