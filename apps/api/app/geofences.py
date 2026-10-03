"""Mapped areas (masterplan 5.12): when a vehicle enters or leaves one. Each vehicle's side of each area is remembered, a change
must be seen on two fixes in a row, and areas set to alert raise one (a restricted area also texts the owner)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import alerts, geofence_rules
from app.models import Geofence, GeofenceEvent, GeofencePresence, Vehicle


async def process(db: AsyncSession, vehicle: Vehicle, trip_id: uuid.UUID | None, at: datetime, lat: float, lng: float) -> list[GeofenceEvent]:
    """One new fix for a vehicle, in time order. Returns the entries and exits it caused."""
    made: list[GeofenceEvent] = []
    fences = (await db.execute(select(Geofence).where(Geofence.is_active.is_(True)))).scalars().all()
    for g in fences:
        if g.vehicle_ids is not None and str(vehicle.id) not in g.vehicle_ids:
            continue
        presence = (await db.execute(select(GeofencePresence).where(GeofencePresence.vehicle_id == vehicle.id, GeofencePresence.geofence_id == g.id))).scalar_one_or_none()
        if presence is None:
            presence = GeofencePresence(vehicle_id=vehicle.id, geofence_id=g.id, inside=None, pending=0)
            db.add(presence)
        state, event = geofence_rules.step({"inside": presence.inside, "pending": presence.pending}, geofence_rules.inside(g.shape, lat, lng))
        presence.inside, presence.pending = state["inside"], state["pending"]
        if event is None:
            continue
        presence.changed_at = at
        row = GeofenceEvent(geofence_id=g.id, vehicle_id=vehicle.id, trip_id=trip_id, kind=event, at=at, lat=lat, lng=lng)
        db.add(row)
        made.append(row)
        if event in (g.alert_on or []):
            restricted = g.kind == "restricted"
            word = "entered" if event == "enter" else "left"
            await alerts.raise_alert(
                db, vehicle, "geofence", at, details={"geofence": g.name, "geofence_id": str(g.id), "event": event, "lat": lat, "lng": lng}, severity="red" if restricted and event == "enter" else "amber",
                text=f"{word} {g.name}", notify=restricted and event == "enter",
            )  # fmt: skip
    await db.flush()
    return made
