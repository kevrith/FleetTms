"""Predictions that are plain sums (masterplan 5.14): what a lease charges for one job, and how a month is likely to end. Money is whole
cents. Each returns its parts, so a prediction can always be shown as how it was worked out."""

import math

from app.lease_rules import div_half, share


def job_days(trips: int, hours_one_way: float, return_empty: bool) -> int:
    """How many days the lorry is tied up: every trip out, and back if it returns empty, in whole days (at least one)."""
    hours = trips * hours_one_way * (2 if return_empty else 1)
    return max(1, math.ceil(hours / 24 - 1e-9))


def job_lease_charge(terms: dict, *, price_cents: int, gross_profit_cents: int, trips: int, total_km: int, days: int) -> dict:
    """What a lease charges for one job: the fixed charge for the days the lorry is used, the rate per trip and per kilometre, and the
    shares of the price and of the profit before the lease. The monthly minimum guarantee is a floor on a whole month, so it is not
    part of any one job."""
    fixed = terms.get("fixed_cents") or 0
    period = terms.get("fixed_period")
    if period == "day":
        fixed_cents = fixed * days
    elif period == "week":
        fixed_cents = div_half(fixed * days, 7)
    elif period == "month":
        fixed_cents = div_half(fixed * days, 30)
    else:
        fixed_cents = 0
    parts = {
        "fixed_cents": fixed_cents, "trips_cents": (terms.get("per_trip_cents") or 0) * trips, "km_cents": (terms.get("per_km_cents") or 0) * total_km,
        "revenue_share_cents": share(price_cents, float(terms.get("revenue_pct") or 0)), "profit_share_cents": share(gross_profit_cents, float(terms.get("profit_pct") or 0)),
    }  # fmt: skip
    return {**parts, "total_cents": sum(parts.values()), "days": days, "trips": trips, "km": total_km}


def project_month(*, to_date_cents: int, days_elapsed: int, days_in_month: int, history_cents: int, history_days: int) -> dict:
    """The month so far plus what the remaining days usually bring in: the daily average of earlier months times the days left.
    None for the projection when there is no earlier month to learn the daily average from."""
    if history_days <= 0:
        return {"per_day_cents": None, "remaining_days": max(0, days_in_month - days_elapsed), "projected_cents": None}
    per_day = round(history_cents / history_days)  # the figure the owner is shown is the one used, so the working adds up
    remaining = max(0, days_in_month - days_elapsed)
    return {"per_day_cents": per_day, "remaining_days": remaining, "projected_cents": to_date_cents + per_day * remaining}
