"""The fraud engine (masterplan 5.13). It gathers the numbers for each check from the database, asks app/fraud_rules.py what they mean,
and records what it finds as a FraudAlert with the evidence behind it. A finding is raised once (its dedupe key), the vehicle's trust
level is noted on it, and the people the business chose are told the way it chose. Callers commit."""

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, fraud_rules
from app.fraud_rules import Thresholds
from app.models import (
    AlertSettings,
    AuditLog,
    BehaviourEvent,
    Business,
    DeviceCheck,
    Expense,
    FraudAlert,
    FuelEntry,
    Geofence,
    Job,
    LocationPoint,
    Membership,
    MembershipStatus,
    ProofOfDelivery,
    Role,
    SavedRoute,
    TrackerAlert,
    TrackingGap,
    Trip,
    TripStatus,
    TyreSwapAlert,
    Vehicle,
    WorkOrder,
    WorkOrderPart,
    WorkOrderStatus,
)
from app.notify import get_email_sender
from app.reminders import NAIROBI
from app.sms import get_sms_sender
from app.tenancy import current_business_id
from app.trust import flag_summary, trust_out

log = logging.getLogger(__name__)
LOOKBACK = timedelta(days=7)  # how far back the sweep looks for things it has not seen
TAMPER_KINDS = ("power_cut", "gps_jamming", "tamper")
SENSITIVE_ACTIONS = {  # changes made after the fact to records other checks lean on, when someone other than the owner made them
    "invoice.voided": "an invoice was voided", "inspection.overridden": "a blocked inspection was overridden", "trip.weight_entered_by_office": "a trip's weight was entered by the office",
    "route_cost.updated": "a route's usual cost was changed", "route_cost.deleted": "a route's usual cost was deleted", "spend_limits.changed": "the spending limits were changed",
    "lease.adjustment": "a lease balance was adjusted", "trip.cancelled": "a trip was cancelled",
}  # fmt: skip
DEFAULT_CHANNELS = {
    "red": {"roles": ["owner", "manager"], "channels": ["sms"]},
    "amber": {"roles": ["owner"], "channels": []},  # shown in the app only
}
CHANNEL_NAMES = ("sms", "email")
ROLE_NAMES = ("owner", "manager", "supervisor", "accountant")


@dataclass
class Finding:
    kind: str
    severity: str
    dedupe_key: str
    title: str
    detail: str | None = None
    evidence: dict = field(default_factory=dict)
    vehicle_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    driver_membership_id: uuid.UUID | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    occurred_at: datetime | None = None
    notify: bool = True


# ---- settings ----------------------------------------------------------------------------------------------------------


async def load_settings(db: AsyncSession) -> tuple[Thresholds, dict]:
    row = (await db.execute(select(AlertSettings))).scalars().first()
    stored = (row.channels if row else None) or {}
    channels = {sev: {**DEFAULT_CHANNELS[sev], **(stored.get(sev) or {})} for sev in DEFAULT_CHANNELS}
    return fraud_rules.thresholds_from(row.thresholds if row else None), channels


# ---- raising and telling -----------------------------------------------------------------------------------------------


async def notify(db: AsyncSession, alert: FraudAlert, channels: dict) -> int:
    """Tells the people the business chose, the way it chose. In-app is always there; text and email are optional per severity."""
    pref = channels.get(alert.severity) or DEFAULT_CHANNELS[alert.severity]
    wanted = {r for r in pref["roles"]}
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    message = f"{business.name}: {alert.title}"
    told = 0
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        if not ({r.role.value for r in m.roles} & wanted):
            continue
        sent = False
        if "sms" in pref["channels"] and m.user.phone:
            await get_sms_sender().send(m.user.phone, message)
            sent = True
        if "email" in pref["channels"] and m.user.email:
            await get_email_sender().send(m.user.email, f"FleetTms alert: {alert.title}", f"{message}\n\n{alert.detail or ''}\n\nOpen FleetTms to see the evidence and say whether it was explained.")
            sent = True
        told += sent
    return told


