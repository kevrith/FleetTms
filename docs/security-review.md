# Security review (Sprint 16)

What was reviewed, what was found, what was fixed, and what is still open. Written to be read by the person commissioning the external penetration test and by the advocate. Nothing here replaces the penetration test, which has not been done.

## How it was reviewed

The brief was: audit the codebase for tenant isolation gaps, permission gaps, unlogged sensitive changes, secrets and personal data in logs, and prioritise fixes. Each question was turned into a test that stays in the suite, so the review keeps being true after today. The standing tests are in `apps/api/tests/test_security_audit.py`, `test_tenant_sweep.py`, `test_rate_limits.py` and `test_permissions.py`; each one fails the build when someone adds a table, route or log line that has not been thought about.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | No rate limit on anything the internet can reach: sign-in, sign-up, one-time codes, quick sign-in, token refresh, invitation acceptance, tracking links, photo links, and the secret-key webhooks. Only per-account lockouts existed. | High | **Fixed.** Per-address limits in Redis on each (login 20/min, codes 10/min, sign-up 5/hour, tracking links 120/min, photo links 300/min), an address that keeps sending a wrong webhook key is shut out for ten minutes, and a backstop of 1,200 requests a minute per address. The limiter fails open if Redis is down, so a Redis outage cannot lock every driver out; the account lockouts still apply. Behind a proxy the real address is believed only when `TRUST_PROXY_HEADERS` says a proxy you control sets it. |
| 2 | One-time codes: a phone number could be texted a code every 60 seconds for ever (SMS cost, and harassment of the person who owns the number). | Medium | **Fixed.** At most 5 codes an hour to any number, applied before the number is looked up, so it also reveals nothing about who is registered. |
| 3 | No security headers on responses (content-type sniffing, framing, referrer leakage, caching of answers that hold a business's data). | Medium | **Fixed.** `nosniff`, `DENY` framing, no referrer, a permissions policy, `no-store`, and HSTS when `ENVIRONMENT=production`. Routes that set their own headers keep them. |
| 4 | No ceiling on the size of a request body other than the photo and import limits. | Low | **Fixed.** Anything declaring more than 12 MB is refused before it is read. |
| 5 | The API would start in production with development settings: a short or missing JWT secret, CORS open to localhost, plan limits and billing switched off, the AI test stand-ins, or text messages going to the in-memory stand-in. | High | **Fixed.** `ENVIRONMENT=production` refuses to start and lists each problem. |
| 6 | Changes that left no audit entry: editing a part, editing a supplier order, recalculating payroll, **accepting an invitation (which sets a password)**, and the setup guide creating a client and a route. | Medium | **Fixed.** All now audited with before and after where it applies. A standing test lists every route that changes something and fails unless it audits, or is on a short list of routes with a written reason (a machine feed whose rows are themselves the record, a code request, and so on). |
| 7 | A raw email address was written to a log line by the report sender used in development and tests. | Low | **Fixed.** Masked. A standing test fails the build if any log call names a phone, email, password, token, code or location outside a masking function or a development-only branch. |
| 8 | Two routes shared one address: the platform console's customer list and the support-access list of businesses by name. The console's richer list silently replaced the names-only one. Found by an existing Sprint 1 test. | Medium | **Fixed.** The console list moved to `/platform/customers`. A check that no two routes share a method and path now runs. |
| 9 | **There is no real SMS sender.** Sign-in codes for drivers, payment reminders and every alert go to an in-memory stand-in. Drivers could not sign in on a live system. | Launch blocker | **Open.** The production startup check now refuses to run while the stand-in is in use. Sprint 17 must add a gateway and list it as a sub-processor. |
| 10 | Dependencies. `pip-audit` on the 56 pinned Python packages: **no known vulnerabilities.** `pnpm audit`: 39 (1 critical, 27 high, 11 moderate). All but two are inside the Expo command-line toolchain used on a developer's machine to build the phone app (`tar`, `xmldom`, `postcss`, `braces`, `image-size`, `node-forge`, `uuid`), which is not shipped in the app. | Medium | **Accepted, to be revisited.** The two that ship are `react-router` (open redirect through a backslash in a link target, and constructor injection when loading server-rendered errors). Both need a link target an attacker controls, or server rendering; this web app does neither (every navigation target is a fixed string or an internal id, and it uses no data router). The fix is only in version 7, a major upgrade scheduled for its own change. The build-tool findings should be cleared with `pnpm.overrides` before the first store build. |
| 11 | `bandit` static analysis of the 19,000 lines of API code. | n/a | **No medium or high findings.** |

## Reviewed and found sound (kept honest by standing tests)

- **Tenant isolation.** All 94 tables that belong to a business are filtered by it on every read, whatever the query looks like (a plain select, a count that names only the table, an alias, a single column, and the new window and lateral queries); the six that are not are named with the reason. A second business asking for the first one's records by id on every route that takes one id (GET and DELETE, over 1,000 requests) got none, and deleted none. Only eleven named files may switch the filter off, and no hand-written SQL reads business data. I checked that these tests can fail: removing the filter, or only for one model, makes them fail.
- **Permissions.** 313 routes need a permission, 19 need a platform admin, 15 need only to be signed in (each explained), 7 are for finishing sign-in, 15 are public (each with what protects it). The role matrix is tested for every role against a representative route of each permission. A new route that is none of these fails the build.
- **Lessor and workshop.** A lessor reaches only the portal routes, and within them only their own leases: another lessor's lease, statement and PDF answer "not found", and every other part of the business answers "forbidden" (existing tests). The workshop role holds the workshop, parts and supplier permissions and nothing financial (role matrix).
- **Secrets.** No secret shaped like a key, token or private key is in a tracked file; no `.env` is tracked; test keys are generated. A scan runs in the suite.

## Not done, and why

- **External penetration test.** Needs an outside party. A brief follows. The sprint's acceptance ("no critical or high findings open") cannot be claimed until it is done and fixed.
- **Row-level security in PostgreSQL.** Tenant isolation is enforced in the application and verified broadly (above), but a mistake there would be the only barrier. Row-level security would add a second one inside the database: policies on all 93 tables keyed on a per-transaction setting, with the application connecting as a role that cannot bypass them and the few cross-business jobs opting in. It is a day or two of careful work and touches every test, so it has not been started here. Recommended before launch; the decision is the owner's.
- **Spreadsheet imports** read an untrusted `.xlsx` (capped at 5 MB and 2,000 rows). Whether the parser is safe against a decompression bomb has not been tested.
- **Mobile.** No certificate pinning. Offline data is encrypted and cleared on sign-out (Sprint 4); rooted or mock-location phones are flagged, not blocked (by design).
- **Secrets storage in production** is environment variables; a secret manager is a hosting decision for Sprint 17. Rotating `JWT_SECRET` signs everyone out and changes every payment-callback and tracker address (re-register them).
- **Account lockout** can be used to lock someone else out for 15 minutes. Accepted: the alternative is guessable passwords.

## Brief for the external penetration test

**Targets.** The API (`/openapi.json` lists every route), the web app, and the Android app, on a staging deployment with its own data. No production, no real customers, no real M-Pesa or KRA calls.

**Accounts to provide.** Two businesses, each with an owner, a manager, a driver and a turnboy; a lessor on one of them; a workshop user; a platform admin.

**What we most want tried.**
1. Reading or changing one business's data as a user of another (every id in every URL, and ids inside request bodies and in lists such as `membership_ids`).
2. Raising privileges: a driver doing a manager's work, a manager doing the owner's (payroll, subscription, deleting data, support access), a lessor seeing anything beyond their lease.
3. Taking over accounts: invitation links, one-time codes, quick sign-in PIN and device secret, refresh-token reuse, two-step bypass, and the lockout.
4. Forging machine inputs: M-Pesa callbacks, the tracker forwarder, the subscription callback (a payment marked paid without being paid).
5. Signed links: photo links and client tracking links (tampering, reuse after expiry, guessing).
6. Uploads: photos, spreadsheets, and the receipt and certificate reader.
7. Rate-limit and lockout bypass; abusing the AI question feature to read other businesses' data or run up cost.
8. The phone app: local storage, token handling, intercepting traffic, the offline queue.

**Out of scope.** Denial of service, social engineering of staff, physical attacks, third parties (Safaricom, KRA, cloud providers).

**Rules.** Test only the staging environment; report findings as found; no data leaves the environment. We commit to fixing critical and high findings and retesting before launch.
