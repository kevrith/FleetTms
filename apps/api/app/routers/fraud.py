"""Fraud alerts (masterplan 5.13): what the engine found with the evidence behind it, the owner's explained/confirmed answer, the
business's own thresholds and who is told how, and each vehicle's fuel baselines."""

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, fraud, fraud_rules
from app.db import get_db
from app.deps import Principal, error, require
from app.models import (
    AlertSettings,
    FraudAlert,
    Membership,
    TrackerAlert,
    Trip,
    TripStatus,
    TyreSwapAlert,
    Vehicle,
)
from app.vehicle_scope import require_vehicle_in_scope, scope_vehicles

router = APIRouter(tags=["fraud"])
LABELS = {
    "fuel_variance": "Fuel above expected", "odometer_mismatch": "Odometer and GPS disagree", "side_trip": "Side trip", "long_stop": "Long unexplained stop", "tamper_then_stop": "Stop after tracker cut",
    "excess_idling": "Excess idling", "overload": "Overloaded", "power_cut": "Tracker power cut", "gps_jamming": "GPS jamming", "tamper": "Tracker tampering", "went_dark": "Went dark during a trip",
    "fake_gps": "Fake GPS app", "rooted_phone": "Rooted phone", "clock_changed": "Phone clock changed", "tyre_swap": "Possible tyre swap", "expense_above_norm": "Expense above the route's norm",
    "fuel_amount_mismatch": "Fuel total does not add up", "delivery_off_site": "Delivery away from the site", "parts_unfitted": "Parts issued but not fitted", "sensitive_change": "Sensitive change by staff",
    "duplicate_mpesa": "M-Pesa code claimed twice", "duplicate_receipt": "Receipt photo used twice", "fuel_siphoning": "Fuel siphoned while parked", "fuel_not_in_tank": "Fuel paid for never reached the tank",
    "unrecorded_refill": "Refill with no fuel purchase recorded", "fuel_model_anomaly": "Fuel above what this vehicle's own model expects",
}  # fmt: skip


class HandleIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)
    outcome: Literal["explained", "confirmed"] = "explained"


class SettingsIn(BaseModel):
    thresholds: dict[str, float] = Field(default_factory=dict)
    channels: dict[str, dict] = Field(default_factory=dict)


async def _names(db: AsyncSession) -> dict[uuid.UUID, str]:
    return {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}


def alert_out(a: FraudAlert, registration: str | None, driver: str | None) -> dict:
    return {
        "id": a.id, "kind": a.kind, "label": LABELS.get(a.kind, a.kind.replace("_", " ").capitalize()), "severity": a.severity, "title": a.title, "detail": a.detail, "evidence": a.evidence,
        "vehicle_id": a.vehicle_id, "registration": registration, "trip_id": a.trip_id, "driver_membership_id": a.driver_membership_id, "driver": driver, "trust_level": a.trust_level,
        "status": a.status, "note": a.note, "handled_at": a.handled_at, "occurred_at": a.occurred_at, "created_at": a.created_at, "notified": a.notified,
    }  # fmt: skip


def _scoped(query, principal: Principal):
    if principal.vehicle_scope is None:
        return query
    allowed = []
    for v in principal.vehicle_scope:
        try:
            allowed.append(uuid.UUID(v))
        except ValueError:
            continue
    return query.where(FraudAlert.vehicle_id.in_(allowed))  # a supervisor sees only their own vehicles' alerts, and none that belong to no vehicle


@router.get("/fraud/alerts")
async def list_alerts(
    status_filter: str | None = None, kind: str | None = None, severity: str | None = None, vehicle_id: uuid.UUID | None = None, trip_id: uuid.UUID | None = None, limit: int = 100,
    principal: Principal = Depends(require("alerts.view")), db: AsyncSession = Depends(get_db),
):  # fmt: skip
    query = _scoped(select(FraudAlert), principal).order_by(FraudAlert.created_at.desc()).limit(min(max(limit, 1), 500))
    for column, value in ((FraudAlert.status, status_filter), (FraudAlert.kind, kind), (FraudAlert.severity, severity), (FraudAlert.vehicle_id, vehicle_id), (FraudAlert.trip_id, trip_id)):
        if value:
            query = query.where(column == value)
    regs = {v.id: v.registration for v in (await db.execute(select(Vehicle))).scalars()}
    names = await _names(db)
    return [alert_out(a, regs.get(a.vehicle_id), names.get(a.driver_membership_id)) for a in (await db.execute(query)).scalars()]


