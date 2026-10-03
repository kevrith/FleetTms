"""GPS trackers (masterplan 5.3, Section 7): fitting a tracker to a vehicle, what Traccar posts to us, and the alerts it raises."""

import hmac
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, tracker_ingest
from app.config import settings
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import TrackerAlert, TrackerDevice, TrackingTier, Vehicle
from app.traccar import parse_forward
from app.vehicle_scope import require_vehicle_in_scope, scope_vehicles

router = APIRouter(tags=["trackers"])


class TrackerIn(BaseModel):
    vehicle_id: uuid.UUID
    imei: str = Field(min_length=6, max_length=20, pattern=r"^[A-Za-z0-9\-]+$")
    name: str | None = Field(default=None, max_length=120)
    brand: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=60)
    sim_phone: str | None = Field(default=None, max_length=20)
    supports_immobiliser: bool = False
    has_fuel_sensor: bool = False
    fuel_unit: Literal["litres", "percent"] = "litres"
    is_active: bool = True


class HandleIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)
    outcome: str = Field(default="explained", pattern="^(explained|confirmed)$")


def device_out(d: TrackerDevice, registration: str | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    quiet = (now - d.last_seen_at).total_seconds() if d.last_seen_at else None
    return {
        "id": d.id, "vehicle_id": d.vehicle_id, "registration": registration, "imei": d.imei, "name": d.name, "brand": d.brand, "model": d.model, "sim_phone": d.sim_phone,
        "supports_immobiliser": d.supports_immobiliser, "has_fuel_sensor": d.has_fuel_sensor, "fuel_unit": d.fuel_unit, "is_active": d.is_active, "online_state": d.online_state, "last_seen_at": d.last_seen_at, "last_position_at": d.last_position_at,
        "quiet_seconds": int(quiet) if quiet is not None else None, "battery_pct": d.battery_pct, "power_v": d.power_v, "power_ok": d.power_ok, "ignition": d.ignition, "gps_ok": d.gps_ok,
        "immobilised": d.immobilised,
    }  # fmt: skip


def alert_out(a: TrackerAlert, registration: str | None = None) -> dict:
    return {
        "id": a.id, "vehicle_id": a.vehicle_id, "registration": registration, "device_id": a.device_id, "trip_id": a.trip_id, "kind": a.kind, "severity": a.severity, "at": a.at,
        "details": a.details, "status": a.status, "note": a.note, "handled_at": a.handled_at, "resolved_at": a.resolved_at, "notified": a.notified,
    }  # fmt: skip


# ---- fitting trackers --------------------------------------------------------------------------------------------------


@router.get("/trackers")
async def list_trackers(principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    vehicles = {v.id: v.registration for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    return [device_out(d, vehicles[d.vehicle_id]) for d in (await db.execute(select(TrackerDevice).order_by(TrackerDevice.created_at))).scalars() if d.vehicle_id in vehicles]


async def _set_tier(db: AsyncSession, vehicle: Vehicle) -> None:
    """A vehicle with a working fuel sensor is Premium; one whose sensor was taken off goes back to Standard (it still has a tracker)."""
    sensors = (await db.execute(select(TrackerDevice.id).where(TrackerDevice.vehicle_id == vehicle.id, TrackerDevice.is_active.is_(True), TrackerDevice.has_fuel_sensor.is_(True)).limit(1))).first()
    if sensors is not None:
        vehicle.tracking_tier = TrackingTier.PREMIUM
    elif vehicle.tracking_tier == TrackingTier.PREMIUM:
        vehicle.tracking_tier = TrackingTier.STANDARD


@router.post("/trackers", status_code=status.HTTP_201_CREATED)
async def add_tracker(body: TrackerIn, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)):
    """Links a tracker (by the IMEI Traccar knows it by) to a vehicle. The vehicle moves up to the tracker tier."""
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == body.vehicle_id))).scalar_one_or_none()
    if vehicle is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    d = TrackerDevice(**{**body.model_dump(), "imei": body.imei.strip().upper()})
    db.add(d)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_imei", "A tracker with that IMEI is already registered.") from None
    if vehicle.tracking_tier == TrackingTier.BASIC:
        vehicle.tracking_tier = TrackingTier.STANDARD
    await _set_tier(db, vehicle)
    audit.record(db, actor_user_id=principal.user.id, action="tracker.added", entity_type="vehicle", entity_id=vehicle.id, after={"imei": d.imei, "supports_immobiliser": d.supports_immobiliser})
    await db.commit()
    return device_out(d, vehicle.registration)


