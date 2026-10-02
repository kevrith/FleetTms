# FleetTms — Masterplan

> **Version:** 1.1 (Planning). Adds proof of delivery, jobs & dispatch, leasing & asset finance, inspections, tyres, incidents, axle loads, extra fraud checks, and state-of-the-art features.
> **Date:** 1 October 2026
> **Owner:** Kelvin — Kastra Enterprises
> **Status:** Blueprint for build. High-level and conceptual; no implementation code.

---

## 1. App Overview & Objectives

**FleetTms** is a fleet and transport management system that shows transport business owners how their business is *really* performing, and protects them from silent losses such as fuel theft, inflated expense claims, and missed services.

It starts as the operating system for Kelvin's own lorry business (the first customer and live test bed), then becomes a **multi-tenant SaaS** sold to other fleet owners in Kenya.

### Core objectives
1. **Visibility**: know where every lorry is, how far it has gone, and what it cost to run.
2. **Profitability**: true profit per trip, per vehicle, per client, and for the whole business.
3. **Fraud prevention**: automatically detect fuel siphoning, false fuel claims, odometer tampering, and suspicious expenses.
4. **Discipline**: never miss a service, licence renewal, or insurance expiry.
5. **Cash control**: track floats given to drivers, daily reconciliation, and who owes the business money.
6. **Simplicity**: drivers need only a few big buttons; owners get clear insight.

### The "why"
Transport owners lose money in ways they can't see: fuel disappearing between the pump and the tank, padded expense claims, debts that are never chased, and lorries that cost more to run than they earn. FleetTms turns those blind spots into numbers and alerts.

---

## 2. Target Audience

| Segment | Description | Key need |
|---|---|---|
| **Owner-drivers** | Start with one lorry and drive it themselves | Simple profit tracking, service reminders, debt tracking |
| **Small fleet owners** (2–10 lorries) | Owner plus hired drivers and turnboys | Fuel theft detection, float control, daily reconciliation |
| **Growing / medium fleets** (10–50+) | Owner, managers, supervisors, accountants | Role-based access, supervisor oversight, payroll, compliance, deep reports |
| **Kelvin's own business** | First tenant / pilot customer | Validate every feature under real conditions |

**Primary market:** Kenya (cargo lorries, tippers, delivery trucks). East Africa is a later expansion.

---

## 3. Users & Roles

One person can hold **multiple roles** (for example, Owner + Driver).

| Role | Can access | Restricted from |
|---|---|---|
| **Owner** | Everything: vehicles, finances, staff, payroll, reports, settings, subscription, users | Nothing |
| **Manager** | Vehicles, trips, clients, expenses, suppliers, alerts, reports; approve floats and reconciliations | Payroll details, subscription billing, deleting the business |
| **Supervisor** | Live map, trips, odometer/expense records, alerts for **assigned vehicles only**; approve daily reconciliations | Company-wide finances, payroll, client billing |
| **Accountant** | Invoices, payments, debtors, expenses, payroll, eTIMS, financial reports | Live map, editing trips, managing user access |
| **Driver** | Own trips, odometer capture, fuel and expense entries, float balance, saved routes | Other drivers' data, profit, company finances |
| **Turnboy / Assistant** | Optional, owner-controlled: view current trip, log expenses | Everything else |
| **Workshop / Storekeeper** | Optional: work orders, inspections defects, tyres, spare parts store | Finances beyond parts costs, trips, payroll |
| **Vehicle Owner (Lessor)** | Free, view-only portal for **their own leased vehicle(s)**: lease statement, amounts earned, paid and owed, and service/inspection history. Location and trip details only if the lease agreement allows it. | The lessee's other vehicles, clients, staff, and overall business finances |
| **Platform Admin** (Kastra Enterprises) | Subscriptions, support tools, platform health | A tenant's private business data, unless the tenant grants temporary, logged support access |

### Owner-driver mode
- The owner can assign themselves as a vehicle's driver.
- The mobile app offers a **switch between Owner view and Driver view**.
- Fraud alerts aimed at *staff dishonesty* are relaxed for the owner. Fuel-efficiency, service, and **theft-while-parked** alerts stay active.
- When the business grows, the lorry is reassigned to a hired driver and all history is kept.

### Access principles
- **Least privilege**: each role sees only what its job requires.
- **Approval flow**: Driver submits → Supervisor/Manager approves → Owner sees everything.
- **Immutable audit trail**: every create, edit, approval, and deletion is logged (who, what, when, before/after values). Sensitive edits after approval trigger alerts.
- **Future:** custom roles (for example, "Workshop Manager").

---

## 4. Platforms

| App | Users | Purpose |
|---|---|---|
| **Web dashboard** (desktop and mobile browser) | Owner, Manager, Supervisor, Accountant | Full management: reports, invoices, payroll, large live map, settings |
| **Mobile app** (Android + iOS, built with Expo) | Drivers, turnboys, and owners on the go | Trip capture, odometer photos, expenses, fuel, alerts, quick reports, approvals |

- **Both apps are built in parallel, feature by feature**, sharing one backend, one set of business rules, and one design language.
- **Language:** English only at launch. All interface text is kept organised so Swahili can be added later.
- **Offline-first mobile app**: works without network and syncs automatically when coverage returns.

---

## 5. Core Features & Functionality

### 5.1 Vehicles
- Vehicle profiles: registration, make/model, capacity (tonnes), fuel type, tank size, **expected fuel consumption** (km per litre, per load condition), current odometer.
- **Tracking tier per vehicle** (see 5.3), which sets its "data trust level."
- **Ownership type:** Owned · Asset-financed (loan) · Leased-in (hired from another owner) · Leased-out (your lorry hired to someone else). See 5.23.
- Legal load limits (gross weight and axle configuration) for overload checks (5.22).
- Home **depot/branch** for businesses with more than one yard.
- Documents with expiry reminders: insurance, inspection, NTSA/TLB licence, permits.
- Assigned crew (driver + turnboy), changeable over time with history.

