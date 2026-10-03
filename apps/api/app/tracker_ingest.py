"""What happens when a tracker reports (masterplan 5.3, 5.13, 5.25). Traccar posts each position and event; we find the device by its
IMEI (which names the business and the vehicle), store the fix, keep the device's status, run the vehicle's mapped areas and driving
behaviour on it, and turn tamper alarms into alerts straight away."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import alerts, behaviour, geofences
from app.models import ImmobiliserCommand, LocationPoint, TrackerDevice, Trip, TripStatus, Vehicle
from app.tenancy import current_business_id
from app.traccar import DRIVING_ALARMS, RESTORED_ALARMS, TAMPER_ALARMS

CLOCK_SLACK = timedelta(minutes=5)


async def device_by_imei(db: AsyncSession, imei: str) -> TrackerDevice | None:
    """Finds a tracker anywhere on the platform (an IMEI belongs to one business) and puts the request in its business."""
    device = (await db.execute(select(TrackerDevice).where(TrackerDevice.imei == imei).execution_options(skip_tenant=True))).scalar_one_or_none()
    if device is not None:
        current_business_id.set(device.business_id)
    return device


async def _active_trip(db: AsyncSession, vehicle_id: uuid.UUID, at: datetime) -> Trip | None:
    return (
        await db.execute(
            select(Trip).where(Trip.vehicle_id == vehicle_id, Trip.started_at.is_not(None), Trip.started_at <= at, (Trip.ended_at.is_(None)) | (Trip.ended_at >= at), Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED, TripStatus.COMPLETED)))
            .order_by(Trip.started_at.desc())
        )
    ).scalars().first()  # fmt: skip


async def _came_back(db: AsyncSession, device: TrackerDevice, vehicle: Vehicle, now: datetime) -> None:
    if device.online_state == "offline":
        await alerts.resolve_alerts(db, vehicle.id, "device_offline", now)
    device.online_state = "online"


def fuel_litres(device: TrackerDevice, vehicle: Vehicle, level: float | None) -> float | None:
    """The tank level in litres, from what the device's fuel sensor reported. A sensor that reports percent needs the tank's size; one
    nobody said was fitted is ignored, because without knowing the unit the number cannot be read."""
    if level is None or not device.has_fuel_sensor or level < 0:
        return None
    if device.fuel_unit == "percent":
        return round(level / 100 * vehicle.tank_litres, 1) if vehicle.tank_litres and level <= 100 else None
    return round(level, 1)


async def handle_position(db: AsyncSession, device: TrackerDevice, p: dict, *, now: datetime | None = None) -> dict:
    """One position from a tracker. Returns {stored, alarms} for the caller's response and tests."""
    now = now or datetime.now(UTC)
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == device.vehicle_id))).scalar_one()
    at = p["at"]
    newest = device.last_position_at is None or at > device.last_position_at
    device.last_seen_at = max(now, device.last_seen_at or now)
    await _came_back(db, device, vehicle, now)
    if p.get("battery_pct") is not None:
        device.battery_pct = float(p["battery_pct"])
    if p.get("power_v") is not None:
        device.power_v = p["power_v"]
        device.power_ok = p["power_v"] > 0.5
    if p.get("ignition") is not None and newest:
        device.ignition = bool(p["ignition"])
    device.gps_ok = bool(p["valid"]) if newest else device.gps_ok
    result = {"stored": False, "alarms": []}

    if p["valid"] and at <= now + CLOCK_SLACK:
        trip = await _active_trip(db, vehicle.id, at)
        stored = (
            await db.execute(
                pg_insert(LocationPoint).values(
                    id=uuid.uuid4(), business_id=current_business_id.get(), recorded_at=at, vehicle_id=vehicle.id, trip_id=trip.id if trip else None, user_id=None, lat=p["lat"], lng=p["lng"],
                    speed_kmh=p["speed_kmh"], heading=p["heading"], accuracy_m=p["accuracy_m"], ignition=p["ignition"], fuel_litres=fuel_litres(device, vehicle, p.get("fuel")), source="tracker", received_at=now,
                ).on_conflict_do_nothing(index_elements=["business_id", "vehicle_id", "recorded_at"]).returning(LocationPoint.recorded_at)
            )
        ).all()  # fmt: skip
        result["stored"] = bool(stored)
        if stored and newest:
            device.last_position_at = at
            await behaviour.feed(db, vehicle.id, [{"at": at, "speed": p["speed_kmh"], "heading": p["heading"], "ignition": p["ignition"], "lat": p["lat"], "lng": p["lng"]}], source="tracker")
            await geofences.process(db, vehicle, trip.id if trip else None, at, p["lat"], p["lng"])
    if p.get("alarm"):
        result["alarms"] = await handle_alarm(db, device, vehicle, p["alarm"], at, p)
    await db.flush()
    return result


async def handle_alarm(db: AsyncSession, device: TrackerDevice, vehicle: Vehicle, alarm: str, at: datetime, p: dict) -> list[str]:
    done: list[str] = []
    where = {"lat": p.get("lat"), "lng": p.get("lng"), "alarm": alarm}
    if alarm in TAMPER_ALARMS:
        kind = TAMPER_ALARMS[alarm]
        if kind == "power_cut":
            device.power_ok = False
        raised = await alerts.raise_alert(db, vehicle, kind, at, device_id=device.id, details=where)
        if raised is not None:
            done.append(kind)
    elif alarm in RESTORED_ALARMS:
        device.power_ok = True
        if await alerts.resolve_alerts(db, vehicle.id, RESTORED_ALARMS[alarm], at):
            done.append("power_restored")
    elif alarm in DRIVING_ALARMS:
        kind = DRIVING_ALARMS[alarm]
        made = await behaviour.record_event(db, vehicle.id, kind, at, source="device", value=p.get("speed_kmh"), lat=p.get("lat"), lng=p.get("lng"))
        if made is not None:
            done.append(kind)
    return done


async def handle_event(db: AsyncSession, device: TrackerDevice, ev: dict, *, now: datetime | None = None) -> dict:
    """An event from Traccar itself: the device went offline or came back, or answered a command."""
    now = now or datetime.now(UTC)
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == device.vehicle_id))).scalar_one()
    at = ev.get("at") or now
    done: list[str] = []
    kind = ev.get("type")
    if kind == "deviceOffline" and device.online_state != "offline":
        device.online_state = "offline"
        if await alerts.raise_alert(db, vehicle, "device_offline", at, device_id=device.id):
            done.append("device_offline")
    elif kind in ("deviceOnline", "deviceUnknown"):
        device.last_seen_at = now
        await _came_back(db, device, vehicle, now)
        done.append("device_online")
    elif kind == "alarm" and ev.get("alarm"):
        done = await handle_alarm(db, device, vehicle, ev["alarm"], at, {"lat": None, "lng": None, "speed_kmh": None})
    elif kind == "commandResult":
        cmd = (await db.execute(select(ImmobiliserCommand).where(ImmobiliserCommand.device_id == device.id, ImmobiliserCommand.status == "sent").order_by(ImmobiliserCommand.sent_at.desc()))).scalars().first()
        if cmd is not None:
            cmd.status, cmd.result_at, cmd.result_note = "acknowledged", now, (ev.get("result") or "The tracker confirmed.")[:255]
            device.immobilised = cmd.action == "immobilise"
            done.append("command_acknowledged")
    await db.flush()
    return {"events": done}
