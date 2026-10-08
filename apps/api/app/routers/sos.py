"""SOS / panic button (masterplan 5.21): the owner, managers and the supervisors who cover the vehicle are texted at
once with the driver's location, and the alert stays on their dashboard until someone takes it."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, push
from app.clock import capture_time
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import (
    CrewAssignment,
    Membership,
    MembershipStatus,
    Role,
    SosAlert,
    Trip,
    TripStatus,
    Vehicle,
)
from app.phone import mask_phone
from app.sms import get_sms_sender
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["sos"])
log = logging.getLogger(__name__)
RESPOND = ("sos.respond",)
REUSE_WINDOW = timedelta(minutes=30)  # a second press in this time updates the same alert instead of texting everyone again
MAX_TRACK = 300


class SosIn(BaseModel):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    captured_at: datetime | None = None  # when the driver pressed it; a phone with no signal sends it later
    client_id: uuid.UUID | None = None


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    captured_at: datetime | None = None


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def alert_out(a: SosAlert, names: dict, vehicles: dict) -> dict:
    v = vehicles.get(a.vehicle_id)
    return {
        "id": a.id, "status": a.status, "driver_name": names.get(a.driver_membership_id), "vehicle_id": a.vehicle_id,
        "registration": v.registration if v else None, "lat": a.lat, "lng": a.lng, "track": a.track,
        "sent_at": a.sent_at, "received_at": a.received_at, "delay_s": max(0, int((a.received_at - a.sent_at).total_seconds())),
        "notified": a.notified, "acknowledged_at": a.acknowledged_at, "resolved_at": a.resolved_at, "note": a.note,
        "map_url": f"https://maps.google.com/?q={a.lat},{a.lng}" if a.lat is not None and a.lng is not None else None,
    }  # fmt: skip


async def _names(db: AsyncSession) -> dict:
    return {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}


async def _recipients(db: AsyncSession, vehicle_id: uuid.UUID | None, exclude_membership: uuid.UUID | None) -> list[str]:
    """Phones of the owner and managers, and of supervisors whose vehicles include this one."""
    phones: set[str] = set()
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        if m.id == exclude_membership or not m.user.phone:
            continue  # an owner who is also the driver is not texted about their own alert
        roles = {r.role: r for r in m.roles}
        if Role.OWNER in roles or Role.MANAGER in roles or Role.SUPERVISOR in roles and vehicle_id is not None and str(vehicle_id) in (roles[Role.SUPERVISOR].vehicle_scope or []):
            phones.add(m.user.phone)
    return sorted(phones)


async def _recipient_tokens(db: AsyncSession, vehicle_id: uuid.UUID | None, exclude_membership: uuid.UUID | None) -> list[str]:
    """Push addresses of the same people the text goes to (a phone number is not needed for a push)."""
    tokens: list[str] = []
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        if m.id == exclude_membership or not m.user.push_token:
            continue
        roles = {r.role: r for r in m.roles}
        if Role.OWNER in roles or Role.MANAGER in roles or Role.SUPERVISOR in roles and vehicle_id is not None and str(vehicle_id) in (roles[Role.SUPERVISOR].vehicle_scope or []):
            tokens.append(m.user.push_token)
    return tokens


async def _tell_where(db: AsyncSession, alert: SosAlert, principal: Principal) -> None:
    """An SOS that went out before the phone knew where it was: once the position arrives, tell the same people where to go."""
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == alert.vehicle_id))).scalar_one_or_none() if alert.vehicle_id else None
    text = f"FleetTms SOS update: {principal.user.name}{f' ({vehicle.registration})' if vehicle else ''} is here: https://maps.google.com/?q={alert.lat},{alert.lng}"
    sms = get_sms_sender()
    for phone in await _recipients(db, alert.vehicle_id, principal.membership_id):
        try:
            await sms.send(phone, text)
        except Exception:
            log.exception("SOS location text to %s failed", mask_phone(phone))


async def do_send_sos(db: AsyncSession, principal: Principal, body: SosIn) -> SosAlert:
    """Raises (or updates) the driver's alert and texts the people who respond. The caller commits."""
    if body.client_id is not None:
        again = (await db.execute(select(SosAlert).where(SosAlert.client_id == body.client_id))).scalar_one_or_none()
        if again is not None and again.user_id == principal.user.id:
            return again
    sent_at = capture_time(body.captured_at)
    live = (
        await db.execute(
            select(SosAlert)
            .where(SosAlert.user_id == principal.user.id, SosAlert.status != "resolved", SosAlert.received_at >= datetime.now(UTC) - REUSE_WINDOW)
            .order_by(SosAlert.received_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if live is not None:  # already raised: just move the pin
        unlocated = live.lat is None
        _add_point(live, body.lat, body.lng, body.accuracy_m, sent_at)
        if unlocated and live.lat is not None:
            await _tell_where(db, live, principal)
        return live
    crew = (
        await db.execute(select(CrewAssignment).where(CrewAssignment.membership_id == principal.membership_id, CrewAssignment.ended_at.is_(None)).limit(1))
    ).scalar_one_or_none() if principal.membership_id else None
    trip = (
        await db.execute(
            select(Trip).where(
                Trip.driver_membership_id == principal.membership_id, Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED))
            ).limit(1)
        )
    ).scalar_one_or_none() if principal.membership_id else None
    alert = SosAlert(
        user_id=principal.user.id, driver_membership_id=principal.membership_id, vehicle_id=crew.vehicle_id if crew else (trip.vehicle_id if trip else None),
        trip_id=trip.id if trip else None, client_id=body.client_id, lat=body.lat, lng=body.lng, sent_at=sent_at, track=[],
    )  # fmt: skip
    db.add(alert)
    await db.flush()
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == alert.vehicle_id))).scalar_one_or_none() if alert.vehicle_id else None
    where = f"https://maps.google.com/?q={body.lat},{body.lng}" if body.lat is not None and body.lng is not None else "Location not known yet."
    text = f"FleetTms SOS: {principal.user.name}{f' ({vehicle.registration})' if vehicle else ''} needs help. {where}"
    sms = get_sms_sender()
    for phone in await _recipients(db, alert.vehicle_id, principal.membership_id):
        try:
            await sms.send(phone, text)
            alert.notified += 1
        except Exception:
            log.exception("SOS text to %s failed", mask_phone(phone))
    await push.send(
        await _recipient_tokens(db, alert.vehicle_id, principal.membership_id),
        "SOS: a driver needs help",
        f"{principal.user.name}{f' ({vehicle.registration})' if vehicle else ''} pressed the SOS button.",
        {"type": "sos", "alert_id": str(alert.id)},
        channel=push.SOS_CHANNEL,
    )
    audit.record(db, actor_user_id=principal.user.id, action="sos.raised", entity_type="sos_alert", entity_id=alert.id, after={"vehicle_id": str(alert.vehicle_id) if alert.vehicle_id else None, "notified": alert.notified})
    return alert


