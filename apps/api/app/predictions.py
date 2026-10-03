"""Predictions (masterplan 5.14), every one with its working: expected fuel for a trip, what a lease charges for a job, and how the month
is likely to end. Each starts with the simplest thing that is true and gets better as the vehicle's own history builds up."""

import calendar
import uuid
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fraud, learned, learned_rules, prediction_rules
from app.fraud_rules import Thresholds
from app.models import Job, JobStatus, LeaseAgreement, Vehicle
from app.profit import add_months, build, month_bounds

DEFAULT_ONE_WAY_HOURS = 12.0


def _money(cents: int) -> str:
    return f"KES {cents / 100:,.2f}"


async def consumption(db: AsyncSession, vehicle: Vehicle, *, distance_km: float, weight_kg: float, origin: str | None, destination: str | None, t: Thresholds) -> dict | None:
    """Kilometres a litre for a job's loaded leg and its empty return, from the best thing known about this vehicle: its learned model
    (once it has enough trips to be reliable), else the average of its own finished trips on this route and load, else None (the
    caller then uses the consumption entered for the vehicle). Returns {kmpl_loaded, kmpl_empty, source, steps}."""
    km = max(float(distance_km), 1.0)
    tonnes = weight_kg / 1000
    model = await learned.train(db, vehicle, t)
    if model and model["reliable"]:
        loaded = learned_rules.predict(model, km=km, tonne_km=tonnes * km)
        empty = learned_rules.predict(model, km=km, tonne_km=0, idle_hours=0)
        c = model["coefs"]
        if loaded > 0 and empty > 0:
            steps = [
                f"Learned from {model['n']} of this vehicle's finished trips. It explains {round(model['r2'] * 100)}% of how their fuel varied and is usually within {model['sigma']:g} litres.",
                f"It found {c['km']:.3f} litres for every kilometre, {c['tonne_km']:.5f} for every tonne carried a kilometre, and {c['idle_hours']:.1f} for every hour of idling.",
                f"Loaded leg: {km:g} km with {tonnes:g} tonnes comes to {loaded:.0f} litres (including the usual {model['mean_idle_hours']:g} hours of idling).",
                f"Empty return: {km:g} km with no cargo comes to {empty:.0f} litres.",
            ]
            return {"kmpl_loaded": round(km / loaded, 2), "kmpl_empty": round(km / empty, 2), "source": "learned", "steps": steps}
    stub_loaded = SimpleNamespace(id=None, vehicle_id=vehicle.id, loaded_weight_kg=weight_kg or None, origin=origin, destination=destination)
    stub_empty = SimpleNamespace(id=None, vehicle_id=vehicle.id, loaded_weight_kg=None, origin=origin, destination=destination)
    got_loaded, got_empty = await fraud.baseline_for(db, stub_loaded, vehicle, t), await fraud.baseline_for(db, stub_empty, vehicle, t)
    steps, out = [], {"kmpl_loaded": None, "kmpl_empty": None}
    for key, label, got in (("kmpl_loaded", "Loaded leg", got_loaded), ("kmpl_empty", "Empty return", got_empty)):
        if got and got["source"].startswith("same"):
            out[key] = round(1 / got["l_per_km"], 2)
            steps.append(f"{label}: this vehicle's own {got['trips']} finished trips on {got['source']} averaged {out[key]:g} km a litre.")
    if out["kmpl_loaded"] is None and out["kmpl_empty"] is None:
        return None
    return {**out, "source": "history", "steps": steps}


async def lease_for_job(db: AsyncSession, vehicle_id: uuid.UUID, *, price_cents: int, gross_profit_cents: int, trips: int, distance_km: int, return_empty: bool, expected_hours: float | None, today: date) -> dict | None:
    """What the lease on a lorry hired in charges for this job, worked out part by part. None for a lorry that is not leased in."""
    a = (await db.execute(select(LeaseAgreement).where(LeaseAgreement.vehicle_id == vehicle_id, LeaseAgreement.direction == "in", LeaseAgreement.status == "active"))).scalars().first()
    if a is None or a.start_date > today or (a.end_date is not None and a.end_date < today):
        return None
    terms = {"fixed_cents": a.fixed_cents, "fixed_period": a.fixed_period, "per_trip_cents": a.per_trip_cents, "per_km_cents": a.per_km_cents, "revenue_pct": float(a.revenue_pct), "profit_pct": float(a.profit_pct)}
    total_km = distance_km * trips * (2 if return_empty else 1)
    days = prediction_rules.job_days(trips, expected_hours or DEFAULT_ONE_WAY_HOURS, return_empty)
    charge = prediction_rules.job_lease_charge(terms, price_cents=price_cents, gross_profit_cents=gross_profit_cents, trips=trips, total_km=total_km, days=days)
    lines = []
    if charge["fixed_cents"]:
        lines.append({"label": f"Fixed charge ({_money(terms['fixed_cents'])} a {terms['fixed_period']}) for {days} day{'s' if days != 1 else ''} of use", "cents": charge["fixed_cents"]})
    if charge["trips_cents"]:
        lines.append({"label": f"{_money(terms['per_trip_cents'])} a trip, {trips} trip{'s' if trips != 1 else ''}", "cents": charge["trips_cents"]})
    if charge["km_cents"]:
        lines.append({"label": f"{_money(terms['per_km_cents'])} a kilometre, {total_km:,} km (out and back)" if return_empty else f"{_money(terms['per_km_cents'])} a kilometre, {total_km:,} km", "cents": charge["km_cents"]})
    if charge["revenue_share_cents"]:
        lines.append({"label": f"{terms['revenue_pct']:g}% of the price ({_money(price_cents)})", "cents": charge["revenue_share_cents"]})
    if charge["profit_share_cents"]:
        lines.append({"label": f"{terms['profit_pct']:g}% of the profit before the lease ({_money(max(gross_profit_cents, 0))})", "cents": charge["profit_share_cents"]})
    note = "The lease's monthly minimum guarantee is not part of any one job, so it is not included."
    return {**charge, "lines": lines, "note": note, "agreement_id": str(a.id)}


