"""Seeded scenarios for the fraud engine: a vehicle with a history of ordinary trips, and a trip run through the API that either behaves
or does one particular dishonest thing. Used by test_fraud.py."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app import fraud
from app.models import BehaviourEvent, FuelEntry, Trip, TripStatus
from tests.helpers import bearer
from tests.leasing import in_db
from tests.shots import fleet, inspect, make_trip, start
from tests.test_dashboard import finish_trip
from tests.test_tracking import send

ROUTE = ("Mombasa", "Nairobi")


async def seeded(client, *, history=3, km=1000, litres=300, origin=ROUTE[0], destination=ROUTE[1]):
    """A fleet whose vehicle has already done `history` trips of `km` kilometres on `litres` of fuel (0.3 litres a kilometre)."""
    f = await fleet(client)
    vehicle_id = uuid.UUID(f.vehicle["id"])
    driver_id = uuid.UUID(f.ids["+254712345678"])

    async def go(db):
        for n in range(history):
            began = datetime.now(UTC) - timedelta(days=20 + n)
            trip = Trip(vehicle_id=vehicle_id, driver_membership_id=driver_id, status=TripStatus.COMPLETED, origin=origin, destination=destination, started_at=began, ended_at=began + timedelta(hours=14), distance_km=km)
            db.add(trip)
            await db.flush()
            db.add(FuelEntry(vehicle_id=vehicle_id, trip_id=trip.id, litres=litres, price_per_litre_cents=18000, amount_cents=litres * 18000, captured_at=began + timedelta(hours=2)))

    await in_db(go)
    return f


async def started(client, f, hours_ago=0.5):
    """A trip that began `hours_ago` hours back (so a long drive fits between then and now), starting from the vehicle's odometer."""
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    trip = await make_trip(client, f)
    odometer = (await client.get(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner))).json()["odometer_km"]
    assert (await start(client, f.driver, trip["id"], value=max(125100, odometer))).status_code == 200
    seen = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()
    moved = datetime.fromisoformat(seen["started_at"]) - timedelta(hours=hours_ago)

    async def back_then(db):
        await db.execute(update(Trip).where(Trip.id == uuid.UUID(trip["id"])).values(started_at=moved))

    await in_db(back_then)
    return {**seen, "started_at": moved.isoformat(), "start_km": max(125100, odometer)}


async def drive(client, f, *, litres=None, km=1000, end=None, phone_km=None, idle_minutes=0):
    """Runs a trip from start to finish. The odometer reads `km` more than at the start (or `end`); fuel is bought for the trip when
    `litres` is given; `phone_km` makes the phone report a drive of about that long (so the GPS has something to say); idling is
    recorded as the tracker would. Returns the trip."""
    trip = await started(client, f, hours_ago=max(0.5, (phone_km or 0) / 50))
    if litres:
        res = await client.post("/fuel", headers=bearer(f.driver), json={"vehicle_id": f.vehicle["id"], "trip_id": trip["id"], "litres": str(litres), "price_per_litre_cents": 18000, "amount_cents": int(litres * 18000)})
        assert res.status_code == 201, res.text
    if phone_km:
        n = max(int(phone_km / 15), 3)
        base = datetime.fromisoformat(trip["started_at"])
        step = (datetime.now(UTC) - base - timedelta(minutes=2)).total_seconds() / n
        fixes = [{"recorded_at": (base + timedelta(seconds=1 + i * step)).isoformat(), "lat": -4.0 + i * (phone_km / n / 111.2), "lng": 39.0, "speed_kmh": 60, "accuracy_m": 5} for i in range(n + 1)]
        assert (await send(client, f.driver, trip, fixes)).status_code == 200
    if idle_minutes:

        async def go(db):
            began = datetime.fromisoformat(trip["started_at"]) + timedelta(minutes=5)
            db.add(BehaviourEvent(vehicle_id=uuid.UUID(f.vehicle["id"]), driver_membership_id=uuid.UUID(f.ids["+254712345678"]), trip_id=uuid.UUID(trip["id"]), kind="idling", at=began, ended_at=began + timedelta(minutes=idle_minutes), value=idle_minutes, source="tracker"))

        await in_db(go)
    await finish_trip(client, f, trip, end=end if end is not None else trip["start_km"] + km)
    return trip


async def sweep():
    return await in_db(lambda db: fraud.sweep(db))


async def open_alerts(client, who, **params):
    res = await client.get("/fraud/alerts", params=params, headers=bearer(who))
    assert res.status_code == 200, res.text
    return res.json()


def by_kind(alerts):
    return {a["kind"]: a for a in alerts}

