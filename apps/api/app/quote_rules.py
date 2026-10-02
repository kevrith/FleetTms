"""Quote pricing (masterplan 5.17). The same rules as packages/business-rules/src/quotes.ts, which the web uses for its
live preview; both are tested against packages/business-rules/src/quote-cases.json so they cannot drift apart."""

import math
from dataclasses import asdict, dataclass
from enum import StrEnum


class BillingMethod(StrEnum):
    PER_TRIP = "per_trip"
    PER_TONNE = "per_tonne"
    PER_KM = "per_km"
    MONTHLY_CONTRACT = "monthly_contract"


@dataclass(frozen=True)
class QuoteInput:
    method: BillingMethod
    rate_cents: int
    distance_km: float
    weight_tonnes: float
    trips: int
    return_empty: bool
    kmpl_loaded: float
    kmpl_empty: float
    fuel_price_cents: int
    tolls_cents: int
    crew_cents: int
    other_cents: int


def half(x: float) -> int:
    """Round half up, matching the TypeScript side (Python's round() rounds halves to even)."""
    return math.floor(x + 0.5)


def price_for(q: QuoteInput) -> int:
    if q.method == BillingMethod.PER_TRIP:
        return q.rate_cents * q.trips
    if q.method == BillingMethod.PER_TONNE:
        return half(q.rate_cents * q.weight_tonnes)
    if q.method == BillingMethod.PER_KM:
        return half(q.rate_cents * q.distance_km * q.trips)
    return q.rate_cents  # a monthly contract is the fee, whatever the number of trips


def quote(q: QuoteInput) -> dict:
    loaded_km = q.distance_km
    empty_km = q.distance_km if q.return_empty else 0
    litres = loaded_km / q.kmpl_loaded + empty_km / q.kmpl_empty
    fuel_cents = half(litres * q.fuel_price_cents)
    per_trip = fuel_cents + q.tolls_cents + q.crew_cents + q.other_cents
    total = per_trip * q.trips
    price = price_for(q)
    profit = price - total
    return {
        "price_cents": price, "loaded_km": loaded_km, "empty_km": empty_km, "fuel_litres": half(litres * 100) / 100,
        "fuel_cents": fuel_cents, "cost_per_trip_cents": per_trip, "total_cost_cents": total, "profit_cents": profit,
        "margin_pct": half(profit / price * 1000) / 10 if price > 0 else None,
    }  # fmt: skip


def from_dict(d: dict) -> QuoteInput:
    return QuoteInput(**{**d, "method": BillingMethod(d["method"])})


__all__ = ["BillingMethod", "QuoteInput", "asdict", "from_dict", "price_for", "quote"]