@router.get("/fraud/alerts/{alert_id}")
async def get_alert(alert_id: uuid.UUID, principal: Principal = Depends(require("alerts.view")), db: AsyncSession = Depends(get_db)):
    a = (await db.execute(_scoped(select(FraudAlert), principal).where(FraudAlert.id == alert_id))).scalar_one_or_none()
    if a is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That alert was not found.")
    reg = (await db.execute(select(Vehicle.registration).where(Vehicle.id == a.vehicle_id))).scalar_one_or_none() if a.vehicle_id else None
    return alert_out(a, reg, (await _names(db)).get(a.driver_membership_id))


@router.post("/fraud/alerts/{alert_id}/handle")
async def handle_alert(alert_id: uuid.UUID, body: HandleIn, principal: Principal = Depends(require("alerts.manage")), db: AsyncSession = Depends(get_db)):
    """Says whether the alert was explained (and how) or confirmed as real. The answer stays on the alert, is counted in the summary,
    and is passed on to the record the alert came from so the same thing is not shown twice."""
    a = (await db.execute(select(FraudAlert).where(FraudAlert.id == alert_id))).scalar_one_or_none()
    if a is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That alert was not found.")
    if a.status != "open":
        raise error(status.HTTP_409_CONFLICT, "already_handled", "That alert has already been answered.")
    a.status, a.note, a.handled_by_user_id, a.handled_at = body.outcome, body.note.strip(), principal.user.id, datetime.now(UTC)
    if a.subject_type == "tracker_alert" and a.subject_id:
        source = (await db.execute(select(TrackerAlert).where(TrackerAlert.id == uuid.UUID(a.subject_id)))).scalar_one_or_none()
        if source is not None and source.status == "open":
            source.status, source.note, source.handled_by_user_id, source.handled_at = body.outcome, a.note, principal.user.id, a.handled_at
    if a.subject_type == "tyre_swap_alert" and a.subject_id:
        source = (await db.execute(select(TyreSwapAlert).where(TyreSwapAlert.id == uuid.UUID(a.subject_id)))).scalar_one_or_none()
        if source is not None and source.status == "open":
            source.status, source.resolved_by_user_id, source.resolved_at, source.resolution_note = "resolved", principal.user.id, a.handled_at, f"{body.outcome}: {a.note}"[:255]
    audit.record(db, actor_user_id=principal.user.id, action=f"fraud_alert.{body.outcome}", entity_type="fraud_alert", entity_id=a.id, after={"kind": a.kind, "note": a.note})
    await db.commit()
    reg = (await db.execute(select(Vehicle.registration).where(Vehicle.id == a.vehicle_id))).scalar_one_or_none() if a.vehicle_id else None
    return alert_out(a, reg, (await _names(db)).get(a.driver_membership_id))


@router.get("/fraud/summary")
async def summary(principal: Principal = Depends(require("alerts.view")), db: AsyncSession = Depends(get_db)):
    """How many alerts are open, and for each kind how many were explained and how many confirmed in the last 90 days: the answers show
    which checks are worth their noise, which is what to tune the thresholds by."""
    rows = (await db.execute(_scoped(select(FraudAlert), principal).where(FraudAlert.created_at >= datetime.now(UTC) - timedelta(days=90)))).scalars().all()
    open_by_severity = Counter(a.severity for a in rows if a.status == "open")
    per_kind: dict[str, Counter] = defaultdict(Counter)
    for a in rows:
        per_kind[a.kind][a.status] += 1
    kinds = []
    for k, c in sorted(per_kind.items(), key=lambda kv: -sum(kv[1].values())):
        answered = c["explained"] + c["confirmed"]
        kinds.append({"kind": k, "label": LABELS.get(k, k), "total": sum(c.values()), "open": c["open"], "explained": c["explained"], "confirmed": c["confirmed"], "confirmed_pct": round(c["confirmed"] / answered * 100) if answered else None})
    return {"open": {"red": open_by_severity["red"], "amber": open_by_severity["amber"], "total": sum(open_by_severity.values())}, "kinds": kinds}


@router.post("/fraud/scan")
async def scan(principal: Principal = Depends(require("alerts.manage")), db: AsyncSession = Depends(get_db)):
    """Runs every check now instead of waiting for the next one (they run by themselves every 15 minutes)."""
    raised = await fraud.sweep(db)
    await db.commit()
    return {"raised": raised}


# ---- thresholds and who is told ----------------------------------------------------------------------------------------


async def settings_out(db: AsyncSession) -> dict:
    t, channels = await fraud.load_settings(db)
    return {
        "thresholds": t.__dict__, "defaults": fraud_rules.DEFAULT.__dict__, "limits": {k: list(v) for k, v in fraud_rules.LIMITS.items()}, "channels": channels,
        "roles": list(fraud.ROLE_NAMES), "channel_names": list(fraud.CHANNEL_NAMES),
    }  # fmt: skip


