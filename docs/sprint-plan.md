# FleetTms — Sprint Plan

> **Version:** 1.1
> **Date:** 1 October 2026
> **Companion to:** `masterplan.md` v1.1 (read that first; this plan turns it into buildable sprints)
> **Team:** Kelvin, solo founder and developer — Kastra Enterprises
> **Cadence:** 2-week sprints (Sprint 0 is 1 week), about **35 weeks** total to public launch

---

## How to Use This Plan

1. Put `masterplan.md` and `sprint-plan.md` in a `/docs` folder at the root of the repository.
2. Work **one sprint at a time**, and inside a sprint, **one story at a time**.
3. Each sprint has:
   - **Goal**: what "done" looks like for the sprint.
   - **Stories**: the work, split by Backend / Web / Mobile / Other.
   - **Acceptance criteria**: how you check it works.
   - **Kickoff brief**: a short summary of the sprint's scope and rules to start from.
   - **Demo**: what you should be able to show at the end.
4. As each story is finished and verified, tick its checkbox (`- [x]`). A partly done story stays unticked, with an italic note saying what is left.
5. At the end of each sprint, update the **progress log** (Section 4) and the project guide with any new decisions.

---

## 1. Development Workflow

### 1.1 Project guide file (set up in Sprint 0)
Keep a project guide at the root of the repository (`PROJECT_GUIDE.md`) and read it at the start of every work session. It should contain:

- **Project summary**: one paragraph on what FleetTms is, linking to `docs/masterplan.md`.
- **Tech stack**: monorepo; React + TypeScript web; Expo (React Native) mobile; FastAPI backend; PostgreSQL + PostGIS + TimescaleDB; Redis job queue; S3-compatible storage; Traccar for trackers.
- **Folder structure**: where the web app, mobile app, backend, shared packages, and docs live.
- **Non-negotiable rules:**
  - Every database record belongs to a business (tenant). Every query must be scoped by tenant. Never skip this.
  - Every endpoint checks the user's role and permissions, including the limited **Lessor** and **Workshop** roles.
  - Every create/edit/delete on financial, trip, lease, or inspection records writes to the audit log.
  - Money stored in the smallest unit (cents) to avoid rounding errors; currency is KES.
  - All times stored in UTC, displayed in Africa/Nairobi.
  - No secrets in code; use environment variables.
  - Business rules (billing, lease charges, profit, fraud checks) live in shared packages, not duplicated in web and mobile.
  - Personal data handling follows Section 11 of the masterplan (data minimisation, retention, consent).
- **How to run things**: commands to start each app, run tests, run migrations, seed demo data.
- **Definition of Done** (see 1.3).
- **Current sprint**: updated at each sprint start.

### 1.2 Story workflow
1. **Plan before building**: list the files to change, the data changes, and the tests to add.
2. **Check the plan against the masterplan** section it implements.
3. **Build it, with tests.**
4. **Run the tests and the app.** Click through the feature on web and on a real Android phone.
5. **Commit** with a clear message on a feature branch, then merge.
6. **Update the project guide** if a new decision or pattern was introduced.

### 1.3 Definition of Done (applies to every story)
- [ ] Works on **web** and **mobile** where the story applies.
- [ ] Tenant isolation and role permissions enforced and **tested**.
- [ ] Audit log entries written for sensitive changes.
- [ ] Automated tests for business rules and API endpoints pass.
- [ ] Works **offline** on mobile where the story involves driver data capture.
- [ ] Handles errors with clear, plain-English messages.
- [ ] No secrets committed; no personal data in logs.
- [ ] Database migration included and reversible.
- [ ] Tested manually on a low-end Android phone.

### 1.4 Working tips
- Refer to the masterplan by section: "Section 5.23 (Leasing)."
- Be explicit about **who** can do **what**: "Only Owner, Manager, and Supervisor (assigned vehicles only) can approve."
- Use **seed data** that looks like real Kenyan operations (registrations like KBX 123A, routes like Naivasha–Nairobi, M-Pesa codes, a leased lorry on a 30% revenue share).
- Every 2–3 sprints, review the codebase for tenant isolation gaps, missing permission checks, and duplicated business logic.

---

## 2. Sprint Overview

| Sprint | Weeks | Phase | Theme | Key milestone |
|---|---|---|---|---|
| **S0** | 1 | Foundation | Repo, tooling, environments, project guide | Empty apps run end to end |
| **S1** | 2–3 | Foundation | Auth, multi-tenancy, roles, audit log, depots, multi-company login | Secure login on web + mobile |
| **S2** | 4–5 | Core Ops | Vehicles & ownership types, staff, crews, documents, Excel import | Fleet set up in the app |
| **S3** | 6–7 | Core Ops | Trips, odometer capture, pre-trip inspections | First inspected trip with photos |
| **S4** | 8–9 | Core Ops | Offline sync, fuel, floats, device integrity | Works with no network |
| **S5** | 10–11 | Core Ops | Expenses, spend limits, reconciliation, services & work orders, dashboard, owner-driver mode | 🚚 **Own fleet live on FleetTms** |
| **S6** | 12–13 | Core Ops | Tyres, spare parts store, incidents, fines, SOS | Workshop fully tracked |
| **S7** | 14–15 | Jobs & Money | Clients, quotes, jobs, dispatch calendar, saved routes | First quote → job |
| **S8** | 16–17 | Jobs & Money | Proof of delivery, billing methods, invoices, axle loads | First POD-backed invoice |
| **S9** | 18–19 | Jobs & Money | M-Pesa payments, debtors, reminders, eTIMS | Payments matched automatically |
| **S10** | 20–21 | Jobs & Money | **True cost & profit engine, leasing & asset finance**, suppliers, payroll | Profit after every deduction |
| **S11** | 22–23 | Tracking | Phone GPS, live map, client tracking links | Lorries visible on map |
| **S12** | 24–25 | Tracking | Trackers, replay, geofences, tamper alerts, idling & behaviour, immobiliser | Tracker data flowing |
| **S13** | 26–27 | Fraud | Fraud engine, alerts, scorecards, route suggestions, fuel prices | 🧪 **Private beta (3–5 owners)** |
| **S14** | 28–29 | Premium | Fuel sensors, predictions, learned anomaly models, document reading | Premium tier working |
| **S15** | 30–31 | SaaS | Subscriptions, onboarding, advanced reports, plain-English questions, messaging | Self-service sign-up |
| **S16** | 32–33 | Launch prep | Security, performance, disaster recovery, compliance sign-off | Launch-ready |
| **S17** | 34–35 | Launch | Store release, production go-live, partner programme, product analytics | 🚀 **Public launch** |

**Legal & compliance track** runs alongside the build (see "Other" stories) so the law is ready when the product is.

---

## 3. Sprints in Detail

---

### Sprint 0: Foundation Setup (Week 1)

**Goal:** a working skeleton. Web, mobile, and backend all run, talk to each other, and deploy to staging.

**Stories**
- [x] **Repo:** monorepo with apps (web, mobile, backend) and shared packages (business rules, types, design tokens, API client).
- [x] **Backend:** FastAPI app with health check, PostgreSQL (PostGIS and TimescaleDB enabled), migrations, Redis job queue, environment config. *Job queue: arq worker with a tested ping task.*
- [x] **Web:** React + TypeScript app with routing, layout shell (navigation from masterplan Section 6), light/dark theme. *Verified: renders "Connected to FleetTms API" in headless Chrome.*
- [x] **Mobile:** Expo app with navigation shell, app name "FleetTms", builds on Android. *Verified on the Android emulator (Pixel 6) through Expo Go.*
- [x] **Shared:** design tokens (red/amber/green with meaning), typography, spacing; shared API client.
- [x] **Tooling:** linting, formatting, test runners, CI running tests on every push. *ESLint, Prettier, tsc, ruff, vitest and pytest all pass locally. CI runs on every push (GitHub repo kevrith/FleetTms) with Redis and a PostGIS/TimescaleDB Postgres; green on main.*
- [ ] **Environments:** local (Docker for database and Redis), staging server, file storage bucket. *Local Docker done. Staging server and storage bucket not started.*
- [x] **Docs:** `PROJECT_GUIDE.md`, `/docs/masterplan.md`, `/docs/sprint-plan.md`, progress log.
- [ ] **Other:** start ODPC registration for Kastra Enterprises; book a data protection advocate; apply for M-Pesa Daraja production access, KRA eTIMS integration, Africa's Talking sender ID, and Google Maps billing. *Needs Kelvin; not started.*

