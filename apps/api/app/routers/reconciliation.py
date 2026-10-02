"""Daily float reconciliation (masterplan 5.6): opening + floats - expenses = closing, approved by someone senior."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.floatcalc import day_bounds, day_sheet
from app.models import (
    CrewAssignment,
    Expense,
    ExpenseStatus,
    FloatTransfer,
    Membership,
    Reconciliation,
    ReconciliationStatus,
)
from app.reminders import nairobi_today
from app.routers.expenses import _with_receipts
from app.vehicle_scope import vehicle_in_scope

router = APIRouter(tags=["reconciliation"])
ACTIONS = {"carry_forward", "returned"}


class SubmitIn(BaseModel):
    day: date | None = None  # the Nairobi day; today when left out
    captured_at: datetime | None = None


class ApproveIn(BaseModel):
    balance_action: str = "carry_forward"
    note: str | None = Field(default=None, max_length=255)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=255)


def _out(r: Reconciliation, name: str | None = None) -> dict:
    return {
        "id": r.id, "driver_membership_id": r.driver_membership_id, "driver_name": name, "day": r.day,
        "opening_cents": r.opening_cents, "floats_cents": r.floats_cents, "expenses_cents": r.expenses_cents,
        "closing_cents": r.closing_cents, "status": r.status.value, "balance_action": r.balance_action,
        "note": r.note, "submitted_at": r.submitted_at, "decided_at": r.decided_at,
    }  # fmt: skip


async def _day_expenses(db: AsyncSession, membership_id: uuid.UUID, day: date) -> list[Expense]:
    start, end = day_bounds(day)
    query = select(Expense).where(
        Expense.driver_membership_id == membership_id, Expense.from_float.is_(True), Expense.spent_at >= start, Expense.spent_at < end
    ).order_by(Expense.spent_at)
    return list((await db.execute(query)).scalars())


async def _pending_count(db: AsyncSession, membership_id: uuid.UUID, day: date) -> int:
    start, end = day_bounds(day)
    return int(
        (
            await db.execute(
                select(func.count()).select_from(Expense).where(
                    Expense.driver_membership_id == membership_id, Expense.from_float.is_(True),
                    Expense.status == ExpenseStatus.AWAITING_APPROVAL, Expense.spent_at >= start, Expense.spent_at < end,
                )
            )
        ).scalar_one()
    )


async def _can_decide(db: AsyncSession, principal: Principal, record: Reconciliation) -> bool:
    """Owners and managers decide on anyone's float. A supervisor only for drivers on their own vehicles."""
    if principal.vehicle_scope is None:
        return True
    expenses = await _day_expenses(db, record.driver_membership_id, record.day)
    crew = (
        await db.execute(
            select(CrewAssignment.vehicle_id).where(
                CrewAssignment.membership_id == record.driver_membership_id, CrewAssignment.ended_at.is_(None)
            )
        )
    ).scalars().all()
    vehicles = {e.vehicle_id for e in expenses if e.vehicle_id} | set(crew)
    return any(vehicle_in_scope(principal, v) for v in vehicles)


@router.get("/me/reconciliation")
async def my_sheet(
    day: date | None = None, principal: Principal = Depends(require("expenses.own")), db: AsyncSession = Depends(get_db)
):
    """Today's float sheet for the driver, and where it stands: not yet submitted, waiting, approved or sent back."""
    if principal.membership_id is None:
        raise error(status.HTTP_403_FORBIDDEN, "not_a_driver", "Only drivers and turnboys have a float.")
    day = day or nairobi_today()
    record = (
        await db.execute(
            select(Reconciliation).where(Reconciliation.driver_membership_id == principal.membership_id, Reconciliation.day == day)
        )
    ).scalar_one_or_none()
    sheet = await day_sheet(db, principal.membership_id, day)
    return {
        "day": day, **sheet, "status": record.status.value if record else "open",
        "note": record.note if record else None, "reconciliation": _out(record) if record else None,
        "expenses": await _with_receipts(db, await _day_expenses(db, principal.membership_id, day)),
    }


async def do_submit_reconciliation(db: AsyncSession, principal: Principal, day: date | None) -> Reconciliation:
    if principal.membership_id is None:
        raise error(status.HTTP_403_FORBIDDEN, "not_a_driver", "Only drivers and turnboys have a float.")
    day = day or nairobi_today()
    if day > nairobi_today():
        raise error(422, "future_day", "You cannot reconcile a day that has not happened.")
    record = (
        await db.execute(
            select(Reconciliation).where(Reconciliation.driver_membership_id == principal.membership_id, Reconciliation.day == day)
        )
    ).scalar_one_or_none()
    if record is not None and record.status == ReconciliationStatus.APPROVED:
        raise error(status.HTTP_409_CONFLICT, "already_approved", "That day has already been approved.")
    sheet = await day_sheet(db, principal.membership_id, day)
    if record is None:
        record = Reconciliation(driver_membership_id=principal.membership_id, day=day, status=ReconciliationStatus.SUBMITTED, **sheet)
        db.add(record)
    else:
        for field, value in sheet.items():
            setattr(record, field, value)
        record.status, record.note, record.submitted_at = ReconciliationStatus.SUBMITTED, None, datetime.now(UTC)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="reconciliation.submitted", entity_type="reconciliation",
        entity_id=record.id, after={"day": day.isoformat(), **{k: v for k, v in sheet.items()}},
    )  # fmt: skip
    return record


