"""A driver's float: what the owner sent, less what they spent (masterplan 5.6).

balance = floats sent - expenses paid from the float, counting only expenses that are in force (recorded or approved).
A day's sheet is the same sum cut at Nairobi midnight: opening + floats - expenses = closing.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import COUNTED, Expense, FloatTransfer
from app.reminders import NAIROBI


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """The start and end of a Nairobi day, as UTC moments (end is the start of the next day)."""
    start = datetime(day.year, day.month, day.day, tzinfo=NAIROBI).astimezone(UTC)
    return start, start + timedelta(days=1)


async def _sums(db: AsyncSession, membership_id: uuid.UUID, start: datetime | None, end: datetime | None) -> tuple[int, int]:
    floats = select(func.coalesce(func.sum(FloatTransfer.amount_cents), 0)).where(
        FloatTransfer.driver_membership_id == membership_id
    )
    spent = select(func.coalesce(func.sum(Expense.amount_cents), 0)).where(
        Expense.driver_membership_id == membership_id, Expense.from_float.is_(True), Expense.status.in_(COUNTED)
    )
    if start is not None:
        floats, spent = floats.where(FloatTransfer.sent_at >= start), spent.where(Expense.spent_at >= start)
    if end is not None:
        floats, spent = floats.where(FloatTransfer.sent_at < end), spent.where(Expense.spent_at < end)
    return int((await db.execute(floats)).scalar_one()), int((await db.execute(spent)).scalar_one())


async def float_balance(db: AsyncSession, membership_id: uuid.UUID) -> int:
    floats, spent = await _sums(db, membership_id, None, None)
    return floats - spent


async def day_sheet(db: AsyncSession, membership_id: uuid.UUID, day: date) -> dict[str, int]:
    start, end = day_bounds(day)
    before_floats, before_spent = await _sums(db, membership_id, None, start)
    floats, spent = await _sums(db, membership_id, start, end)
    opening = before_floats - before_spent
    return {"opening_cents": opening, "floats_cents": floats, "expenses_cents": spent, "closing_cents": opening + floats - spent}
