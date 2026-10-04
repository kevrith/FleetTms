"""The partner programme's money rules, in whole cents. Server side only: nothing on a phone or a browser works commission out."""

import secrets
from datetime import datetime

# No 0, O, 1, I or L: a code read out over the phone or typed from a business card is not mixed up.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


def commission_cents(basis_cents: int, share_bp: int) -> int:
    """The partner's share of a payment, rounded down to the cent: 20 percent (2000) of 1,800.00 is 360.00."""
    return basis_cents * share_bp // 10_000


def add_months(moment: datetime, months: int) -> datetime:
    index = moment.year * 12 + (moment.month - 1) + months
    year, month = divmod(index, 12)
    day = min(moment.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month])
    return moment.replace(year=year, month=month + 1, day=day)


def in_window(first_paid_at: datetime, paid_at: datetime, months: int) -> bool:
    """Commission runs for `months` months from the business's first payment (zero means for as long as it pays)."""
    return months <= 0 or paid_at < add_months(first_paid_at, months)


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