def _add_point(alert: SosAlert, lat: float | None, lng: float | None, accuracy: float | None, at: datetime) -> None:
    if lat is None or lng is None:
        return
    alert.lat, alert.lng = lat, lng
    alert.track = [*alert.track, {"lat": lat, "lng": lng, "accuracy_m": accuracy, "at": at.isoformat()}][-MAX_TRACK:]


async def _mine(db: AsyncSession, principal: Principal, alert_id: uuid.UUID) -> SosAlert:
    alert = (await db.execute(select(SosAlert).where(SosAlert.id == alert_id, SosAlert.user_id == principal.user.id))).scalar_one_or_none()
    if alert is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That alert was not found.")
    return alert


@router.post("/sos", status_code=status.HTTP_201_CREATED)
async def send_sos(body: SosIn, principal: Principal = Depends(require_any("trips.own")), db: AsyncSession = Depends(get_db)):
    alert = await do_send_sos(db, principal, body)
    await db.commit()
    return alert_out(alert, await _names(db), {v.id: v for v in (await db.execute(select(Vehicle))).scalars()})


@router.post("/sos/{alert_id}/location")
async def update_location(alert_id: uuid.UUID, body: LocationIn, principal: Principal = Depends(require_any("trips.own")), db: AsyncSession = Depends(get_db)):
    """Live location while the alert is open."""
    alert = await _mine(db, principal, alert_id)
    if alert.status == "resolved":
        raise error(status.HTTP_409_CONFLICT, "closed", "That alert is already closed.")
    unlocated = alert.lat is None
    _add_point(alert, body.lat, body.lng, body.accuracy_m, capture_time(body.captured_at))
    if unlocated and alert.lat is not None:
        await _tell_where(db, alert, principal)
    await db.commit()
    return {"status": alert.status, "acknowledged": alert.acknowledged_at is not None}