@router.put("/trackers/{tracker_id}")
async def update_tracker(tracker_id: uuid.UUID, body: TrackerIn, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(TrackerDevice).where(TrackerDevice.id == tracker_id))).scalar_one_or_none()
    if d is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That tracker was not found.")
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == body.vehicle_id))).scalar_one_or_none()
    if vehicle is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    for k, v in {**body.model_dump(), "imei": body.imei.strip().upper()}.items():
        setattr(d, k, v)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_imei", "A tracker with that IMEI is already registered.") from None
    await _set_tier(db, vehicle)
    audit.record(db, actor_user_id=principal.user.id, action="tracker.updated", entity_type="vehicle", entity_id=vehicle.id, after={"imei": d.imei, "is_active": d.is_active})
    await db.commit()
    return device_out(d, vehicle.registration)


# ---- what Traccar posts ------------------------------------------------------------------------------------------------


@router.post("/hooks/traccar/{key}")
async def traccar_forward(key: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Traccar's forwarder: one position or one event per post. The secret in the address says it is our Traccar. A device nobody has
    registered is acknowledged and ignored, so Traccar does not keep retrying it."""
    if not settings.traccar_forward_key or not hmac.compare_digest(settings.traccar_forward_key, key):
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "Not allowed.")
    try:
        body = parse_forward(await request.json())
    except (ValueError, AttributeError, KeyError, TypeError):
        raise error(422, "bad_payload", "That is not something Traccar sends.") from None
    device = await tracker_ingest.device_by_imei(db, body["imei"]) if body["imei"] else None
    if device is None or not device.is_active:
        return {"accepted": False, "reason": "unknown_device"}
    out: dict = {"accepted": True}
    if body["position"]:
        out["position"] = await tracker_ingest.handle_position(db, device, body["position"])
    if body["event"]:
        out["event"] = await tracker_ingest.handle_event(db, device, body["event"])
    await db.commit()
    return out


# ---- alerts ------------------------------------------------------------------------------------------------------------


@router.get("/tracker/alerts")
async def list_alerts(status_filter: str | None = None, principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    """Tamper and tracker alerts for the vehicles the caller may see, newest first. `status_filter=open` for what needs a look."""
    names = {v.id: v.registration for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    query = select(TrackerAlert).order_by(TrackerAlert.at.desc()).limit(200)
    if status_filter:
        query = query.where(TrackerAlert.status == status_filter)
    return [alert_out(a, names[a.vehicle_id]) for a in (await db.execute(query)).scalars() if a.vehicle_id in names]


@router.post("/tracker/alerts/{alert_id}/handle")
async def handle_alert(alert_id: uuid.UUID, body: HandleIn, principal: Principal = Depends(require_any("alerts.manage")), db: AsyncSession = Depends(get_db)):
    """Says what an alert was: explained (a harmless reason) or confirmed (it was real). The note is kept with who wrote it."""
    a = (await db.execute(select(TrackerAlert).where(TrackerAlert.id == alert_id))).scalar_one_or_none()
    if a is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That alert was not found.")
    require_vehicle_in_scope(principal, a.vehicle_id)
    a.status, a.note, a.handled_by_user_id, a.handled_at = body.outcome, body.note, principal.user.id, datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action=f"tracker_alert.{body.outcome}", entity_type="vehicle", entity_id=a.vehicle_id, after={"alert_id": str(a.id), "kind": a.kind}, note=body.note)
    await db.commit()
    return alert_out(a)


