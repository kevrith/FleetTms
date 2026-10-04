"""Driver scorecards (masterplan 5.25): safety, fuel efficiency, punctuality, inspections and alerts for each driver over a period,
from the trips they drove. The scoring rules are in app/scorecard_rules.py (mirrored in the shared package)."""

import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
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


class Loaded:
    """Everything the cards need, read in a few queries for all drivers at once. A card used to read its own driver's rows one
    query at a time, which is thirteen thousand queries for a fleet of three hundred drivers."""

    def __init__(self, vehicles: dict[uuid.UUID, Vehicle], t: fraud_rules.Thresholds) -> None:
        self.vehicles, self.t = vehicles, t
        self.behaviour: dict[uuid.UUID, Counter] = defaultdict(Counter)
        self.alerts: dict[uuid.UUID, list[FraudAlert]] = defaultdict(list)
        self.inspections: dict[uuid.UUID, InspectionStatus] = {}
        self.fuel: dict[uuid.UUID, float] = {}
        self.idle: dict[uuid.UUID, float] = {}
        self.history: dict = {}  # each vehicle's own fuel history, read once (fraud.baseline_for)


async def load_all(db: AsyncSession, by_driver: dict[uuid.UUID, list[Trip]], vehicles: dict[uuid.UUID, Vehicle], t: fraud_rules.Thresholds, start: datetime, end: datetime) -> Loaded:
    loaded = Loaded(vehicles, t)
    rows = await db.execute(select(BehaviourEvent.driver_membership_id, BehaviourEvent.kind, func.count()).where(BehaviourEvent.driver_membership_id.in_(list(by_driver)), BehaviourEvent.at >= start, BehaviourEvent.at < end).group_by(BehaviourEvent.driver_membership_id, BehaviourEvent.kind))
    for driver, kind, n in rows:
        loaded.behaviour[driver][kind] = n
    for a in (await db.execute(select(FraudAlert).where(FraudAlert.driver_membership_id.in_(list(by_driver)), FraudAlert.occurred_at >= start, FraudAlert.occurred_at < end))).scalars():
        loaded.alerts[a.driver_membership_id].append(a)
    every = [x for trips in by_driver.values() for x in trips]
    inspection_ids = [x.inspection_id for x in every if x.inspection_id]
    if inspection_ids:
        loaded.inspections = {i.id: i.status for i in (await db.execute(select(Inspection).where(Inspection.id.in_(inspection_ids)))).scalars()}
    done = [x for x in every if x.status in (TripStatus.DELIVERED, TripStatus.COMPLETED) and x.ended_at is not None]
    loaded.fuel, loaded.idle = await fraud._fuel_by_trip(db, done), await fraud._idle_hours(db, [x.id for x in done])
    loaded.history = await fraud.preload_histories(db, {x.vehicle_id for x in done if loaded.fuel.get(x.id)})
    return loaded


async def card(db: AsyncSession, member: Membership, trips: list[Trip], loaded: Loaded) -> dict:
    t, vehicles = loaded.t, loaded.vehicles
    km = sum(fraud.best_km(x) or 0 for x in trips)
    counts: Counter = loaded.behaviour.get(member.id, Counter())
    variances: list[float] = []
    done = [x for x in trips if x.status in (TripStatus.DELIVERED, TripStatus.COMPLETED) and x.ended_at is not None]
    for x in done:
        kms = fraud.best_km(x)
        if loaded.fuel.get(x.id) and kms and x.vehicle_id in vehicles:
            baseline = await fraud.baseline_for(db, x, vehicles[x.vehicle_id], t, history=loaded.history)
            if baseline:
                v = fraud_rules.fuel_check(litres=loaded.fuel[x.id], km=kms, idle_hours=loaded.idle.get(x.id, 0.0), l_per_km=baseline["l_per_km"], t=t)
                if v["variance_pct"] is not None:
                    variances.append(v["variance_pct"])
    timed = [x for x in trips if x.started_at and x.scheduled_for]
    on_time = sum(1 for x in timed if x.started_at <= x.scheduled_for + ON_TIME_START)
    clean = sum(1 for x in trips if loaded.inspections.get(x.inspection_id) == InspectionStatus.PASSED)
    defects = sum(1 for x in trips if loaded.inspections.get(x.inspection_id) == InspectionStatus.PASSED_WITH_DEFECTS)
    raised = loaded.alerts.get(member.id, [])
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
    by_driver = {d: trips for d, trips in by_driver.items() if d in members}
    loaded = await load_all(db, by_driver, vehicles, t, begin, finish) if by_driver else None
    cards = [await card(db, members[d], trips, loaded) for d, trips in by_driver.items()]
    cards.sort(key=lambda c: (-(c["overall"] if c["overall"] is not None else -1), c["name"]))
    return {"from": start, "to": end, "drivers": cards, "weights": scorecard_rules.WEIGHTS}

