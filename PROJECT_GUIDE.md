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

- **Offline sync.** The phone queues what the driver does (`apps/mobile/src/offline/`): an encrypted vault (key in
  SecureStore), a store, and an engine that uploads photos (with phone-chosen ids) then sends actions to
  `POST /sync`. Every action has a client id; the server records a `SyncReceipt`, so a resend is a "duplicate".
  Server core functions (`do_start_trip`, `do_submit_inspection`, `do_add_fuel`, ...) are shared by the online
  endpoints and sync, take the time the driver did it, and never commit; callers commit. Keep new offline actions in
  `app/routers/sync.py` HANDLERS and `src/offline/runtime.tsx`, and add engine tests in `offline.test.ts`.
- **Device integrity and trust.** `POST /devices/integrity` (or the `device` part of a sync) records `mock_location`,
  `rooted` and `clock_changed`. Flags lower a vehicle's trust (`app/trust.py`) and never block work.
- **Fuel and floats.** Money is in cents. M-Pesa codes are 10 capital letters and numbers and unique per business.
  A float is recorded by owner or manager (`floats.manage`); `/me/float` is the driver's balance.
- **Emulator limits.** The Android emulator's still camera returns black frames, which the server refuses as blank, so
  photo steps cannot be completed there. Use a real phone for those. Airplane mode works:
  `adb shell cmd connectivity airplane-mode enable|disable`.

- **Expenses and floats.** An expense only counts when its status is `recorded` or `approved` (`COUNTED`). A float
  balance is floats sent less counted expenses paid from the float (`app/floatcalc.py`); a day sheet is the same sum cut
  at Nairobi midnight. Spend limits: most specific rule wins; the owner (`expenses.approve_limit`) is never held up.
  M-Pesa codes go through `app/mpesa.py` so a code is claimed once across fuel and expenses.
- **Reconciliation.** A driver submits a day; senior staff approve (`reconciliations.approve`, supervisors only for
  their own vehicles). Approval refreshes the figures, refuses while an expense waits for the owner, and a returned
  balance becomes a negative float transfer.
- **Work orders and service.** Defects become work orders inside `do_submit_inspection` (so offline-synced
  inspections do too). Completing a work order creates its expense and, for service, the history record and schedule
  reset. Service due logic is `app/service_rules.py`; reminders are `app/service_reminders.py` (once per due key).
- **Quick sign-in.** `DeviceLogin` holds a per-phone secret hash and a PIN hash. The secret is checked before the PIN so
  guessing from elsewhere cannot lock the owner out; five wrong PINs revoke it; logout-all revokes it. Drivers and
  turnboys only. The phone keeps its secret in SecureStore (`apps/mobile/src/quick.ts`).
- **Dashboard.** `GET /dashboard` builds numbers and alerts limited by the caller's permissions and vehicle scope.
  New alert kinds go in `app/routers/dashboard.py`; keep red (act now) ahead of amber (soon).

- **Scheduled reports.** `app/report_schedules.py` (job, 06:30 Nairobi), `app/report_delivery.py` (SMTP and WhatsApp
  senders; with no keys in `.env` an in-memory outbox is used), `app/report_files.py` (Excel and PDF). Keys are
  `SMTP_*` and `WHATSAPP_*` in `.env.example`. Permission: `reports.schedule` (owner, manager).

- **Sprint 6 (tyres, parts, incidents, SOS).** `app/routers/tyres.py` (+ `app/tyre_rules.py` for positions, km and
  due rules), `parts.py`, `incidents.py`, `sos.py`. Tyre and parts costs are booked as expenses on the vehicle when
  fitted or issued (completing a work order books only labour and non-store parts). The driver app sends
  `incident.report` and `sos.send` through the sync queue; the engine sends an SOS before anything else. Tyre serials
  are checked in `do_submit_inspection`; `/me/tyre-positions` deliberately hides the serials from drivers.
  Permissions: tyres and parts use `workshop.manage`; `incidents.manage` (owner, manager); `sos.respond` (owner,
  manager, supervisor).

