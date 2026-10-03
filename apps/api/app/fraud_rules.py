"""Fraud and anomaly rules (masterplan 5.13): what counts as too much fuel, a side trip, a stop nobody can explain, too much idling.
Pure functions, the same as packages/business-rules/src/fraud.ts and tested against fraud-cases.json on both sides. The engine in
app/fraud.py gathers the numbers from the database and asks these what they mean."""

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from statistics import median

from app.geofence_rules import inside
from app.gps_rules import haversine_km


@dataclass(frozen=True)
class Thresholds:
    fuel_variance_pct: float = 10  # fuel above what the distance and the idling explain, in percent
    idle_litres_per_hour: float = 3.0  # what a lorry burns standing with the engine on
    min_baseline_trips: int = 3  # trips needed before a vehicle's own history is used as its normal
    min_fuel_km: float = 30  # shorter trips are too small for litres per kilometre to mean anything
    long_stop_minutes: int = 45  # standing this long away from any known place needs an explanation
    stop_radius_m: float = 100  # moving less than this is still the same stop
    side_trip_pct: float = 25  # driving this much further than the route is a side trip ...
    side_trip_min_km: float = 15  # ... if it is also at least this many kilometres more
    tamper_window_hours: float = 6  # a stop this soon after a tracker was cut is worse
    excess_idle_pct: float = 20  # idling as a share of the trip's time ...
    excess_idle_minutes: int = 60  # ... and at least this long
    fuel_drop_litres: int = 15  # a tank falling this much while the lorry is parked is siphoning ...
    fuel_refill_litres: int = 20  # ... and a tank rising this much is a refill
    refill_paid_gap_pct: int = 10  # fuel paid for that never reached the tank, in percent of what was paid (and at least 10 litres)
    model_min_trips: int = 12  # trips a vehicle needs before its learned fuel model is used alongside the rules
    model_z: float = 3.0  # how many usual misses above the model's prediction a trip's fuel must be to be flagged


DEFAULT = Thresholds()
LIMITS: dict[str, tuple[float, float]] = {  # what a business may set each threshold to
    "fuel_variance_pct": (3, 50), "idle_litres_per_hour": (0, 10), "min_baseline_trips": (1, 20), "min_fuel_km": (5, 500), "long_stop_minutes": (10, 480),
    "stop_radius_m": (30, 500), "side_trip_pct": (5, 200), "side_trip_min_km": (1, 500), "tamper_window_hours": (1, 48), "excess_idle_pct": (5, 90),
    "excess_idle_minutes": (10, 600), "fuel_drop_litres": (5, 300), "fuel_refill_litres": (5, 500), "refill_paid_gap_pct": (3, 100), "model_min_trips": (6, 100), "model_z": (2, 6),
}  # fmt: skip
MOVING_KMH = 5  # a fix this fast is not part of a stop


def thresholds_from(overrides: dict | None) -> Thresholds:
    """The defaults with a business's own values on top. Unknown names and values outside the allowed range are ignored."""
    values = {}
    for f in fields(Thresholds):
        raw = (overrides or {}).get(f.name)
        low, high = LIMITS[f.name]
        if isinstance(raw, int | float) and not isinstance(raw, bool) and low <= raw <= high:
            values[f.name] = f.type(raw)  # counts and minutes are whole numbers, the rest may have decimals
    return Thresholds(**values)


def load_band(kg: float | None) -> str:
    """Loads in five-tonne steps, so a trip is compared with trips carrying about the same."""
    if kg is None or kg < 500:
        return "empty"
    return f"{int(kg // 5000) * 5}t"


def route_key(origin: str | None, destination: str | None) -> str:
    return f"{(origin or '').strip().lower()}|{(destination or '').strip().lower()}"


def baseline(samples: list[dict], t: Thresholds = DEFAULT) -> dict | None:
    """A vehicle's normal litres per kilometre from its earlier trips ({litres, km, idle_hours}), with what idling used taken out.
    None until there are enough trips to call anything normal."""
    rates = []
    for s in samples:
        if s["km"] >= t.min_fuel_km and s["litres"] > 0:
            net = max(s["litres"] - s.get("idle_hours", 0) * t.idle_litres_per_hour, 0)
            if net > 0:
                rates.append(net / s["km"])
    if len(rates) < t.min_baseline_trips:
        return None
    return {"l_per_km": round(median(rates), 4), "trips": len(rates)}


