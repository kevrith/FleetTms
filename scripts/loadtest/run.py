"""Load test for the API against a database made by seed.py. It measures, it does not judge: the numbers go in docs/performance.md.

    # the API under test, on its own port, pointed at the load database (same JWT_SECRET as this script)
    cd apps/api && set -a && . ../../.env && set +a
    DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@localhost:5499/fleettms_load RATE_LIMITS_ENABLED=false TRACCAR_FORWARD_KEY=load-test-key-change-me \
        .venv/bin/uvicorn app.main:app --port 8011 &
    DATABASE_URL=... .venv/bin/python ../../scripts/loadtest/run.py --api http://localhost:8011 --seed-json seed.json --db-url postgresql://USER:PASSWORD@localhost:5499/fleettms_load

Three runs: read screens (each endpoint, a number of requests at a given concurrency), GPS ingest at a target rate for a time, and both at once.
"""

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

import httpx
import psycopg
from app.security import create_access_token
from app.tracker_simulator import position

READS = [
    ("live map (every vehicle)", "/map/vehicles"),
    ("vehicles", "/vehicles"),
    ("trips (latest)", "/trips"),
    ("dashboard", "/dashboard"),
    ("profit", "/profit"),
    ("expenses", "/expenses"),
    ("fuel", "/fuel"),
    ("fraud alerts", "/fraud/alerts"),
    ("staff", "/staff"),
    ("audit trail", "/audit"),
    ("scorecards", "/scorecards"),
    ("report: profit", "/report-catalog/profit"),
    ("report: fuel efficiency", "/report-catalog/fuel_efficiency"),
]


# What people have open all day: these are measured while positions are arriving. The heavy reports are not (see the read run).
EVERYDAY = {"live map (every vehicle)", "vehicles", "trips (latest)", "expenses", "staff", "fraud alerts"}


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))] if ordered else 0.0


async def timed(client: httpx.AsyncClient, method: str, url: str, **kw) -> tuple[float, int]:
    started = time.perf_counter()
    try:
        res = await client.request(method, url, **kw)
        return (time.perf_counter() - started) * 1000, res.status_code
    except httpx.HTTPError:
        return (time.perf_counter() - started) * 1000, 0


async def read_run(client: httpx.AsyncClient, headers: dict, n: int, concurrency: int, trip_id: str, only: set[str] | None = None) -> list[dict]:
    out = []
    targets = [t for t in [*READS, ("one trip's replay", f"/trips/{trip_id}/replay")] if only is None or t[0] in only]
    for name, path in targets:
        sem = asyncio.Semaphore(concurrency)
        latencies: list[float] = []
        codes: dict[int, int] = {}

        async def one(path=path, sem=sem, latencies=latencies, codes=codes):
            async with sem:
                ms, code = await timed(client, "GET", path, headers=headers)
                latencies.append(ms)
                codes[code] = codes.get(code, 0) + 1

        started = time.perf_counter()
        await asyncio.gather(*[one() for _ in range(n)])
        wall = time.perf_counter() - started
        out.append({"name": name, "path": path, "requests": n, "concurrency": concurrency, "p50_ms": round(pct(latencies, 0.5)), "p95_ms": round(pct(latencies, 0.95)), "max_ms": round(max(latencies)), "rps": round(n / wall, 1), "status": codes})
    return out