- **Sprint 7 (clients, quotes, jobs, dispatch).** `app/routers/clients.py`, `quotes.py`, `jobs.py`. Quote maths is
  `app/quote_rules.py`, mirrored by `packages/business-rules/src/quotes.ts`; both must pass
  `packages/business-rules/src/quote-cases.json` (change a rule, change the cases). `app/scheduling.py` decides who is
  free (a lorry with a work order in progress or waiting for parts is in the workshop; overlapping trips for the lorry
  or crew are refused) and is used by every way of creating a trip. `app/jobs_service.py` keeps a job's status in step
  with its trips. Permissions: `clients.manage` (owner, manager, accountant), `jobs.manage` (owner, manager); anyone with
  `trips.view` can see jobs and the calendar, without prices.

- **Sprint 8 (proof of delivery, load checks, billing).** `app/pod.py` (code, signature, flags), `app/invoicing.py`
  (trip and contract invoices), `app/invoice_files.py` (PDF with the proof attached), `app/routers/invoices.py`. Billing
  and load rules are `app/billing_rules.py` and `app/load_rules.py`, mirrored in `packages/business-rules`
  (`billing.ts`, `load.ts`) and tested against `billing-cases.json` and `load-cases.json`. A wrong delivery code is
  counted in its own transaction, because the failed request rolls back. Odometer readings below the vehicle's last one
  are refused in `_record_reading`. Permission: `invoices.manage` (owner, accountant).

- **Sprint 9 (payments, debtors, reminders, eTIMS).** Client M-Pesa payments: `app/daraja.py` (Safaricom client, with a stand-in
  when `DARAJA_CONSUMER_KEY` is empty; callback addresses are `/hooks/c2b/{business}/{key}/...` because Safaricom refuses
  addresses containing "mpesa", and the key is an HMAC of the business id under `JWT_SECRET`, so rotating that secret means
  registering the addresses again), `app/payments.py` (one `MpesaTransaction` per M-Pesa code, so a repeat changes nothing; a
  payment is applied only when its account number names an open invoice, via `debtor_rules.invoice_number_from`; the rest waits
  in the queue; `allocate()` is the one place money goes onto an invoice from M-Pesa, auto or by hand), `routers/payments.py`.
  Statement import: `app/mpesa_statement.py` + `routers/statements.py` (CSV or Excel; matches fuel, expense and float claims by
  M-Pesa code, flags `statement_amount_differs` and `not_on_statement` on the claim, and recovers client payments whose
  notice was missed). Debtors and ageing: `routers/debtors.py`; rules in `app/debtor_rules.py` mirrored by
  `packages/business-rules/src/debtors.ts`, both tested against `debtor-cases.json`. Reminders: `app/payment_reminders.py`
  (daily 08:00; each step once per channel, only the latest step after a gap; off until the owner turns it on, off per client
  with `reminders_enabled`). eTIMS: `app/etims_rules.py` (invoice to KRA body, tax codes, retry gaps), `app/etims.py` (OSCU
  client and a stand-in when `ETIMS_BASE_URL` is empty; the device key is fetched when needed and never stored),
  `app/etims_service.py` (queue on issue, worker every 5 minutes, backoff, `needs_review` queue, credit note when a sent
  invoice is voided), `routers/etims.py`. Settings live in `PaymentSettings` (one row per business, `get_settings()`). eTIMS
  is written to KRA's OSCU documentation and has not been run against KRA's sandbox: check field names, item and tax codes
  there first. Permissions: `invoices.manage` for payments, statements, debtors and the eTIMS queue; `business.manage`
  (owner) to change settings, register with Safaricom and connect the device.