async def raise_finding(db: AsyncSession, f: Finding, channels: dict | None = None) -> FraudAlert | None:
    """Records a finding unless the same one was raised before. Returns None for a repeat."""
    existing = (await db.execute(select(FraudAlert).where(FraudAlert.dedupe_key == f.dedupe_key))).scalars().first()
    if existing is not None:
        return None
    if channels is None:
        _, channels = await load_settings(db)
    trust = None
    if f.vehicle_id is not None:
        vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == f.vehicle_id))).scalar_one_or_none()
        if vehicle is not None:
            trust = trust_out(vehicle, (await flag_summary(db, [vehicle.id])).get(vehicle.id, {}))["level"]
    alert = FraudAlert(
        kind=f.kind, severity=f.severity, vehicle_id=f.vehicle_id, trip_id=f.trip_id, driver_membership_id=f.driver_membership_id, subject_type=f.subject_type, subject_id=f.subject_id,
        dedupe_key=f.dedupe_key, title=f.title, detail=f.detail, evidence=f.evidence, trust_level=trust, occurred_at=f.occurred_at or datetime.now(UTC),
    )  # fmt: skip
    db.add(alert)
    await db.flush()
    audit.record(db, actor_user_id=None, action=f"fraud_alert.{f.kind}", entity_type="fraud_alert", entity_id=alert.id, after={"severity": f.severity, "title": f.title})
    if f.notify:
        alert.notified = await notify(db, alert, channels)
    return alert


async def upgrade_alert(db: AsyncSession, dedupe_key: str, f: Finding, channels: dict) -> FraudAlert | None:
    """A finding that turns out worse than first thought (a long stop that followed a tracker being cut) replaces the milder one and
    tells people again. Only an alert nobody has answered yet is changed."""
    a = (await db.execute(select(FraudAlert).where(FraudAlert.dedupe_key == dedupe_key))).scalars().first()
    if a is None or a.status != "open" or a.kind == f.kind:
        return None
    a.kind, a.severity, a.title, a.detail, a.evidence = f.kind, f.severity, f.title, f.detail, f.evidence
    audit.record(db, actor_user_id=None, action=f"fraud_alert.{f.kind}", entity_type="fraud_alert", entity_id=a.id, after={"severity": f.severity, "title": f.title, "upgraded": True})
    if f.notify:
        a.notified += await notify(db, a, channels)
    return a


# ---- gathering what the checks need ------------------------------------------------------------------------------------


async def _vehicle(db: AsyncSession, vehicle_id: uuid.UUID) -> Vehicle:
    return (await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))).scalar_one()


def best_km(trip: Trip) -> float | None:
    """The distance to trust for a trip: the GPS when the odometer is the odd one out, otherwise the odometer, else whatever GPS there is."""
    gps = trip.tracker_distance_km if trip.tracker_distance_km is not None else trip.gps_distance_km
    if (trip.distance_detail or {}).get("suspect") == "odometer" and gps is not None:
        return float(gps)
    if trip.distance_km is not None:
        return float(trip.distance_km)
    return float(gps) if gps is not None else None


