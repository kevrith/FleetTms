"""Document clearance for a trip: reads the business's rule and the documents on record, and says whether the trip may start
(rules in app/clearance_rules.py). A manager or owner is told when a start is refused."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clearance_rules, push, ratelimit
from app.models import (
    Business,
    ComplianceDocument,
    Membership,
    MembershipStatus,
    Role,
    Trip,
    Vehicle,
)
from app.reminders import NAIROBI
from app.sms import get_sms_sender
from app.tenancy import current_business_id

ALLOWED_REQUIRED = (*clearance_rules.DRIVER_DOCS, *clearance_rules.VEHICLE_DOCS)


async def rule_of(db: AsyncSession) -> tuple[str, list[str]]:
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    return business.document_rule, list(business.required_documents or [])


async def _latest(db: AsyncSession, *, vehicle_id: uuid.UUID | None = None, membership_id: uuid.UUID | None = None) -> dict[str, date]:
    """The document of each kind that runs longest: a renewal is a later date, and the older record is not a reason to refuse."""
    query = select(ComplianceDocument)
    query = query.where(ComplianceDocument.vehicle_id == vehicle_id) if vehicle_id is not None else query.where(ComplianceDocument.membership_id == membership_id)
    out: dict[str, date] = {}
    for d in (await db.execute(query)).scalars():
        out[d.doc_type.value] = max(out.get(d.doc_type.value, d.expires_on), d.expires_on)
    return out


async def check(db: AsyncSession, trip: Trip, *, today: date) -> dict:
    """What the business's rule says about this trip's driver and vehicle on `today`."""
    mode, required = await rule_of(db)
    if mode == "off":
        return {"mode": "off", "blocked": False, "issues": [], "overridden": False}
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == trip.vehicle_id))).scalar_one()
    items: list[dict] = []
    if any(r in clearance_rules.VEHICLE_DOCS for r in required):
        have = await _latest(db, vehicle_id=vehicle.id)
        items += [{"doc_type": r, "subject": "vehicle", "name": vehicle.registration, "expires_on": have.get(r)} for r in required if r in clearance_rules.VEHICLE_DOCS]
    if trip.driver_membership_id is not None and any(r in clearance_rules.DRIVER_DOCS for r in required):
        member = (await db.execute(select(Membership).where(Membership.id == trip.driver_membership_id))).scalar_one_or_none()
        if member is not None:
            have = await _latest(db, membership_id=member.id)
            items += [{"doc_type": r, "subject": "driver", "name": member.user.name, "expires_on": have.get(r)} for r in required if r in clearance_rules.DRIVER_DOCS]
    ends = trip.planned_end.astimezone(NAIROBI).date() if trip.planned_end else None
    result = clearance_rules.assess(mode=mode, today=today, items=items, trip_ends_on=ends)
    result["overridden"] = trip.compliance_override_at is not None
    for issue in result["issues"]:
        issue["text"] = clearance_rules.sentence(issue)
    return result


async def tell_managers(db: AsyncSession, trip: Trip, result: dict, vehicle_registration: str) -> None:
    """A start was refused: the owner and managers are texted and pushed, once an hour for the same trip however often the driver tries."""
    if await ratelimit.hit("clearance_refused", str(trip.id), 1, 3600) is not None:
        return
    people = [m for m in (await db.execute(select(Membership))).scalars() if m.status == MembershipStatus.ACTIVE and {r.role for r in m.roles} & {Role.OWNER, Role.MANAGER}]
    reasons = " ".join(i["text"] for i in result["issues"] if i["blocking"])
    message = f"FleetTms: {vehicle_registration} could not start a trip. {reasons} Renew it, or allow the trip in the app."
    sms = get_sms_sender()
    for phone in sorted({m.user.phone for m in people if m.user.phone}):
        await sms.send(phone, message)
    await push.send(
        sorted({m.user.push_token for m in people if m.user.push_token}), f"{vehicle_registration} could not start a trip", reasons,
        {"type": "clearance", "trip_id": str(trip.id)},
    )  # fmt: skip

