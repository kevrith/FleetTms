"""Seeds a large simulated fleet into a database, for load tests and restore drills.

    cd apps/api && set -a && . ../../.env && set +a
    .venv/bin/python ../../scripts/loadtest/seed.py --url postgresql://USER:PASSWORD@localhost:5499/fleettms_load --vehicles 300 --points 2000000

It never touches anything whose database name does not contain "load" or "drill". Run the migrations on that database first. What it
makes is a business like the biggest customers we expect: one owner, some managers, a driver for every lorry, clients, trips over the last
90 days with fuel and expenses, and GPS points as the drivers' phones would have sent them. The numbers are random but fixed by --seed.
It prints what it made as JSON, including the id of an owner session that the load test uses to sign in without a password.
"""

import argparse
import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

import psycopg
from app.models import Base
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import make_url

T = Base.metadata.tables
CHUNK = 5000
TOWNS = [("Mombasa", -4.04, 39.67), ("Nairobi", -1.29, 36.82), ("Nakuru", -0.30, 36.07), ("Kisumu", -0.09, 34.77), ("Eldoret", 0.51, 35.27), ("Malaba", 0.64, 34.28)]


def chunks(rows):
    for i in range(0, len(rows), CHUNK):
        yield rows[i : i + CHUNK]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="postgresql://USER:PASSWORD@HOST:PORT/DATABASE")
    p.add_argument("--vehicles", type=int, default=300)
    p.add_argument("--trips-per-vehicle", type=int, default=40)
    p.add_argument("--points", type=int, default=2_000_000)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    url = make_url(args.url)
    if not any(w in (url.database or "") for w in ("load", "drill")):
        sys.exit("Refusing: the database name must contain 'load' or 'drill'.")
    rng = random.Random(args.seed)
    now = datetime.now(UTC)
    engine = create_engine(url.set(drivername="postgresql+psycopg"))
    ids = lambda n: [uuid.UUID(int=rng.getrandbits(128), version=4) for _ in range(n)]

    business_id, owner_id, session_id = ids(3)
    vehicles, drivers = ids(args.vehicles), ids(args.vehicles)
    driver_members = ids(args.vehicles)
    managers, manager_members = ids(10), ids(10)
    owner_member = uuid.UUID(int=rng.getrandbits(128), version=4)
    clients = ids(40)
    trips = ids(args.vehicles * args.trips_per_vehicle)

    with engine.begin() as db:
        db.execute(insert(T["businesses"]).values(id=business_id, name="Load Test Haulage", complimentary=True))
        db.execute(insert(T["users"]).values(id=owner_id, name="Load Owner", email="owner@load.test", totp_enabled=True))
        db.execute(insert(T["memberships"]).values(id=owner_member, user_id=owner_id, business_id=business_id))
        db.execute(insert(T["role_assignments"]).values(membership_id=owner_member, role="owner", business_id=business_id))
        db.execute(insert(T["sessions"]).values(id=session_id, user_id=owner_id, business_id=business_id, refresh_hash="x" * 64, mfa_verified=True, expires_at=now + timedelta(days=2)))
        db.execute(insert(T["users"]), [{"id": u, "name": f"Manager {i}", "email": f"m{i}@load.test"} for i, u in enumerate(managers)])
        db.execute(insert(T["memberships"]), [{"id": m, "user_id": u, "business_id": business_id} for m, u in zip(manager_members, managers, strict=True)])
        db.execute(insert(T["role_assignments"]), [{"membership_id": m, "role": "manager", "business_id": business_id} for m in manager_members])
        db.execute(insert(T["users"]), [{"id": u, "name": f"Driver {i}", "phone": f"+2547{i:08d}"} for i, u in enumerate(drivers)])
        db.execute(insert(T["memberships"]), [{"id": m, "user_id": u, "business_id": business_id} for m, u in zip(driver_members, drivers, strict=True)])
        db.execute(insert(T["role_assignments"]), [{"membership_id": m, "role": "driver", "business_id": business_id} for m in driver_members])
        db.execute(insert(T["vehicles"]), [{"id": v, "registration": f"K{chr(65 + i % 26)}{chr(65 + i // 26 % 26)} {100 + i}X", "make": "Isuzu", "model": "FVZ", "business_id": business_id, "odometer_km": rng.randint(50_000, 600_000), "capacity_tonnes": 30, "tank_litres": 400} for i, v in enumerate(vehicles)])
        db.execute(insert(T["clients"]), [{"id": c, "name": f"Client {i} Ltd", "business_id": business_id} for i, c in enumerate(clients)])

        trip_rows, fuel_rows, expense_rows, windows = [], [], [], []
        for i, trip in enumerate(trips):
            v = i % args.vehicles
            start = now - timedelta(days=rng.randint(1, 89), hours=rng.randint(0, 20)) + timedelta(microseconds=i)  # unique, so two trips of one lorry never share a GPS timestamp
            end = start + timedelta(hours=rng.randint(8, 30))
            origin, dest = rng.sample(TOWNS, 2)
            windows.append((trip, vehicles[v], drivers[v], start, end, origin))
            trip_rows.append({"id": trip, "vehicle_id": vehicles[v], "driver_membership_id": driver_members[v], "status": "completed", "origin": origin[0], "destination": dest[0], "started_at": start, "ended_at": end, "delivered_at": end - timedelta(hours=1), "distance_km": rng.randint(300, 900), "created_at": start - timedelta(hours=1), "business_id": business_id})
            for _ in range(2):
                litres = rng.randint(120, 300)
                fuel_rows.append({"id": uuid.UUID(int=rng.getrandbits(128), version=4), "vehicle_id": vehicles[v], "trip_id": trip, "litres": litres, "price_per_litre_cents": 18_500, "amount_cents": litres * 18_500, "station": "Total", "captured_at": start + timedelta(hours=rng.randint(1, 8)), "business_id": business_id})
            for _ in range(3):
                expense_rows.append({"id": uuid.UUID(int=rng.getrandbits(128), version=4), "vehicle_id": vehicles[v], "trip_id": trip, "driver_membership_id": driver_members[v], "category": rng.choice(["toll", "parking", "food", "repair"]), "amount_cents": rng.randint(20_000, 400_000), "spent_at": start + timedelta(hours=rng.randint(1, 20)), "business_id": business_id})
        for table, rows in (("trips", trip_rows), ("fuel_entries", fuel_rows), ("expenses", expense_rows)):
            for part in chunks(rows):
                db.execute(insert(T[table]), part)

    # GPS points: one a minute along each trip, as a phone would send them, copied in because there are millions.
    per_trip = max(1, args.points // len(trips))
    written = 0
    with psycopg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False)) as conn, conn.cursor() as cur:
        with cur.copy("COPY location_points (id, recorded_at, received_at, business_id, vehicle_id, trip_id, user_id, lat, lng, speed_kmh, source) FROM STDIN") as copy:
            for trip, vehicle, driver, start, _end, origin in windows:
                lat, lng = origin[1], origin[2]
                for k in range(per_trip):
                    lat += rng.uniform(-0.004, 0.006)
                    lng += rng.uniform(-0.004, 0.006)
                    copy.write_row((uuid.UUID(int=rng.getrandbits(128), version=4), start + timedelta(minutes=k), start + timedelta(minutes=k, seconds=5), business_id, vehicle, trip, driver, round(lat, 5), round(lng, 5), round(rng.uniform(0, 90), 1), "phone"))
                    written += 1
        conn.commit()
        cur.execute("ANALYZE")
        conn.commit()
    print(json.dumps({"business_id": str(business_id), "owner_user_id": str(owner_id), "session_id": str(session_id), "vehicles": args.vehicles, "trips": len(trips), "fuel_entries": len(fuel_rows), "expenses": len(expense_rows), "location_points": written, "vehicle_ids": [str(v) for v in vehicles[:5]]}))


if __name__ == "__main__":
    main()