### 5.2 Trips
- Trips are created from a **job** (see 5.17): client, route, cargo, billing method, assigned vehicle and crew.
- **Pre-trip inspection** (5.19) must pass before the trip can start.
- **Start Trip**: mandatory odometer photo → trip begins.
- **Loading**: cargo photo, weighbridge ticket, loaded weight (overload check, 5.22).
- **Delivery**: **proof of delivery** (5.18).
- **End Trip**: mandatory odometer photo → trip closes.
- Trip timeline: start/end, loading and offloading times, stops, GPS path, distance (odometer vs GPS vs tracker), idle time, fuel, expenses, income.
- **Loaded vs empty kilometres** recorded per trip (return legs with no cargo).
- Trip status: scheduled → in progress → delivered (POD) → completed → invoiced → paid.

### 5.3 Location & Distance Tracking (three tiers)

| Tier | Data source | Strength |
|---|---|---|
| **Basic** | Driver's phone GPS (mobile app) + odometer photos + manual fuel entry | Good for honest operations and owner-drivers |
| **Standard** | Hardware **GPS tracker** in the vehicle + odometer photos | Tamper-resistant distance and location |
| **Premium** | GPS tracker + **fuel level sensor** | Gold standard: detects fuel drops in real time, including while parked |

- **Device-agnostic**: works with common GPS tracker brands used in Kenya (Teltonika, Concox, Ruptela, and others) through a single integration layer. Owners are not locked into specific hardware.
- **Live map**: all vehicles shown as moving, parked, idle, or offline; tap for trip details.
- Trip replay: view the path a lorry actually took.

### 5.4 Odometer Capture (anti-tampering)
- Required at trip start and end (configurable: per trip or per day).
- **Live camera capture.** The mobile app blocks gallery uploads. On web, photo metadata is checked for freshness.
- Every photo stamped with **time and GPS location**.
- **Automatic reading of the odometer number** from the photo; the driver confirms. A mismatch between the typed and read value is flagged.
- Three-way distance check: **odometer vs phone GPS vs tracker**.

### 5.5 Fuel Management
- Fuel purchases paid by the owner via **M-Pesa Paybill** directly to stations, recorded against vehicle and trip: litres, price per litre, station, amount, M-Pesa code, receipt photo.
- **M-Pesa transaction import** (via integration or uploaded M-Pesa statements) to avoid double entry.
- Expected vs actual consumption per trip, per vehicle, per driver.
- Fuel-sensor data (Premium) shows refills and drops as they happen.

### 5.6 Driver Float & Daily Reconciliation
- Owner sends M-Pesa for tolls, parking, food, etc., recorded as a **float** to that driver.
- Driver logs each expense in the app (type, amount, photo of receipt where possible).
- End of day: **float − expenses = balance**. The balance is carried forward or returned. Supervisor/Manager/Owner approves.
- **Expected cost per route** (for example, usual parking or toll costs) flags unusual claims.

### 5.7 Expenses
- **Daily trip expenses**: tolls, parking, food, loading/offloading, police/county fees, etc.
- **Other expenses**: repairs, tyres, insurance, licences, permits, garage fees.
- **Overheads**: payroll, office, subscriptions.
- Every expense linked to a vehicle (and trip where relevant) so **true cost per lorry** is always known.
- **Spend limits:** expenses above an owner-set amount (per category or per role) need approval before they count.
- **Duplicate detection:** the same receipt photo or M-Pesa code cannot be claimed twice.
- **Fixed ownership costs** spread monthly per vehicle: annual insurance, licences, asset-finance repayments, lease charges, depreciation (5.23).

### 5.8 Service & Maintenance
- Service schedules by **kilometres** (for example, every 10,000 km) and/or **time** (for example, every 3 months), whichever comes first.
- Advance reminders ("Service due in 500 km").
- Service history and costs per vehicle.
- Suggested parts list per service type, which links to supplier ordering.

### 5.9 Suppliers & Parts Ordering
- Supplier directory: spare parts, oil, tyres, garages, with contacts and items supplied.
- Create a **parts order** → send to the supplier via **WhatsApp** in one tap.
  - **Phase 1:** WhatsApp "click-to-send" (free; opens WhatsApp with the order pre-written).
  - **Later:** official WhatsApp Business API for automatic sending and status updates.
- Order tracking: sent → confirmed → collected → paid.

### 5.10 Clients, Billing & Debts
- **Billing method set per client, overridable per job:**
  - **Per trip** (fixed amount)
  - **Per tonne** (rate × weight, with weighbridge ticket photo)
  - **Monthly contract** (fixed fee; trips still tracked to measure contract profitability)
  - **Per kilometre** (optional)
- **Saved client routes**: a client's route is stored once (pickup, drop-off, preferred path, notes) and reused on every future job.
- Invoices: automatic for contracts, per job for others; partial payments supported.
- **KRA eTIMS** submission of invoices.
- **M-Pesa payments** from clients (Paybill/Till) matched automatically to invoices.
- **Debtors view**: balance per client, ageing (0–30, 31–60, 61–90, 90+ days), payment history.
- **Automatic payment reminders** via SMS, email, or WhatsApp.

### 5.11 Staff & Payroll
- Staff records: drivers, turnboys/assistants, supervisors, managers, accountants.
- Licence/document expiry reminders for drivers.
- **Monthly salary** tracking with salary advances deducted at month end.
- **Optional (later phase):** statutory deductions (PAYE, SHIF, NSSF, Housing Levy) and payslips.

### 5.12 Route Planning
- Best route suggestions between points, considering distance and traffic.
- **Saved routes** per client and per common destination.
- **Mapped areas**: owners can mark zones (depots, client sites, fuel stations, restricted areas). The system notices when a lorry enters or leaves, or goes somewhere it shouldn't (geofencing).
- **Later:** truck-specific routing (weight limits, low bridges) using a truck-aware mapping provider.

### 5.13 Fraud & Anomaly Detection (the heart of FleetTms)
The system learns each vehicle's normal behaviour from its initial setup data and history, then flags deviations.

