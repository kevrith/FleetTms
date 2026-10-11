"""Fuel efficiency (masterplan 5.14): for each lorry, driver and route over the last few months, the litres per 100 km, km per litre and money per
km, month by month, with the lorry's distance from the consumption it is expected to have and the fuel alerts that were raised."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fraud
from app.db import get_db
from app.deps import Principal, require
from app.floatcalc import day_bounds
from app.fuel_efficiency import against_expected, expected_kmpl, ratios
from app.lease_rules import add_months
from app.models import FraudAlert, FuelEntry, Membership, Trip, TripStatus, Vehicle
from app.reminders import NAIROBI, nairobi_today
from app.vehicle_scope import require_vehicle_in_scope, scope_vehicles

router = APIRouter(tags=["fuel"])
MAX_MONTHS = 12
FUEL_ALERTS = ("fuel_variance", "fuel_model_anomaly", "fuel_siphoning", "fuel_not_in_tank", "fuel_amount_mismatch")


def month_of(moment: datetime) -> str:
    return moment.astimezone(NAIROBI).strftime("%Y-%m")


def _row(km: float, litres: float, cost_cents: int) -> dict:
    return {"km": round(km), "litres": round(litres, 1), "cost_cents": cost_cents, **ratios(km, litres, cost_cents)}


@router.get("/fuel-efficiency")
async def fuel_efficiency(
    months: int = Query(default=3, ge=1, le=MAX_MONTHS), vehicle_id: uuid.UUID | None = None,
    principal: Principal = Depends(require("reports.view")), db: AsyncSession = Depends(get_db),
):  # fmt: skip
    """The calendar months up to and including this one. Distance is the trip's distance of record (the odometer, or GPS for a lorry set to use
    it); fuel is every purchase recorded for the lorry in the period, so fuel bought between trips still counts against the distance driven."""
    if vehicle_id is not None:
        require_vehicle_in_scope(principal, vehicle_id)
    first = add_months(nairobi_today().replace(day=1), -(months - 1))
    begin, _ = day_bounds(first)
    end = datetime.now(UTC)
    t, _ = await fraud.load_settings(db)
    query = scope_vehicles(select(Vehicle), principal)
    if vehicle_id is not None:
        query = query.where(Vehicle.id == vehicle_id)
    vehicles = {v.id: v for v in (await db.execute(query)).scalars()}
    trips = [
        x for x in (await db.execute(select(Trip).where(Trip.vehicle_id.in_(list(vehicles)), Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED)), Trip.ended_at >= begin, Trip.ended_at <= end))).scalars()
        if fraud.best_km(x)
    ] if vehicles else []  # fmt: skip
    entries = list((await db.execute(select(FuelEntry).where(FuelEntry.vehicle_id.in_(list(vehicles)), FuelEntry.captured_at >= begin, FuelEntry.captured_at <= end))).scalars()) if vehicles else []

    km: dict[tuple[uuid.UUID, str], float] = defaultdict(float)
    litres: dict[tuple[uuid.UUID, str], float] = defaultdict(float)
    cost: dict[tuple[uuid.UUID, str], int] = defaultdict(int)
    for x in trips:
        km[(x.vehicle_id, month_of(x.ended_at))] += fraud.best_km(x) or 0
    for e in entries:
        key = (e.vehicle_id, month_of(e.captured_at))
        litres[key] += float(e.litres)
        cost[key] += e.amount_cents
    month_keys = [add_months(first, i).strftime("%Y-%m") for i in range(months)]

    rows = []
    for v in sorted(vehicles.values(), key=lambda v: v.registration):
        monthly = [{"month": m, **_row(km[(v.id, m)], litres[(v.id, m)], cost[(v.id, m)])} for m in month_keys]
        total_km, total_l, total_c = (sum(x[(v.id, m)] for m in month_keys) for x in (km, litres, cost))
        expected = expected_kmpl(float(v.expected_kmpl_loaded) if v.expected_kmpl_loaded else None, float(v.expected_kmpl_empty) if v.expected_kmpl_empty else None)
        whole = _row(total_km, total_l, total_c)
        if not total_km and not total_l:
            continue
        rows.append({
            "vehicle_id": v.id, "registration": v.registration, "distance_source": v.distance_source, "trips": sum(1 for x in trips if x.vehicle_id == v.id),
            "expected_km_per_litre": expected, **whole, **against_expected(whole["l_per_100km"], expected, t.fuel_variance_pct), "monthly": monthly,
        })  # fmt: skip

    # Drivers and routes: only fuel that can be tied to a trip (entered on it, or bought while it ran), set against the distance of those same trips.
    fuel_by_trip = await fraud._fuel_by_trip(db, trips)
    members = {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()} if trips else {}
    drivers: dict[uuid.UUID, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # km, litres, trips counted, cost
    routes: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    price: dict[uuid.UUID, float] = {}  # the lorry's average pump price in the period, to put a cost on the fuel tied to a trip
    for vid in vehicles:
        bought = sum(float(e.litres) for e in entries if e.vehicle_id == vid)
        price[vid] = sum(e.amount_cents for e in entries if e.vehicle_id == vid) / bought if bought else 0.0
    for x in trips:
        used = fuel_by_trip.get(x.id)
        if not used:
            continue
        for bucket in ((drivers[x.driver_membership_id] if x.driver_membership_id else None), routes[f"{x.origin or '?'} to {x.destination or '?'}"]):
            if bucket is not None:
                bucket[0] += fraud.best_km(x) or 0
                bucket[1] += used
                bucket[2] += 1
                bucket[3] += used * price[x.vehicle_id]
    by_driver = [{"membership_id": d, "name": members.get(d, "Former staff"), "trips_counted": int(s[2]), **_row(s[0], s[1], round(s[3]))} for d, s in drivers.items()]
    by_route = [{"route": r, "trips_counted": int(s[2]), **_row(s[0], s[1], round(s[3]))} for r, s in routes.items()]
    for table in (by_driver, by_route):
        table.sort(key=lambda r: (r["l_per_100km"] is None, -(r["l_per_100km"] or 0)))  # thirstiest first

    alert_query = select(FraudAlert).where(FraudAlert.kind.in_(FUEL_ALERTS), FraudAlert.occurred_at >= begin, FraudAlert.occurred_at <= end).order_by(FraudAlert.occurred_at.desc()).limit(50)
    alerts = [
        {"id": a.id, "kind": a.kind, "severity": a.severity, "status": a.status, "title": a.title, "vehicle_id": a.vehicle_id, "trip_id": a.trip_id, "occurred_at": a.occurred_at}
        for a in (await db.execute(alert_query)).scalars() if a.vehicle_id in vehicles
    ]  # fmt: skip
    return {
        "from": first, "to": nairobi_today(), "months": month_keys, "limit_pct": t.fuel_variance_pct, "vehicles": rows, "drivers": by_driver, "routes": by_route, "alerts": alerts,
    }  # fmt: skip
