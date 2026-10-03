"""A vehicle's fuel level over time (masterplan 5.3, Premium): the chart behind the siphoning and refill alerts."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fraud, fuel_sensor_rules
from app.db import get_db
from app.deps import Principal, error, require
from app.models import TrackerDevice, Vehicle
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["fuel-sensor"])
MAX_POINTS = 600
MAX_SPAN = timedelta(days=7)


@router.get("/vehicles/{vehicle_id}/fuel-level")
async def fuel_level(vehicle_id: uuid.UUID, start: datetime | None = None, end: datetime | None = None, principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)):
    """The tank level between two moments (the last 24 hours by default, at most a week), with the refills and parked drops found in
    it and the fuel purchases recorded in the same period, so a drop with nothing bought, or fuel bought that never went in, shows."""
    vehicle = (await db.execute(scope_vehicles(select(Vehicle), principal).where(Vehicle.id == vehicle_id))).scalar_one_or_none()
    if vehicle is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    end = end or datetime.now(UTC)
    start = start or end - timedelta(hours=24)
    if end <= start:
        raise error(422, "bad_range", "The end is before the start.")
    if end - start > MAX_SPAN:
        raise error(422, "range_too_long", "Show at most a week at a time.")
    devices = (await db.execute(select(TrackerDevice).where(TrackerDevice.vehicle_id == vehicle_id, TrackerDevice.has_fuel_sensor.is_(True), TrackerDevice.is_active.is_(True)))).scalars().all()
    out = {"vehicle_id": vehicle.id, "registration": vehicle.registration, "has_sensor": bool(devices), "unit": devices[0].fuel_unit if devices else None, "tank_litres": vehicle.tank_litres, "from": start, "to": end}
    if not devices:
        return {**out, "readings": 0, "points": [], "events": [], "purchases": []}
    t, _ = await fraud.load_settings(db)
    readings = await fraud.fuel_readings(db, vehicle_id, start, end)
    stride = max(1, -(-len(readings) // MAX_POINTS))
    shown = readings[::stride]
    if readings and shown[-1] is not readings[-1]:
        shown.append(readings[-1])
    events = fuel_sensor_rules.find_fuel_events(readings, t)
    purchases = await fraud.fuel_purchases(db, vehicle_id, start, end)
    return {
        **out, "readings": len(readings), "points": [{"at": r["at"], "litres": r["litres"]} for r in shown],
        "events": [{"kind": e["kind"], "litres": e["litres"], "before": e["before"], "after": e["after"], "start": e["start"], "end": e["end"], "lat": e["lat"], "lng": e["lng"]} for e in events],
        "purchases": [{"at": p.captured_at, "litres": float(p.litres), "station": p.station, "amount_cents": p.amount_cents} for p in purchases],
    }  # fmt: skip
