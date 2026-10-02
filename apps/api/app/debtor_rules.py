"""Debtors (masterplan 5.10). The same rules as packages/business-rules/src/debtors.ts, tested against
debtor-cases.json on both sides."""

import re
from datetime import date

BUCKETS = ("current", "1_30", "31_60", "61_90", "over_90")
DEFAULT_REMINDER_OFFSETS = (-3, 1, 7, 14, 30)
_REFERENCE = re.compile(r"^INV[\s\-_.#:]*0*(\d{1,6})$", re.IGNORECASE)


def days_late(due: date, today: date) -> int:
    return (today - due).days


def ageing_bucket(due: date, today: date) -> str:
    """Ageing counts from the due date: an invoice that is not yet due is "current"."""
    late = days_late(due, today)
    if late <= 0:
        return "current"
    if late <= 30:
        return "1_30"
    if late <= 60:
        return "31_60"
    if late <= 90:
        return "61_90"
    return "over_90"


def invoice_number_from(text: str | None) -> str | None:
    """The invoice number a customer meant by what they typed as the M-Pesa account number, or None if it is not one."""
    found = _REFERENCE.match((text or "").strip())
    if not found:
        return None
    return f"INV-{int(found.group(1)):04d}"


def reminder_offset_due(*, due: date, today: date, offsets: list[int] | tuple[int, ...], sent: set[int] | list[int]) -> int | None:
    """Which reminder to send today for an unpaid invoice, as days from the due date (negative is before it), or None.
    Only the latest one that has come round is sent, so a backlog never means several messages in one day."""
    late = days_late(due, today)
    reached = [o for o in offsets if o <= late]
    if not reached:
        return None
    latest = max(reached)
    return None if latest in sent else latest
