"""The register of personal data breaches (masterplan 11.2 item 8), for platform admins.

A breach is written down the moment FleetTms becomes aware of it. The Data Protection Commissioner must be told within 72 hours of that
moment when the breach is likely to put people at risk, so each entry carries its deadline and shows when it has been missed. The
affected businesses are told through a text to their owners and a line in their own audit trail; telling the individuals is the
business's job as controller, and FleetTms records when it has asked them to."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, platform_admin
from app.models import BreachIncident, Membership, MembershipStatus, Role
from app.sms import get_sms_sender
from app.tenancy import current_business_id

router = APIRouter(tags=["platform"])
ODPC_HOURS = 72


class BreachIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    severity: Literal["low", "medium", "high", "critical"]
    discovered_at: datetime | None = None
    occurred_at: datetime | None = None
    businesses_affected: list[uuid.UUID] = []
    people_affected: int | None = Field(default=None, ge=0)
    data_involved: str | None = Field(default=None, max_length=500)
    risk_to_people: bool = True


class BreachUpdate(BaseModel):
    status: Literal["open", "contained", "closed"] | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    people_affected: int | None = Field(default=None, ge=0)
    data_involved: str | None = Field(default=None, max_length=500)
    risk_to_people: bool | None = None
    root_cause: str | None = Field(default=None, max_length=5000)
    actions_taken: str | None = Field(default=None, max_length=5000)
    businesses_affected: list[uuid.UUID] | None = None


class NotifyIn(BaseModel):
    who: Literal["odpc", "businesses", "people"]
    at: datetime | None = None
    message: str | None = Field(default=None, min_length=10, max_length=300)  # the text sent to each affected business's owners


def out(b: BreachIncident, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    deadline = b.discovered_at + timedelta(hours=ODPC_HOURS)
    needs_odpc = b.risk_to_people and b.odpc_notified_at is None
    return {
        "id": b.id, "title": b.title, "description": b.description, "severity": b.severity, "status": b.status, "discovered_at": b.discovered_at, "occurred_at": b.occurred_at,
        "businesses_affected": b.businesses_affected, "people_affected": b.people_affected, "data_involved": b.data_involved, "risk_to_people": b.risk_to_people,
        "contained_at": b.contained_at, "odpc_notified_at": b.odpc_notified_at, "businesses_notified_at": b.businesses_notified_at, "people_notified_at": b.people_notified_at,
        "root_cause": b.root_cause, "actions_taken": b.actions_taken, "created_at": b.created_at, "updated_at": b.updated_at,
        "odpc_deadline": deadline if b.risk_to_people else None,
        "odpc_hours_left": round((deadline - now).total_seconds() / 3600, 1) if needs_odpc else None,
        "odpc_overdue": bool(needs_odpc and now > deadline),
        "odpc_late": bool(b.odpc_notified_at and b.odpc_notified_at > deadline),
    }  # fmt: skip


async def _get(db: AsyncSession, breach_id: uuid.UUID) -> BreachIncident:
    row = await db.get(BreachIncident, breach_id)
    if row is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That breach was not found.")
    return row


@router.post("/platform/breaches", status_code=status.HTTP_201_CREATED)
async def record_breach(body: BreachIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Written down when we become aware of it: that moment starts the 72 hours."""
    row = BreachIncident(**body.model_dump(exclude={"businesses_affected", "discovered_at"}), businesses_affected=[str(i) for i in body.businesses_affected],
                         discovered_at=body.discovered_at or datetime.now(UTC), created_by_user_id=principal.user.id)  # fmt: skip
    db.add(row)
    await db.commit()
    return out(row)


@router.get("/platform/breaches")
async def list_breaches(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    return [out(b) for b in (await db.execute(select(BreachIncident).order_by(BreachIncident.discovered_at.desc()))).scalars()]


@router.get("/platform/breaches/{breach_id}")
async def read_breach(breach_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    return out(await _get(db, breach_id))


@router.patch("/platform/breaches/{breach_id}")
async def update_breach(breach_id: uuid.UUID, body: BreachUpdate, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    row = await _get(db, breach_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, [str(i) for i in value] if field == "businesses_affected" else value)
    if body.status in ("contained", "closed") and row.contained_at is None:
        row.contained_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return out(row)


async def _owners_phones(db: AsyncSession) -> list[str]:
    owners = (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars().all()
    return [m.user.phone for m in owners if m.user.phone and Role.OWNER in {r.role for r in m.roles}]


@router.post("/platform/breaches/{breach_id}/notify")
async def record_notification(breach_id: uuid.UUID, body: NotifyIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Records that the Commissioner, the affected businesses or the individuals have been told. Telling the businesses also sends their
    owners the text and writes a line in each business's own audit trail, so they can show when they were told."""
    row = await _get(db, breach_id)
    at = body.at or datetime.now(UTC)
    if body.who == "odpc":
        row.odpc_notified_at = at
    elif body.who == "people":
        row.people_notified_at = at
    else:
        if not row.businesses_affected:
            raise error(status.HTTP_422_UNPROCESSABLE_ENTITY, "no_businesses", "Say which businesses are affected first.")
        if not body.message:
            raise error(status.HTTP_422_UNPROCESSABLE_ENTITY, "message_needed", "Write the message the owners will receive.")
        sms = get_sms_sender()
        for business_id in row.businesses_affected:
            current_business_id.set(uuid.UUID(business_id))
            try:
                for phone in await _owners_phones(db):
                    await sms.send_platform(phone, body.message)
                audit.record(db, actor_user_id=principal.user.id, action="platform.breach_notified", entity_type="breach", entity_id=row.id, note=body.message[:200])
                await db.flush()
            finally:
                current_business_id.set(None)
        row.businesses_notified_at = at
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return out(row)
