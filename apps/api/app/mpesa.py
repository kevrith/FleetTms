"""M-Pesa codes. One code can back one claim, whether it was claimed as fuel or as an expense."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Expense, FinanceInstalment, FuelEntry, LeaseEntry, SalaryAdvance

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
    """True if a fuel entry, an expense, a lease payment, a loan repayment or a salary advance in this business already used the code."""
    for model in (FuelEntry, Expense, LeaseEntry, FinanceInstalment, SalaryAdvance):
        if (await db.execute(select(model.id).where(model.mpesa_code == code).limit(1))).first() is not None:
            return True
    return False
