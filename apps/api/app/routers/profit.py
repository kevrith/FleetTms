"""The profit engine's reports (masterplan 5.15): by trip, vehicle, client, driver, depot and business, in whole months."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Principal, error, require_any
from app.lease_rules import add_months
from app.profit import build
from app.reminders import nairobi_today

router = APIRouter(tags=["profit"])
MAX_MONTHS = 24


@router.get("/profit")
async def profit(
    from_month: date | None = Query(default=None), to_month: date | None = Query(default=None), include_trips: bool = False,
    principal: Principal = Depends(require_any("finance.view")), db: AsyncSession = Depends(get_db),
):  # fmt: skip
    """Profit for the calendar months from `from_month` to `to_month` (any day in each). Defaults to this month."""
    last = (to_month or nairobi_today()).replace(day=1)
    first = (from_month or last).replace(day=1)
    if first > last:
        raise error(422, "bad_range", "The first month is after the last month.")
    if add_months(first, MAX_MONTHS) <= last:
        raise error(422, "range_too_long", f"Choose {MAX_MONTHS} months or fewer.")
    out = await build(db, first, last)
    if not include_trips:
        out["trips"] = out["trips"][:0]
    return out
