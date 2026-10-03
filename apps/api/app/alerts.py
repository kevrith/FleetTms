"""Tracker alerts (masterplan 5.13): a power cut, jamming, a tracker gone quiet, a lorry in a place it must not be. Raised the moment
the news arrives, and the owner and managers are texted at once (the classic step before siphoning or hijacking is cutting the tracker)."""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.models import (
    Business,
    Membership,
    MembershipStatus,
    Role,
    TrackerAlert,
    Trip,
    TripStatus,
    Vehicle,
)
from app.reminders import NAIROBI
from app.sms import get_sms_sender
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
DEDUPE = timedelta(minutes=10)  # the same fault reported again within this is the same alert
SEVERITY = {"power_cut": "red", "gps_jamming": "red", "tamper": "red", "sos": "red", "low_battery": "amber", "device_offline": "amber", "geofence": "amber"}
TITLES = {
    "power_cut": "the tracker lost power from the vehicle. Someone may have cut or removed it.",
    "gps_jamming": "the tracker reports GPS jamming. Its position cannot be trusted.",
    "tamper": "the tracker reports tampering.",
    "sos": "the tracker's SOS button was pressed.",
    "low_battery": "the tracker's battery is low.",
    "device_offline": "the tracker has stopped reporting.",
}


async def notify_owners(db: AsyncSession, message: str) -> int:
    sent = 0
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        if {r.role for r in m.roles} & {Role.OWNER, Role.MANAGER} and m.user.phone:
            await get_sms_sender().send(m.user.phone, message)
            sent += 1
    return sent


async def raise_alert(
    db: AsyncSession, vehicle: Vehicle, kind: str, at: datetime, *, device_id: uuid.UUID | None = None, details: dict | None = None, severity: str | None = None, text: str | None = None, notify: bool = True,
) -> TrackerAlert | None:  # fmt: skip
    """Records an alert and texts the owner and managers. The same kind for the same vehicle already open within ten minutes is
    not raised again. Returns None when it was a repeat."""
    recent = (await db.execute(select(TrackerAlert).where(TrackerAlert.vehicle_id == vehicle.id, TrackerAlert.kind == kind, TrackerAlert.status == "open", TrackerAlert.at >= at - DEDUPE))).scalars().first()
    if recent is not None and kind != "geofence":  # each area is its own alert
        return None
    trip = (await db.execute(select(Trip).where(Trip.vehicle_id == vehicle.id, Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED))))).scalars().first()
    alert = TrackerAlert(vehicle_id=vehicle.id, device_id=device_id, trip_id=trip.id if trip else None, kind=kind, severity=severity or SEVERITY.get(kind, "amber"), at=at, details=details or {})
    db.add(alert)
    await db.flush()
    audit.record(db, actor_user_id=None, action=f"tracker_alert.{kind}", entity_type="vehicle", entity_id=vehicle.id, after={"alert_id": str(alert.id), "at": at.isoformat()})
    if notify:
        business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
        when = at.astimezone(NAIROBI).strftime("%H:%M")
        alert.notified = await notify_owners(db, f"{business.name}: {vehicle.registration}: {text or TITLES.get(kind, kind.replace('_', ' '))} ({when})")
    return alert


async def resolve_alerts(db: AsyncSession, vehicle_id: uuid.UUID, kind: str, at: datetime) -> int:
    """Closes open alerts of a kind (the power came back, the tracker came online)."""
    rows = (await db.execute(select(TrackerAlert).where(TrackerAlert.vehicle_id == vehicle_id, TrackerAlert.kind == kind, TrackerAlert.status == "open"))).scalars().all()
    for a in rows:
        a.status, a.resolved_at = "resolved", at
    return len(rows)
