"""The live map (masterplan 5.3): where every lorry is and what state it is in, and the path a trip took."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import tracking
from app.config import settings
from app.db import get_db
from app.deps import Principal, feature, require
from app.gps_rules import vehicle_state
from app.models import (
    Depot,
    Membership,
    SosAlert,
    TrackerDevice,
    TrackingGap,
    Trip,
    TripStatus,
    Vehicle,
)
from app.routers.trips import get_trip
from app.trust import flag_summary, trust_out
from app.vehicle_scope import require_vehicle_in_scope, scope_vehicles

router = APIRouter(tags=["livemap"])
ACTIVE = (TripStatus.IN_PROGRESS, TripStatus.DELIVERED)
MAX_TRACK_POINTS = 1500


@router.get("/map/vehicles", dependencies=[Depends(feature("live_map"))])
async def map_vehicles(principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    """Every vehicle in the caller's scope with its last known position and state: moving, idle, offline, parked or unknown."""
    now = datetime.now(UTC)
    vehicles = (await db.execute(scope_vehicles(select(Vehicle).where(Vehicle.is_active.is_(True)), principal).order_by(Vehicle.registration))).scalars().all()
    ids = [v.id for v in vehicles]
    trips = {t.vehicle_id: t for t in (await db.execute(select(Trip).where(Trip.vehicle_id.in_(ids), Trip.status.in_(ACTIVE)))).scalars()} if ids else {}
    last = await tracking.last_positions(db, ids)
    names = {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    depots = {d.id: d.name for d in (await db.execute(select(Depot))).scalars()}
    devices = {d.vehicle_id: d for d in (await db.execute(select(TrackerDevice).where(TrackerDevice.is_active.is_(True)))).scalars()}
    flags = await flag_summary(db, ids)
    dark = {g.vehicle_id: g for g in (await db.execute(select(TrackingGap).where(TrackingGap.resolved_at.is_(None)))).scalars()}
    sos = {a.vehicle_id: a for a in (await db.execute(select(SosAlert).where(SosAlert.status != "resolved").order_by(SosAlert.received_at))).scalars() if a.vehicle_id in ids}
    out = []
    for v in vehicles:
        p, t = last.get(v.id), trips.get(v.id)
        a = sos.get(v.id)
        state = vehicle_state(on_trip=t is not None, last_at=p.recorded_at if p else None, now=now, speed_kmh=p.speed_kmh if p else None)
        out.append(
            {
                "vehicle_id": v.id, "registration": v.registration, "state": state, "depot": depots.get(v.depot_id), "going_dark": v.id in dark,
                "position": tracking.point_out(p) if p else None, "source": p.source if p else None, "trust": trust_out(v, flags.get(v.id, {})),
                "tracker": None if v.id not in devices else {"online": devices[v.id].online_state != "offline", "power_ok": devices[v.id].power_ok, "battery_pct": devices[v.id].battery_pct, "ignition": devices[v.id].ignition, "immobilised": devices[v.id].immobilised}, "age_seconds": int((now - p.recorded_at).total_seconds()) if p else None,
                "sos": None if a is None else {"id": a.id, "status": a.status, "since": a.sent_at, "lat": a.lat, "lng": a.lng, "driver": names.get(a.driver_membership_id)},
                "trip": None if t is None else {"id": t.id, "origin": t.origin, "destination": t.destination, "status": t.status.value, "started_at": t.started_at, "driver": names.get(t.driver_membership_id)},
            }
        )
    return {"as_of": now, "going_dark_minutes": settings.going_dark_minutes, "vehicles": out}


@router.get("/trips/{trip_id}/track")
async def trip_track(trip_id: uuid.UUID, principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    """The path a trip took, for the map. Long trips are thinned to what a map can draw; the distance is worked out from every fix."""
    trip = await get_trip(db, principal, trip_id)
    require_vehicle_in_scope(principal, trip.vehicle_id)
    points = await tracking.trip_points(db, trip.id)
    stride = max(1, -(-len(points) // MAX_TRACK_POINTS))
    shown = points[::stride]
    if points and shown[-1] is not points[-1]:
        shown.append(points[-1])
    return {
        "trip_id": trip.id, "status": trip.status.value, "started_at": trip.started_at, "ended_at": trip.ended_at, "fixes": len(points), "gps_distance_km": trip.gps_distance_km,
        "odometer_distance_km": trip.distance_km, "distance_check": trip.distance_check, "points": [tracking.point_out(p) for p in shown],
    }  # fmt: skip


@router.get("/map/gaps", dependencies=[Depends(feature("live_map"))])
async def map_gaps(principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    """Trips whose phone has gone quiet, and recent ones that have come back."""
    names = {v.id: v.registration for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    since = datetime.now(UTC) - timedelta(days=7)
    rows = (await db.execute(select(TrackingGap).where((TrackingGap.resolved_at.is_(None)) | (TrackingGap.detected_at >= since)).order_by(TrackingGap.detected_at.desc()).limit(100))).scalars()
    return [
        {"id": g.id, "trip_id": g.trip_id, "registration": names[g.vehicle_id], "last_seen_at": g.last_seen_at, "detected_at": g.detected_at, "resolved_at": g.resolved_at, "notified": g.notified}
        for g in rows if g.vehicle_id in names
    ]  # fmt: skip