| Check | What it catches |
|---|---|
| Fuel paid vs distance driven vs expected consumption | Inflated fuel claims, pump short-filling |
| Fuel-sensor drop while vehicle parked or engine off | **Siphoning** |
| Fuel-sensor refill amount vs litres paid | Paying for fuel that never entered the tank |
| Odometer vs GPS vs tracker distance mismatch | Odometer tampering, unrecorded side trips |
| Route deviation from saved/expected route | Unauthorised trips, side business with your lorry |
| Long unexplained stops in unusual places | Possible siphoning or unauthorised activity |
| Expense claim above route norms | Padded tolls, parking, food |
| Edits to approved records | Covering tracks after the fact |
| Phone GPS off or tracker offline mid-trip | Attempts to go dark |
| **Fake GPS app, rooted phone, or changed phone clock** | Faked locations and backdated records on the phone tier |
| **Tracker power cut or GPS jamming** | The classic step before siphoning or hijacking |
| **Duplicate receipt photo or M-Pesa code** | Claiming the same expense twice |
| **Tyre serial mismatch at inspection** | Tyre swapping (new tyres replaced with worn ones) |
| **Excess idling** | Fuel burned with no distance; also explains fuel variance fairly |
| **Spare parts issued vs fitted** | Parts taken from the store but never fitted |
| **Overloading** | Fines, damage, and drivers carrying unrecorded extra cargo for cash |

- Each alert shows **severity**, **evidence** (numbers, map, photos), and the vehicle's **trust level**.
- Owners can mark alerts as *explained* or *confirmed*, and the system gets smarter over time.
- **Thresholds are adjustable** per business (for example, alert above 10% fuel variance).

### 5.14 Predictions
- Expected fuel for a planned trip (from route distance, load, vehicle history).
- **Expected trip profit** before accepting a job ("Is this job worth taking?").
- Monthly profit forecast per vehicle and for the business.
- Starts with simple averages and rules; becomes smarter as data grows.

### 5.15 Reports & Dashboards
- **Daily, weekly, monthly, and custom date range** reports.
- Profit & loss: per trip, vehicle, client, driver, and business.
- **Profit vs cash**: earned (invoiced) vs actually received.
- Fuel efficiency rankings: vehicles and drivers.
- **Cost per km**, revenue per km, **loaded vs empty km**, and idle time per vehicle.
- **Profit after lease and finance**: gross trip profit vs net profit after lease charges, loan repayments, and depreciation (5.23).
- **Lessor statements** per leased vehicle; lease income for leased-out vehicles.
- Tyre cost per km, incident and fine history, driver scorecards.
- Expenses breakdown, service costs, debtors ageing, float reconciliation summary, alert history.
- Export to PDF and Excel; scheduled reports sent by email or WhatsApp (for example, every morning at 7am).

### 5.16 Notifications
- In-app and push notifications (mobile).
- SMS for critical alerts and payment reminders.
- Email for reports and invoices.
- WhatsApp (later, via Business API).
- Owners choose which alerts go to which channel and role.

### 5.17 Jobs, Quotes & Dispatch
The full lifecycle: **quote → job → dispatch → trip → proof of delivery → invoice → payment**.
- **Quotes:** price a job using the client's billing method, route distance, expected fuel at current pump prices, tolls, and crew costs. The system shows **expected profit** before you accept. Quotes can be sent to the client by WhatsApp, SMS, or email.
- **Jobs:** an accepted quote (or a recurring contract job) becomes a job with cargo details, pickup and delivery windows, and special instructions.
- **Dispatch & availability calendar:** see which lorries and crews are free, in service, or booked; assign a job and the driver gets it on their phone.
- One job can need several trips (e.g., 120 tonnes moved over four loads).

### 5.18 Proof of Delivery (POD)
- At delivery the driver captures: photo of offloaded cargo, photo of the signed delivery note, recipient's name, and either an on-screen signature or a **one-time code sent to the client's phone**.
- GPS and time stamps prove where and when delivery happened; delivery outside the client's mapped site is flagged.
- Shortages or damage are recorded at delivery with photos and quantities.
- Confirmed POD can trigger the invoice automatically and is attached to it, which settles "we never received it" disputes.

### 5.19 Pre-Trip Inspection & Work Orders
- Daily checklist before the first trip: tyres, brakes, lights, oil, coolant, leaks, body damage, tyre serials, with photos for any fault.
- Critical defects (e.g., brakes) **block the trip** until a manager overrides with a reason.
- Defects automatically create **work orders** for the workshop or garage: issue, priority, assigned mechanic or supplier, parts used, labour cost, and status.
- Preventive work (from service schedules, 5.8) and corrective work (from defects and breakdowns) share one work-order system.
- Inspection photos protect owners in disputes about who caused damage.

### 5.20 Tyre Management
- Every tyre recorded by **serial number**, brand, size, cost, and supplier.
- Tyre position on each vehicle (e.g., front-left steer, rear-axle inner-right), fitted and removed dates, kilometres covered, tread depth readings, retreads, and rotations.
- Serials checked during inspections; a mismatch raises a **tyre swap** alert.
- Reports: tyre cost per km by brand and supplier, tyres due for rotation or replacement.

### 5.21 Incidents, Breakdowns & Fines
- One-tap reports for **breakdown, accident, police stop, traffic fine, county cess, cargo theft**, with photos, location, and notes.
- Breakdowns create urgent work orders and update the job's expected delivery time.
- Accidents link to **insurance claims** with documents and claim status.
- Fines tracked per driver and vehicle, including who pays (business or driver deduction via payroll).
- **SOS / panic button** for drivers: alerts the owner and supervisors instantly with live location (hijacking and security risk).

### 5.22 Load & Axle Compliance
- Each vehicle stores its legal gross weight and axle configuration.
- Loaded weight from the weighbridge ticket (with photo) is checked against the limit **before the trip starts**; overloads are flagged.
- Tracks overload fines and weighbridge records per trip, which also reuses the weight for per-tonne billing.

### 5.23 Vehicle Ownership, Leasing & Asset Finance
Many operators don't own every lorry they run. FleetTms calculates **true profit after every deduction**, including what is paid to the lorry's owner.

**Ownership types per vehicle**

| Type | Meaning | What FleetTms tracks |
|---|---|---|
| **Owned** | The business owns it outright | Depreciation, insurance, licences |
| **Asset-financed** | Bought on a loan (bank or asset finance company) | Lender, loan amount, repayment schedule, balance, interest, overdue alerts |
| **Leased-in** | Hired from another owner (the **lessor**) | Lease agreement, charges owed, payments made, balance due to the lessor |
| **Leased-out** | Your lorry hired to someone else | Lease income, payments received, lessee's balance |

