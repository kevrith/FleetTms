"""What a driver or turnboy can ask for and look back on from the phone: repair and tyre requests, past trips, pay."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.clock import capture_time
from app.db import get_db
from app.deps import Principal, error, require
from app.models import (
    CrewAssignment,
    PayrollLine,
    PayrollRun,
    Photo,
    PhotoKind,
    Priority,
    Trip,
    TripStatus,
    Vehicle,
    WorkOrder,
    WorkOrderSource,
)
from app.photos import claim_photo, photo_out, photos_by_id
from app.routers.trips import trip_out
from app.tyre_rules import valid_position

router = APIRouter(tags=["me"])

KINDS = {
    "tyre": "Tyre", "engine": "Engine", "brakes": "Brakes", "electrical": "Electrical",
    "body": "Body or cab", "other": "Other",
}  # fmt: skip
PAID_RUNS = ("approved", "paid")


class RepairIn(BaseModel):
    kind: Literal["tyre", "engine", "brakes", "electrical", "body", "other"]
    position: str | None = Field(default=None, max_length=40)  # for a tyre: which one
    can_drive: bool = True  # false means the vehicle should not move until it is seen to
    description: str | None = Field(default=None, max_length=1000)
    occurred_at: datetime | None = None
    photo_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    photo_client_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)  # ids the phone gave photos offline


def _request_out(wo: WorkOrder, registration: str | None, photos: dict[uuid.UUID, Photo] | None = None) -> dict:
    photos = photos or {}
    return {
        "id": wo.id, "title": wo.title, "description": wo.description, "priority": wo.priority.value,
        "status": wo.status.value, "registration": registration, "opened_at": wo.opened_at, "completed_at": wo.completed_at,
        "photos": [photo_out(photos[uuid.UUID(i)]) for i in wo.photo_ids if uuid.UUID(i) in photos],
    }  # fmt: skip


async def do_request_repair(db: AsyncSession, principal: Principal, body: RepairIn) -> WorkOrder:
    """A work order raised by the crew of a vehicle, for the workshop and owner to see. The caller commits."""
    if principal.membership_id is None:
        raise error(status.HTTP_403_FORBIDDEN, "not_your_vehicle", "You are not assigned to a vehicle.")
    crew = (
        await db.execute(
            select(CrewAssignment).where(CrewAssignment.membership_id == principal.membership_id, CrewAssignment.ended_at.is_(None)).limit(1)
        )
    ).scalar_one_or_none()
    if crew is None:
        raise error(status.HTTP_403_FORBIDDEN, "not_your_vehicle", "You are not assigned to a vehicle.")
    position = (body.position or "").strip() or None
    if position is not None and (body.kind != "tyre" or not valid_position(position)):
        raise error(422, "bad_position", "Only a tyre has a position, like steer_left.")
    opened = capture_time(body.occurred_at)
    photo_ids: list[str] = []
    for pid, cid in [(p, None) for p in body.photo_ids] + [(None, c) for c in body.photo_client_ids]:
        photo = await claim_photo(db, principal, pid, PhotoKind.REPAIR, required=False, client_id=cid, near=opened)
        if photo is not None:
            photo_ids.append(str(photo.id))
    title = KINDS[body.kind] + (f" ({position.replace('_', ' ')})" if position else "") + (": do not drive" if not body.can_drive else ": driver request")
    wo = WorkOrder(
        vehicle_id=crew.vehicle_id, source=WorkOrderSource.MANUAL, title=title[:160],
        description=(body.description or "").strip() or None, opened_at=opened,
        priority=Priority.URGENT if not body.can_drive else Priority.HIGH if body.kind in ("brakes", "tyre") else Priority.NORMAL,
        created_by_user_id=principal.user.id, parts=[], photo_ids=photo_ids,
    )  # fmt: skip
    db.add(wo)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="work_order.requested", entity_type="work_order", entity_id=wo.id,
        after={"kind": body.kind, "position": position, "can_drive": body.can_drive},
    )  # fmt: skip
    return wo


@router.post("/me/repair-requests", status_code=status.HTTP_201_CREATED)
async def request_repair(body: RepairIn, principal: Principal = Depends(require("trips.own")), db: AsyncSession = Depends(get_db)):
    wo = await do_request_repair(db, principal, body)
    await db.commit()
    registration = (await db.execute(select(Vehicle.registration).where(Vehicle.id == wo.vehicle_id))).scalar_one()
    return _request_out(wo, registration, await photos_by_id(db, wo.photo_ids))


@router.get("/me/repair-requests")
async def my_repair_requests(principal: Principal = Depends(require("trips.own")), db: AsyncSession = Depends(get_db)):
    """The requests this person raised, newest first, so they can see whether the workshop has picked them up."""
    rows = (
        await db.execute(
            select(WorkOrder, Vehicle.registration)
            .join(Vehicle, Vehicle.id == WorkOrder.vehicle_id)
            .where(WorkOrder.created_by_user_id == principal.user.id, WorkOrder.source == WorkOrderSource.MANUAL)
            .order_by(WorkOrder.opened_at.desc())
            .limit(20)
        )
    ).all()
    photos = await photos_by_id(db, [i for wo, _ in rows for i in wo.photo_ids])
    return [_request_out(wo, registration, photos) for wo, registration in rows]


@router.get("/me/trip-history")
async def my_trip_history(
    limit: int = 30, principal: Principal = Depends(require("trips.own")), db: AsyncSession = Depends(get_db)
):
    """Trips this person has finished, newest first."""
    if principal.membership_id is None:
        return []
    query = (
        select(Trip)
        .where(
            or_(Trip.driver_membership_id == principal.membership_id, Trip.turnboy_membership_id == principal.membership_id),
            Trip.status == TripStatus.COMPLETED,
        )
        .order_by(Trip.ended_at.desc().nulls_last(), Trip.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [await trip_out(db, t) for t in (await db.execute(query)).scalars()]


@router.get("/me/pay")
async def my_pay(principal: Principal = Depends(require("trips.own")), db: AsyncSession = Depends(get_db)):
    """This person's own pay for months the owner has approved: pay, advances and fines taken, and what is left. Nobody else's."""
    if principal.membership_id is None:
        return []
    rows = (
        await db.execute(
            select(PayrollRun, PayrollLine)
            .join(PayrollLine, PayrollLine.run_id == PayrollRun.id)
            .where(PayrollLine.membership_id == principal.membership_id, PayrollRun.status.in_(PAID_RUNS))
            .order_by(PayrollRun.month.desc())
            .limit(12)
        )
    ).all()
    return [
        {
            "month": run.month, "status": run.status, "paid_on": run.paid_on, "gross_cents": line.gross_cents,
            "advances_cents": line.advances_cents, "fines_cents": line.fines_cents, "net_cents": line.net_cents,
        }
        for run, line in rows
    ]  # fmt: skip