**Acceptance criteria**
- [x] One command starts the whole stack locally. *(`pnpm dev` verified: Docker, migrations, API and web all came up.)*
- [x] Web and mobile both display data from the backend health endpoint. *Web home shows the health status. On Android the app now opens on the real sign-in screen and signs in against the API (the health text was replaced by real screens).*
- [ ] CI passes on a pull request; staging deploy works. *CI passes on push to main; PR run and staging deploy still to do.*

**Kickoff brief**
> Set up the FleetTms monorepo: React + TypeScript web, Expo mobile, FastAPI backend with PostgreSQL (PostGIS + TimescaleDB) and Redis, shared packages for business rules, types, design tokens, and API client. Add linting, tests, CI, local Docker, and the project guide per Section 1.1. Agree the folder structure before creating anything.

**Demo:** web and Android both show "Connected to FleetTms API."

---

### Sprint 1: Auth, Multi-Tenancy, Roles & Audit (Weeks 2–3)

**Goal:** secure accounts for multiple businesses, with roles enforced everywhere.

**Stories**
- **Backend:**
  - [x] Business (tenant) model; automatic tenant scoping on every query. *ORM-level filter on every SELECT/UPDATE/DELETE, fails closed without a tenant, blocks cross-tenant writes. Postgres row-level security as a second layer is a Sprint 16 item.*
  - [x] **Depots/branches** per business.
  - [x] Users and role assignments: Owner, Manager, Supervisor, Accountant, Driver, Turnboy, Workshop/Storekeeper, **Lessor** placeholder. Multiple roles per user; supervisor scope by assigned vehicles. *All roles and multi-role work. Supervisor `vehicle_scope` is enforced on vehicles, crew and documents since Sprint 2.*
  - [x] **One login, several companies**, with a company switcher.
  - [x] Driver login: phone + SMS one-time code (fake SMS sender in development).
  - [x] Owner/staff login: email or phone + password + two-step verification. *Authenticator app (TOTP) or SMS code, one or the other. SMS needs a phone number on the account; codes are single-use and tied to their purpose.*
  - [x] Sessions, logout all devices, instant access revocation.
  - [x] Permission system matching masterplan Section 3.
  - [x] **Audit log** service used by all later features. *Append-only: a database trigger rejects UPDATE and DELETE.*
  - [x] Platform Admin with no default tenant access; time-limited, logged support access.
- **Web:**
  - [x] Sign-up, login, 2-step setup, invite users, assign roles, users list, depots, company switcher. *Whole flow driven in a real browser. The company switcher is covered by API tests but was not clicked in the browser.*
- **Mobile:**
  - [x] OTP login, role-based home, **Owner/Driver view switch**. *Verified on the Android emulator.*
- **Privacy:**
  - [x] Driver monitoring notice with stored acknowledgement; Terms & Privacy acceptance stored with version.
- **Other:**
  - [x] Draft T&Cs, Privacy Policy, Data Processing Agreement for legal review. *Drafts are in `docs/legal/`. Still need the advocate's review and the blanks filled in.*

**Acceptance criteria**
- [x] Business A can never see or change Business B's data (automated tests prove it). *Tests were checked to fail when the tenant filter is switched off.*
- [x] Each role's access matches the masterplan table (automated tests per role).
- [x] A user in two companies switches between them without seeing mixed data. *API test.*
- [x] Every role change appears in the audit log.

**Kickoff brief**
> Implement multi-tenancy, depots, multi-company login, authentication (driver OTP; owner/staff password + two-step), all roles including Workshop and Lessor placeholders, permissions, and the audit log per masterplan Sections 3, 10, and 11.2. Tenant isolation must be automatic and covered by tests.

**Demo:** create two businesses, invite a driver, log in on Android with OTP, switch views and companies.

---

### Sprint 2: Vehicles, Ownership, Staff, Crews & Documents (Weeks 4–5)

**Goal:** an owner can set up the whole fleet and team, including how each lorry is owned.

**Stories**
- [x] **Vehicles:** registration, make/model, capacity, fuel type, tank size, expected consumption (loaded and empty), odometer, tracking tier, depot, **legal load limit and axle configuration**. *Supervisors see only their assigned vehicles (closes the Sprint 1 carry-over).*
- [x] **Ownership type:** Owned, Asset-financed, Leased-in, Leased-out, with the basic lessor/lender/lessee record (full lease engine in S10). *The party kind must match the ownership type.*
- [x] **Staff:** profiles, licence details, crew assignments with history. *Salary is visible and editable only with payroll access (Owner).*
- [x] **Documents:** insurance, inspection, NTSA/TLB licences, permits, driving licences, with expiry reminders (30/14/7 days) by SMS to owners, managers and the staff member. *Records and expiry dates only: attaching a scanned copy needs the storage bucket (Sprint 0 carry-over). SMS goes through the fake sender until Africa's Talking arrives.*
- [~] **Excel import:** vehicles and staff, with validation and an error report (all or nothing, row numbers, dry-run, downloadable templates). *Clients, suppliers and opening balances are not built: their tables do not exist yet (clients Sprint 7, suppliers and balances later). Add them to the importer when those tables arrive.*
- [x] **Web:** vehicles list and detail (edit, crew, documents), lessors and lenders, staff page, import page, "documents needing attention" on Home. **Mobile:** owner vehicle list, driver "My vehicle" card. *Web driven end to end in headless Chrome (sign-up, SMS two-step, depot, lessor, leased-in vehicle, driver invite, crew, document, expiry card, bad and good Excel imports, fresh SMS sign-in). Mobile verified on the Android emulator (Pixel 6): driver sign-in with SMS code, My vehicle card with crew, owner sign-in, two-step chooser (text option disabled without a phone), owner vehicle list.*
- [x] **Seed data:** `python -m app.cli seed-demo` builds a Kenyan demo fleet with leased-in, asset-financed and leased-out lorries.

**Acceptance criteria**
- [x] Owner adds a lorry, sets it as leased-in from a named lessor, and assigns a driver and turnboy. *API tests.*
- [x] Reassigning crew keeps history. *API tests.*
- [x] An Excel file with 20 vehicles imports cleanly; a bad row is reported, not silently skipped. *API tests.*
- [x] Expiry reminders fire on schedule (test with fake dates).

**Kickoff brief**
> Implement vehicles (with ownership type, load limits, depot), staff, crew assignments, documents with reminders, and Excel import per masterplan Sections 5.1, 5.11, 5.23 (setup only), and 5.29. Add realistic Kenyan seed data, including one leased-in and one asset-financed lorry.

**Demo:** full fleet set up from an Excel import; an insurance expiry SMS arrives.

---

### Sprint 3: Trips, Odometer Capture & Pre-Trip Inspection (Weeks 6–7)

**Goal:** drivers inspect the lorry, then start and end trips with trustworthy odometer photos.

**Stories**
- [x] **Pre-trip inspection:** configurable checklist (tyres, brakes, lights, oil, coolant, leaks, body, tyre serials; each business can reword, add, retire, and mark items critical), photos for faults, critical defects **block the trip** unless a manager overrides with a reason. *Minor faults are saved as open defects, ready to become work orders in Sprint 5.*
- [x] **Trips:** status flow (scheduled, in progress, delivered, completed; cancel before start), loading step with cargo photo and optional loaded weight. *A manager schedules the trip for the vehicle's crew; jobs and dispatch arrive in Sprint 7.*
- [~] **Odometer readings:** live camera only, guided frame, quality checks (size, blank or covered lens, freshness), time and GPS stamp, driver confirmation, flags for mismatched or backward readings (also `large_jump` and `no_location`). *Not built: automatic reading of the number from the photo. It needs an on-device text-recognition module, which Expo Go cannot run; it needs a development build. The reading is typed and confirmed by the driver today. The `mismatch` flag is ready for when the reader exists.*
- [x] **Photos:** private storage with short-lived (5 minute) signed viewing links; duplicate photos refused. *Local-disk storage for now. The S3-compatible bucket (a Sprint 0 carry-over) slots in behind the same functions.*
- [x] **Web:** trips list and detail with inspection result, odometer photos, flags and distance; manager override; inspection checklist editor; web capture with EXIF freshness check.
- [x] **Shared:** distance and odometer validation rules (`packages/business-rules`, enforced again by the API).

**Acceptance criteria**
- [x] A trip cannot start without a passed inspection and an odometer photo. *API tests; also seen on the emulator (no Start button until inspected).*
- [x] Gallery uploads are impossible on mobile. *There is no gallery picker anywhere in the app; the only photo path is the live camera. The server also refuses photos that are stale, blank, repeated or too small.*
- [x] A failed brake check blocks the trip; a manager override is audit-logged. *API tests, web, and the emulator.*