async def _idle_hours(db: AsyncSession, trip_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    out: dict[uuid.UUID, float] = defaultdict(float)
    if trip_ids:
        for e in (await db.execute(select(BehaviourEvent).where(BehaviourEvent.trip_id.in_(trip_ids), BehaviourEvent.kind == "idling"))).scalars():
            out[e.trip_id] += (e.value or 0) / 60
    return out


async def _fuel_by_trip(db: AsyncSession, trips: list[Trip]) -> dict[uuid.UUID, float]:
    """Litres bought for each trip: entries tied to it, and the vehicle's untied entries made while it was running."""
    out: dict[uuid.UUID, float] = defaultdict(float)
    if not trips:
        return out
    ids = {t.id for t in trips}
    entries = (await db.execute(select(FuelEntry).where(FuelEntry.vehicle_id.in_({t.vehicle_id for t in trips})))).scalars().all()
    for e in entries:
        if e.trip_id in ids:
            out[e.trip_id] += float(e.litres)
        elif e.trip_id is None:
            for t in trips:
                if t.vehicle_id == e.vehicle_id and t.started_at and t.started_at <= e.captured_at <= (t.ended_at or datetime.now(UTC)):
                    out[t.id] += float(e.litres)
                    break
    return out


async def baseline_for(db: AsyncSession, trip: Trip, vehicle: Vehicle, t: Thresholds, *, exclude_self: bool = True) -> dict | None:
    """The vehicle's normal litres per km for trips like this one. Tried in order: the same route and load band, the same load band
    on any route, then the consumption entered for the vehicle. Returns {l_per_km, trips, source} or None."""
    others = (await db.execute(select(Trip).where(Trip.vehicle_id == trip.vehicle_id, Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED)), Trip.distance_km.is_not(None)).order_by(Trip.ended_at.desc()).limit(60))).scalars().all()
    others = [o for o in others if not (exclude_self and o.id == trip.id)]
    fuel, idle = await _fuel_by_trip(db, others), await _idle_hours(db, [o.id for o in others])
    band, key = fraud_rules.load_band(trip.loaded_weight_kg), fraud_rules.route_key(trip.origin, trip.destination)

    def samples(rows: list[Trip]) -> list[dict]:
        return [{"litres": fuel[o.id], "km": best_km(o) or 0, "idle_hours": idle[o.id]} for o in rows if fuel.get(o.id)]

    same_route = [o for o in others if fraud_rules.load_band(o.loaded_weight_kg) == band and fraud_rules.route_key(o.origin, o.destination) == key]
    for source, rows in (("same route and load", same_route), ("same load", [o for o in others if fraud_rules.load_band(o.loaded_weight_kg) == band])):
        got = fraud_rules.baseline(samples(rows), t)
        if got:
            return {**got, "source": source}
    kmpl = vehicle.expected_kmpl_empty if band == "empty" else vehicle.expected_kmpl_loaded
    if kmpl and float(kmpl) > 0:
        return {"l_per_km": round(1 / float(kmpl), 4), "trips": 0, "source": "the consumption entered for the vehicle"}
    return None


async def _expected_km(db: AsyncSession, trip: Trip, t: Thresholds) -> tuple[float, str] | None:
    """How far the trip should have been: the saved route's distance, or what trips between the same places usually come to."""
    if trip.job_id:
        job = (await db.execute(select(Job).where(Job.id == trip.job_id))).scalar_one_or_none()
        if job and job.route_id:
            route = (await db.execute(select(SavedRoute).where(SavedRoute.id == job.route_id))).scalar_one_or_none()
            if route and route.distance_km > 0:
                return float(route.distance_km), "the saved route"
    key = fraud_rules.route_key(trip.origin, trip.destination)
    if key == "|":
        return None
    rows = (await db.execute(select(Trip).where(Trip.vehicle_id.is_not(None), Trip.id != trip.id, Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED)), Trip.distance_km.is_not(None)).order_by(Trip.ended_at.desc()).limit(80))).scalars().all()
    km = [best_km(o) for o in rows if fraud_rules.route_key(o.origin, o.destination) == key and best_km(o)]
    return (float(median(km)), "trips between the same places") if len(km) >= t.min_baseline_trips else None


async def _places(db: AsyncSession, trip: Trip) -> list[dict]:
    """Where a long stop needs no explaining: depots, client sites and fuel stations, and the delivery site."""
    out = [g.shape for g in (await db.execute(select(Geofence).where(Geofence.is_active.is_(True), Geofence.kind.in_(("depot", "client_site", "fuel_station"))))).scalars() if not g.vehicle_ids or str(trip.vehicle_id) in g.vehicle_ids]
    if trip.job_id:
        job = (await db.execute(select(Job).where(Job.id == trip.job_id))).scalar_one_or_none()
        route = (await db.execute(select(SavedRoute).where(SavedRoute.id == job.route_id))).scalar_one_or_none() if job and job.route_id else None
        if route and route.dropoff_lat is not None and route.dropoff_lng is not None:
            out.append({"type": "circle", "lat": route.dropoff_lat, "lng": route.dropoff_lng, "radius_m": route.site_radius_m or 500})
    return out