@router.post("/me/reconciliation/submit")
async def submit_sheet(
    body: SubmitIn | None = None, principal: Principal = Depends(require("expenses.own")), db: AsyncSession = Depends(get_db)
):
    record = await do_submit_reconciliation(db, principal, (body or SubmitIn()).day)
    await db.commit()
    return _out(record)


@router.get("/reconciliations")
async def list_reconciliations(
    status_filter: ReconciliationStatus | None = None,
    day: date | None = None,
    principal: Principal = Depends(require_any("reconciliations.approve", "finance.view")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Reconciliation).order_by(Reconciliation.day.desc(), Reconciliation.submitted_at.desc()).limit(200)
    if status_filter:
        query = query.where(Reconciliation.status == status_filter)
    if day:
        query = query.where(Reconciliation.day == day)
    rows = list((await db.execute(query)).scalars())
    names = {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    visible = [r for r in rows if await _can_decide(db, principal, r)] if principal.vehicle_scope is not None else rows
    return [_out(r, names.get(r.driver_membership_id)) for r in visible]


async def _get(db: AsyncSession, principal: Principal, record_id: uuid.UUID) -> Reconciliation:
    record = (await db.execute(select(Reconciliation).where(Reconciliation.id == record_id))).scalar_one_or_none()
    if record is None or not await _can_decide(db, principal, record):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That reconciliation was not found.")
    return record


@router.get("/reconciliations/{record_id}")
async def read_reconciliation(
    record_id: uuid.UUID, principal: Principal = Depends(require("reconciliations.approve")), db: AsyncSession = Depends(get_db)
):
    record = await _get(db, principal, record_id)
    member = (await db.execute(select(Membership).where(Membership.id == record.driver_membership_id))).scalar_one_or_none()
    return _out(record, member.user.name if member else None) | {
        "expenses": await _with_receipts(db, await _day_expenses(db, record.driver_membership_id, record.day)),
        "pending_expenses": await _pending_count(db, record.driver_membership_id, record.day),
    }


@router.post("/reconciliations/{record_id}/approve")
async def approve(
    record_id: uuid.UUID,
    body: ApproveIn,
    principal: Principal = Depends(require("reconciliations.approve")),
    db: AsyncSession = Depends(get_db),
):
    """Approves the day. The leftover balance is carried forward, or the driver returns the cash and it goes to zero."""
    record = await _get(db, principal, record_id)
    if record.status != ReconciliationStatus.SUBMITTED:
        raise error(status.HTTP_409_CONFLICT, "not_submitted", "Only a submitted day can be approved.")
    if body.balance_action not in ACTIONS:
        raise error(422, "bad_action", "Choose carry_forward or returned.")
    # Expenses over a limit have not been counted yet; the owner decides on them before the day can close.
    pending = await _pending_count(db, record.driver_membership_id, record.day)
    if pending:
        raise error(
            status.HTTP_409_CONFLICT, "pending_expenses",
            f"{pending} expense{'s are' if pending != 1 else ' is'} still waiting for the owner's approval.",
        )  # fmt: skip
    sheet = await day_sheet(db, record.driver_membership_id, record.day)
    for field, value in sheet.items():
        setattr(record, field, value)  # the figures as they stand now
    if body.balance_action == "returned":
        if record.closing_cents < 0:
            raise error(422, "nothing_to_return", "The driver overspent, so there is no cash to return.")
        if record.closing_cents > 0:
            _, end = day_bounds(record.day)
            db.add(
                FloatTransfer(
                    driver_membership_id=record.driver_membership_id, amount_cents=-record.closing_cents,
                    note=f"Returned at reconciliation for {record.day.isoformat()}", sent_at=min(end, datetime.now(UTC)),
                    created_by_user_id=principal.user.id,
                )
            )  # fmt: skip
    record.status = ReconciliationStatus.APPROVED
    record.balance_action, record.note = body.balance_action, body.note
    record.decided_by_user_id, record.decided_at = principal.user.id, datetime.now(UTC)
    audit.record(
        db, actor_user_id=principal.user.id, action="reconciliation.approved", entity_type="reconciliation",
        entity_id=record.id, after={"day": record.day.isoformat(), "closing_cents": record.closing_cents, "balance_action": body.balance_action},
        note=body.note,
    )  # fmt: skip
    await db.commit()
    return _out(record)


@router.post("/reconciliations/{record_id}/reject")
async def reject(
    record_id: uuid.UUID,
    body: RejectIn,
    principal: Principal = Depends(require("reconciliations.approve")),
    db: AsyncSession = Depends(get_db),
):
    """Sends the day back to the driver with a reason; they fix it and submit again."""
    record = await _get(db, principal, record_id)
    if record.status != ReconciliationStatus.SUBMITTED:
        raise error(status.HTTP_409_CONFLICT, "not_submitted", "Only a submitted day can be sent back.")
    record.status, record.note = ReconciliationStatus.REJECTED, body.note
    record.decided_by_user_id, record.decided_at = principal.user.id, datetime.now(UTC)
    audit.record(
        db, actor_user_id=principal.user.id, action="reconciliation.rejected", entity_type="reconciliation",
        entity_id=record.id, after={"day": record.day.isoformat()}, note=body.note,
    )  # fmt: skip
    await db.commit()
    return _out(record)