**Kickoff brief**
> Implement pre-trip inspections and trips with odometer capture per masterplan Sections 5.2, 5.4, and 5.19 (inspection part). Live camera only on mobile, number reading with confirmation, time + GPS stamps, private photo storage. Defects are stored ready to become work orders in Sprint 5.

**Demo:** inspect a lorry, start a trip by photographing the odometer, end it, and view it on the web.

---

### Sprint 4: Offline Sync, Fuel, Floats & Device Integrity (Weeks 8–9)

**Goal:** the driver app works with no network, phones can't be easily faked, and fuel and floats are recorded.

**Stories**
- [x] **Offline-first:** encrypted local storage (XChaCha20-Poly1305; the key lives in the phone's secure keystore), queued actions (inspections, trip start/loading/delivery/end, photos, fuel), automatic sync (when the network returns, when the app opens, every minute), sync status badge, original capture time kept, conflict rules, clear on logout. *Conflicts: the server's rules decide. A record it cannot accept stays on the phone with the reason and a Try again or Delete choice. Signing out wipes the vault after warning about anything unsent; an expired session keeps the vault until a different person signs in. Expenses join the queue in Sprint 5.*
- [x] **Backend:** idempotent batched sync (`POST /sync`, up to 50 actions, each applied in its own savepoint; an action id already applied is answered as a duplicate). Photos carry a phone-chosen id so a retried upload stores once. *Records use the time the driver did them (up to 7 days old); a photo must have been taken within 15 minutes of the record it backs.*
- [x] **Device integrity:** the app reports a mock-location sighting, a rooted phone, and its clock; the server compares the clock itself. Flags are recorded and lower the vehicle's trust level (High, Medium, Low, starting from the tracking tier). They never block anyone. *The mock-location check reads Android's `mocked` flag on locations; it has not been tried against a real fake-GPS app.*
- [x] **Fuel:** entries with litres, price, amount, station, M-Pesa code, receipt photo. *The receipt is optional but flagged when missing; a total that does not match litres times price is flagged; a repeated M-Pesa code is refused.*
- [x] **Floats:** owner or manager records M-Pesa floats; the driver sees the balance (offline too). *Recording only: expenses are subtracted from Sprint 5.*
- [x] **Web:** Expenses area (floats, fuel), trust column and trust card on vehicles. **Mobile:** sync badge and "could not be sent" list, Expenses tab (float balance, fuel entry), everything working from the phone's saved data.

**Acceptance criteria**
- [x] In airplane mode a driver completes inspection, trip, and fuel; everything syncs correctly later. *Android emulator, 2 Oct 2026: with airplane mode on, the driver did the inspection, started the trip, photographed the cargo, marked it delivered, ended the trip and entered fuel. Six items waited on the phone (and survived an emulator restart). On reconnect they synced in order with the times they were done: trip completed, 480 km, inspection passed, fuel stored. Caveat: the emulator cannot take a usable still photo (every mode gives black), so the server's blank-photo rule refused the photos until it was switched off for the test run; that rule has its own API tests. Real phone cameras are untested.*
- [x] The same batch sent twice creates no duplicates. *API tests, including a split batch and a lost reply on the phone side.*
- [x] A phone running a fake-GPS app is flagged. *Android emulator, 2 Oct 2026: a mock location was fed to the phone through Android's test-location provider (the same mechanism fake-GPS apps use); the app read it as mocked, the server recorded a `mock_location` flag against the vehicle, and its trust level drops to low by the rule. Not tried with a named fake-GPS app from the Play Store.*

**Kickoff brief**
> Make the mobile app offline-first per masterplan Sections 4 and 13, add device integrity checks (Section 10), fuel entries (5.5), and floats (5.6, recording only). Offline records keep their original capture time, are stored encrypted, and sync idempotently.

**Demo:** full working morning in airplane mode → network on → data appears on the web.

---

### Sprint 5: Expenses, Reconciliation, Services & Dashboard (Weeks 10–11)

**Goal:** daily operations run in FleetTms. 🚚 **Milestone: your own lorries go live.**

**Stories**
- [x] **Expenses:** categories (trip, other, overhead), receipt photos, M-Pesa code, links to vehicle, trip and float, approval status. *Drivers record trip expenses; managers and accountants record the rest. A driver's vehicle and trip in progress are filled in for them.*
- [x] **Spend limits** per category and role (most specific rule wins; the owner sets them), and **duplicate receipt / M-Pesa code detection**. *An over-limit expense waits for the owner and does not count until approved. The same M-Pesa code cannot back an expense or a fuel entry twice; the same receipt photo cannot be used twice.*
- [x] **Expected costs per route** flag unusual claims (flagged, never blocked).
- [x] **Daily reconciliation:** opening + floats - expenses = closing, by driver and Nairobi day. Approved by a supervisor (their own vehicles), manager or owner; the balance is carried forward or the cash is returned. *A day cannot be approved while an expense waits for the owner.*
- [x] **Service schedules** by km and/or time (whichever comes first), advance reminders by SMS (once per due service), service history and cost.
- [x] **Work orders:** every inspection defect becomes one automatically; service reminders raise one too. Mechanic or garage, parts, labour, status. Completing one records its cost as a repair or service expense on the vehicle and restarts the service schedule.
- [~] **Owner dashboard v1** (web and mobile) and basic daily/weekly/monthly/custom reports. *Today's numbers and "needs attention" alerts, red before amber. Income, profit and money owed show "not yet" until billing exists. Reports: totals, expenses by type, by vehicle (km per litre), by day. Excel and PDF export of any report range (web). Scheduled reports: daily, weekly or monthly, sent as a PDF by email (SMTP) or WhatsApp (Cloud API), managed on the web Reports page, once per finished period at 06:30 Nairobi time, with a Send now test and the last error shown. Built and tested against stand-in senders; not yet tried against a real mail server or WhatsApp account, which needs the keys in `.env` (and an approved message template to message people first on WhatsApp). The owner's mobile dashboard type-checks but has not been run on a device.*
- [x] **Owner-driver mode** alert rules: an owner who also drives is never asked to approve their own spending or their own day.
- [x] **Driver app:** Add Expense in two taps plus the amount (category, then Save); float balance in very large text; end-of-day report; everything works offline through the sync queue.
- [x] **Quick sign-in on the phone** (requested alongside this sprint): the first sign-in on a phone always needs an SMS code. After that a driver can turn on a 6-digit PIN in More. Five wrong PINs switch it off; "sign out of all devices" and turning it off end it.

**Acceptance criteria**
- [x] A driver logs expenses; a supervisor approves the evening reconciliation. *API tests; web approval driven in Chrome; the driver side on the Android emulator.*
- [x] An expense over the limit waits for owner approval; a reused receipt is rejected. *API tests and the web.*
- [x] An inspection defect becomes a work order automatically. *API tests and the web.*
- [ ] **Kelvin runs his own fleet on FleetTms for a full week.** *Not something I can do. This is the milestone: use it daily and log every problem.*

**Kickoff brief**
> Implement expenses with spend limits and duplicate detection (5.7), reconciliation (5.6), service schedules (5.8), work orders (5.19), owner-driver alert rules (Section 3), and dashboard v1 with basic reports (5.15, Section 6).

**Demo:** a full working day from inspection to evening reconciliation.

**After this sprint:** use FleetTms daily on your own lorries and log every problem.

---

### Sprint 6: Tyres, Parts Store, Incidents & SOS (Weeks 12–13)

**Goal:** the workshop and on-road problems are fully tracked.

**Stories**
- [x] **Tyres:** serials, positions, fitting/removal, km, tread readings, retreads, rotations; serial checks during inspections with **tyre swap** flags. *Serial numbers are unique per business (case, spaces and dashes ignored). One tyre per position. Kilometres run follow the vehicle's odometer and carry over across fittings. A tyre's cost lands on the vehicle once, when first fitted; a retread's cost goes to the vehicle it last ran on. Tyres are flagged for rotation (15,000 km since fitted or moved) and replacement (100,000 km or tread at 3 mm). The driver's phone shows the recorded positions but not their serials, so the driver has to read them off the tyres; a serial that differs raises an alert (mismatch, unknown, or a tyre recorded elsewhere), shown on the owner's dashboard in red. Cost per km by brand and supplier on the web.*
- [x] **Spare parts store:** stock, reorder levels, parts issued to work orders, stock counts, issued-vs-fitted checks. *Receiving averages the unit cost. Issuing takes stock down (locked, so the last filter cannot be issued twice) and charges the vehicle at once; completing the work order books only labour and parts bought outside the store, so nothing is charged twice. Returns restock and reverse the charge. Parts issued but not marked as fitted are listed, and flagged when the work is finished. Low stock shows as an alert. Not built: turning low stock into a supplier order, because the supplier directory (masterplan 5.9) does not exist yet.*
- [x] **Incidents:** breakdown, accident, police stop, traffic fine, county cess, cargo theft, with photos and location; insurance claims; fines per driver with optional payroll deduction. *Drivers report from the phone (works offline, keeps the time it happened); a breakdown raises an urgent work order. Managers add fines and say who pays: a fine the business pays is a vehicle cost, one the driver pays is flagged for deduction from pay (payroll itself arrives in a later sprint). Claims move through filed, documents requested, assessed, approved, paid or rejected. Not built: the web has no screen for adding claim documents (the API accepts them), and a breakdown does not yet update a job's expected delivery time because jobs arrive in Sprint 7.*
- [x] **SOS button:** instant alert with live location to owner and supervisors. *The owner, managers and the supervisors who cover the vehicle are texted with a map link; the alert shows in red at the top of the owner's dashboard (phone and web, refreshed every 10 to 15 seconds) and as a banner on every web page. An SOS pressed with no signal waits on the phone and goes first, ahead of photos and other records, when there is signal. A second press within 30 minutes moves the pin instead of texting everyone again. While the alert is open the phone sends its position every 15 seconds. The driver sees whether anyone has answered. SMS is still the in-memory sender until a real gateway is connected, and there are no push notifications yet.*
- [~] **Workshop role** screens on web and mobile. *Web: work orders (issue parts from the store, mark fitted, return), tyres, parts store, service due. Mobile: work orders with issue, fitted and return, and the parts list, for the workshop role; the work-order screens are also on owner and manager phones. The workshop screens on the phone type-check but have not been run on a device or emulator.*

**Acceptance criteria**
- [x] Swapping a tyre serial between inspections raises an alert. *API tests; also on the Android emulator, where a wrong serial typed into the inspection raised an open alert.*
- [x] Issuing a filter to a work order reduces stock and adds its cost to the vehicle. *API tests, including that completing the work order does not charge it again.*
- [x] SOS reaches the owner within seconds (or as soon as the phone has network). *Emulator: the alert was stored about one second after pressing, with the location, and the manager was texted. Offline behaviour is covered by engine tests (an SOS waits, then goes first when there is signal); it was not run with airplane mode on the emulator.*

**Kickoff brief**
> Implement tyre management (5.20), spare parts store (5.24), incidents, fines, insurance claims and SOS (5.21), and Workshop role screens. Tyre and parts costs must flow into each vehicle's cost.

**Demo:** report a breakdown, raise a work order, issue parts, and replace a tyre.

---

### Sprint 7: Clients, Quotes, Jobs & Dispatch (Weeks 14–15)

**Goal:** work flows from quote to dispatched job.

**Stories**
- [x] **Clients:** contacts, KRA PIN, default billing method and rates. *KRA PIN format is checked (a letter, nine digits, a letter). Billing is per trip, per tonne, per km or a monthly contract, with a default rate and payment terms per client. Owners, managers and accountants manage clients.*
- [x] **Saved routes:** pickup, drop-off, path, distance, expected costs, notes. *Stored once per client with distance, usual duration, tolls, crew and other costs per trip, and the preferred path. Quotes and jobs start from them.*
- [x] **Quotes:** price from billing method, distance, expected fuel, tolls, and crew costs; show expected profit; send by WhatsApp/SMS/email. *The calculation is in `packages/business-rules/src/quotes.ts` and mirrored in `apps/api/app/quote_rules.py`; both are tested against the same file of cases, so the web preview and a saved quote cannot disagree. Fuel uses the lorry's loaded and empty km per litre, the return leg, and the pump price (the average of the latest fuel entries, or typed in). A loss shows as a negative profit. Email and WhatsApp send a PDF with only the price (never our costs or profit); SMS sends a short text. Quotes expire (14 days by default) and cannot be accepted after that. Sending is tried against stand-in senders only; real email and WhatsApp need the keys from Sprint 5's scheduled reports, and SMS is still the in-memory sender.*
- [~] **Jobs:** from accepted quotes or recurring contracts; cargo, windows, instructions; multi-trip jobs. *Accepting a quote makes a job (one job per quote); jobs can also be set up directly. A job can need several trips and follows them: planned, dispatched, on the road, completed. "Do this job again" copies the client, cargo, billing and saved route with new dates. Not built: recurring contracts that create their own jobs on a schedule; repeating is done by hand for now.*
- [x] **Dispatch calendar:** lorry and crew availability (booked, in service, free); assign jobs, driver notified. *Dispatching a trip checks the lorry and the crew: a lorry with work in progress or waiting for parts is "in service" and cannot be booked, and a lorry or crew member already booked for an overlapping time is refused, whether dispatched from a job or scheduled by hand. The calendar shows each lorry and crew member day by day. The driver is texted and sees the job (client, cargo, instructions) on their phone.*

**Acceptance criteria**
- [x] A quote shows expected profit, is accepted, becomes a job, and is dispatched to a driver. *API tests, and on the Android emulator: a quote with its expected profit was accepted, dispatched to Peter's lorry through the real API, and the job showed on his phone.*
- [x] A lorry in the workshop can't be double-booked. *API tests: a lorry with work in progress cannot be dispatched or scheduled by hand, and a booked lorry or crew member is refused; also checked against the dev API.*
- [x] A repeat job reuses the client's saved route. *API tests.*

**Kickoff brief**
> Implement clients, saved routes, quotes, jobs, and the dispatch calendar per masterplan Sections 5.10 (clients and routes) and 5.17. Quote calculations live in the shared package with tests.

**Demo:** quote → accept → job → dispatched trip on the driver's phone.

---

### Sprint 8: Proof of Delivery, Billing & Invoices (Weeks 16–17)

**Goal:** every delivery is proven and invoiced correctly.

**Stories**
- [x] **Proof of delivery:** cargo and delivery note photos, recipient name, signature or one-time code to the client's phone, GPS and time stamps, shortages/damage; delivery outside the client's site is flagged. *A trip for a client job cannot be delivered without it. The recipient confirms by drawing a signature on the phone, or by a 6-digit code texted to the client (30 minutes, one text a minute, five wrong guesses and the code is locked; the guess count is kept even though the failed request rolls back). Both photos are required; damage needs a photo. Flags (never blocking): outside the client's site (a saved route can hold the site's position and radius), no GPS, shortage, damage. Works offline: only the code needs a network, to be texted, so with no signal the driver signs.*
- [x] **Axle/load checks:** loaded weight from weighbridge ticket vs legal limit, flagged before the trip starts. *Cargo can now be loaded and weighed before the lorry leaves. The ticket photo and net weight are recorded; the overload is worked out from the vehicle's legal gross limit and empty weight (or its payload capacity if the empty weight is not known), shown on the driver's phone at once, in red on the owner's dashboard, and on the trip. It is flagged, not blocked. Not built: per-axle weights (the ticket gives only the total).*
- [x] **Billing methods:** per trip, per tonne, monthly contract, per km; default per client, overridable per job. *Calculations are in `packages/business-rules/src/billing.ts` and `apps/api/app/billing_rules.py`, tested against the same cases (`billing-cases.json`, `load-cases.json`). Money is in cents; per-client VAT percentage (default 0, set it with your accountant).*
- [x] **Invoices:** automatic on POD or monthly for contracts; numbering; PDF with POD attached; partial payments (manual for now). *A per-trip, per-tonne or per-km trip is invoiced the moment its proof of delivery is confirmed. A per-tonne trip is billed from the weighbridge weight; if there is no ticket it is not invoiced, the dashboard says so, and the office can invoice it by entering the weight from the paper ticket (recorded). Contract jobs get one invoice a month (run on the 1st for the month before, or by hand) that lists every trip it covered. Numbers INV-0001 onward per business. The PDF carries the proof of delivery as its second page: recipient, time, location, the delivery note and cargo photos, the signature, weighbridge ticket, shortages and damage. Payments are entered by hand (cash, M-Pesa, bank, cheque), cannot exceed what is owed, and an invoice with payments cannot be voided. Invoices can be sent by email or WhatsApp (PDF) or SMS through the stand-in senders. Owners and accountants manage invoices; managers can see a trip's proof but not its money.*

