"""Data protection requests from the business's own people (masterplan 11.2 item 6).

The business is the controller of its staff's data, so it answers; FleetTms gives it the tools. A person can ask to see their data,
have it corrected, taken away, or used less, and to receive a copy they can move elsewhere. The owner sees each request with the date by
which it must be answered, can download everything held about the person, can remove the person (their staff details go and they become
anonymous; what they did stays as the business's record, which the law may require it to keep), and must give a reason to refuse."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, person_data, retention
from app.config import settings
from app.db import get_db
from app.deps import Principal, current_principal, error, require
from app.models import DataSubjectRequest, Membership, MembershipStatus, Role
from app.reminders import nairobi_today

router = APIRouter(tags=["privacy"])

Kind = Literal["access", "correct", "delete", "object", "portability"]


class RequestIn(BaseModel):
    kind: Kind
    details: str | None = Field(default=None, max_length=2000)


class OnBehalfIn(RequestIn):
    membership_id: uuid.UUID


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=3, max_length=2000)


class RefuseIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


def out(r: DataSubjectRequest, names: dict[uuid.UUID, str], today: date) -> dict:
    return {
        "id": r.id, "kind": r.kind, "details": r.details, "status": r.status, "due_on": r.due_on, "resolution": r.resolution, "created_at": r.created_at, "resolved_at": r.resolved_at,
        "membership_id": r.membership_id, "person": names.get(r.membership_id) if r.membership_id else None,
        "overdue": r.status == "open" and r.due_on < today, "days_left": (r.due_on - today).days if r.status == "open" else None,
    }  # fmt: skip


async def _names(db: AsyncSession) -> dict[uuid.UUID, str]:
    return {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}


def _new(principal: Principal, membership_id: uuid.UUID, body: RequestIn) -> DataSubjectRequest:
    return DataSubjectRequest(
        membership_id=membership_id, requested_by_user_id=principal.user.id, kind=body.kind, details=body.details,
        due_on=nairobi_today() + timedelta(days=settings.dsar_due_days),
    )  # fmt: skip


@router.post("/me/data-requests", status_code=status.HTTP_201_CREATED)
async def ask_about_myself(body: RequestIn, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    """Any signed-in person asks their employer about their own data."""
    if principal.business_id is None or principal.membership_id is None or principal.support:
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "You do not have permission to do this.")
    row = _new(principal, principal.membership_id, body)
    db.add(row)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="privacy.request_made", entity_type="data_subject_request", entity_id=row.id, after={"kind": body.kind})
    await db.commit()
    return out(row, await _names(db), nairobi_today())


@router.get("/me/data-requests")
async def my_requests(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    if principal.business_id is None or principal.membership_id is None:
        return []
    rows = (await db.execute(select(DataSubjectRequest).where(DataSubjectRequest.membership_id == principal.membership_id).order_by(DataSubjectRequest.created_at.desc()))).scalars().all()
    today = nairobi_today()
    return [out(r, {}, today) for r in rows]


@router.post("/data-requests", status_code=status.HTTP_201_CREATED)
async def log_request(body: OnBehalfIn, principal: Principal = Depends(require("privacy.manage")), db: AsyncSession = Depends(get_db)):
    """The owner records a request someone made in person or by phone, so the clock starts and the answer is on record."""
    if (await db.execute(select(Membership.id).where(Membership.id == body.membership_id))).first() is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That person was not found.")
    row = _new(principal, body.membership_id, body)
    db.add(row)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="privacy.request_logged", entity_type="data_subject_request", entity_id=row.id, after={"kind": body.kind}, note="Recorded on the person's behalf")
    await db.commit()
    return out(row, await _names(db), nairobi_today())


@router.get("/data-requests")
async def list_requests(state: str | None = None, principal: Principal = Depends(require("privacy.manage")), db: AsyncSession = Depends(get_db)):
    stmt = select(DataSubjectRequest).order_by(DataSubjectRequest.due_on, DataSubjectRequest.created_at)
    if state:
        stmt = stmt.where(DataSubjectRequest.status == state)
    names, today = await _names(db), nairobi_today()
    return [out(r, names, today) for r in (await db.execute(stmt)).scalars()]


@router.get("/data-requests/summary")
async def summary(principal: Principal = Depends(require("privacy.manage")), db: AsyncSession = Depends(get_db)):
    today = nairobi_today()
    open_rows = (await db.execute(select(DataSubjectRequest).where(DataSubjectRequest.status == "open"))).scalars().all()
    return {"open": len(open_rows), "overdue": sum(1 for r in open_rows if r.due_on < today), "answer_within_days": settings.dsar_due_days}


async def _get(db: AsyncSession, request_id: uuid.UUID) -> DataSubjectRequest:
    row = (await db.execute(select(DataSubjectRequest).where(DataSubjectRequest.id == request_id))).scalar_one_or_none()
    if row is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That request was not found.")
    return row


async def _open(db: AsyncSession, request_id: uuid.UUID) -> DataSubjectRequest:
    row = await _get(db, request_id)
    if row.status != "open":
        raise error(status.HTTP_409_CONFLICT, "already_answered", "That request has already been answered.")
    return row


async def _person(db: AsyncSession, row: DataSubjectRequest) -> Membership:
    membership = (await db.execute(select(Membership).where(Membership.id == row.membership_id))).scalar_one_or_none() if row.membership_id else None
    if membership is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That person was not found.")
    return membership


@router.get("/data-requests/{request_id}/export")
async def export_person(request_id: uuid.UUID, principal: Principal = Depends(require("privacy.manage")), db: AsyncSession = Depends(get_db)):
    """Everything held about the person, as a zip of spreadsheets, to give to them."""
    row = await _get(db, request_id)
    membership = await _person(db, row)
    data, counts = await person_data.build(db, membership)
    audit.record(db, actor_user_id=principal.user.id, action="privacy.person_data_exported", entity_type="data_subject_request", entity_id=row.id, after={"rows": sum(counts.values())})
    await db.commit()
    return Response(data, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="personal-data.zip"'})


@router.post("/data-requests/{request_id}/apply-deletion")
async def apply_deletion(request_id: uuid.UUID, principal: Principal = Depends(require("privacy.manage")), db: AsyncSession = Depends(get_db)):
    """Removes the person: staff details and personal documents are deleted, sign-in ends, and they become anonymous if they work for no
    one else. What they did stays under the anonymous name, because those are the business's own records."""
    row = await _open(db, request_id)
    if row.kind != "delete":
        raise error(status.HTTP_409_CONFLICT, "not_a_deletion", "Only a request to delete can remove the person.")
    membership = await _person(db, row)
    owners = (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars().all()
    if Role.OWNER in {r.role for r in membership.roles} and sum(1 for m in owners if Role.OWNER in {r.role for r in m.roles}) < 2:
        raise error(status.HTTP_409_CONFLICT, "last_owner", "The only owner cannot be removed. Add another owner first, or close the business.")
    anonymous = await retention.anonymise_membership(db, membership, datetime.now(UTC))
    audit.record(db, actor_user_id=principal.user.id, action="privacy.person_removed", entity_type="membership", entity_id=membership.id, after={"anonymous": anonymous}, note="Data protection request to delete")
    await db.commit()
    return {"removed": True, "anonymous": anonymous}


@router.post("/data-requests/{request_id}/complete")
async def complete(request_id: uuid.UUID, body: ResolveIn, principal: Principal = Depends(require("privacy.manage")), db: AsyncSession = Depends(get_db)):
    row = await _open(db, request_id)
    if row.kind == "delete":
        membership = await _person(db, row)
        if membership.anonymised_at is None:
            raise error(status.HTTP_409_CONFLICT, "not_applied", "Remove the person first, or refuse the request with a reason.")
    row.status, row.resolution, row.resolved_by_user_id, row.resolved_at = "completed", body.resolution, principal.user.id, datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="privacy.request_completed", entity_type="data_subject_request", entity_id=row.id, after={"kind": row.kind})
    await db.commit()
    return out(row, await _names(db), nairobi_today())


@router.post("/data-requests/{request_id}/refuse")
async def refuse(request_id: uuid.UUID, body: RefuseIn, principal: Principal = Depends(require("privacy.manage")), db: AsyncSession = Depends(get_db)):
    """A request may be refused where the law requires the data to be kept, but the person is owed the reason."""
    row = await _open(db, request_id)
    row.status, row.resolution, row.resolved_by_user_id, row.resolved_at = "refused", body.reason, principal.user.id, datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="privacy.request_refused", entity_type="data_subject_request", entity_id=row.id, after={"kind": row.kind}, note=body.reason[:200])
    await db.commit()
    return out(row, await _names(db), nairobi_today())