@router.get("/fraud/settings")
async def get_settings(principal: Principal = Depends(require("alerts.settings")), db: AsyncSession = Depends(get_db)):
    return await settings_out(db)


@router.put("/fraud/settings")
async def put_settings(body: SettingsIn, principal: Principal = Depends(require("alerts.settings")), db: AsyncSession = Depends(get_db)):
    """Changes the thresholds the checks use and who is told how. Anything left out keeps its current value."""
    for name, value in body.thresholds.items():
        if name not in fraud_rules.LIMITS:
            raise error(422, "unknown_threshold", f"There is no threshold called {name}.")
        low, high = fraud_rules.LIMITS[name]
        if not low <= value <= high:
            raise error(422, "threshold_out_of_range", f"{name} must be between {low:g} and {high:g}.")
    for severity, pref in body.channels.items():
        if severity not in fraud.DEFAULT_CHANNELS:
            raise error(422, "unknown_severity", "Alerts are red or amber.")
        if not set(pref.get("roles", [])) <= set(fraud.ROLE_NAMES) or not set(pref.get("channels", [])) <= set(fraud.CHANNEL_NAMES):
            raise error(422, "unknown_channel", "Choose from the roles and channels listed.")
    row = (await db.execute(select(AlertSettings))).scalars().first()
    before = {"thresholds": row.thresholds if row else {}, "channels": row.channels if row else {}}
    if row is None:
        row = AlertSettings(thresholds={}, channels={})
        db.add(row)
        await db.flush()
    row.thresholds = {**(row.thresholds or {}), **body.thresholds}
    row.channels = {**(row.channels or {}), **{s: {"roles": p.get("roles", fraud.DEFAULT_CHANNELS[s]["roles"]), "channels": p.get("channels", fraud.DEFAULT_CHANNELS[s]["channels"])} for s, p in body.channels.items()}}
    row.updated_by_user_id, row.updated_at = principal.user.id, datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="alert_settings.changed", entity_type="alert_settings", entity_id=row.id, before=before, after={"thresholds": row.thresholds, "channels": row.channels})
    await db.commit()
    return await settings_out(db)


# ---- baselines ---------------------------------------------------------------------------------------------------------


@router.get("/vehicles/{vehicle_id}/baselines")
async def vehicle_baselines(vehicle_id: uuid.UUID, principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)):
    """What this vehicle normally burns, by route and by load, worked out from its own finished trips with the idling taken out."""
    require_vehicle_in_scope(principal, vehicle_id)
    vehicle = (await db.execute(scope_vehicles(select(Vehicle), principal).where(Vehicle.id == vehicle_id))).scalar_one_or_none()
    if vehicle is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    t, _ = await fraud.load_settings(db)
    trips = (await db.execute(select(Trip).where(Trip.vehicle_id == vehicle_id, Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED)), Trip.distance_km.is_not(None)).order_by(Trip.ended_at.desc()).limit(200))).scalars().all()
    fuel, idle = await fraud._fuel_by_trip(db, trips), await fraud._idle_hours(db, [x.id for x in trips])
    groups: dict[tuple[str, str], list[Trip]] = defaultdict(list)
    for x in trips:
        if fuel.get(x.id):
            groups[(fraud_rules.route_key(x.origin, x.destination), fraud_rules.load_band(x.loaded_weight_kg))].append(x)
    out = []
    for (key, band), rows in groups.items():
        samples = [{"litres": fuel[x.id], "km": fraud.best_km(x) or 0, "idle_hours": idle[x.id]} for x in rows]
        got = fraud_rules.baseline(samples, fraud_rules.Thresholds(**{**t.__dict__, "min_baseline_trips": 1}))
        if got:
            origin, _, destination = key.partition("|")
            out.append({"route": f"{origin.title()} to {destination.title()}" if origin and destination else "No route recorded", "load_band": band, "l_per_km": got["l_per_km"], "km_per_litre": round(1 / got["l_per_km"], 2), "trips": got["trips"], "established": got["trips"] >= t.min_baseline_trips})
    out.sort(key=lambda r: -r["trips"])
    return {"vehicle_id": vehicle.id, "registration": vehicle.registration, "declared_kmpl_loaded": vehicle.expected_kmpl_loaded, "declared_kmpl_empty": vehicle.expected_kmpl_empty, "needed_trips": t.min_baseline_trips, "baselines": out}