- **Sprint 10 (leases, finance, profit, payroll, suppliers).** Rules in `app/lease_rules.py` (lease charge, lease account standing, loan
  schedule, ownership monthly, net profit, "not paying off"), mirrored by `packages/business-rules/src/lease.ts` and tested against
  `lease-cases.json`, `finance-cases.json` and `profit-cases.json`; money in cents, percentages in hundredths so no float touches money.
  `app/leases.py` is the lease account (`run_month` works a month out and books offsets; one offset per expense or fuel entry through
  `source_id`; `add_payment`; `statement`), `app/lease_config.py` the responsibility matrix, `app/profit.py` the engine (one pass over a
  window of whole months, leases use the ledger row when the month has been run and the agreement's own terms when it has not, and a
  cost the lease makes the owner's is excluded from running costs and shown as `lessor_paid`), `app/payroll_service.py` (salary
  allocation by days crewed; approved runs are used, else the salary on file), `app/lease_notices.py` (daily SMS, monthly charges job).
  Routers: `leases`, `finance` (loans and ownership costs), `payroll`, `suppliers`, `profit`, `portal`. Permissions: `finance.view` to look,
  `leases.manage` and `payroll.manage` (owner, accountant) to change. A lessor is a membership with the `lessor` role and a `party_id`
  (invite with `party_id`); the portal answers "not found" for anyone else's lease. The M-Pesa code is claimed once across fuel,
  expenses, lease payments, loan repayments and advances (`app/mpesa.py`). The dashboard builds last month's profit on every load: move
  it to a cached figure in Sprint 16 if it gets slow.

- **Sprint 11 (phone GPS, live map, tracking links).** Rules in `app/gps_rules.py` mirrored by `packages/business-rules/src/gps.ts`, tested
  against `gps-cases.json`. `app/tracking.py` ingests a crew's fixes (`POST /trips/{id}/locations`): only the trip's own crew, only between
  the trip's start (2 minutes' slack) and its end, one row per vehicle and moment (`location_points` is a TimescaleDB hypertable on
  `recorded_at`; a hypertable row's time cannot be updated across chunks, so tests insert old rows rather than moving them). `finalise()` sets
  `gps_distance_km` and `distance_check` when a trip ends or late fixes arrive. `app/tracking_jobs.py`: going-dark watcher (every 5
  minutes, `GOING_DARK_MINUTES`) and the 12-month purge. `routers/livemap.py` is the map and a trip's path (`livemap.view`, supervisor scope
  applies), `routers/tracking_links.py` the client links (secret shown once, hash stored) and the public `GET /track/{token}`. On the phone,
  `apps/mobile/src/tracking/tracker.ts` is the tested logic (no trip begun means nothing kept; nothing kept after the trip's end; encrypted
  file; batches) and `task.ts` the Expo background task; tracking follows the trip's state in `offline/runtime.tsx`. The monitoring notice is
  `draft-2`; bump `MONITORING_NOTICE_VERSION` whenever what is tracked changes.
- **Development build for the phone.** Background location does not work in Expo Go on Android. To build one: `cd apps/mobile`, `npx expo
  prebuild --platform android` (the generated `android/` is git-ignored), then in `android/` use JDK 17 (`JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`;
  the JDK 21 here has no `jlink`), an installed NDK in `build.gradle` (`ndkVersion`; 27.1.12297006 worked here, the empty 26.1 folder does not), and
  `./gradlew assembleDebug -PreactNativeArchitectures=x86_64`. Install the APK, `adb reverse tcp:8081 tcp:8081`, run `expo start`, and
  grant background location. On the emulator, `adb emu geo fix <lng> <lat>` makes a fix.

