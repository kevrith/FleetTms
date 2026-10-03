"""Driver messaging (masterplan 5.27): announcements and direct messages from the office to drivers, with read receipts, optionally about a
job so that instructions are on record instead of lost in phone calls."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import (
    Business,
    CrewAssignment,
    Job,
    Membership,
    MembershipStatus,
    Message,
    MessageRecipient,
    Role,
    Trip,
)
from app.sms import get_sms_sender

router = APIRouter(tags=["messages"])
DRIVER_ROLES = {Role.DRIVER, Role.TURNBOY}


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    all_drivers: bool = False  # everyone who drives for the business (a supervisor: those on their own vehicles)
    membership_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    job_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    also_sms: bool = False  # for a driver who is not looking at the app: a short text as well

    @model_validator(mode="after")
    def _someone(self):
        if self.all_drivers == bool(self.membership_ids):
            raise ValueError("Send it to all drivers, or choose who it is for, not both and not neither.")
        return self


def _is_driver(m: Membership) -> bool:
    return bool({r.role for r in m.roles} & DRIVER_ROLES)


async def _audience(db: AsyncSession, principal: Principal) -> dict[uuid.UUID, Membership]:
    """The drivers this person may message: all of them, or for a supervisor those crewing the vehicles they look after."""
    members = {m.id: m for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars() if _is_driver(m)}
    if principal.vehicle_scope is None:
        return members
    scope = []
    for v in principal.vehicle_scope:
        try:
            scope.append(uuid.UUID(v))
        except ValueError:
            continue
    mine = set((await db.execute(select(CrewAssignment.membership_id).where(CrewAssignment.vehicle_id.in_(scope), CrewAssignment.ended_at.is_(None)))).scalars())
    return {k: m for k, m in members.items() if k in mine}


def sender_out(msg: Message, rows: list[MessageRecipient], names: dict[uuid.UUID, str], sender: str | None) -> dict:
    return {
        "id": msg.id, "kind": msg.kind, "body": msg.body, "job_id": msg.job_id, "trip_id": msg.trip_id, "also_sms": msg.also_sms, "created_at": msg.created_at, "from": sender,
        "recipients": len(rows), "read": sum(1 for r in rows if r.read_at is not None),
        "receipts": [{"membership_id": r.membership_id, "name": names.get(r.membership_id), "read_at": r.read_at, "sms_sent": r.sms_sent} for r in sorted(rows, key=lambda r: names.get(r.membership_id) or "")],
    }  # fmt: skip


@router.post("/messages", status_code=status.HTTP_201_CREATED)
async def send_message(body: MessageIn, principal: Principal = Depends(require("messages.send")), db: AsyncSession = Depends(get_db)):
    audience = await _audience(db, principal)
    if body.all_drivers:
        chosen = list(audience.values())
    else:
        unknown = [i for i in body.membership_ids if i not in audience]
        if unknown:
            raise error(422, "not_a_driver", "You can only message the drivers you look after, and each one must be an active driver or turnboy.")
        chosen = [audience[i] for i in dict.fromkeys(body.membership_ids)]
    if not chosen:
        raise error(422, "nobody", "There is nobody to send that to yet.")
    if body.job_id is not None and (await db.execute(select(Job.id).where(Job.id == body.job_id))).first() is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That job was not found.")
    if body.trip_id is not None and (await db.execute(select(Trip.id).where(Trip.id == body.trip_id))).first() is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That trip was not found.")
    msg = Message(sender_user_id=principal.user.id, kind="direct" if len(chosen) == 1 and not body.all_drivers else "announcement", body=body.body.strip(), job_id=body.job_id, trip_id=body.trip_id, also_sms=body.also_sms)
    db.add(msg)
    await db.flush()
    rows = []
    business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
    for m in chosen:
        row = MessageRecipient(message_id=msg.id, membership_id=m.id)
        if body.also_sms and m.user.phone:
            await get_sms_sender().send(m.user.phone, f"{business.name}: {body.body.strip()[:130]}")
            row.sms_sent = True
        db.add(row)
        rows.append(row)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="message.sent", entity_type="message", entity_id=msg.id, after={"kind": msg.kind, "recipients": len(rows), "job_id": str(body.job_id) if body.job_id else None})
    await db.commit()
    names = {m.id: m.user.name for m in chosen}
    return sender_out(msg, rows, names, principal.user.name)


@router.get("/messages")
async def sent_messages(job_id: uuid.UUID | None = None, limit: int = 50, principal: Principal = Depends(require("messages.send")), db: AsyncSession = Depends(get_db)):
    """What has been sent, and who has read it. A supervisor sees their own messages only; owner and manager see all."""
    query = select(Message).order_by(Message.created_at.desc()).limit(min(max(limit, 1), 200))
    if job_id:
        query = query.where(Message.job_id == job_id)
    if principal.vehicle_scope is not None:
        query = query.where(Message.sender_user_id == principal.user.id)
    msgs = list((await db.execute(query)).scalars())
    rows: dict[uuid.UUID, list[MessageRecipient]] = {m.id: [] for m in msgs}
    for r in (await db.execute(select(MessageRecipient).where(MessageRecipient.message_id.in_(list(rows))))).scalars() if rows else []:
        rows[r.message_id].append(r)
    members = {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    senders = {m.user_id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    return [sender_out(m, rows[m.id], members, senders.get(m.sender_user_id)) for m in msgs]


@router.get("/me/messages")
async def my_messages(principal: Principal = Depends(require_any("trips.own")), db: AsyncSession = Depends(get_db)):
    """A driver's inbox, newest first, with how many are still unread."""
    mine = (await db.execute(select(MessageRecipient).where(MessageRecipient.membership_id == principal.membership_id))).scalars().all()
    by_message = {r.message_id: r for r in mine}
    msgs = list((await db.execute(select(Message).where(Message.id.in_(list(by_message))).order_by(Message.created_at.desc()).limit(100))).scalars()) if by_message else []
    senders = {m.user_id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    return {
        "unread": sum(1 for r in mine if r.read_at is None),
        "messages": [{"id": m.id, "kind": m.kind, "body": m.body, "job_id": m.job_id, "trip_id": m.trip_id, "from": senders.get(m.sender_user_id), "created_at": m.created_at, "read_at": by_message[m.id].read_at} for m in msgs],
    }  # fmt: skip


@router.post("/me/messages/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(message_id: uuid.UUID, principal: Principal = Depends(require_any("trips.own")), db: AsyncSession = Depends(get_db)):
    """The read receipt. Safe to repeat: the first time it was read is kept."""
    row = (await db.execute(select(MessageRecipient).where(MessageRecipient.message_id == message_id, MessageRecipient.membership_id == principal.membership_id))).scalar_one_or_none()
    if row is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That message was not found.")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await db.commit()