async def _fixes(db: AsyncSession, trip: Trip, end: datetime) -> list[dict]:
    rows = (await db.execute(select(LocationPoint).where(LocationPoint.vehicle_id == trip.vehicle_id, LocationPoint.recorded_at >= trip.started_at, LocationPoint.recorded_at <= end).order_by(LocationPoint.recorded_at))).scalars().all()
    source = "tracker" if any(r.source == "tracker" for r in rows) else "phone"
    return [{"at": r.recorded_at, "lat": r.lat, "lng": r.lng, "speed": r.speed_kmh} for r in rows if r.source == source]


def _hhmm(moment: datetime) -> str:
    return moment.astimezone(NAIROBI).strftime("%H:%M")


# ---- the checks on one trip --------------------------------------------------------------------------------------------


async def check_trip(db: AsyncSession, trip: Trip, now: datetime | None = None) -> int:
    """Every check that can be made on a trip so far. Safe to run again and again: what was found before is not raised twice.
    Returns how many new alerts were raised."""
    if trip.started_at is None:
        return 0
    now = now or datetime.now(UTC)
    if trip.ended_at is not None and now - trip.ended_at > timedelta(days=30):
        return 0  # too old to act on: finishing the totals of an old trip must not raise news about it
    t, channels = await load_settings(db)
    vehicle = await _vehicle(db, trip.vehicle_id)
    reg = vehicle.registration
    ended = trip.status in (TripStatus.DELIVERED, TripStatus.COMPLETED) and trip.ended_at is not None
    end = trip.ended_at or now
    base = {"vehicle_id": vehicle.id, "trip_id": trip.id, "driver_membership_id": trip.driver_membership_id}
    raised = 0

    async def put(f: Finding) -> None:
        nonlocal raised
        raised += (await raise_finding(db, f, channels)) is not None

    if ended:
        found = fraud_rules.odometer_finding(trip.distance_check, trip.distance_detail)
        if found["flagged"]:
            src = (trip.distance_detail or {}).get("sources", {})
            who = {"odometer": "The odometer looks wrong.", "phone": "The phone's GPS looks wrong.", "tracker": "The tracker looks wrong."}.get(found["suspect"], "The sources disagree and we cannot say which is wrong.")
            await put(Finding("odometer_mismatch", found["severity"], f"odometer:{trip.id}", f"{reg}: odometer says {trip.distance_km} km but the GPS says {round(trip.tracker_distance_km or trip.gps_distance_km or 0)} km", who,
                              {"sources_km": src, "suspect": found["suspect"], "odometer_km": trip.distance_km}, occurred_at=trip.ended_at, **base))  # fmt: skip

        km, fuel = best_km(trip), (await _fuel_by_trip(db, [trip])).get(trip.id)
        if km and fuel:
            baseline = await baseline_for(db, trip, vehicle, t)
            idle = (await _idle_hours(db, [trip.id])).get(trip.id, 0.0)
            if baseline:
                v = fraud_rules.fuel_check(litres=fuel, km=km, idle_hours=idle, l_per_km=baseline["l_per_km"], t=t)
                if v["flagged"]:
                    await put(Finding("fuel_variance", v["severity"], f"fuel:{trip.id}", f"{reg}: {fuel:g} litres of fuel for {km:g} km, {v['variance_pct']:g}% more than expected", f"About {v['expected_litres']:g} litres were expected, going by {baseline['source']}.",
                                      {"litres": fuel, "km": km, "expected_litres": v["expected_litres"], "variance_pct": v["variance_pct"], "idle_hours": round(idle, 1), "baseline_l_per_km": baseline["l_per_km"], "baseline_source": baseline["source"], "baseline_trips": baseline["trips"], "threshold_pct": t.fuel_variance_pct},
                                      occurred_at=trip.ended_at, **base))  # fmt: skip

        gps = trip.tracker_distance_km if trip.tracker_distance_km is not None else trip.gps_distance_km
        expected = await _expected_km(db, trip, t) if gps else None
        if gps and expected:
            s = fraud_rules.side_trip_check(gps_km=float(gps), expected_km=expected[0], t=t)
            if s["flagged"]:
                await put(Finding("side_trip", "amber", f"side_trip:{trip.id}", f"{reg}: drove {s['extra_km']:g} km further than the route", f"The GPS says {float(gps):g} km; {expected[1]} says {expected[0]:g} km. Somewhere else may have been visited.",
                                  {"gps_km": float(gps), "expected_km": expected[0], "extra_km": s["extra_km"], "over_pct": s["over_pct"], "expected_from": expected[1]}, occurred_at=trip.ended_at, **base))  # fmt: skip

        idle_min = (await _idle_hours(db, [trip.id])).get(trip.id, 0.0) * 60
        i = fraud_rules.idle_check(idle_minutes=idle_min, trip_minutes=(trip.ended_at - trip.started_at).total_seconds() / 60, t=t)
        if i["flagged"]:
            await put(Finding("excess_idling", "amber", f"idle:{trip.id}", f"{reg}: engine idling for {round(idle_min)} minutes", f"{i['share_pct']:g}% of the trip's time, burning fuel with no distance.", {"idle_minutes": round(idle_min), "share_pct": i["share_pct"]}, occurred_at=trip.ended_at, **base))  # fmt: skip

        if trip.overload_kg and trip.overload_kg > 0:
            await put(Finding("overload", "red", f"overload:{trip.id}", f"{reg}: loaded {trip.overload_kg:,} kg over the legal limit", "Overloading brings fines and damages the vehicle.", {"overload_kg": trip.overload_kg, "loaded_weight_kg": trip.loaded_weight_kg}, occurred_at=trip.loaded_at, **base))  # fmt: skip

    # stops: run on trips still going as well, so a lorry parked somewhere strange is noticed while it is still there
    places, tampers = await _places(db, trip), []
    for a in (await db.execute(select(TrackerAlert).where(TrackerAlert.vehicle_id == trip.vehicle_id, TrackerAlert.kind.in_(TAMPER_KINDS), TrackerAlert.at >= trip.started_at - timedelta(hours=t.tamper_window_hours), TrackerAlert.at <= end))).scalars():
        tampers.append(a.at)
    for stop in fraud_rules.find_stops(await _fixes(db, trip, end), t):
        if fraud_rules.explain_stop(stop, places=places, t=t) is None:
            continue
        key = f"stop:{trip.id}:{stop['start'].strftime('%Y%m%d%H%M')}"
        cut = fraud_rules.tamper_before(stop["start"], tampers, t)
        where = {"lat": round(stop["lat"], 5), "lng": round(stop["lng"], 5)}
        evidence = {"from": stop["start"].isoformat(), "to": stop["end"].isoformat(), "minutes": round(stop["minutes"]), **where}
        if cut is not None:
            worse = Finding("tamper_then_stop", "red", key, f"{reg}: stopped {round(stop['minutes'])} minutes away from any known place, soon after the tracker was cut", f"The tracker was cut at {_hhmm(cut)} and the lorry stood from {_hhmm(stop['start'])}. This is how siphoning and hijacks start.",
                            {**evidence, "tracker_cut_at": cut.isoformat()}, occurred_at=stop["start"], **base)  # fmt: skip
            if await upgrade_alert(db, key, worse, channels) is None:
                await put(worse)
        else:
            await put(Finding("long_stop", "amber", key, f"{reg}: stopped {round(stop['minutes'])} minutes away from any known place", f"From {_hhmm(stop['start'])} to {_hhmm(stop['end'])}. Not a depot, a client's site or a fuel station.", evidence, occurred_at=stop["start"], **base))  # fmt: skip
    return raised


