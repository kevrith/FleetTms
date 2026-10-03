"""Phone GPS rules (masterplan 5.3). The same rules as packages/business-rules/src/gps.ts, tested against
gps-cases.json on both sides: which fixes to trust, how far a trip really went, what state a lorry is in, and whether
the odometer and the GPS agree."""

import math
from datetime import datetime

EARTH_KM = 6371.0
MAX_ACCURACY_M = 100  # a fix less accurate than this is not trusted for distance
MAX_SPEED_KMH = 200  # faster than this between two fixes is a jump in the signal, not driving
MIN_STEP_M = 15  # steps shorter than this are jitter while standing still
FRESH_SECONDS = 5 * 60  # a lorry reporting within this is "live"
MOVING_KMH = 5
DEFAULT_SPEED_KMH = 40
MIN_POINTS_FOR_CHECK = 3
TOLERANCE_PCT = 15
TOLERANCE_KM = 10


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def good_fix(lat: float, lng: float, accuracy_m: float | None) -> bool:
    return -90 <= lat <= 90 and -180 <= lng <= 180 and (accuracy_m is None or accuracy_m <= MAX_ACCURACY_M)


def path_distance_km(points: list[dict]) -> tuple[float, int]:
    """(kilometres driven, fixes used). Each point is {at: datetime, lat, lng, accuracy_m}. Poor fixes are dropped, a step
    that would mean more than 200 km/h is a jump and is ignored, and steps under 15 m are standing-still jitter."""
    kept = sorted((p for p in points if good_fix(p["lat"], p["lng"], p.get("accuracy_m"))), key=lambda p: p["at"])
    total, last = 0.0, None
    for p in kept:
        if last is None:
            last = p
            continue
        step_km = haversine_km(last["lat"], last["lng"], p["lat"], p["lng"])
        if step_km * 1000 < MIN_STEP_M:
            continue  # stay anchored on the last real position, so slow creep is not lost to jitter
        hours = (p["at"] - last["at"]).total_seconds() / 3600
        if hours > 0 and step_km / hours <= MAX_SPEED_KMH:
            total += step_km
        last = p  # a jump is skipped, but the lorry really is at the new place
    return round(total, 3), len(kept)


def vehicle_state(*, on_trip: bool, last_at: datetime | None, now: datetime, speed_kmh: float | None) -> str:
    """moving, idle (on a trip but standing), offline (on a trip but not reporting), parked (no trip), or unknown (never seen)."""
    if last_at is None:
        return "unknown"
    if not on_trip:
        return "parked"
    if (now - last_at).total_seconds() > FRESH_SECONDS:
        return "offline"
    return "moving" if (speed_kmh or 0) >= MOVING_KMH else "idle"


def distance_check(odometer_km: int | None, gps_km: float | None, points: int) -> str:
    """Does the odometer agree with the phone's GPS? ok, mismatch (they differ by more than 15 percent and 10 km), or no_gps."""
    if gps_km is None or points < MIN_POINTS_FOR_CHECK or odometer_km is None:
        return "no_gps"
    return "mismatch" if abs(odometer_km - gps_km) > max(TOLERANCE_KM, TOLERANCE_PCT / 100 * max(odometer_km, gps_km)) else "ok"


def eta_minutes(remaining_km: float, recent_speeds_kmh: list[float]) -> int | None:
    """Minutes to go, rounded up to 5, from the speed the lorry has actually been making (its moving speeds), else 40 km/h."""
    if remaining_km < 0:
        return None
    moving = [s for s in recent_speeds_kmh if s >= 10]
    speed = sum(moving) / len(moving) if moving else DEFAULT_SPEED_KMH
    minutes = remaining_km / speed * 60
    return int(math.ceil(minutes / 5) * 5)


# ---- three-way distance: odometer, phone GPS and the tracker (masterplan 5.4) ----------------------------------------------


def _agree(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOLERANCE_KM, TOLERANCE_PCT / 100 * max(a, b))


def three_way(*, odometer_km: float | None, phone_km: float | None, phone_points: int, tracker_km: float | None, tracker_points: int) -> dict:
    """Compares every source that has something to say. All agreeing is "ok". When they do not, `suspect` names the one source
    that disagrees with both of the others while those two agree with each other (usually the odometer being wound back, or a
    phone left behind); with only two sources there is no way to tell which is wrong, so no one is named."""
    sources: dict[str, float] = {}
    if odometer_km is not None:
        sources["odometer"] = float(odometer_km)
    if phone_km is not None and phone_points >= MIN_POINTS_FOR_CHECK:
        sources["phone"] = float(phone_km)
    if tracker_km is not None and tracker_points >= MIN_POINTS_FOR_CHECK:
        sources["tracker"] = float(tracker_km)
    if len(sources) < 2:
        return {"check": "no_gps", "suspect": None, "sources": sources}
    names = list(sources)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1 :]]
    if all(_agree(sources[a], sources[b]) for a, b in pairs):
        return {"check": "ok", "suspect": None, "sources": sources}
    suspect = None
    if len(names) == 3:
        for name in names:
            others = [n for n in names if n != name]
            if _agree(sources[others[0]], sources[others[1]]) and not _agree(sources[name], sources[others[0]]) and not _agree(sources[name], sources[others[1]]):
                suspect = name
    return {"check": "mismatch", "suspect": suspect, "sources": sources}