- **Sprint 12 (trackers, tamper alerts, behaviour, immobiliser).** Rules are pure and mirrored in TypeScript, tested against shared case
  files: `behaviour_rules.py` (`step(state, fix)` returns the new state and the events found), `geofence_rules.py`, `immobiliser_rules.py`,
  and `gps_rules.three_way`. Traccar posts to `POST /hooks/traccar/{TRACCAR_FORWARD_KEY}` (`routers/trackers.py`; empty key means the
  address answers 403). `app/traccar.py` parses its JSON (speeds are in knots, the device is `device.uniqueId` which is the IMEI, alarms
  are `position.attributes.alarm`) and sends commands through its REST API (`TRACCAR_URL`, `TRACCAR_TOKEN`; with neither set a fake keeps
  the commands for tests). Traccar sends each position on its own and again inside the event it raised, so every step is idempotent:
  `tracker_ingest.handle_position` stores one row per vehicle and moment, and alerts and behaviour events are de-duplicated.
  Docker: `docker compose --profile tracking up -d traccar` after setting `TRACCAR_FORWARD_KEY`; with this Traccar version the forward
  settings are `FORWARD_TYPE=json` and `EVENT_FORWARD_TYPE=json` (the `enable` and `json` keys of older versions do nothing).
  Try it without hardware: `cd apps/api && TRACCAR_FORWARD_KEY=<key from .env> .venv/bin/python -m app.tracker_simulator --imei <imei> --scenario trip` (also
  `powercut`, `jamming`, `offline`; `--url`, `--delay`). Services: `alerts.py` (raise, de-duplicate, text, resolve), `behaviour.py`,
  `geofences.py`, `immobiliser.py`; jobs in `tracking_jobs.py` (`watch_devices` every 5 minutes). Permissions: `livemap.view` to see,
  `vehicles.manage` to fit trackers, `geofences.manage` and `alerts.manage` (owner, manager), `immobiliser.use` (owner only). The
  immobiliser always checks twice and never sends to a moving vehicle; do not add a way around it. Web: `pages/Tracking.tsx` (alerts,
  trackers, and the areas and behaviour tabs), `Replay.tsx` and `Immobiliser.tsx` cards on the vehicle and trip pages; `MapView` now draws
  areas and takes clicks. Mobile has no new screens in this sprint. Unverified: no real tracker; per-model alarm names.

## Testing against a real phone/emulator

- API tests use a separate `fleettms_test` database that they create and migrate themselves.
- Android emulator: `emulator -avd Pixel_6`, then `pnpm dev:mobile` and press `a`. The emulator reaches the host
  at `10.0.2.2`. Start the API with `--host 0.0.0.0`.

## Definition of Done

See docs/sprint-plan.md Section 1.3.

## Current sprint

Sprints 0 and 1 are done apart from carry-overs (staging, storage bucket, external applications, advocate
review). Sprint 2 (vehicles, ownership, staff, crews, documents, Excel import) is done. Sprint 3 (trips, odometer
capture, pre-trip inspection) is built and tested; automatic odometer reading needs a development build. Sprint 4
(offline sync, fuel, floats, device integrity) is built and tested; on a device, a full offline morning including a
real odometer photo and a real fake-GPS app are still to be tried. Sprint 5 (expenses, reconciliation, services, work orders,
dashboard, quick sign-in) is built and tested; use it on your own lorries for a full week and log every problem.
Sprints 6 to 8 (tyres and parts, clients and jobs, proof of delivery and billing) are built and tested. Sprint 9 (payments,
debtors, reminders, eTIMS) is built and tested against the stand-ins; it has not been run against the Safaricom or KRA
sandboxes (needs your keys). Sprint 10 (leases, loans, ownership costs, profit engine, payroll, suppliers, lessor portal) is built and
tested; compare its profit figures with your own spreadsheet on real lorries. Sprint 11 (phone GPS, live map, client tracking links) is built and was checked on the emulator with a development build; try it on a real phone in a moving lorry. Sprint 12 (trackers, tamper alerts, behaviour, immobiliser) is built and tested, and Traccar's post format was checked against a real Traccar server; no real tracker has been tried. Next: Sprint 13 (fraud engine, alerts, scorecards).

Create the first platform admin with `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_NAME` and `PLATFORM_ADMIN_PASSWORD`
set in `.env`, then `cd apps/api && .venv/bin/python -m app.cli create-platform-admin`.