**Lease agreement (set up once per leased vehicle)**
- Lessor's name, phone, KRA PIN, and M-Pesa/bank payment details.
- Start and end dates, notice period, security deposit.
- **Payment model** (choose one or combine):
  - Fixed amount per **month**, **week**, or **day**
  - Fixed amount per **trip**
  - Rate per **kilometre**
  - **Percentage of revenue** (e.g., lessor gets 30% of what the lorry earns)
  - **Percentage of profit** after agreed costs
  - A **minimum guarantee** with revenue share above it (e.g., at least KES 120,000/month, or 30% of revenue, whichever is higher)
- **Cost responsibility matrix:** who pays for fuel, routine service, major repairs, tyres, insurance, licences, driver salary, tracker subscription, fines. For example, the lessee pays fuel and the driver, while the lessor pays insurance and major engine repairs.
- **Offsets:** if the lessee pays a cost that belongs to the lessor (e.g., an engine repair), it is automatically deducted from the next lease payment, with receipts as evidence.

**Lease ledger & payments**
- Lease charges accrue automatically from the agreement (time-based charges each period; trip, km, and revenue-based charges from actual trips).
- Payments to the lessor recorded with M-Pesa code, or sent via M-Pesa where integrated.
- **Balance owed to the lessor** always visible, with due-date reminders and overdue alerts.
- **Lessor statement** (PDF or portal view): period, trips or km, revenue (if revenue share), charges, offsets, payments, balance. Transparent statements reduce disputes.
- The lessor gets the optional free **Lessor portal** (Section 3), seeing only what the agreement allows.

**Profit after all deductions**
For each leased vehicle, reports show:

