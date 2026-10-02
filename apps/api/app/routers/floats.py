import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import FloatTransfer, Membership, MembershipStatus, Role

router = APIRouter(tags=["floats"])
MPESA = re.compile(r"^[A-Z0-9]{10}$")


class FloatIn(BaseModel):
    driver_membership_id: uuid.UUID
    amount_cents: int = Field(gt=0, le=100_000_000)
    mpesa_code: str | None = None
    note: str | None = Field(default=None, max_length=255)
    sent_at: datetime | None = None


def _out(f: FloatTransfer) -> dict:
    return {
        "id": f.id, "driver_membership_id": f.driver_membership_id, "amount_cents": f.amount_cents,
        "mpesa_code": f.mpesa_code, "note": f.note, "sent_at": f.sent_at,
    }  # fmt: skip


@router.post("/floats", status_code=status.HTTP_201_CREATED)
async def send_float(
    body: FloatIn, principal: Principal = Depends(require("floats.manage")), db: AsyncSession = Depends(get_db)
):
    """Records money the owner sent a driver. The money moves in M-Pesa; this keeps the record and the balance."""
    member = (await db.execute(select(Membership).where(Membership.id == body.driver_membership_id))).scalar_one_or_none()
    roles = {r.role for r in member.roles} if member else set()
    if member is None or member.status != MembershipStatus.ACTIVE or not roles & {Role.DRIVER, Role.TURNBOY}:
        raise error(422, "wrong_recipient", "Floats go to an active driver or turnboy.")
    code = body.mpesa_code.strip().upper() if body.mpesa_code else None
    if code and not MPESA.match(code):
        raise error(422, "invalid_mpesa_code", "An M-Pesa code is 10 letters and numbers, like QGH7XYZ123.")
    sent_at = body.sent_at or datetime.now(UTC)
    if sent_at > datetime.now(UTC):
        raise error(422, "bad_time", "A float cannot be sent in the future.")
    transfer = FloatTransfer(
        driver_membership_id=member.id, amount_cents=body.amount_cents, mpesa_code=code, note=body.note,
        sent_at=sent_at, created_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(transfer)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_mpesa_code", "That M-Pesa code was already recorded.") from None
    audit.record(
        db, actor_user_id=principal.user.id, action="float.sent", entity_type="float_transfer", entity_id=transfer.id,
        after={"driver_membership_id": str(member.id), "amount_cents": body.amount_cents, "mpesa_code": code},
    )  # fmt: skip
    await db.commit()
    return _out(transfer)


@router.get("/floats")
async def list_floats(
    driver_membership_id: uuid.UUID | None = None,
    principal: Principal = Depends(require_any("floats.manage", "finance.view")),
    db: AsyncSession = Depends(get_db),
):
    query = select(FloatTransfer).order_by(FloatTransfer.sent_at.desc()).limit(200)
    if driver_membership_id:
        query = query.where(FloatTransfer.driver_membership_id == driver_membership_id)
    return [_out(f) for f in (await db.execute(query)).scalars()]


@router.get("/me/float")
async def my_float(principal: Principal = Depends(require("expenses.own")), db: AsyncSession = Depends(get_db)):
    """The driver's float: what has been sent to them. Expenses are subtracted from Sprint 5."""
    if principal.membership_id is None:
        return {"balance_cents": 0, "received_cents": 0, "recent": []}
    mine = FloatTransfer.driver_membership_id == principal.membership_id
    received = (await db.execute(select(func.coalesce(func.sum(FloatTransfer.amount_cents), 0)).where(mine))).scalar_one()
    recent = (await db.execute(select(FloatTransfer).where(mine).order_by(FloatTransfer.sent_at.desc()).limit(10))).scalars()
    return {"balance_cents": int(received), "received_cents": int(received), "recent": [_out(f) for f in recent]}
