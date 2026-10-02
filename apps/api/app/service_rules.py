"""When a service is due: by kilometres, by time, or both, whichever comes first (masterplan 5.8)."""

import calendar
from dataclasses import dataclass
from datetime import date


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class ServiceDue:
    status: str  # ok, due_soon or overdue
    next_km: int | None
    km_left: int | None
    next_due_on: date | None
    days_left: int | None

    @property
    def key(self) -> str:
        """Identifies one due occurrence, so it is reminded about once."""
        return f"{self.next_km or ''}|{self.next_due_on.isoformat() if self.next_due_on else ''}"


def service_due(
    *,
    every_km: int | None,
    every_months: int | None,
    last_done_km: int,
    last_done_on: date | None,
    advance_km: int,
    advance_days: int,
    odometer_km: int,
    today: date,
    started_on: date,
) -> ServiceDue:
    next_km = km_left = next_due_on = days_left = None
    if every_km:
        next_km = last_done_km + every_km
        km_left = next_km - odometer_km
    if every_months:
        next_due_on = add_months(last_done_on or started_on, every_months)
        days_left = (next_due_on - today).days
    overdue = (km_left is not None and km_left <= 0) or (days_left is not None and days_left <= 0)
    soon = (km_left is not None and km_left <= advance_km) or (days_left is not None and days_left <= advance_days)
    return ServiceDue("overdue" if overdue else "due_soon" if soon else "ok", next_km, km_left, next_due_on, days_left)