> **Revenue** − **operating costs** (fuel, trip expenses, crew pay, the lessee's share of maintenance and tyres) = **Gross profit**
> Gross profit − **lease charges** + **offsets recovered** = **Net profit to the lessee**

*Worked example (one month, one leased lorry):* revenue KES 600,000; fuel KES 230,000; trip expenses KES 40,000; driver and turnboy KES 55,000; lessee's maintenance KES 15,000 → gross profit KES 260,000. Lease charge: 30% of revenue = KES 180,000, minus a KES 20,000 engine repair the lessee paid on the lessor's behalf = KES 160,000 payable. **Net profit to the lessee: KES 100,000.** FleetTms also flags when a lease isn't worth it (e.g., three months in a row where the lessor earns more than the operator).

The same logic applies to **asset-financed** lorries (loan repayments as a cost) and to **leased-out** lorries (lease income instead of trip revenue).

### 5.24 Spare Parts Store
- Stock of parts kept at the yard (oil, filters, belts, bulbs, tyres in store): quantities, cost, reorder levels.
- Parts **issued to a vehicle** against a work order; low stock triggers a supplier order (5.9).
- Issued-vs-fitted checks and periodic stock counts expose store leakage.

### 5.25 Driver Behaviour & Idling
- From trackers (and the phone where possible): speeding, harsh braking, harsh acceleration, sharp cornering, **idle time** with the engine on, and night driving.
- Idle fuel is factored into fuel checks, so alerts are fairer and more accurate.
- **Driver scorecards**: safety, fuel efficiency, punctuality, inspection compliance, alerts; useful for bonuses and coaching.
- Rest-time monitoring: long continuous driving without breaks is flagged for fatigue.

### 5.26 Client Tracking Link
- Share a secure, expiring link that shows the client where their cargo is and the expected arrival time.
- Shows only that delivery's progress, not the driver's details or other trips, and expires after delivery.

### 5.27 Driver Communication
- Announcements and direct messages from owner, manager, or supervisor to drivers inside the app, with read receipts.
- Instructions are recorded on the job, instead of being lost in phone calls.

### 5.28 Smart Features
- **Document reading:** fuel receipts, weighbridge tickets, delivery notes, insurance certificates, and logbooks are photographed and their details filled in automatically (driver/owner confirms).
- **Learned anomaly detection:** beyond fixed thresholds, models learn each lorry's normal behaviour by route, load, and season, so alerts become more accurate over time.
- **Ask in plain English:** owners type questions like "Which driver used the most fuel per km this month?" or "Is the Nakuru contract profitable?" and get answers from their own data, with the numbers shown.
- **Current fuel prices:** EPRA's monthly pump prices used in quotes and predictions.
- **Remote engine immobiliser** (via compatible trackers) for theft recovery: **Owner-only**, works only when the vehicle is stopped or below a very low speed, requires a confirmation step, and is fully audit-logged.

### 5.29 Business Setup & Growth Tools
- **Multiple depots/branches** per business, with reports by depot.
- **One login, several companies:** an owner running more than one business switches between them without logging out.
- **Import from Excel:** vehicles, staff, clients, suppliers, and opening balances (debts owed, lease balances), so a business can switch to FleetTms in an afternoon.

---

## 6. User Interface Design Principles

**Guiding principle: owners get insight, drivers get simplicity.**

### Owner / manager home: "How is my business doing right now?"
1. **Today's numbers**: income, expenses, profit, active trips, money owed.
2. **Alerts panel**: urgent fraud and service alerts at the top, colour-coded by severity.
3. **Live map** of the fleet.
4. **Quick actions**: send float, record payment, create quote/job, order parts, pay lessor.
5. Navigation: Jobs & Dispatch · Vehicles · Trips · Clients & Debts · Expenses · Workshop (inspections, work orders, tyres, parts) · Leases & Finance · Staff & Payroll · Suppliers · Reports · Settings.

### Driver home: "What do I need to do now?"
1. **Today's trip card**: client, route, saved directions, cargo.
2. **Pre-trip inspection**, then **one big Start Trip / End Trip button** that opens the camera for the odometer.
3. **Add Expense**: type → amount → photo → done.
4. **Float balance** in large text.
5. **Deliver** button for proof of delivery, and **Report Problem** (breakdown, accident, police stop) plus an **SOS** button.
6. **Sync status badge**: offline / pending / all saved.

### Design rules
- Large tap targets and minimal typing for drivers (often working in harsh conditions).
- Plain English, short labels, icons with text.
- Works well on low-end Android phones and slow networks.
- Consistent design across web and mobile.
- Colour used for meaning (red = alert, amber = warning, green = fine), always paired with text or icons for accessibility.
- Dark mode support for night driving.

---

## 7. High-Level Technical Stack Recommendations

| Layer | Recommendation | Why |
|---|---|---|
| **Project structure** | Monorepo with shared business rules, data types, and design system | Build web and mobile in parallel without duplicating logic |
| **Web dashboard** | React + TypeScript | Matches existing skills; rich dashboards and reports |
| **Mobile app** | Expo (React Native) + TypeScript, Android and iOS | Background GPS, live camera, offline storage, push notifications; reuses React skills |
| **Backend API** | Python (FastAPI) | Matches existing skills; strong for data analysis, predictions, and fraud detection |
| **Main database** | PostgreSQL with geographic extension (PostGIS) | Reliable relational data plus maps, routes, and geofences |
| **GPS history storage** | Time-series extension for PostgreSQL (e.g., TimescaleDB) | Handles millions of location points efficiently |
| **GPS tracker ingestion** | Open-source tracker server (e.g., Traccar) as the device-agnostic layer | Already supports hundreds of tracker brands and protocols |
| **Photo storage** | Cloud object storage (S3-compatible), private and encrypted | Odometer photos, receipts, weighbridge tickets |
| **Background jobs** | Job queue (e.g., Redis-based) | Fraud checks, reports, reminders, syncing |
| **Maps & routing** | Google Maps Platform at launch; evaluate HERE for truck-specific routing later | Familiar, good Kenya coverage; truck routing as an upgrade |
| **Odometer reading** | On-device text recognition (mobile) with cloud OCR fallback | Fast, works offline |
| **Payments** | M-Pesa Daraja (client payments, transaction matching; subscription billing) | Kenya's dominant payment method |
| **Tax compliance** | KRA eTIMS integration | Mandatory invoicing compliance |
| **SMS / OTP** | Africa's Talking | Reliable Kenyan SMS and OTP delivery |
| **WhatsApp** | Click-to-send first; WhatsApp Business API later | Free to start; automate later |
| **Hosting** | Cloud provider with an African region (or Kenya-based hosting), with backups in a second location | Low latency; supports data protection requirements |
| **Device integrity** | Mobile checks for mock-location apps, rooted/jailbroken phones, and clock changes | Keeps phone-tier data trustworthy |
| **Document reading & AI** | Cloud document-reading service for receipts and tickets; a large language model for plain-English questions, answering only from the tenant's own data | Less typing; insight without building every report |
| **Anomaly models** | Start with rules and averages; add learned models in Python once enough data exists | Accuracy improves with data, no premature complexity |
| **Product analytics** | Privacy-respecting usage analytics (no personal data) | See which features owners use and where they get stuck |

---

## 8. Conceptual Data Model

Every record belongs to a **Business (tenant)**. Data from one business is never visible to another.

| Entity | Key information | Relationships |
|---|---|---|
| **Business (Tenant)** | Name, KRA PIN, contacts, subscription plan, settings, alert thresholds | Has many users, vehicles, clients, suppliers |
| **User** | Name, phone, email, login method, status | Belongs to a business; has one or more roles |
| **Role Assignment** | Role type, scope (e.g., assigned vehicles for supervisors) | Links users to permissions |
| **Staff Profile** | Job title, salary, licence details, document expiries | Linked to a user (drivers, turnboys, etc.) |
| **Vehicle** | Registration, model, capacity, fuel type, tank size, expected consumption, odometer, tracking tier | Has crew assignments, trips, fuel, expenses, services, documents |
| **Tracking Device** | Type (tracker / fuel sensor), brand, identifier, status | Belongs to a vehicle |
| **Location Point** | Time, coordinates, speed, ignition, fuel level (if sensor) | Belongs to a vehicle (and trip) |
| **Crew Assignment** | Driver, turnboy, start/end dates | Links staff to vehicles over time |
| **Client** | Name, contacts, KRA PIN, default billing method and rates | Has saved routes, trips, invoices |
| **Saved Route** | Pickup, drop-off, path, distance, expected costs, notes | Belongs to a client or business |
| **Mapped Area (Geofence)** | Name, shape on map, type (depot, client site, restricted) | Belongs to a business |
| **Trip** | Status, times, cargo, weight, billing method, rate, distances (odometer/GPS/tracker) | Vehicle, crew, client, route; has fuel, expenses, income |
| **Odometer Reading** | Value, photo, time, location, auto-read value, confirmed value | Belongs to a trip/vehicle |
| **Fuel Entry** | Litres, price, amount, station, M-Pesa code, receipt photo | Vehicle, trip |
| **Float** | Amount sent, M-Pesa code, date, recipient | Driver, vehicle |
| **Expense** | Category, amount, photo, date, approval status | Vehicle, trip, float (if paid from float) |
| **Reconciliation** | Float total, expenses total, balance, outcome, approver | Driver, day |
| **Service Schedule** | Interval (km/time), last service, next due | Vehicle |
| **Service Record** | Date, odometer, work done, parts, cost, garage | Vehicle, supplier |
| **Supplier** | Name, contacts, WhatsApp number, items supplied | Has orders |
| **Parts Order** | Items, quantities, status, cost | Supplier, vehicle, service |
| **Invoice** | Number, amounts, due date, eTIMS status | Client, trips/contract |
| **Payment** | Amount, method, M-Pesa code, date | Invoice(s) |
| **Payroll Entry** | Month, salary, advances, deductions, net pay | Staff |
| **Alert** | Type, severity, evidence, status (open / explained / confirmed) | Vehicle, trip, driver |
| **Audit Log** | Who, what, when, before/after values | Any record |
| **Consent & Privacy Record** | Notices shown, consents given, data requests | User |
| **Subscription** | Plan, vehicles billed, status, renewal date, payments | Business |
| **Depot** | Name, location | Business; has vehicles and staff |
| **Quote / Job** | Client, cargo, pickup/delivery windows, price, expected profit, status | Client; has trips |
| **Proof of Delivery** | Photos, delivery note, recipient, signature or code, time, location, shortages/damage | Trip |
| **Inspection** | Checklist results, photos, tyre serials, pass/fail | Vehicle, driver |
| **Work Order** | Issue, type (preventive/corrective), priority, mechanic/supplier, parts, labour, status | Vehicle, inspection, incident |
| **Tyre** | Serial, brand, size, cost, position history, km, tread readings, retreads | Vehicle (current position) |
| **Spare Part / Stock Movement** | Item, quantity, cost, issued to work order | Store, vehicle |
| **Incident** | Type, photos, location, cost, fine, insurance claim status | Vehicle, driver, trip |
| **Lessor / Lender** | Name, contacts, KRA PIN, payment details | Has lease or finance agreements |
| **Lease Agreement** | Direction (in/out), dates, payment model, rates, minimum guarantee, deposit, cost responsibility matrix | Vehicle, lessor |
| **Lease Charge / Offset / Payment** | Period or trip, amount, basis, receipts, M-Pesa code | Lease agreement |
| **Finance Agreement** | Lender, amount, schedule, balance | Vehicle |
| **Driver Score / Behaviour Event** | Event type, time, location, severity, score | Driver, vehicle, trip |
| **Message** | Sender, recipients, text, read receipts | Business, job |

---

## 9. Pricing (SaaS Subscription)

**Model:** monthly subscription, **priced per vehicle**, with tiers aligned to the tracking approaches. Prices below are **proposed starting points** in KES, to be validated with real fleet owners during the pilot.

| Plan | Price per vehicle / month | Best for | Includes |
|---|---|---|---|
| **Starter** | **KES 1,000** | Owner-drivers, small fleets using phones only | Trips, odometer photos, phone GPS tracking, quotes & jobs, proof of delivery, inspections, fuel & expenses, floats & reconciliation, service reminders, clients & debts, **leasing & finance tracking**, basic reports, 2 user roles (Owner, Driver) |
| **Standard** | **KES 1,800** | Fleets with GPS trackers | Everything in Starter + GPS tracker integration, live fleet map, trip replay, geofencing, tamper and idling alerts, driver scorecards, full fraud detection, tyres & parts store, client tracking links, all roles, custom reports, eTIMS invoicing |
| **Premium** | **KES 2,800** | Fleets serious about fuel theft | Everything in Standard + fuel sensor integration, real-time siphoning alerts, remote immobiliser, predictions & learned anomaly models, plain-English questions, scheduled reports, priority support |

### Pricing rules
- **Free trial:** 14 days, full Standard features, no payment details needed.
- **Annual billing:** pay for 10 months, get 12 (about 17% off).
- **Volume discounts:** 11–30 vehicles: 10% off; 31+ vehicles: custom pricing.
- **Mixed fleets allowed**: each vehicle can be on a different plan.
- **Payment:** M-Pesa (Paybill / STK push), card, or bank transfer. Invoices issued via eTIMS.
- **Grace period:** 7 days after a failed payment before the account goes read-only. **Data is never deleted for non-payment without notice** (see retention policy).
- **Lessor portal is free** and doesn't count as a user; the leased vehicle is billed once, on the operator's (lessee's) subscription.
- **Partner programme:** GPS tracker installers who resell FleetTms earn a recurring commission.

### Optional add-ons (usage-based)
| Add-on | Pricing approach |
|---|---|
| SMS bundles (alerts, reminders) | Prepaid bundles at cost + small margin |
| WhatsApp Business API messages | Per message, passed through + margin |
| Payroll with statutory deductions | KES 100 per employee / month |
| Hardware (GPS trackers, fuel sensors) | Through installer partners; FleetTms earns a referral fee or margin |
| Onboarding & data migration | One-off fee for larger fleets |

> **Note:** Kelvin's own transport business runs on FleetTms as the pilot tenant at no charge.

---

## 10. Security Considerations

### Authentication
- **Drivers & turnboys:** phone number + one-time SMS code (no passwords to forget).
- **Owners, managers, supervisors, accountants:** email/phone + password **with two-step verification** (SMS code or authenticator app).
- Session timeouts, device management ("log out all devices"), and immediate access removal when staff leave.

### Data security
- **Strict tenant isolation**: every request is checked against the user's business and role.
- **Encryption** in transit (HTTPS everywhere) and at rest (database, backups, photos).
- Photos stored privately and shown only through short-lived secure links.
- **Immutable audit logs** for all financial and trip records.
- Rate limiting and protection against brute-force login attempts.
- Regular automated **backups** with tested restores, stored in a separate location.
- Secrets (API keys, M-Pesa credentials) kept in a secure vault, never in code.
- Mobile app: offline data stored encrypted on the device and cleared on logout.
- Regular security reviews and dependency updates; penetration test before public launch.
- **Platform Admin access to tenant data** only with the tenant's permission, time-limited and logged.
- **Device integrity checks** on the mobile app (mock location, rooted phones, clock tampering); flagged devices are reported, not silently blocked.
- **Remote immobiliser safeguards:** Owner-only, stationary-only, confirmation step, full audit log.
- **Lessor portal isolation:** lessors see only their own vehicles and only the data their agreement allows.
- **Disaster recovery targets:** lose no more than 15 minutes of data (point-in-time database backups) and be back online within 4 hours; tested at least twice a year.

---

## 11. Legal, Privacy & Data Protection

FleetTms processes personal data (names, phone numbers, ID/licence details, salaries, and **location data of employees**), so compliance with the **Kenya Data Protection Act, 2019 (DPA)** and its regulations is built in from day one, not added later.

> ⚠️ This section is a planning framework, not legal advice. Final Terms, Privacy Policy, and Data Protection Policy should be reviewed by a Kenyan advocate familiar with data protection before public launch.

### 11.1 Roles under the law
| Party | DPA role | Responsibility |
|---|---|---|
| **Kastra Enterprises (FleetTms)** | **Data Controller** for account/subscription data; **Data Processor** for each fleet owner's business data | Registers with the ODPC; secures the platform; processes data only on tenants' instructions |
| **Each fleet owner (tenant)** | **Data Controller** for their staff, clients, and fleet data | Lawful basis for monitoring staff; informing drivers; handling staff data requests |

### 11.2 Compliance requirements built into the plan
1. **ODPC registration**: Kastra Enterprises registers with the Office of the Data Protection Commissioner as controller/processor before commercial launch.
2. **Data Protection Impact Assessment (DPIA)**: required because FleetTms performs **systematic location tracking of employees**. Completed and filed before launch, reviewed when major features are added.
3. **Data Processing Agreement (DPA contract)**: every tenant accepts a processing agreement as part of sign-up, defining what Kastra Enterprises may and may not do with their data.
4. **Lawful basis & transparency for driver monitoring:**
   - Drivers and turnboys see a **clear in-app notice** at first login explaining what is tracked (location, odometer photos, fuel, expenses), why, when, and who sees it, and they acknowledge it.
   - Tracking is limited to **work purposes and working time / active trips**. Phone-based tracking stops when the driver ends the trip or shift.
   - Owners receive a template **employee monitoring notice** to include in employment contracts.
5. **Data minimisation**: only collect what the features need. No contacts, personal photos, or unrelated phone data.
6. **Data subject rights**, supported in-product:
   - Right to be informed, to access, to correct, to delete (where legally allowed), to object, and to data portability.
   - Requests logged and answered within legal timelines; tenants get tools to export or correct a staff member's data.
7. **Consent management**: consent and notice records stored with timestamps; marketing messages only with opt-in.
8. **Data breach response:**
   - Internal incident response plan with named responsibilities.
   - Notify the **ODPC within 72 hours** of becoming aware of a breach likely to cause risk, and notify affected tenants and individuals without undue delay.
   - Breach register kept for every incident.
9. **Cross-border transfers**: data hosted in-region where possible. Any transfer outside Kenya (e.g., cloud hosting, SMS or maps providers) only with appropriate safeguards and disclosure in the Privacy Policy.
10. **Sub-processor list**: published list of third parties (cloud host, SMS, maps, payments), each bound by data protection terms.
11. **Data Protection Officer (or designated contact)**: a named privacy contact at Kastra Enterprises for requests and complaints.
12. **Staff training & access control** within Kastra Enterprises: only authorised people can access production systems.
13. **Driver behaviour scoring & SOS:** covered by the DPIA and the monitoring notice; scores are tools for coaching, and any disciplinary decision needs human review.
14. **Lessors and recipients:** lessors see driver and location data only where the lease allows it and drivers have been informed; delivery recipients' names, signatures, and phone numbers are used only for proof of delivery.
15. **AI features:** plain-English questions and document reading process only the tenant's own data; sub-processors used for AI are disclosed and contractually barred from training on customer data.

### 11.3 Data retention policy (proposed)
| Data | Retention |
|---|---|
| Financial records (invoices, payments, expenses, payroll) | Minimum **5 years** (Kenya tax record-keeping requirements), then deleted or anonymised |
| Raw GPS location points | **12 months**, then summarised into trip totals and the raw points deleted |
| Odometer and receipt photos | **24 months**, or longer if linked to an open dispute or alert |
| Audit logs | **5 years** |
| Former employee data | Kept only as long as required by employment/tax law, then deleted |
| Cancelled tenant accounts | Read-only for **90 days** for export, then permanently deleted (except records the law requires to be kept) |

### 11.4 Terms & Conditions (outline)
1. Acceptance of terms and eligibility (registered business or individual owner, 18+).
2. Description of the service and subscription plans.
3. Account registration, security, and responsibility for users added by the owner.
4. **Fleet owner obligations:** lawful use, informing and obtaining acknowledgement from drivers about monitoring, accuracy of data entered.
5. Acceptable use: no illegal tracking, no tracking of non-employees or private vehicles without consent, no misuse of data.
6. Subscription, billing, free trial, renewals, refunds, late payment, and suspension.
7. Hardware (trackers, sensors): supplied by third parties; FleetTms not liable for hardware faults.
8. **Fraud alerts are indicators, not proof.** Owners must investigate before disciplinary action; FleetTms is not liable for decisions made on alerts.
9. **Leasing:** lease calculations follow the terms the users enter; FleetTms is a record-keeping tool, not a party to lease agreements, and lessor portal access is granted by the operator.
10. **Remote immobiliser:** used at the owner's own risk and only within the platform's safety limits.
11. Data ownership: **the tenant owns their business data**; Kastra Enterprises processes it only to provide the service.
12. Availability, maintenance windows, and support.
13. Intellectual property of the FleetTms platform.
14. Limitation of liability and indemnity.
15. Termination, data export, and deletion.
16. Changes to terms (with advance notice).
17. Governing law (Laws of Kenya) and dispute resolution.
18. Contact information.

### 11.5 Privacy Policy (outline)
1. Who we are (Kastra Enterprises) and how to contact the privacy officer.
2. What personal data we collect: account, staff, driver location, photos, financial, device, and usage data.
3. Why we collect it and the lawful basis for each purpose.
4. How location tracking works, when it is active, and when it stops.
5. Who we share data with (sub-processors, KRA via eTIMS, M-Pesa) and why.
6. Cross-border transfers and safeguards.
7. How long we keep data (retention table).
8. How we protect data (security summary).
9. Your rights under the Kenya Data Protection Act and how to exercise them.
10. Complaints, including the right to complain to the **ODPC**.
11. Cookies and analytics (web).
12. Changes to this policy.

### 11.6 Data Protection Policy (internal, outline)
1. Purpose and scope.
2. Data protection principles (lawfulness, fairness, transparency, purpose limitation, minimisation, accuracy, storage limitation, integrity & confidentiality, accountability).
3. Roles and responsibilities (privacy officer, developers, support staff).
4. Data classification (public, internal, confidential, sensitive).
5. Access control and least privilege.
6. DPIA process for new features.
7. Retention and secure deletion procedures.
8. Breach detection, response, and 72-hour notification process.
9. Handling data subject requests.
10. Vendor / sub-processor due diligence.
11. Training and awareness.
12. Annual review and audit.

### 11.7 Other relevant laws to review
- **Computer Misuse and Cybercrimes Act, 2018**: security of systems and data.
- **Employment Act, 2007**: employee records and fair treatment in disciplinary matters.
- **Tax Procedures Act & eTIMS requirements**: invoicing and record keeping.
- **Consumer Protection Act, 2012**: fair subscription terms.
- **Traffic Act / NTSA rules**: vehicle and driver document compliance features.

---

## 12. Development Phases & Milestones

Web and mobile are built **in parallel, feature by feature**, so each phase delivers something usable on both.

### Phase 0: Foundation (Weeks 1–3)
- Monorepo setup, shared design system, backend skeleton, database.
- Multi-tenancy, authentication (OTP + 2-step), roles & permissions, audit logging, depots, one login for several companies.
- Privacy groundwork: consent/notice records, data processing agreement flow.
- **Legal track (in parallel):** ODPC registration, DPIA draft, T&Cs, Privacy Policy, Data Protection Policy drafted and sent for legal review.

### Phase 1: Core Operations MVP (Weeks 4–13)
- Vehicles (including ownership type), staff, crew assignments, documents & expiry reminders, Excel import.
- Trips with **odometer photo capture** and **pre-trip inspections**.
- Offline mode and sync on mobile; device integrity checks.
- Fuel entries (Paybill), floats, expenses with spend limits and duplicate detection, **daily reconciliation**.
- Service schedules, work orders, owner dashboard, basic reports, owner-driver mode.
- Tyres, spare parts store, incidents, fines, and SOS.
- **Milestone (end of week 11):** Kelvin's own lorries running on FleetTms.

### Phase 2: Jobs, Money & Leasing (Weeks 14–21)
- Clients, quotes, jobs, dispatch calendar, saved routes.
- **Proof of delivery**, billing methods, invoices, axle-load checks.
- M-Pesa payments, debtors, reminders, KRA eTIMS.
- **True cost & profit engine:** asset finance, **leasing (charges, offsets, lessor payments, statements, lessor portal)**, depreciation, cost per km, empty km.
- Suppliers & WhatsApp ordering, payroll.

### Phase 3: Tracking & Fraud Detection (Weeks 22–27)
- Phone GPS tracking, live map, client tracking links.
- GPS trackers, trip replay, geofences, **tamper alerts**, idling & driving behaviour, immobiliser.
- **Fraud & anomaly engine**, driver scorecards, route suggestions, EPRA prices.
- **Milestone:** private beta with 3–5 other fleet owners.

### Phase 4: Premium & SaaS Launch (Weeks 28–35)
- Fuel sensors, siphoning detection, predictions, learned anomaly models, document reading.
- Subscriptions, onboarding, advanced and scheduled reports, plain-English questions, driver messaging.
- Security hardening, disaster recovery test, penetration test, final legal sign-off.
- Store release, partner programme, product analytics.
- **Milestone:** public launch of FleetTms.

### Phase 5: Growth (post-launch)
- WhatsApp Business API, statutory payroll deductions, custom roles, truck-specific routing, Swahili, and the expansion items in Section 14.

> Timelines assume a solo founder working steadily, and are estimates to adjust as the build progresses.

---

## 13. Potential Challenges & Solutions

| Challenge | Solution |
|---|---|
| **Drivers resisting tracking or finding workarounds** | Transparent notices; tracker hardware for higher trust; "going dark" alerts; three-way distance checks; simple driver app so compliance is easy |
| **Poor network coverage on routes** | Offline-first mobile app; trackers buffer data; records keep original capture time |
| **Inaccurate expected fuel consumption** | Owner enters a starting value; system learns real averages per vehicle and load over time |
| **False fraud alerts annoying owners** | Adjustable thresholds; alerts show evidence; "explained" feedback improves accuracy |
| **Many GPS tracker brands and protocols** | Device-agnostic ingestion layer (e.g., Traccar) supporting hundreds of devices |
| **Large volumes of GPS data** | Time-series storage; summarise and delete raw points after 12 months |
| **Maps and SMS costs growing with usage** | Cache routes; batch requests; pass SMS/WhatsApp costs through as add-ons |
| **Data protection compliance** | Privacy-by-design, DPIA, ODPC registration, legal review, retention policy, audit trails |
| **Odometer photos that are blurry or unreadable** | Guided capture frame, quality check before accepting, manual confirmation with flag |
| **Solo founder building web and mobile together** | Shared monorepo and business rules; feature-by-feature phases; launch with own fleet first |
| **Low willingness to pay among small owners** | Low-cost Starter tier; free trial; show money saved (e.g., fuel recovered) in reports |
| **Owner-driver alerts making no sense** | Owner-driver mode adjusts which alerts apply |
| **Lease disputes between operator and lessor** | Agreed terms stored in the system, automatic calculations, offsets with receipts, transparent lessor statements and portal |
| **Many different lease arrangements** | Flexible payment models (time, trip, km, revenue share, profit share, minimum guarantee) plus a cost responsibility matrix |
| **Drivers faking GPS on their phones** | Mock-location, rooted-phone, and clock-change detection; trackers for higher trust |
| **Delivery disputes and short deliveries** | Proof of delivery with photos, recipient code or signature, and GPS stamps |
| **Recipients not wanting to sign on a phone** | Accept a photo of the signed delivery note or a one-time code instead |
| **Immobiliser misuse or accidents** | Owner-only, stationary-only, confirmation step, audit logged |
| **AI answers that are wrong** | Answers always show the underlying numbers and link to the source report |
| **Bigger scope stretching the solo build** | Core money-protecting features first; smart features after the beta |

---

## 14. Future Expansion Possibilities

- **Swahili** (and other languages).
- **Full client portal**: clients request jobs, see all their deliveries, PODs, and invoices, and pay online.
- **Load board / marketplace**: connect fleet owners with clients who need transport, and help fill empty return legs.
- **Fleet leasing marketplace**: connect lorry owners who want to lease out with operators who need vehicles.
- **Fuel station partnerships**: discounted fuel and automatic litre verification.
- **Insurance & financing partners**: better premiums or loans backed by real fleet data.
- **East Africa expansion**: Uganda, Tanzania, Rwanda (multi-currency, local tax and payment integrations).
- **Cross-border trip support**: border documents, transit times, multi-currency expenses.
- **AI assistant actions**: beyond answering questions, drafting quotes, chasing debts, and suggesting which lorry to send.
- **Public API** for large fleets to connect their own systems.

---

## 15. Open Questions to Confirm

1. Validate proposed pricing (KES 1,000 / 1,800 / 2,800 per vehicle) with 5–10 fleet owners.
2. Should odometer capture be per trip, per day, or configurable per business? (Proposed: configurable.)
3. Should statutory payroll deductions be in Phase 2 or later?
4. Preferred GPS tracker and fuel sensor installer partners in Kenya.
5. Hosting location decision (Kenya-based vs African cloud region).
6. Who will serve as the named data protection contact at Kastra Enterprises?
7. Which lease payment models are most common among operators you know (fixed monthly, per trip, or revenue share)?
8. Should lessors be able to see their lorry's live location by default, or only when the agreement says so? (Proposed: only when agreed.)
9. Which trackers will support the remote immobiliser, and should it be offered at launch or after the beta?

---

*End of FleetTms Masterplan v1.1*
