"""Driving behaviour and replay (masterplan 5.3, 5.25): the events found in a vehicle's fixes, and the path a vehicle took with those
events marked on it."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import tracking
from app.db import get_db
from app.deps import Principal, error, require
from app.models import (
    BehaviourEvent,
    Geofence,
    GeofenceEvent,
    LocationPoint,
    Membership,
    TrackerAlert,
    Trip,
    Vehicle,
)
from app.routers.trips import get_trip
from app.vehicle_scope import require_vehicle_in_scope, scope_vehicles

router = APIRouter(tags=["behaviour"])
MAX_REPLAY_POINTS = 2000
MAX_SPAN = timedelta(days=3)
LABELS = {
    "speeding": "Speeding", "harsh_braking": "Harsh braking", "harsh_acceleration": "Harsh acceleration", "harsh_cornering": "Sharp cornering", "idling": "Idling",
    "night_driving": "Night driving", "long_driving": "Long driving without rest",
}  # fmt: skip


def event_out(e: BehaviourEvent, registration: str | None = None, driver: str | None = None) -> dict:
    return {
        "id": e.id, "vehicle_id": e.vehicle_id, "registration": registration, "driver_membership_id": e.driver_membership_id, "driver": driver, "trip_id": e.trip_id, "kind": e.kind,
        "label": LABELS.get(e.kind, e.kind), "at": e.at, "ended_at": e.ended_at, "value": e.value, "limit": e.limit_value, "lat": e.lat, "lng": e.lng, "source": e.source,
    }  # fmt: skip


async def _names(db: AsyncSession) -> dict[uuid.UUID, str]:
    return {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}


@router.get("/behaviour/events")
async def behaviour_events(
    vehicle_id: uuid.UUID | None = None, driver_id: uuid.UUID | None = None, kind: str | None = None, start: datetime | None = None, end: datetime | None = None, limit: int = 200,
    principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db),
):  # fmt: skip
    regs = {v.id: v.registration for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    names = await _names(db)
    query = select(BehaviourEvent).order_by(BehaviourEvent.at.desc()).limit(min(max(limit, 1), 1000))
    for column, value in ((BehaviourEvent.vehicle_id, vehicle_id), (BehaviourEvent.driver_membership_id, driver_id), (BehaviourEvent.kind, kind)):
        if value:
            query = query.where(column == value)
    if start:
        query = query.where(BehaviourEvent.at >= start)
    if end:
        query = query.where(BehaviourEvent.at <= end)
    return [event_out(e, regs[e.vehicle_id], names.get(e.driver_membership_id)) for e in (await db.execute(query)).scalars() if e.vehicle_id in regs]


@router.get("/behaviour/summary")
async def behaviour_summary(start: datetime | None = None, end: datetime | None = None, principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    """How many of each kind of event, per vehicle and per driver, in a period (the last 30 days by default)."""
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=30)
    regs = {v.id: v.registration for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    names = await _names(db)
    by_vehicle: dict = defaultdict(lambda: defaultdict(int))
    by_driver: dict = defaultdict(lambda: defaultdict(int))
    for e in (await db.execute(select(BehaviourEvent).where(BehaviourEvent.at >= start, BehaviourEvent.at <= end))).scalars():
        if e.vehicle_id not in regs:
            continue
        by_vehicle[e.vehicle_id][e.kind] += 1
        if e.driver_membership_id:
            by_driver[e.driver_membership_id][e.kind] += 1
    return {
        "from": start, "to": end,
        "vehicles": [{"vehicle_id": v, "registration": regs[v], "counts": dict(c), "total": sum(c.values())} for v, c in sorted(by_vehicle.items(), key=lambda kv: -sum(kv[1].values()))],
        "drivers": [{"driver_membership_id": d, "name": names.get(d), "counts": dict(c), "total": sum(c.values())} for d, c in sorted(by_driver.items(), key=lambda kv: -sum(kv[1].values()))],
    }  # fmt: skip


async def replay(db: AsyncSession, vehicle_id: uuid.UUID, start: datetime, end: datetime) -> dict:
    """The path between two moments with what happened along it. A tracker's path is used when there is one, else the phone's; long
    paths are thinned to what a map can draw."""
    if end <= start:
        raise error(422, "bad_range", "The end is before the start.")
    if end - start > MAX_SPAN:
        raise error(422, "range_too_long", "Replay at most three days at a time.")
    points = list((await db.execute(select(LocationPoint).where(LocationPoint.vehicle_id == vehicle_id, LocationPoint.recorded_at >= start, LocationPoint.recorded_at <= end).order_by(LocationPoint.recorded_at))).scalars())
    source = "tracker" if any(p.source == "tracker" for p in points) else "phone"
    points = [p for p in points if p.source == source]
    stride = max(1, -(-len(points) // MAX_REPLAY_POINTS))
    shown = points[::stride]
    if points and shown[-1] is not points[-1]:
        shown.append(points[-1])
    names = await _names(db)
    fences = {g.id: g.name for g in (await db.execute(select(Geofence))).scalars()}
    events = [
        {**event_out(e, None, names.get(e.driver_membership_id)), "group": "behaviour"}
        for e in (await db.execute(select(BehaviourEvent).where(BehaviourEvent.vehicle_id == vehicle_id, BehaviourEvent.at >= start, BehaviourEvent.at <= end).order_by(BehaviourEvent.at))).scalars()
    ]  # fmt: skip
    events += [
        {"group": "geofence", "kind": f"geofence_{e.kind}", "label": f"{'Entered' if e.kind == 'enter' else 'Left'} {fences.get(e.geofence_id, 'an area')}", "at": e.at, "ended_at": None, "lat": e.lat, "lng": e.lng, "value": None}
        for e in (await db.execute(select(GeofenceEvent).where(GeofenceEvent.vehicle_id == vehicle_id, GeofenceEvent.at >= start, GeofenceEvent.at <= end))).scalars()
    ]  # fmt: skip
    events += [
        {"group": "alert", "kind": a.kind, "label": a.kind.replace("_", " ").capitalize(), "at": a.at, "ended_at": None, "lat": (a.details or {}).get("lat"), "lng": (a.details or {}).get("lng"), "value": None, "severity": a.severity}
        for a in (await db.execute(select(TrackerAlert).where(TrackerAlert.vehicle_id == vehicle_id, TrackerAlert.at >= start, TrackerAlert.at <= end))).scalars()
    ]  # fmt: skip
    events.sort(key=lambda e: e["at"])
    return {"source": source, "from": start, "to": end, "fixes": len(points), "points": [tracking.point_out(p) | {"ignition": p.ignition} for p in shown], "events": events}


@router.get("/trips/{trip_id}/replay")
async def trip_replay(trip_id: uuid.UUID, principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    trip: Trip = await get_trip(db, principal, trip_id)
    require_vehicle_in_scope(principal, trip.vehicle_id)
    if trip.started_at is None:
        raise error(409, "not_started", "That trip has not started, so there is nothing to replay.")
    end = trip.ended_at or datetime.now(UTC)
    out = await replay(db, trip.vehicle_id, trip.started_at, min(end, trip.started_at + MAX_SPAN))
    return {**out, "trip_id": trip.id, "vehicle_id": trip.vehicle_id}


@router.get("/vehicles/{vehicle_id}/replay")
async def vehicle_replay(vehicle_id: uuid.UUID, start: datetime, end: datetime, principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    require_vehicle_in_scope(principal, vehicle_id)
    if (await db.execute(select(Vehicle.id).where(Vehicle.id == vehicle_id))).first() is None:
        raise error(404, "not_found", "That vehicle was not found.")
    return {**await replay(db, vehicle_id, start, end), "vehicle_id": vehicle_id}