# ---- the sweep: everything else ----------------------------------------------------------------------------------------


async def _membership_for_user(db: AsyncSession, user_id: uuid.UUID | None) -> uuid.UUID | None:
    if user_id is None:
        return None
    m = (await db.execute(select(Membership).where(Membership.user_id == user_id))).scalars().first()
    return m.id if m else None


async def sweep(db: AsyncSession, now: datetime | None = None) -> int:
    """Looks over the last week for everything the engine watches that is not tied to one trip's end: tracker tamper, going dark, fake
    GPS, tyre swaps, padded expenses, fuel that does not add up, parts never fitted, and sensitive changes by staff. Then every recent
    trip is checked. Returns how many new alerts were raised."""
    now = now or datetime.now(UTC)
    since = now - LOOKBACK
    _, channels = await load_settings(db)
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    raised = 0

    async def put(f: Finding) -> None:
        nonlocal raised
        raised += (await raise_finding(db, f, channels)) is not None

    reg = lambda vid: vehicles[vid].registration if vid in vehicles else "A vehicle"
    for a in (await db.execute(select(TrackerAlert).where(TrackerAlert.at >= since))).scalars():
        if a.kind in TAMPER_KINDS:
            words = {"power_cut": "the tracker lost power", "gps_jamming": "the tracker reports GPS jamming", "tamper": "the tracker reports tampering"}[a.kind]
            await put(Finding(a.kind, "red", f"tamper:{a.id}", f"{reg(a.vehicle_id)}: {words}", "Cutting or jamming the tracker is the classic step before siphoning or hijacking.", {**a.details, "at": a.at.isoformat()}, vehicle_id=a.vehicle_id, trip_id=a.trip_id,
                              subject_type="tracker_alert", subject_id=str(a.id), occurred_at=a.at, notify=False))  # fmt: skip  (the tracker alert already texted the owner)
        elif a.kind == "device_offline" and a.trip_id is not None:
            await put(Finding("went_dark", "amber", f"dark:tracker:{a.id}", f"{reg(a.vehicle_id)}: tracker stopped reporting during a trip", None, {**a.details, "at": a.at.isoformat()}, vehicle_id=a.vehicle_id, trip_id=a.trip_id, subject_type="tracker_alert", subject_id=str(a.id), occurred_at=a.at, notify=False))  # fmt: skip
    for g in (await db.execute(select(TrackingGap).where(TrackingGap.detected_at >= since))).scalars():
        trip = (await db.execute(select(Trip).where(Trip.id == g.trip_id))).scalar_one_or_none()
        await put(Finding("went_dark", "amber", f"dark:gap:{g.id}", f"{reg(g.vehicle_id)}: phone stopped reporting its location during a trip", "The phone may be off, out of battery, or the app closed on purpose.",
                          {"last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None, "detected_at": g.detected_at.isoformat()}, vehicle_id=g.vehicle_id, trip_id=g.trip_id, driver_membership_id=trip.driver_membership_id if trip else None,
                          subject_type="tracking_gap", subject_id=str(g.id), occurred_at=g.detected_at, notify=False))  # fmt: skip
    wording = {"mock_location": ("fake_gps", "red", "a fake-GPS app was running on the phone"), "rooted": ("rooted_phone", "amber", "the phone is rooted"), "clock_changed": ("clock_changed", "amber", "the phone's clock was wrong")}
    for c in (await db.execute(select(DeviceCheck).where(DeviceCheck.reported_at >= since))).scalars():
        for flag in c.flags:
            if flag in wording and c.vehicle_id is not None:
                kind, severity, words = wording[flag]
                await put(Finding(kind, severity, f"device:{c.id}:{flag}", f"{reg(c.vehicle_id)}: {words}", "Locations and times from this phone cannot be fully trusted.", {"flag": flag, "device_id": c.device_id, "clock_offset_s": c.clock_offset_s, "app_version": c.app_version},
                                  vehicle_id=c.vehicle_id, driver_membership_id=await _membership_for_user(db, c.user_id), subject_type="device_check", subject_id=str(c.id), occurred_at=c.reported_at))  # fmt: skip
    for s in (await db.execute(select(TyreSwapAlert).where(TyreSwapAlert.status == "open"))).scalars():
        await put(Finding("tyre_swap", "red", f"tyre:{s.id}", f"{reg(s.vehicle_id)}: possible tyre swap at {s.position.replace('_', ' ')}", "New tyres may have been replaced with worn ones.", {"position": s.position, "recorded_serial": s.expected_serial, "serial_read": s.seen_serial, "reason": s.reason},
                          vehicle_id=s.vehicle_id, subject_type="tyre_swap_alert", subject_id=str(s.id), occurred_at=s.created_at))  # fmt: skip
    for e in (await db.execute(select(Expense).where(Expense.spent_at >= since))).scalars():
        if "unusual_for_route" in e.flags:
            trip = (await db.execute(select(Trip).where(Trip.id == e.trip_id))).scalar_one_or_none() if e.trip_id else None
            await put(Finding("expense_above_norm", "amber", f"expense:{e.id}:norm", f"{reg(e.vehicle_id) if e.vehicle_id else 'Expense'}: {e.category.value.replace('_', ' ')} claim well above the usual for the route", f"KES {e.amount_cents / 100:,.2f} claimed.",
                              {"amount_cents": e.amount_cents, "category": e.category.value, "route": f"{trip.origin} to {trip.destination}" if trip else None}, vehicle_id=e.vehicle_id, trip_id=e.trip_id, driver_membership_id=e.driver_membership_id, subject_type="expense", subject_id=str(e.id), occurred_at=e.spent_at))  # fmt: skip
    for f in (await db.execute(select(FuelEntry).where(FuelEntry.captured_at >= since))).scalars():
        if "amount_mismatch" in f.flags:
            await put(Finding("fuel_amount_mismatch", "amber", f"fuelentry:{f.id}:amount", f"{reg(f.vehicle_id)}: fuel total does not match litres times price", f"{f.litres} litres at KES {f.price_per_litre_cents / 100:,.2f} is not KES {f.amount_cents / 100:,.2f}.",
                              {"litres": float(f.litres), "price_per_litre_cents": f.price_per_litre_cents, "amount_cents": f.amount_cents, "station": f.station}, vehicle_id=f.vehicle_id, trip_id=f.trip_id, driver_membership_id=await _membership_for_user(db, f.recorded_by_user_id),
                              subject_type="fuel_entry", subject_id=str(f.id), occurred_at=f.captured_at))  # fmt: skip
    for pod in (await db.execute(select(ProofOfDelivery).where(ProofOfDelivery.captured_at >= since))).scalars():
        if "outside_site" in pod.flags:
            trip = (await db.execute(select(Trip).where(Trip.id == pod.trip_id))).scalar_one_or_none()
            if trip is not None:
                await put(Finding("delivery_off_site", "amber", f"pod:{pod.id}:site", f"{reg(trip.vehicle_id)}: delivery recorded away from the client's site", f"Delivered to {pod.recipient_name}, but not where the client's site is.", {"recipient": pod.recipient_name}, vehicle_id=trip.vehicle_id, trip_id=trip.id,
                                  driver_membership_id=trip.driver_membership_id, subject_type="pod", subject_id=str(pod.id), occurred_at=pod.captured_at))  # fmt: skip
    closed = {w for w in (await db.execute(select(WorkOrder.id).where(WorkOrder.status.not_in((WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.WAITING_PARTS))))).scalars()}
    for p in (await db.execute(select(WorkOrderPart).where(WorkOrderPart.part_id.is_not(None), WorkOrderPart.fitted.is_(False)))).scalars():
        if p.work_order_id in closed:
            wo = (await db.execute(select(WorkOrder).where(WorkOrder.id == p.work_order_id))).scalar_one()
            await put(Finding("parts_unfitted", "amber", f"part:{p.id}", f"{reg(wo.vehicle_id)}: {p.quantity} x {p.name} issued from the store but never marked as fitted", "Check the part really went on the vehicle.", {"part": p.name, "quantity": p.quantity, "work_order": wo.title}, vehicle_id=wo.vehicle_id, subject_type="work_order_part", subject_id=str(p.id), occurred_at=now))  # fmt: skip
    owners = {m.user_id for m in (await db.execute(select(Membership))).scalars() if Role.OWNER in {r.role for r in m.roles}}
    names = {m.user_id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    for log_row in (await db.execute(select(AuditLog).where(AuditLog.created_at >= since, AuditLog.action.in_(list(SENSITIVE_ACTIONS))))).scalars():
        if log_row.actor_user_id is None or log_row.actor_user_id in owners:
            continue
        who = names.get(log_row.actor_user_id, "Someone")
        await put(Finding("sensitive_change", "amber", f"audit:{log_row.id}", f"{who}: {SENSITIVE_ACTIONS[log_row.action]}", "Changes like this can cover tracks. Make sure it was meant.", {"action": log_row.action, "by": who, "entity": log_row.entity_type, "note": log_row.note}, occurred_at=log_row.created_at))  # fmt: skip

    for trip in (await db.execute(select(Trip).where(Trip.started_at.is_not(None), Trip.started_at >= since - timedelta(days=1)))).scalars().all():
        raised += await check_trip(db, trip, now)
    return raised


# ---- raised on the spot ------------------------------------------------------------------------------------------------


async def duplicate_attempt(db: AsyncSession, *, kind: str, user_id: uuid.UUID | None, vehicle_id: uuid.UUID | None, what: str, evidence: dict) -> FraudAlert | None:
    """Someone tried to claim the same receipt photo or M-Pesa code twice. The claim was refused; this makes sure the owner can see it."""
    stamp = evidence.get("code") or evidence.get("sha_prefix") or "x"
    title = {"duplicate_mpesa": "tried to claim an M-Pesa code that was already used", "duplicate_receipt": "tried to use a receipt photo that was already used"}[kind]
    who = (await db.execute(select(Membership).where(Membership.user_id == user_id))).scalars().first() if user_id else None
    name = who.user.name if who else "Someone"
    return await raise_finding(db, Finding(kind, "amber", f"dupe:{kind}:{user_id}:{stamp}", f"{name} {title}", what, evidence, vehicle_id=vehicle_id, driver_membership_id=who.id if who else None, subject_type="user", subject_id=str(user_id) if user_id else None))


async def duplicate_mpesa(db: AsyncSession, *, code: str, user_id: uuid.UUID | None, vehicle_id: uuid.UUID | None = None) -> FraudAlert | None:
    first = None
    for model, label in ((FuelEntry, "a fuel entry"), (Expense, "an expense")):
        row = (await db.execute(select(model).where(model.mpesa_code == code).limit(1))).scalars().first()
        if row is not None:
            first = {"used_on": label, "at": (row.captured_at if model is FuelEntry else row.spent_at).isoformat(), "record_id": str(row.id)}
            break
    return await duplicate_attempt(db, kind="duplicate_mpesa", user_id=user_id, vehicle_id=vehicle_id, what=f"M-Pesa code {code} was already used" + (f" on {first['used_on']}." if first else "."), evidence={"code": code, "first_use": first})


async def duplicate_photo(db: AsyncSession, *, sha: str, user_id: uuid.UUID | None) -> FraudAlert | None:
    from app.models import Photo

    original = (await db.execute(select(Photo).where(Photo.sha256 == sha))).scalars().first()
    first = {"kind": original.kind.value, "taken_at": original.captured_at.isoformat(), "photo_id": str(original.id), "uploaded_by": str(original.uploaded_by_user_id)} if original else None
    return await duplicate_attempt(db, kind="duplicate_receipt", user_id=user_id, vehicle_id=None, what="The exact same photo was submitted again.", evidence={"sha_prefix": sha[:12], "first_use": first})
