"""Billing (masterplan 5.10). The same rules as packages/business-rules/src/billing.ts, tested against the same cases.
Money is whole cents."""

import math
from datetime import date

from app.quote_rules import BillingMethod


def half(x: float) -> int:
    return math.floor(x + 0.5)


def trip_amount(*, method: BillingMethod, rate_cents: int, weight_kg: int | None, distance_km: int | None) -> int | None:
    """What one delivered trip is billed at, or None when it cannot be billed yet (no weighbridge weight for a per-tonne
    trip, no distance for a per-km trip) or is never billed per trip (a monthly contract)."""
    if method == BillingMethod.PER_TRIP:
        return rate_cents
    if method == BillingMethod.PER_TONNE:
        return half(rate_cents * weight_kg / 1000) if weight_kg and weight_kg > 0 else None
    if method == BillingMethod.PER_KM:
        return half(rate_cents * distance_km) if distance_km is not None else None
    return None


def vat_cents(subtotal_cents: int, vat_pct: float) -> int:
    return half(subtotal_cents * float(vat_pct) / 100)


def invoice_totals(lines_cents: list[int], vat_pct: float) -> dict:
    subtotal = sum(lines_cents)
    vat = vat_cents(subtotal, vat_pct)
    return {"subtotal_cents": subtotal, "vat_cents": vat, "total_cents": subtotal + vat}


def invoice_standing(*, total_cents: int, paid: list[int], voided: bool, due: date, today: date) -> dict:
    paid_cents = sum(paid)
    if voided:
        return {"paid_cents": paid_cents, "balance_cents": 0, "status": "void", "overdue": False}
    balance = total_cents - paid_cents
    status = "paid" if balance <= 0 else "partially_paid" if paid_cents > 0 else "issued"
    return {"paid_cents": paid_cents, "balance_cents": balance, "status": status, "overdue": balance > 0 and due < today}
