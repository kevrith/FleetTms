"""When recurring work falls due. Pure date arithmetic, so it can be tested without a database."""

from datetime import date, datetime, time, timedelta

from app.reminders import NAIROBI

CADENCES = ("daily", "weekly", "monthly")


def due_dates(cadence: str, *, weekdays: list[int], day_of_month: int | None, starts_on: date, ends_on: date | None, first: date, last: date) -> list[date]:
    """Every day from `first` to `last` (inclusive) on which the schedule falls, no earlier than it starts and no later than it ends."""
    out = []
    day = max(first, starts_on)
    stop = min(last, ends_on) if ends_on else last
    while day <= stop:
        if cadence == "daily" or (cadence == "weekly" and day.weekday() in weekdays) or (cadence == "monthly" and day.day == day_of_month):
            out.append(day)
        day += timedelta(days=1)
    return out


def pickup_at(day: date, at: time) -> datetime:
    """The moment of pick-up on that day: the clock time is Nairobi's."""
    return datetime.combine(day, at, tzinfo=NAIROBI)