async def forecast(db: AsyncSession, today: date) -> dict:
    """How this month is likely to end, for the business and each vehicle: what the month has earned so far plus the daily average of
    the last three full months for the days left, less the lease, finance and ownership charges those months averaged. The profit
    engine's own figures are used, so it agrees with the profit pages."""
    first, _ = month_bounds(today)
    earlier = [add_months(first, -k) for k in (3, 2, 1)]
    history = [await build(db, m, m) for m in earlier]
    current = await build(db, first, first)
    days_elapsed, days_in_month = today.day, calendar.monthrange(today.year, today.month)[1]
    history_days = sum(calendar.monthrange(m.year, m.month)[1] for m in earlier)

    def work(now_row: dict, past_rows: list[dict], gross_key="gross", net_key="net") -> dict:
        history_gross = sum(r[gross_key] for r in past_rows)
        fixed_per_month = round(sum(r[gross_key] - r[net_key] for r in past_rows) / len(past_rows)) if past_rows else 0
        has_history = history_gross != 0 or any(r[net_key] != 0 for r in past_rows)
        proj = prediction_rules.project_month(to_date_cents=now_row[gross_key], days_elapsed=days_elapsed, days_in_month=days_in_month, history_cents=history_gross, history_days=history_days if has_history else 0)
        projected_net = None if proj["projected_cents"] is None else proj["projected_cents"] - fixed_per_month
        return {
            "gross_to_date_cents": now_row[gross_key], "net_to_date_cents": now_row[net_key], "gross_per_day_cents": proj["per_day_cents"], "remaining_days": proj["remaining_days"],
            "projected_gross_cents": proj["projected_cents"], "fixed_charges_cents": fixed_per_month, "projected_net_cents": projected_net,
        }  # fmt: skip

    def vehicle_row(report: dict, vid: uuid.UUID) -> dict:
        return next((v for v in report["vehicles"] if v["vehicle_id"] == vid), {"gross": 0, "net": 0})

    business_hist = [h["business"] for h in history]
    business = work(current["business"], business_hist, "gross", "net_after_overheads")
    vehicles = []
    for v in current["vehicles"]:
        vehicles.append({"vehicle_id": v["vehicle_id"], "registration": v["registration"], **work(v, [vehicle_row(h, v["vehicle_id"]) for h in history])})
    booked = (await db.execute(select(Job).where(Job.status.in_((JobStatus.PLANNED, JobStatus.DISPATCHED, JobStatus.IN_PROGRESS))))).scalars().all()
    steps = [
        f"So far this month ({days_elapsed} of {days_in_month} days): {_money(business['gross_to_date_cents'])} of profit before lease, finance and ownership charges.",
        (f"The last three full months averaged {_money(business['gross_per_day_cents'])} a day, so the {business['remaining_days']} days left add about {_money(business['gross_per_day_cents'] * business['remaining_days'])}."
         if business["gross_per_day_cents"] is not None else "There are no earlier months to learn a daily average from yet, so there is no forecast."),
    ]
    if business["projected_net_cents"] is not None:
        steps.append(f"Lease, finance, ownership and overhead costs averaged {_money(business['fixed_charges_cents'])} a month, which comes off: about {_money(business['projected_net_cents'])} for the month.")
    return {
        "month": first, "today": today, "days_elapsed": days_elapsed, "days_in_month": days_in_month, "history_months": earlier,
        "business": business, "vehicles": sorted(vehicles, key=lambda r: r["registration"]), "steps": steps,
        "booked_work": {"jobs": len(booked), "expected_profit_cents": sum(j.expected_profit_cents or 0 for j in booked)},
    }  # fmt: skip

