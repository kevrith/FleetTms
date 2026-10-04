# Performance (Sprint 16)

How fast the system is with a large customer and live GPS, what was slow, what was fixed, and what is still slow. Everything here was measured; what was not measured is said so.

## The test

`scripts/loadtest/seed.py` builds a simulated large customer in a scratch database; `scripts/loadtest/run.py` measures the API against it. It refuses any database whose name does not contain "load" or "drill".

| | |
|---|---|
| Customer | 1 business, 300 vehicles, 300 drivers, 10 managers, 40 clients |
| History | 12,000 trips over 90 days, 24,000 fuel entries, 36,000 expenses |
| GPS | 1,998,000 points (one a minute along each trip), a TimescaleDB hypertable |
| Database | 971 MB |
| Machine | A 20-core development PC. The database, the API, the load generator and the browser all ran on it, so the numbers are indicative, not a production forecast. Other work (another session's tests) was sometimes running on the same machine. |
| What is measured | The API only: no browser, no map drawing, no phone, no network latency |
| Readers | 5 at a time, 15 requests per screen |
| GPS | 100 tracker positions a second for 20 seconds (6,000 a minute: about 300 lorries each reporting every 3 seconds) through the real tracker webhook |

## What was slow, and what was done

**Driver scorecards: 45 seconds, 13,055 queries.** Each of 300 drivers read its own rows one query at a time, and each trip re-read its vehicle's whole fuel history. Now the rows for all drivers are read in a few queries and each vehicle's history is read once. **3.4 seconds, 18 queries, and the output is identical** (compared field by field on all 300 drivers). Over HTTP the old version took 76 seconds.

**Live map: the "latest position of each vehicle" query scanned every point of the last 30 days** (650,000 here; over 13 million for a fleet reporting every minute). Now one index lookup per vehicle. **547 ms to 31 ms, identical result,** and the cost now follows the number of vehicles, not the number of points.

**Missing indexes** on the date ranges the dashboard, reports and scorecards use: fuel by date, expenses by date, trips by start and by end, behaviour events by driver and time, and the audit trail by business and time (migration 0021). On this size, narrow-range queries went from 1.6 to 3.0 ms to 0.09 to 0.18 ms, now index-only scans. At 24,000 rows the saving is small in absolute terms; it grows with the table.

**The profit engine read every trip, odometer reading, job and invoice ever recorded**, whatever months were asked for, so it would get slower for ever. It now reads only the months asked for. The output is identical. **No speed-up was measured**, because in this test all the data is inside the window; the benefit is for a business with years of history, and is not measured.

## Results with the final code

One API process:

| Screen | median | slowest of 15 |
|---|---|---|
| Vehicles | 102 ms | 242 ms |
| Expenses, fuel, audit trail | 46 to 60 ms | 80 to 133 ms |
| Staff, fraud alerts | 182 to 202 ms | 290 to 411 ms |
| Live map (300 vehicles) | 393 ms | 623 ms |
| One trip's replay | 172 ms | 442 ms |
| Trips (a page of 50) | 1.2 s | 1.5 s |
| Fuel efficiency report | 3.5 s | 8.1 s |
| Dashboard | 10.3 s | 17.7 s |
| Profit | 6.0 s | 9.1 s |
| Profit report | 8.7 s | 18.2 s |
| Driver scorecards | 8.4 s | 120 s (one request waited behind the others) |

Four API processes:

| Screen | median | slowest of 15 |
|---|---|---|
| Vehicles | 60 ms | 113 ms |
| Live map | 235 ms | 701 ms |
| Trips (a page of 50) | 1.1 s | 1.9 s |
| Dashboard | 5.2 s | 7.6 s |
| Profit | 3.5 s | 4.4 s |
| Driver scorecards | 4.6 s | 13 s |
| Profit report | 4.5 s | 10.3 s |

For one reader and one process (no queueing), in the API: scorecards 3.4 s, dashboard 3.5 s, profit 2.7 s, profit report 2.8 s.

**GPS ingest** (100 positions a second, 20 seconds, every one stored, no errors):

| | achieved | median | 95th percentile | slowest |
|---|---|---|---|---|
| One process, nobody reading | 99.9/s | 70 ms | 764 ms | 2.9 s |
| Four processes, nobody reading | 99.9/s | 21 ms | 28 ms | 37 ms |
| One process, six everyday screens being read | 80/s | 418 ms | 6.7 s | 17 s |
| Four processes, six everyday screens being read | 100/s | 22 ms | 369 ms | 1.1 s |

## What this says

- **Run at least four API processes** (`uvicorn --workers 4`, or one per core up to a point). The API is one event loop per process, and the heavy reports are CPU-bound Python, so on one process a dashboard request holds up every tracker post and every other screen behind it. With four, ingest keeps its pace while people read.
- **The light screens are fine** (under 0.4 s at the median) even for 300 vehicles. **The heavy reports are not quick** at this size: 3 to 5 seconds a request for the dashboard, profit, scorecards and the profit report, because they read tens of thousands of rows and compute in Python. They are acceptable one at a time and poor when several people open them together.
- **100 tracker positions a second is comfortable**, and well above what 300 lorries send if each reports every 10 to 30 seconds (10 to 30 a second).

## Still slow, and what to do next

1. **Dashboard, profit, scorecards and the profit report**: cache each business's result for a minute or two (it is the same for everyone with the same permissions), or compute them in the worker and show the last result with its time. Reading rows as plain tuples instead of objects would help too. This is the biggest remaining win.
2. **Trips list**: still about five queries per row (255 for a page of 50). A page loads in about a second; batching `trip_out` would remove most of it. It was left alone because that function is used across the API.
3. **Map**: the other tables it reads (people, depots, devices, gaps) are read whole; fine now, worth a look beyond a few hundred vehicles.
4. **A "last position" table** updated on each point would make the map independent of the size of the points table. Not needed yet.
5. **Not measured:** ten times this size; more than five readers; a real browser drawing 300 markers; the phone's own sync load; the time to build the data copy for an owner with years of history.

## Reproducing it

```
# a scratch database with the app's migrations, then:
cd apps/api && set -a && . ../../.env && set +a
.venv/bin/python ../../scripts/loadtest/seed.py --url postgresql://USER:PASSWORD@localhost:PORT/fleettms_load --vehicles 300 --points 2000000 > seed.json
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@localhost:PORT/fleettms_load RATE_LIMITS_ENABLED=false TRACCAR_FORWARD_KEY=load-test-key-change-me \
  .venv/bin/uvicorn app.main:app --port 8011 --workers 4 &
.venv/bin/python ../../scripts/loadtest/run.py --api http://localhost:8011 --seed-json seed.json --db-url postgresql://USER:PASSWORD@localhost:PORT/fleettms_load --out result.json
```