async def ingest_run(client: httpx.AsyncClient, key: str, imeis: list[str], rate: int, seconds: int) -> dict:
    """Posts tracker positions at `rate` a second, spread over every device, for `seconds`."""
    latencies: list[float] = []
    codes: dict[int, int] = {}
    interval = 1 / rate
    started = time.perf_counter()
    tasks = []
    sem = asyncio.Semaphore(200)
    where = {i: (-1.29 + random.random() / 10, 36.8 + random.random() / 10) for i in imeis}

    async def send(imei: str, k: int):
        async with sem:
            la, ln = where[imei]
            where[imei] = (la + 0.0005, ln + 0.0005)
            body = position(imei, datetime.now(UTC), *where[imei], speed_kmh=60)
            ms, code = await timed(client, "POST", f"/hooks/traccar/{key}", json=body)
            latencies.append(ms)
            codes[code] = codes.get(code, 0) + 1

    k = 0
    while time.perf_counter() - started < seconds:
        tasks.append(asyncio.create_task(send(imeis[k % len(imeis)], k)))
        k += 1
        await asyncio.sleep(max(0, started + k * interval - time.perf_counter()))
    await asyncio.gather(*tasks)
    wall = time.perf_counter() - started
    return {"target_per_s": rate, "seconds": seconds, "sent": k, "achieved_per_s": round(k / wall, 1), "p50_ms": round(pct(latencies, 0.5)), "p95_ms": round(pct(latencies, 0.95)), "max_ms": round(max(latencies)), "status": codes}


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", required=True)
    p.add_argument("--seed-json", required=True)
    p.add_argument("--db-url", required=True)
    p.add_argument("--key", default="load-test-key-change-me", help="TRACCAR_FORWARD_KEY the API under test was started with")
    p.add_argument("--reads", type=int, default=60)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--mixed-reads", type=int, default=10, help="requests for each everyday screen while ingesting")
    p.add_argument("--rate", type=int, default=100, help="tracker positions a second")
    p.add_argument("--seconds", type=int, default=30)
    p.add_argument("--out")
    args = p.parse_args()
    seed = json.loads(Path(args.seed_json).read_text())
    if "load" not in args.db_url and "drill" not in args.db_url:
        sys.exit("Refusing: the database name must contain 'load' or 'drill'.")

    with psycopg.connect(args.db_url) as conn, conn.cursor() as cur:
        vehicles = [r[0] for r in cur.execute("SELECT id FROM vehicles WHERE business_id = %s", (seed["business_id"],)).fetchall()]
        have = {r[0] for r in cur.execute("SELECT imei FROM tracker_devices").fetchall()}
        imeis = [f"3569{i:011d}" for i in range(len(vehicles))]
        missing = [{"vehicle_id": v, "imei": i, "business_id": uuid.UUID(seed["business_id"])} for v, i in zip(vehicles, imeis, strict=True) if i not in have]
        if missing:  # through the model's own table, so every default a tracker needs is filled in
            from app.models import Base
            from sqlalchemy import create_engine, insert

            with create_engine(args.db_url.replace("postgresql://", "postgresql+psycopg://")).begin() as db:
                db.execute(insert(Base.metadata.tables["tracker_devices"]), missing)
        trip_id = cur.execute("SELECT id FROM trips WHERE business_id = %s ORDER BY started_at DESC LIMIT 1", (seed["business_id"],)).fetchone()[0]
        conn.commit()
        before = cur.execute("SELECT count(*) FROM location_points WHERE source = 'tracker'").fetchone()[0]

    token = create_access_token(uuid.UUID(seed["owner_user_id"]), uuid.UUID(seed["session_id"]))
    headers = {"Authorization": f"Bearer {token}"}
    report: dict = {"seed": {k: v for k, v in seed.items() if k not in ("session_id", "owner_user_id", "vehicle_ids")}}
    async with httpx.AsyncClient(base_url=args.api, timeout=120, limits=httpx.Limits(max_connections=300)) as client:
        warm = await timed(client, "GET", "/map/vehicles", headers=headers)
        report["warmup"] = {"status": warm[1]}
        def save():  # after every phase, so a run that is stopped early still leaves what it measured
            if args.out:
                Path(args.out).write_text(json.dumps(report, indent=1, default=str))

        print("-- reads", flush=True)
        report["reads"] = await read_run(client, headers, args.reads, args.concurrency, str(trip_id))
        save()
        print("-- ingest", flush=True)
        report["ingest"] = await ingest_run(client, args.key, imeis, args.rate, args.seconds)
        save()
        print("-- the everyday screens while ingesting", flush=True)
        ingest = asyncio.create_task(ingest_run(client, args.key, imeis, args.rate, args.seconds))
        await asyncio.sleep(2)
        mixed_reads = await read_run(client, headers, args.mixed_reads, args.concurrency, str(trip_id), only=EVERYDAY)
        report["mixed"] = {"ingest": await ingest, "reads": mixed_reads}
        save()
    with psycopg.connect(args.db_url) as conn:
        after = conn.execute("SELECT count(*) FROM location_points WHERE source = 'tracker'").fetchone()[0]
    report["stored_tracker_points"] = after - before
    text = json.dumps(report, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
