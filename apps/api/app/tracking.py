"""Phone GPS (masterplan 5.3, 11.2). A crew's phone reports the lorry's position during a trip, and only during a trip: the server
refuses any fix from before the trip started or after it ended, so tracking provably stops when the work does. Points are
stored once per vehicle and moment; a resend changes nothing. When a trip ends (or late points arrive for an ended trip) the
distance the GPS saw is worked out and compared with the odometer."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import behaviour, fraud, geofences
from app.gps_rules import good_fix, path_distance_km, three_way
from app.models import LocationPoint, TrackingGap, Trip, TripStatus, Vehicle
from app.tenancy import current_business_id

CLOCK_SLACK = timedelta(minutes=2)  # a phone's clock may run a little fast
START_SLACK = timedelta(minutes=2)  # the first fix may be taken just before the odometer photo is submitted


class TrackingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class IngestResult:
    accepted: int = 0
    duplicate: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    def reject(self, why: str) -> None:
        self.rejected[why] = self.rejected.get(why, 0) + 1


async def ingest(db: AsyncSession, trip: Trip, user_id: uuid.UUID | None, points: list[dict], *, now: datetime | None = None) -> IngestResult:
    """Stores a phone's batch of fixes for a trip. Fixes outside the trip's working time are refused, not stored."""
    now = now or datetime.now(UTC)
    if trip.status in (TripStatus.SCHEDULED, TripStatus.CANCELLED) or trip.started_at is None:
        raise TrackingError("not_tracking", "Location is only recorded while a trip is running.")
    lower = trip.started_at - START_SLACK
    result = IngestResult()
    rows: dict[datetime, dict] = {}
    for p in points:
        at = p["recorded_at"]
        if not good_fix(p["lat"], p["lng"], None):
            result.reject("bad_fix")
        elif at < lower:
            result.reject("before_trip_start")
        elif trip.ended_at is not None and at > trip.ended_at:
            result.reject("after_trip_end")  # tracking stops when the trip does
        elif at > now + CLOCK_SLACK:
            result.reject("in_the_future")
        elif at in rows:
            result.duplicate += 1
        else:
            rows[at] = {
                "id": uuid.uuid4(), "business_id": current_business_id.get(), "recorded_at": at, "vehicle_id": trip.vehicle_id, "trip_id": trip.id, "user_id": user_id,
                "lat": p["lat"], "lng": p["lng"], "speed_kmh": p.get("speed_kmh"), "heading": p.get("heading"), "accuracy_m": p.get("accuracy_m"), "source": "phone", "received_at": now,
            }  # fmt: skip
    if rows:
        stored = (
            await db.execute(
                pg_insert(LocationPoint).values(list(rows.values())).on_conflict_do_nothing(index_elements=["business_id", "vehicle_id", "recorded_at"]).returning(LocationPoint.recorded_at)
            )
        ).all()
        result.accepted = len(stored)
        result.duplicate += len(rows) - len(stored)
        # The phone's fixes are scored and checked against mapped areas too, unless the vehicle's tracker is doing it.
        if stored and not await behaviour.tracker_is_reporting(db, trip.vehicle_id, now):
            fresh = [rows[t] for (t,) in stored]
            await behaviour.feed(db, trip.vehicle_id, [{"at": r["recorded_at"], "speed": r["speed_kmh"], "heading": r["heading"], "ignition": None, "lat": r["lat"], "lng": r["lng"]} for r in fresh], source="phone")
            vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == trip.vehicle_id))).scalar_one()
            for r in sorted(fresh, key=lambda r: r["recorded_at"]):
                await geofences.process(db, vehicle, trip.id, r["recorded_at"], r["lat"], r["lng"])
    if result.accepted:
        await db.execute(update(TrackingGap).where(TrackingGap.trip_id == trip.id, TrackingGap.resolved_at.is_(None)).values(resolved_at=now))
        if trip.ended_at is not None:
            await finalise(db, trip)  # a late batch from an offline phone changes the trip's totals
    return result


async def trip_points(db: AsyncSession, trip_id: uuid.UUID) -> list[LocationPoint]:
    return list((await db.execute(select(LocationPoint).where(LocationPoint.trip_id == trip_id).order_by(LocationPoint.recorded_at))).scalars())


async def finalise(db: AsyncSession, trip: Trip) -> None:
    """Works out what the phone's GPS and the vehicle's tracker each say the trip came to, and whether the odometer agrees with them."""
    points = await trip_points(db, trip.id)
    km, used = path_distance_km([{"at": p.recorded_at, "lat": p.lat, "lng": p.lng, "accuracy_m": p.accuracy_m} for p in points if p.source == "phone"])
    trip.gps_distance_km, trip.gps_points = (km if used else None), used
    t_km, t_used = 0.0, 0
    if trip.started_at is not None:
        end = trip.ended_at or datetime.now(UTC)
        # A tracker reports all the time, not only on trips, so its part of the trip is found by time, whenever it arrived.
        theirs = (await db.execute(select(LocationPoint).where(LocationPoint.vehicle_id == trip.vehicle_id, LocationPoint.source == "tracker", LocationPoint.recorded_at >= trip.started_at, LocationPoint.recorded_at <= end).order_by(LocationPoint.recorded_at))).scalars().all()
        t_km, t_used = path_distance_km([{"at": p.recorded_at, "lat": p.lat, "lng": p.lng, "accuracy_m": p.accuracy_m} for p in theirs])
    trip.tracker_distance_km, trip.tracker_points = (t_km if t_used else None), t_used
    verdict = three_way(odometer_km=trip.distance_km, phone_km=km if used else None, phone_points=used, tracker_km=t_km if t_used else None, tracker_points=t_used)
    trip.distance_check = verdict["check"]
    trip.distance_detail = {"sources": verdict["sources"], "suspect": verdict["suspect"]}
    if trip.ended_at is not None:
        await fraud.check_trip(db, trip)  # the fuel, distance and stop checks that need the finished trip


async def last_positions(db: AsyncSession, vehicle_ids: list[uuid.UUID], *, since: datetime | None = None) -> dict[uuid.UUID, LocationPoint]:
    """The newest fix for each vehicle (looking back 30 days at most, which keeps the scan to the newest chunks)."""
    if not vehicle_ids:
        return {}
    since = since or datetime.now(UTC) - timedelta(days=30)
    rows = (
        await db.execute(
            select(LocationPoint).ext(distinct_on(LocationPoint.vehicle_id)).where(LocationPoint.vehicle_id.in_(vehicle_ids), LocationPoint.recorded_at >= since)
            .order_by(LocationPoint.vehicle_id, LocationPoint.recorded_at.desc())
        )
    ).scalars()  # fmt: skip
    return {p.vehicle_id: p for p in rows}


async def last_point_time(db: AsyncSession, trip_id: uuid.UUID) -> datetime | None:
    return (await db.execute(select(func.max(LocationPoint.recorded_at)).where(LocationPoint.trip_id == trip_id))).scalar_one()


def point_out(p: LocationPoint) -> dict:
    return {"at": p.recorded_at, "lat": p.lat, "lng": p.lng, "speed_kmh": p.speed_kmh, "heading": p.heading, "accuracy_m": p.accuracy_m}