@router.get("/me/sos")
async def my_sos(principal: Principal = Depends(require_any("trips.own")), db: AsyncSession = Depends(get_db)):
    """The driver's latest alert, so the app can say whether anyone has answered."""
    alert = (await db.execute(select(SosAlert).where(SosAlert.user_id == principal.user.id).order_by(SosAlert.received_at.desc()).limit(1))).scalar_one_or_none()
    if alert is None or alert.status == "resolved":
        return None
    return {"id": alert.id, "status": alert.status, "acknowledged": alert.acknowledged_at is not None, "sent_at": alert.sent_at}


@router.get("/sos")
async def list_alerts(active_only: bool = True, principal: Principal = Depends(require_any(*RESPOND)), db: AsyncSession = Depends(get_db)):
    vehicles = {v.id: v for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    query = select(SosAlert).order_by(SosAlert.received_at.desc()).limit(100)
    if active_only:
        query = query.where(SosAlert.status != "resolved")
    names = await _names(db)
    rows = (await db.execute(query)).scalars().all()
    if principal.vehicle_scope is not None:
        rows = [a for a in rows if a.vehicle_id in vehicles]
    return [alert_out(a, names, vehicles) for a in rows]


async def _respond(db: AsyncSession, principal: Principal, alert_id: uuid.UUID) -> SosAlert:
    alert = (await db.execute(select(SosAlert).where(SosAlert.id == alert_id))).scalar_one_or_none()
    if alert is None or (principal.vehicle_scope is not None and str(alert.vehicle_id) not in principal.vehicle_scope):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That alert was not found.")
    return alert


@router.post("/sos/{alert_id}/acknowledge")
async def acknowledge(alert_id: uuid.UUID, body: NoteIn, principal: Principal = Depends(require_any(*RESPOND)), db: AsyncSession = Depends(get_db)):
    alert = await _respond(db, principal, alert_id)
    if alert.status == "active":
        alert.status, alert.acknowledged_at, alert.acknowledged_by_user_id = "acknowledged", datetime.now(UTC), principal.user.id
        alert.note = body.note or alert.note
        audit.record(db, actor_user_id=principal.user.id, action="sos.acknowledged", entity_type="sos_alert", entity_id=alert.id)
    await db.commit()
    return alert_out(alert, await _names(db), {v.id: v for v in (await db.execute(select(Vehicle))).scalars()})


@router.post("/sos/{alert_id}/resolve")
async def resolve(alert_id: uuid.UUID, body: NoteIn, principal: Principal = Depends(require_any(*RESPOND)), db: AsyncSession = Depends(get_db)):
    alert = await _respond(db, principal, alert_id)
    if alert.status != "resolved":
        alert.status, alert.resolved_at = "resolved", datetime.now(UTC)
        if alert.acknowledged_at is None:
            alert.acknowledged_at, alert.acknowledged_by_user_id = alert.resolved_at, principal.user.id
        alert.note = body.note or alert.note
        audit.record(db, actor_user_id=principal.user.id, action="sos.resolved", entity_type="sos_alert", entity_id=alert.id, note=body.note)
    await db.commit()
    return alert_out(alert, await _names(db), {v.id: v for v in (await db.execute(select(Vehicle))).scalars()})