def fuel_check(*, litres: float, km: float, idle_hours: float, l_per_km: float, t: Thresholds = DEFAULT) -> dict:
    """Fuel bought for a trip against what the distance and the idling explain."""
    if km < t.min_fuel_km or l_per_km <= 0:
        return {"flagged": False, "expected_litres": None, "variance_pct": None, "severity": None}
    expected = l_per_km * km + idle_hours * t.idle_litres_per_hour
    variance = (litres - expected) / expected * 100
    flagged = variance > t.fuel_variance_pct
    return {"flagged": flagged, "expected_litres": round(expected, 1), "variance_pct": round(variance, 1), "severity": ("red" if variance > 2 * t.fuel_variance_pct else "amber") if flagged else None}


def side_trip_check(*, gps_km: float, expected_km: float, t: Thresholds = DEFAULT) -> dict:
    """Driving much further than the route (or than this route usually takes) means somewhere else was visited on the way."""
    extra = gps_km - expected_km
    flagged = expected_km > 0 and gps_km > expected_km * (1 + t.side_trip_pct / 100) and extra >= t.side_trip_min_km
    return {"flagged": flagged, "extra_km": round(extra, 1), "over_pct": round(extra / expected_km * 100, 1) if expected_km > 0 else None}


def find_stops(fixes: list[dict], t: Thresholds = DEFAULT) -> list[dict]:
    """Where a vehicle stood still for a while. Fixes are {at, lat, lng, speed}, oldest first. A stop is a run of fixes that stay
    within the stop radius of where it began and are not moving fast; its length is from the first fix to the last."""
    stops: list[dict] = []
    run: list[dict] = []

    def close() -> None:
        if len(run) >= 2:
            minutes = (run[-1]["at"] - run[0]["at"]).total_seconds() / 60
            stops.append({"start": run[0]["at"], "end": run[-1]["at"], "minutes": round(minutes, 1), "lat": run[0]["lat"], "lng": run[0]["lng"]})

    for f in fixes:
        still = f.get("speed") is None or f["speed"] < MOVING_KMH
        if run and still and haversine_km(run[0]["lat"], run[0]["lng"], f["lat"], f["lng"]) * 1000 <= t.stop_radius_m:
            run.append(f)
            continue
        close()
        run = [f] if still else []
    close()
    return stops


def explain_stop(stop: dict, *, places: list[dict], t: Thresholds = DEFAULT) -> str | None:
    """None when a stop needs no explaining (short, or at a known place: a depot, a client's site, a fuel station, the delivery
    site), otherwise "unexplained". `places` are shapes ({type, ...})."""
    if stop["minutes"] < t.long_stop_minutes:
        return None
    if any(inside(p, stop["lat"], stop["lng"]) for p in places):
        return None
    return "unexplained"


def tamper_before(stop_start: datetime, tampers: list[datetime], t: Thresholds = DEFAULT) -> datetime | None:
    """The latest tracker tamper (power cut, jamming) within the window before a stop began or while it lasted, if any."""
    window = timedelta(hours=t.tamper_window_hours)
    near = [x for x in tampers if stop_start - window <= x <= stop_start + timedelta(minutes=30)]
    return max(near) if near else None


def idle_check(*, idle_minutes: float, trip_minutes: float, t: Thresholds = DEFAULT) -> dict:
    share = idle_minutes / trip_minutes * 100 if trip_minutes > 0 else 0
    return {"flagged": idle_minutes >= t.excess_idle_minutes and share >= t.excess_idle_pct, "share_pct": round(share, 1)}


def odometer_finding(check: str | None, detail: dict | None) -> dict:
    """What a failed three-way distance check means: red when the odometer is the odd one out (it may have been wound back), amber
    when the sources disagree and nobody can say which is wrong."""
    if check != "mismatch":
        return {"flagged": False, "severity": None, "suspect": None}
    suspect = (detail or {}).get("suspect")
    return {"flagged": True, "severity": "red" if suspect == "odometer" else "amber", "suspect": suspect}
