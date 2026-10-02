"""M-Pesa codes. One code can back one claim, whether it was claimed as fuel or as an expense."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Expense, FuelEntry

PATTERN = re.compile(r"^[A-Z0-9]{10}$")


def tidy(raw: str | None) -> str | None:
    """The code in capitals, or None if nothing was given. Raises ValueError if it is not a valid code."""
    if raw is None or not raw.strip():
        return None
    code = raw.strip().upper()
    if not PATTERN.match(code):
        raise ValueError("An M-Pesa code is 10 letters and numbers, like QGH7XYZ123.")
    return code


async def taken(db: AsyncSession, code: str) -> bool:
    """True if a fuel entry or an expense in this business already used the code."""
    fuel = (await db.execute(select(FuelEntry.id).where(FuelEntry.mpesa_code == code).limit(1))).first()
    spent = (await db.execute(select(Expense.id).where(Expense.mpesa_code == code).limit(1))).first()
    return fuel is not None or spent is not None
