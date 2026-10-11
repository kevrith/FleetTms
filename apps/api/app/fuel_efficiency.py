"""Fuel efficiency figures for the owner (masterplan 5.14): litres per 100 km, km per litre and money per km, and how far a lorry is
from the consumption it is expected to have. Server side only; the web shows what is worked out here."""


def ratios(km: float, litres: float, cost_cents: int) -> dict:
    """The three ways owners read fuel use. None when there is nothing to divide by (no distance, or no fuel bought)."""
    if km <= 0 or litres <= 0:
        return {"km_per_litre": None, "l_per_100km": None, "cost_per_km_cents": round(cost_cents / km) if km > 0 and cost_cents > 0 else None}
    return {"km_per_litre": round(km / litres, 2), "l_per_100km": round(litres / km * 100, 1), "cost_per_km_cents": round(cost_cents / km)}


def expected_kmpl(loaded: float | None, empty: float | None) -> float | None:
    """What the lorry is expected to do over a spread of trips: the mean of its loaded and empty figures, or whichever one is entered."""
    given = [x for x in (loaded, empty) if x]
    return round(sum(given) / len(given), 2) if given else None


def against_expected(l_per_100km: float | None, kmpl: float | None, limit_pct: float) -> dict:
    """How far the lorry's litres per 100 km are above (positive) or below (negative) what is expected, and whether that is past the limit."""
    if l_per_100km is None or not kmpl:
        return {"vs_expected_pct": None, "above_expected": False}
    expected = 100 / kmpl
    pct = round((l_per_100km - expected) / expected * 100, 1)
    return {"vs_expected_pct": pct, "above_expected": pct > limit_pct}
