"""Driver scorecards (masterplan 5.25): safety, fuel efficiency, punctuality, inspections and alerts for each driver over a period,
from the trips they drove. The scoring rules are in app/scorecard_rules.py (mirrored in the shared package)."""

import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fraud, fraud_rules, scorecard_rules
from app.db import get_db
from app.deps import Principal, error, require
from app.floatcalc import day_bounds
from app.models import (
    BehaviourEvent,
    FraudAlert,
    Inspection,
    InspectionStatus,
    Membership,
    Trip,
    TripStatus,
    Vehicle,
)
from app.reminders import NAIROBI
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["scorecards"])
ON_TIME_START = timedelta(minutes=30)  # starting within this of the scheduled time counts as on time
MAX_DAYS = 366


async def card(db: AsyncSession, member: Membership, trips: list[Trip], start: datetime, end: datetime, vehicles: dict[uuid.UUID, Vehicle], t: fraud_rules.Thresholds) -> dict:
    km = sum(fraud.best_km(x) or 0 for x in trips)
    counts: Counter = Counter()
    for e in (await db.execute(select(BehaviourEvent).where(BehaviourEvent.driver_membership_id == member.id, BehaviourEvent.at >= start, BehaviourEvent.at < end))).scalars():
        counts[e.kind] += 1
    variances: list[float] = []
    done = [x for x in trips if x.status in (TripStatus.DELIVERED, TripStatus.COMPLETED) and x.ended_at is not None]
    fuel, idle = await fraud._fuel_by_trip(db, done), await fraud._idle_hours(db, [x.id for x in done])
    for x in done:
        kms = fraud.best_km(x)
        if fuel.get(x.id) and kms and x.vehicle_id in vehicles:
            baseline = await fraud.baseline_for(db, x, vehicles[x.vehicle_id], t)
            if baseline:
                v = fraud_rules.fuel_check(litres=fuel[x.id], km=kms, idle_hours=idle[x.id], l_per_km=baseline["l_per_km"], t=t)
                if v["variance_pct"] is not None:
                    variances.append(v["variance_pct"])
    timed = [x for x in trips if x.started_at and x.scheduled_for]
    on_time = sum(1 for x in timed if x.started_at <= x.scheduled_for + ON_TIME_START)
    inspections = {i.id: i.status for i in (await db.execute(select(Inspection).where(Inspection.id.in_([x.inspection_id for x in trips if x.inspection_id])))).scalars()}
    clean = sum(1 for x in trips if inspections.get(x.inspection_id) == InspectionStatus.PASSED)
    defects = sum(1 for x in trips if inspections.get(x.inspection_id) == InspectionStatus.PASSED_WITH_DEFECTS)
    raised = (await db.execute(select(FraudAlert).where(FraudAlert.driver_membership_id == member.id, FraudAlert.occurred_at >= start, FraudAlert.occurred_at < end))).scalars().all()
    confirmed, still_open = sum(a.status == "confirmed" for a in raised), sum(a.status == "open" for a in raised)
    parts = {
        "safety": scorecard_rules.safety_score(dict(counts), km), "fuel": scorecard_rules.fuel_score(variances), "punctuality": scorecard_rules.punctuality_score(on_time, len(timed)),
        "inspections": scorecard_rules.inspection_score(clean, defects, len(trips)), "alerts": scorecard_rules.alerts_score(confirmed, still_open),
    }  # fmt: skip
    score = scorecard_rules.overall(parts)
    return {
        "membership_id": member.id, "name": member.user.name, "trips": len(trips), "km": round(km), **parts, "overall": score, "band": scorecard_rules.band(score),
        "detail": {"behaviour": dict(counts), "trips_with_fuel_checked": len(variances), "avg_fuel_variance_pct": round(sum(variances) / len(variances), 1) if variances else None, "on_time": on_time, "timed_trips": len(timed), "clean_inspections": clean, "inspections_with_defects": defects,
                   "alerts_confirmed": confirmed, "alerts_open": still_open, "alerts_explained": sum(a.status == "explained" for a in raised)},
    }  # fmt: skip


@router.get("/scorecards")
async def scorecards(start: date | None = None, end: date | None = None, principal: Principal = Depends(require("reports.view")), db: AsyncSession = Depends(get_db)):
    """One card per driver who drove in the period (the last 30 days by default), best first."""
    end = end or datetime.now(NAIROBI).date()
    start = start or end - timedelta(days=29)
    if end < start:
        raise error(422, "bad_range", "The end date is before the start date.")
    if (end - start).days >= MAX_DAYS:
        raise error(422, "range_too_long", "Choose a range of a year or less.")
    begin, _ = day_bounds(start)
    _, finish = day_bounds(end)
    t, _ = await fraud.load_settings(db)
    vehicles = {v.id: v for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    by_driver: dict[uuid.UUID, list[Trip]] = defaultdict(list)
    for x in (await db.execute(select(Trip).where(Trip.started_at >= begin, Trip.started_at < finish, Trip.driver_membership_id.is_not(None)))).scalars():
        if x.vehicle_id in vehicles:
            by_driver[x.driver_membership_id].append(x)
    members = {m.id: m for m in (await db.execute(select(Membership))).scalars()}
    cards = [await card(db, members[d], trips, begin, finish, vehicles, t) for d, trips in by_driver.items() if d in members]
    cards.sort(key=lambda c: (-(c["overall"] if c["overall"] is not None else -1), c["name"]))
    return {"from": start, "to": end, "drivers": cards, "weights": scorecard_rules.WEIGHTS}