**Acceptance criteria**
- [x] Confirming POD generates a correct invoice with the POD attached. *API tests, and on the Android emulator: a signed proof of delivery synced, and invoice INV-0001 was issued for KES 27,000.00 (9,000 kg at KES 3,000 per tonne). The PDF with its second page is checked by API tests.*
- [x] A per-tonne job bills from the weighbridge weight; an overload is flagged before departure. *API tests (the ticket said 28.4 t and the invoice billed 28.4 t); on the emulator a 12,000 kg load on a lorry limited to 10,000 kg of cargo showed "OVERLOADED by 2,000 kg" before the trip started.*
- [x] A contract invoice shows the trips it covered. *API tests.*

**Also done this sprint (requested during it): odometer fraud rules.** *A trip's start reading is now filled in from the vehicle's last reading (the previous trip's end reading), on the phone and the web, and the phone keeps that reading up to date offline. A reading lower than the vehicle's last one is refused by the server (before the photo is used up) and the phone and web will not submit it; it used to be only flagged. Higher readings are still accepted (a large jump is flagged). If an odometer is genuinely replaced, a manager corrects the vehicle's reading first, which is audit-logged.*

**Kickoff brief**
> Implement proof of delivery (5.18), load and axle checks (5.22), billing methods and invoices (5.10, except M-Pesa, eTIMS, reminders). Billing calculations in the shared package with thorough tests; money in cents.

**Demo:** deliver with a recipient code and watch the invoice appear.

---

### Sprint 9: Payments, Debtors, Reminders & eTIMS (Weeks 18–19)

**Goal:** know who owes you, and get paid faster.

**Stories**
- [x] **M-Pesa Daraja:** client payments matched to invoices; unmatched payments go to a manual queue. *Safaricom calls a secret address per business; a payment that names an invoice number (INV-0001, typed loosely) is put against it, up to what is owed. Anything else (no account number, an unknown or voided or paid invoice, an overpayment's remainder) waits in a queue, where the office matches it (or splits it across invoices), or sets it aside with a reason. The same M-Pesa code twice counts once; a payment already entered by hand is not counted again; the same code cannot be entered by hand twice. The owner sets the Paybill or Till number and registers the addresses from Settings. Invoices and reminders tell the client the Paybill and account number. Built against Daraja's C2B interface; not yet run against the real Safaricom sandbox (needs your consumer key and a public address), so a development stand-in and a "send test payment" button are used.*
- [x] **M-Pesa statement import** for fuel, float, and lease payments. *Upload the business's statement (CSV or Excel). Money that left is matched to fuel, expenses and floats by M-Pesa code; a claim for a different amount, or a claim in the statement's period whose code is not on the statement, is flagged on the claim and on the dashboard. Money that came in is matched to client payments, and recovers one whose notice was missed. Safe to upload again. Not built: PDF statements. Lease payments, loan repayments and salary advances are matched too since Sprint 10.*
- [x] **Debtors view** with ageing; **payment reminders** by SMS and email. *Ageing counts from the due date (not yet due, 1 to 30, 31 to 60, 61 to 90, over 90 days late), per client and in total, with each client's open invoices, payments and reminders. Reminders are off until the owner turns them on; by default 3 days before the due date then 1, 7, 14 and 30 days after; each step goes once per channel, only the latest step after a gap, three tries on a failing channel; off per client; "Remind now" by hand. The email carries the invoice PDF. Not built: WhatsApp reminders (invoices can still be sent by WhatsApp by hand).*
- [x] **KRA eTIMS** invoice submission with status and retries. *Every invoice is queued when it is issued, sent every five minutes, and retried with growing gaps (5 minutes up to a day, 9 tries) when KRA cannot be reached. A refusal from KRA, a VAT rate with no eTIMS code, or running out of tries puts it in a review queue where a person fixes and resends it, or marks it handled by hand. A voided invoice that KRA already has is cancelled with a credit note. The PDF carries the KRA receipt number and QR code. Written to KRA's OSCU documentation; not yet run against KRA's sandbox (needs the business's registered device), so field names, tax codes and item codes must be checked there first. Item registration, the tax code for invoices with no VAT, and the device key (fetched when needed, never stored) are the first things to confirm.*
- [x] **Profit vs cash** on the dashboard. *This month: invoiced (before VAT), costs recorded (fuel and expenses), profit on paper, paid to you, cash after costs, and money owed. Costs exclude salaries, lease and overheads until the true-cost engine (Sprint 10).*

**Acceptance criteria**
- [ ] A sandbox payment marks the right invoice paid. *Done with simulated Safaricom notices (API tests post the C2B payload to the callback address, and the stand-in "send test payment" does the same path); not run against Safaricom's sandbox.*
- [x] Ageing is correct on test data. *Shared cases tested in Python and TypeScript, and API tests with invoices at every age.*
- [ ] An eTIMS sandbox submission shows its status. *Status, retries, review queue and credit notes work against the stand-in; not run against KRA's sandbox.*

**Kickoff brief**
> Integrate M-Pesa Daraja payments with invoice matching, statement import, debtors with ageing, reminders, and eTIMS per masterplan Section 5.10. Sandbox first, credentials in environment variables, retries and a manual-review queue for failures.

**Demo:** pay an invoice from the sandbox and watch the debtors view update.

---

### Sprint 10: True Cost, Profit Engine & Leasing (Weeks 20–21)

**Goal:** true profit per lorry after **every** deduction, including what is paid to a lorry's owner.

**Stories**
- [x] **Lease agreements (leased-in and leased-out):** lessor details, dates, deposit, notice period; payment models (per month/week/day, per trip, per km, % of revenue, % of profit, minimum guarantee with revenue share); **cost responsibility matrix**. *One running lease per lorry, checked against the vehicle's ownership type and its lessor or lessee. The parts of a charge add up (fixed amount, per trip, per km, share of revenue, share of profit); a minimum a month is a floor under the total. Part months are pro-rated. The matrix covers fuel, routine service, major repairs, tyres, insurance, licences, crew pay, tracker and fines, with the usual split as the default. Terms changes are audit-logged with before and after.*
- [x] **Lease engine (shared package):** automatic charges from the agreement and actual trips; **offsets** for lessor costs paid by the lessee; lease ledger with balance owed; due-date reminders and overdue alerts. *Rules are in `packages/business-rules/src/lease.ts` and `apps/api/app/lease_rules.py`, tested against `lease-cases.json`, `finance-cases.json` and `profit-cases.json`. A month is worked out from the lorry's real trips, kilometres, revenue and gross profit (`POST /leases/{id}/run`, and on the 1st by the worker); an expense the operator paid that the matrix makes the owner's becomes one offset against the charge, backed by the expense and its receipt, never counted twice. Payments, offsets, and corrections (with a reason) make up the ledger. The dashboard shows overdue and due-soon lease payments; the owner and accountant are texted once per month's charge, and a late lessee is texted too. Not built: the lessee's usage for a leased-out lease comes from figures the office types in (trips happen on their side).*
- [x] **Lessor payments:** record M-Pesa payments (or pay via M-Pesa where integrated); statement import matching. *Payments are recorded by hand with their M-Pesa code (one code is claimed once across fuel, expenses, lease, loan and advance payments); the M-Pesa statement import matches them by code and flags a different amount. Not built: sending money through M-Pesa from FleetTms (B2C).*
- [x] **Lessor statements** (PDF) and the **Lessor portal** (view-only, own vehicles, location only if the agreement allows). *Statement per month with the basis of the charge, offsets, payments, balance brought forward and carried; PDF; sent by WhatsApp or email. A lessor is invited as a lessor tied to one lessor party, signs in and sees only that party's leased-in leases: account, statement, PDF, the lorry's service and inspection history. Trips only if the agreement allows; revenue and profit only for the parts the charge depends on. Another lessor's lease answers "not found". Location is not shown: the live map arrives in Sprint 11, and the agreement already holds the permission.*
- [x] **Leased-out:** lease income and the lessee's balance. *Same account, other direction: charges are income, payments are received, and the lorry's profit row counts the lease income as its revenue.*
- [x] **Asset finance:** repayment schedules, balances, overdue alerts. *Reducing-balance schedule from the amount, rate and months (or the lender's own repayment); repayments ticked off in full or in part with an M-Pesa code; loan balance, overdue amount, next due date; dashboard alerts; closes when paid off.*
- [x] **Ownership costs:** insurance, licences, depreciation spread monthly. *Yearly premiums spread over twelve months, depreciation straight-line over a life, part months pro-rated. An insurance or licence expense for a lorry that has the same cost set up is not counted twice.*
- [x] **Profit engine:** gross profit, **net profit after lease and finance**, cost per km, revenue per km, loaded vs empty km; per trip, vehicle, client, driver, depot, business; flag leases that aren't paying off. *`GET /profit` in whole months (up to 24). Vehicle rows carry revenue, fuel, expenses, crew pay, gross, owner's share, loan, fixed costs, net, cost and revenue per km, loaded and empty km. Client and driver rows are the trips' own contribution (revenue less the fuel and expenses booked to the trip). A contract trip with no invoice yet takes an estimated share of the month's fee; a delivered trip with no invoice is counted as unbilled. A lease where the owner earned more than the operator for three months in a row is flagged on the report and the dashboard. The dashboard answers "how much did the leased lorry make me last month after paying its owner". Loaded and empty km are estimates from trips (a trip with a job or a load is loaded) and gaps between trips until GPS arrives.*
- [x] **Suppliers & WhatsApp parts ordering**; **payroll** with advances and fine deductions, allocated to vehicles. *Suppliers and numbered orders (PO-0001); sent by a WhatsApp link that opens the chat with the order written (the free first phase); sent, confirmed, collected, paid or cancelled; collecting an order puts the parts into the store at a weighted cost; drafts can be made from what is running low, grouped by the supplier named on each part. Payroll: monthly runs from the salaries on staff records, advances taken back in full and fines taken from the driver's pay (never more than the salary, the rest waits), approved runs lock, and each salary's cost is spread over the vehicles crewed by days and counts towards each lorry's profit (an estimate from the salary on file is used until a run is approved). Not built: statutory deductions and payslips (a later phase in the masterplan); importing suppliers from Excel; paying staff or suppliers through M-Pesa.*

**Acceptance criteria**
- [x] The masterplan's worked example (Section 5.23) produces exactly: gross profit KES 260,000, lease payable KES 160,000, net profit KES 100,000. *API test seeds the example (three trips for 600,000, fuel 230,000, tolls 40,000, service 15,000, crew pay 55,000 from two salaries spread by days, a 20,000 engine repair the operator paid) and checks all three figures, and the same after the month is worked out into the ledger. See the note below about what the example does with the repair.*
- [x] A minimum-guarantee lease charges the guarantee in a slow month and the revenue share in a busy one. *Shared cases, and an API test with a slow and a busy month.*
- [x] A lessor logs in and sees only their lorry's statement. *API tests: own lease, statement and PDF yes; another lessor's lease, statement and PDF answer not found; every other part of the business is refused.*
- [x] Profit per lorry matches a hand-calculated spreadsheet. *API test with a worked sheet in its comment (revenue 450,000, fuel 120,000, tolls 18,000, crew 40,000, lease 90,000, insurance 3,000 a month, net 179,000).*

**Note on the worked example.** The masterplan's net of KES 100,000 treats the 20,000 engine repair as both outside the operator's costs and as a recovery against the lease. If the operator really paid 20,000 to the garage and then paid the lessor 160,000, the operator's cash profit is 80,000 (600,000 less 340,000 of running costs less 180,000 of lease charge). FleetTms follows the masterplan's figures, as the acceptance criterion asks, and shows what was paid on the owner's behalf on its own line, so the 20,000 is visible. Decide whether the net should deduct it.

**Kickoff brief**
> Implement leasing and asset finance per masterplan Section 5.23 (all payment models, cost responsibility matrix, offsets, ledger, payments, statements, Lessor portal), ownership costs, the profit engine with net profit after lease and finance (5.15), suppliers and WhatsApp ordering (5.9), and payroll (5.11). Write tests from hand-calculated examples, starting with the worked example in 5.23.

**Demo:** "How much did the leased lorry actually make me last month, after paying its owner?" answered on the dashboard, with the lessor statement ready to send.

---

### Sprint 11: Phone GPS, Live Map & Client Tracking Links (Weeks 22–23)

**Goal:** see where every lorry is, and let clients see their delivery.

**Stories**
- [x] **Mobile:** background tracking **only during active trips**, battery-friendly, offline buffering, visible indicator, stops at trip end. *A background task follows the trip's state on the phone (started by the driver or by the office): it starts with the trip, shows a notification while it runs and a green "Location is on" panel on the trip screen (red with the reason if location permission is refused), and stops when the trip ends. Fixes wait in an encrypted file until there is a network and are sent in batches of 500. High-accuracy GPS, one fix every 20 seconds or 40 metres; fixes vaguer than 100 m are dropped on the phone. Nothing is kept with no trip running, and a fix taken after the trip's end is thrown away on the phone and refused by the server. A development build is needed: Expo Go on Android cannot run background location.*
- [x] **Backend:** time-series location storage, GPS trip distance, "going dark" detection, 12-month retention job. *`location_points` is a TimescaleDB hypertable (one row per vehicle and moment, so a resend changes nothing). Only the trip's own crew may send, only between the trip's start and end. At trip end (and when late offline fixes arrive) the GPS distance is worked out (poor fixes dropped, signal jumps and standing-still jitter ignored) and compared with the odometer: more than 15 percent and 10 km apart is flagged "mismatch" on the trip and the dashboard. A watcher every 5 minutes opens a "gap" when a trip's phone has been quiet for 15 minutes (or never reported), texts the owner and managers once, shows it on the dashboard and map, and closes it when a fix arrives. A daily job deletes points older than 12 months after making sure each trip's distance totals are stored.*
- [x] **Live map** on web and mobile. *Web: a map of every vehicle in the caller's scope (supervisors only theirs), coloured moving, standing on a trip, not reporting, parked or never seen, refreshing every 15 seconds, with the trip's path when a vehicle is chosen, and a "Where it went" map with the GPS and odometer distances on each trip. Mobile (owners, managers, supervisors): a list of the same states; tapping a lorry opens its position in the phone's maps app. A full map on the phone is not built. Map tiles come from OpenStreetMap (disclose as a sub-processor).*
- [x] **Client tracking link:** secure, expiring, delivery progress and expected arrival only. *The office makes a link for a trip that has not been delivered (optionally texted to the client). The secret is shown once and only a hash is kept; it lives 7 days at most and can be switched off. The client's page shows the business, route, cargo, status, the lorry's position on a map, progress and expected arrival (from the distance left to the client's site and the speed the lorry has been making), and nothing else: no driver, no vehicle, no money, no other trips. After delivery the link answers "delivered" and shows no position. Unknown links answer "not found".*
- [x] **Privacy:** monitoring notice updated; no tracking outside work time. *Notice is now draft-2 (what is recorded, when, who sees it, 12-month retention, the notification), so every driver must accept it again at next sign-in. The server enforces the working-time rule, the phone follows it, and a driver can check `GET /me/tracking`. Still to do: the data protection impact assessment and legal review of the notice.*

**Acceptance criteria**
- [x] Location records with the phone locked during a trip and provably stops at trip end. *On the Android emulator with a development build: a trip in progress, the screen locked, GPS fixes injected; fixes taken before and after locking reached the server. The trip was then ended: the tracking service stopped, and four more injected fixes were not stored. Server-side, API tests show fixes after the end are refused and before the start are refused. Not tried on a real phone or in a moving vehicle (the emulator's GPS is injected).*
- [x] A client link shows progress and stops working after delivery. *API tests (progress, expected arrival, exact set of fields, delivered, revoked, expired, unknown).*

**Kickoff brief**
> Implement phone GPS tracking (5.3, 11.2), live map, going-dark detection, GPS retention (11.3), and client tracking links (5.26). Optimise for battery and low-end Android phones.

**Demo:** simulate a trip and watch it live; open the client link on another phone.

---

### Sprint 12: Trackers, Tamper Alerts, Behaviour & Immobiliser (Weeks 24–25)

**Goal:** tamper-resistant tracking and driving insight (Standard tier).

**Stories**
- [x] **Tracker ingestion** via Traccar; devices linked to vehicles; device status. *Traccar forwards each position and event as JSON to `POST /hooks/traccar/{key}` (the key is `TRACCAR_FORWARD_KEY`; empty switches the address off). A tracker is fitted to a vehicle by its IMEI (one IMEI belongs to one tracker across the whole platform) and moves the vehicle up to the standard tier. Each device shows online or offline, power, battery, ignition, GPS lock and when it was last heard. Positions are stored in the same hypertable as the phone's, with a source, and a repeat of the same fix changes nothing. Web: Trackers and alerts page. The post format was checked against a real Traccar 6 server (see the acceptance notes), not only against what the docs say.*
- [x] **Three-way distance** per trip; **trip replay**; **geofences** with enter/exit events. *At trip end the odometer, the phone's GPS and the tracker's GPS are compared. When all three are there and one disagrees with the two that agree, that one is named (usually a wound-back odometer); with only two there is no way to tell which is wrong, so nobody is named. Tracker fixes that arrive late are matched to the trip by time. Replay (trip, or a vehicle for up to three days) shows the path with play controls and marks speeding, hard stops, idling, alerts and area crossings on it. Areas are circles or outlines drawn on the map (depot, client site, fuel station, restricted), optionally for some vehicles only; entry and exit are noted once each, and a restricted area texts the owner.*
- [x] **Tamper alerts:** tracker power cut, GPS jamming, device offline. *A power cut, jamming or a tamper alarm is red, texts the owner at once and lowers the vehicle's trust level for 30 days; low battery and offline are amber. The same fault reported again is the same alert. Power coming back closes a power alert; a tracker heard again closes an offline one. A watcher every 5 minutes (`TRACKER_OFFLINE_MINUTES`, 30) catches a tracker that went quiet without telling us. An alert is explained or confirmed as real with a note, by the owner or a manager, and audit-logged.*
- [x] **Driving behaviour & idling:** speeding, harsh braking/acceleration, cornering, idle time, long driving without rest. *Rules in `behaviour_rules.py`, mirrored in `packages/business-rules/src/behaviour.ts` and tested against `behaviour-cases.json`: speed over 80 km/h for 30 seconds, braking harder than 9 km/h per second, acceleration over 7 km/h per second, sideways acceleration over 2.5 m/s squared, engine on and standing for 10 minutes, driving 4.5 hours without a 30-minute rest, night driving 22:00 to 05:00. The thresholds are global constants, not yet set per business. Events are given to the driver on the trip. With a tracker the tracker's fixes are scored; the phone is scored only when there is no tracker, so nothing is counted twice, and idling needs a tracker (a phone does not know the engine is on). Web: Driving behaviour page by driver and by vehicle.*
- [x] **Remote immobiliser** (supported trackers): Owner-only, stationary-only, confirmation step, audit-logged. *Owner only (`immobiliser.use`). Step one records a request with a reason and checks the rules (supported, tracker online, position under 3 minutes old, speed 5 km/h or less); a refusal says why and sends nothing. Step two, within 2 minutes, needs the vehicle's number plate typed and the owner's password, and checks the rules again against the newest position before anything is sent. Releasing is always allowed. Every step is audit-logged, including refusals, wrong passwords and failures. The rule is mirrored in `immobiliser.ts` and tested against `immobiliser-cases.json`.*
- [x] **Vehicle trust level** shown everywhere. *On the live map, the vehicle list, the vehicle page and each trip, with tracker tamper counted alongside the phone flags.*

**Acceptance criteria**
- [x] Simulated tracker data appears on the map and replays correctly. *API tests post simulated Traccar data (`app/tracker_simulator.py`) and read it back from the live map and the replay, with its events marked and in order. `TRACCAR_FORWARD_KEY=<key> python -m app.tracker_simulator --imei <imei> --scenario trip|powercut|jamming|offline` sends the same data to a running API. The web replay screen was built and compiles; it was not clicked through in a browser in this sprint.*
- [x] A simulated power cut raises an alert immediately. *API test: the alert is red, the owner's text is sent in the same request, and the dashboard shows it.*
- [x] The immobiliser refuses to act on a moving vehicle. *API tests: refused at request, and refused again at confirmation when the vehicle drove off in between; nothing reaches Traccar.*

**Not verified**
- No real tracker, SIM or engine cut-off relay was used. Alarm names other than `hardBraking`, as sent by each tracker brand through Traccar, are from Traccar's documentation and need checking per model (power cut, jamming and tamper alarm names especially).
- A real Traccar 6 server (Docker image) was run with an OsmAnd-protocol device. Its JSON for positions and for events was captured and is now a test; the engine command call was accepted by it (queued, as the device had no live connection). Delivery of an engine stop to hardware was not tried.
- Traccar settings changed between versions: this one needs `FORWARD_TYPE=json` and `EVENT_FORWARD_TYPE=json` (the compose file sets them). `docker compose --profile tracking up -d traccar` starts it; `TRACCAR_FORWARD_KEY` must be set in `.env` first.
- Password attempts on the immobiliser are audit-logged but not rate-limited: add a lockout before relying on it.

**Kickoff brief**
> Integrate trackers through Traccar (5.3, Section 7), with replay, geofences, tamper alerts, driving behaviour and idling (5.25), and the immobiliser with all safeguards (5.28, Section 10). Include a tracker data simulator for testing.

**Demo:** replay a trip with idle periods and a harsh-braking event marked.

---

### Sprint 13: Fraud Engine, Alerts & Scorecards (Weeks 26–27)

**Goal:** FleetTms catches theft and dishonesty automatically. 🧪 **Milestone: private beta.**

**Stories**
- **Fraud engine** with every check in masterplan Section 5.13 except fuel sensors, including fake GPS, tamper events, duplicate receipts, tyre swaps, idling-adjusted fuel checks, parts issued-vs-fitted, and overloading.
- **Baselines** per vehicle by route and load.
- **Alerts** with severity, evidence, trust level; explained/confirmed feedback; adjustable thresholds; channel preferences.
- **Driver scorecards** (safety, fuel efficiency, punctuality, inspections, alerts).
- **Route suggestions** via Google Maps; **EPRA fuel prices** feeding quotes.
- **Beta:** onboarding checklist and in-app feedback button.

**Acceptance criteria**
- Seeded scenarios (inflated fuel, rolled-back odometer, side trip, padded parking, fake GPS, tracker power cut, tyre swap) each raise the right alert with evidence.
- Normal trips raise none; long idling no longer causes false fuel alerts.

**Kickoff brief**
> Build the fraud engine (5.13, all checks except fuel sensors), baselines, alerts, scorecards (5.25), route suggestions (5.12), and fuel price updates (5.28). Create seeded scenarios for every fraud type plus normal trips, and test that each triggers exactly the right alert.

**Demo:** run the "siphoning after a tracker power cut" scenario and show the alert with its evidence.

---

### Sprint 14: Fuel Sensors, Predictions & Smart Reading (Weeks 28–29)

**Goal:** the Premium tier and smarter automation.

**Stories**
- **Fuel sensors:** fuel level chart, refills and drops; siphoning-while-parked and refill-vs-paid alerts.
- **Predictions:** expected fuel per trip, expected trip profit (including lease charges for leased lorries), monthly forecasts.
- **Learned anomaly models** trained per vehicle once enough history exists, alongside the rules.
- **Document reading:** fuel receipts, weighbridge tickets, delivery notes, insurance certificates, logbooks, with confirmation.

**Acceptance criteria**
- A simulated overnight fuel drop triggers a siphoning alert.
- A quote for a leased lorry shows expected net profit after the lease charge.
- A photographed fuel receipt fills litres, amount, and station correctly.

**Kickoff brief**
> Add fuel sensors and Premium alerts (5.3, 5.13), predictions (5.14), learned anomaly models, and document reading (5.28). Keep every prediction explainable and show how it was calculated.

**Demo:** quote a job on a leased lorry and see expected fuel and net profit.

---

### Sprint 15: Subscriptions, Onboarding, Reports & Smart Questions (Weeks 30–31)

**Goal:** other fleet owners can sign up, pay, and run without help.

**Stories**
- **Subscriptions** per masterplan Section 9: per-vehicle plans, mixed plans, trial, annual and volume discounts, M-Pesa and card, grace period, read-only mode, free Lessor portal.
- **Feature gating** by plan per vehicle; SMS bundle add-on.
- **Self-service onboarding:** business → import or add vehicles → staff → first job; sample data option.
- **Advanced reports:** custom ranges, PDF/Excel export, scheduled reports by email.
- **Ask in plain English:** answers from the tenant's own data, always showing the numbers.
- **Driver messaging:** announcements and direct messages with read receipts.
- **Platform Admin console** and full data export for owners.

**Acceptance criteria**
- A new owner signs up and reaches a first job in under 15 minutes.
- Trial → M-Pesa payment → plan active; failed payment → grace → read-only, no data lost.
- "Which lorry had the highest cost per km last month?" returns the right answer with numbers.

**Kickoff brief**
> Implement subscriptions and pricing (Section 9), feature gating, onboarding, advanced and scheduled reports, plain-English questions (5.28, answering only from the tenant's data), driver messaging (5.27), the Platform Admin console, and data export.

**Demo:** sign up as a new transport company from scratch.

---

### Sprint 16: Security, Performance, Disaster Recovery & Compliance (Weeks 32–33)

**Goal:** safe, fast, and legally ready.

**Stories**
- **Security:** full review of tenant isolation, permissions (especially Lessor and Workshop), rate limits, secrets; external **penetration test**; fix findings.
- **Performance:** load test with large simulated fleets and live GPS; indexes; map performance.
- **Disaster recovery:** point-in-time backups, **tested restore**, meeting the 15-minute data-loss and 4-hour recovery targets; monitoring and uptime alerts.
- **Data protection:** finalise DPIA (including behaviour scoring, SOS, AI features); confirm ODPC registration; final T&Cs, Privacy Policy, sub-processor list; breach plan; data subject request workflow; retention jobs verified.

**Acceptance criteria**
- No critical or high penetration-test findings open.
- A full restore from backup succeeds within the target.
- Legal documents approved by the advocate.

**Kickoff brief**
> Audit the codebase for tenant isolation gaps, permission gaps, unlogged sensitive changes, secrets, and personal data in logs, and prioritise fixes. Then complete load testing, monitoring, and disaster recovery per Section 10, and verify retention per Section 11.3.

**Demo:** restore staging from backup and show the system back within target.

---

### Sprint 17: Launch (Weeks 34–35)

**Goal:** FleetTms live for the public. 🚀

**Stories**
- **Release:** Play Store and App Store submissions; production deployment; landing page with pricing.
- **Partner programme:** tracker installer sign-up, referral tracking, commission reports.
- **Product analytics:** privacy-respecting usage tracking and onboarding funnel.
- **Support:** help articles, WhatsApp/email support channel.

**Acceptance criteria**
- Apps approved in both stores.
- A partner referral is tracked through to a paid subscription.

**Kickoff brief**
> Prepare store submissions, production go-live, the partner programme (Section 9), product analytics (Section 7), and support resources.

**Demo:** FleetTms live in production with the first paying customer.

---

## 4. Progress Log (update every sprint)

| Sprint | Dates | Status | What shipped | Carried over | Notes / decisions |
|---|---|---|---|---|---|
| S0 | 2026-10-02 | 🟨 In progress | Monorepo, API, web, mobile shells, Docker, job queue, lint/test tooling | staging deploy, storage bucket, external applications | Ports 5442/8010/5180 |
| S1 | 2026-10-02 | ✅ Done, with carry-overs | Tenancy, auth (OTP + password + TOTP or SMS second step), roles, audit log, depots, support access, web + mobile screens, draft legal docs | advocate review of `docs/legal/` | Tenant isolation is ORM-level; RLS planned for S16. Dev-only: OTP codes are printed to the API console. |
| S2 | 2026-10-02 | ✅ Done, with carry-overs | Vehicles, ownership, lessors/lenders, staff profiles, crew with history, documents with SMS expiry reminders, Excel import (vehicles, staff), demo seed, web pages, mobile vehicle list and My vehicle card | Import of clients, suppliers and opening balances (tables do not exist yet); document file upload (needs storage bucket) | Reminders run daily at 07:00 Africa/Nairobi through the arq worker. Supervisor scope now enforced. |
| S3 | 2026-10-02 | 🟨 Built; mobile capture partly verified | Pre-trip inspection with configurable checklist, critical-fault block and manager override, trips with start/loading/delivered/end, odometer photos with flags and distance, private photo storage with signed links, web trips and checklist pages, mobile inspection and trip flow | Automatic odometer reading from the photo (needs a development build); odometer confirm and submit screens on mobile not run end to end (the emulator's camera returns black stills); S3 bucket for photos | Photos refused if stale (10 min), blank, too small or repeated. Local-disk photo storage in `media_store/` (git-ignored). |
| S4 | 2026-10-02 | 🟨 Built; on-device checks partly done | Idempotent offline sync, encrypted offline vault and queue, sync badge and rejected-record handling, fuel entries, floats, device integrity and vehicle trust, web Expenses and trust pages, mobile Expenses tab | A full offline morning with a real odometer photo on a device; a real fake-GPS app test; receipt photo flow on a device | Receipts optional but flagged. Records older than 7 days are refused. Mobile has its own test suite now (`pnpm test`). |
| S5 | 2026-10-02 | 🟨 Built and tested; the real-world week is yours | Expenses with limits, duplicate and route checks; reconciliation; service schedules and reminders; work orders from defects and services; dashboard v1 and reports; owner-driver rules; mobile Expenses and offline expenses; quick sign-in with a PIN | PDF/Excel export and scheduled reports; owner mobile dashboard not run on a device; a real week of use on your own lorries | Reminders run daily at 07:00 and 07:05 Africa/Nairobi. Income, profit and money owed wait for billing (Sprints 8 to 10). |
| S6 | | ⬜ | | | |
| S7 | | ⬜ | | | |
| S8 | | ⬜ | | | |
| S9 | 2026-10-02 | 🟨 Built and tested against stand-ins | Daraja C2B callbacks with invoice matching and a manual queue, M-Pesa statement import (fuel, expenses, floats, client payments), debtors with ageing, SMS and email payment reminders, eTIMS queue with retries, review queue and credit notes, profit against cash on the dashboard, web pages and settings | Real Safaricom and KRA sandbox runs (need your keys, a public address and the registered eTIMS device); WhatsApp reminders (lease payments in the statement import were added in Sprint 10) | Callback addresses carry an HMAC of the business id (rotating JWT_SECRET means registering them again). eTIMS field names, tax codes and item codes are from KRA's documentation and unchecked. |
| S10 | 2026-10-02 | 🟨 Built and tested; not tried on your real lorries | Leases (in and out, every payment model, cost matrix), lease ledger with offsets, payments, corrections, overdue alerts and texts, statements (PDF, WhatsApp, email), Lessor portal, asset finance with schedules, ownership costs, profit engine (trip, vehicle, client, driver, depot, business) with net after lease and finance, payroll with advances and fines, suppliers and WhatsApp orders, M-Pesa statement matching for lease, loan and advance payments | Try it on your own leased and financed lorries and compare with your spreadsheet; staff payslips and statutory deductions; B2C payments through M-Pesa; supplier Excel import; lessor location (Sprint 11) | Profit is in whole months. Salaries come from approved runs, else the salary on file. The masterplan example's net of 100,000 does not deduct the 20,000 repair the operator fronted (cash profit is 80,000). |
| S11 | 2026-10-03 | 🟨 Built, tested, and checked on the emulator | Phone GPS (background task, encrypted buffer, stops at trip end), location hypertable, GPS distance and odometer check, going-dark watcher, retention job, live map (web, mobile list), trip path, client tracking links and page, monitoring notice draft-2 | Try on a real phone in a moving lorry and watch battery use; full map on the phone; DPIA and legal review of the notice; tune the 15-minute going-dark limit and 5-minute live window | Mobile needs a development build (Expo Go cannot do background location): see PROJECT_GUIDE. GPS accuracy is set to high because balanced mode gives positions too vague for a lorry's route. |
| S12 | 2026-10-03 | 🟨 Built and tested; not tried on a real tracker | Traccar ingestion (post format checked against a real Traccar 6 server), trackers fitted by IMEI with status, three-way distance with the odd one named, replay with play controls, mapped areas (circle or outline, enter and exit, restricted texts the owner), tamper alerts with immediate text, offline watcher, driving behaviour and idling by driver and vehicle, immobiliser with request, plate and password confirmation and safety checks twice, trust level on map, vehicles and trips, tracker simulator, Traccar in compose (profile) | Fit one real tracker and check which alarm names its model sends; try the engine stop on a parked vehicle you own; set speed and idle limits per business; mobile screens for alerts | Behaviour limits are global constants. Idling and harsh events from the phone alone are rough: a tracker gives the reliable reading. |
| S13 | | ⬜ | | | |
| S14 | | ⬜ | | | |
| S15 | | ⬜ | | | |
| S16 | | ⬜ | | | |
| S17 | | ⬜ | | | |

Status key: ⬜ Not started · 🟨 In progress · ✅ Done · 🟥 Blocked

---

## 5. Sprint Rituals (solo-friendly)

- **Sprint start (30 min):** re-read the sprint section, update "Current sprint" in the project guide, order the stories.
- **Daily (5 min):** pick one story; finish it to the Definition of Done before starting another.
- **Mid-sprint check:** if behind, move the lowest-value story to the next sprint rather than cutting tests or security.
- **Sprint end (1 hr):** demo on web + Android; update the progress log; review the sprint's code for tenant isolation and duplicated logic.
- **From Sprint 5 onward:** spend 15 minutes a week reviewing real data from your own lorries. Real problems beat planned features.

---

## 6. Risks to Watch During the Build

| Risk | Early warning sign | Response |
|---|---|---|
| Scope creep | Adding "small" features mid-sprint | Park ideas in a backlog; review at sprint end |
| Web and mobile drifting apart | Same rule written twice | Move logic into the shared package immediately |
| Tenant or lessor data leak | Any query without tenant or vehicle scoping | Automated isolation tests block merging |
| Lease calculation errors | Lessor disputes a statement | Test every payment model against hand-calculated examples |
| Background GPS draining batteries | Driver complaints | Tune sampling; rely on trackers for Standard/Premium |
| Integration delays (Daraja, eTIMS approvals) | Waiting on credentials | Apply in Sprint 0 |
| Burnout as a solo founder | Skipping rituals, long nights | Keep sprints realistic; move stories forward, don't cram |

---

*End of FleetTms Sprint Plan v1.1*
