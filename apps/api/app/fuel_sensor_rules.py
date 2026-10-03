"""Fuel level sensors (masterplan 5.3, 5.13): finding refills and parked drops in a tank's level over time, and matching refills with
the fuel that was paid for. The same as packages/business-rules/src/fuelsensor.ts, tested against fuelsensor-cases.json on both
sides. A drop while the lorry is moving is fuel sloshing and burning, not a theft, so only a parked drop counts."""

from datetime import timedelta
from statistics import median

from app.fraud_rules import DEFAULT, Thresholds

NOISE_L = 1.0  # a change smaller than this between two readings is the sensor, not the tank
SETTLE_MIN = 10  # a change that stops for this long is over
DROP_WINDOW_MIN = 60  # fuel leaving faster than this much time is siphoning; slower is burning
MOVING_KMH = 5
MIN_GAP_L = 10  # fuel paid for but missing from the tank must be at least this many litres
MATCH_WINDOW_MIN = 180  # a refill belongs to a purchase made within this long of it


def smooth(readings: list[dict]) -> list[float]:
    """Each level replaced by the middle of it and its two neighbours, which removes a single wild reading."""
    levels = [r["litres"] for r in readings]
    if len(levels) < 3:
        return levels
    return [levels[0], *[median(levels[i - 1 : i + 2]) for i in range(1, len(levels) - 1)], levels[-1]]


def find_fuel_events(readings: list[dict], t: Thresholds = DEFAULT) -> list[dict]:
    """Refills and parked drops. Readings are {at, litres, speed, lat, lng}, oldest first. A change is a run of readings moving the
    same way, ended when it settles. A drop counts if it is big enough, quick enough and the lorry never moved; a refill if it is big
    enough and the lorry never moved."""
    if len(readings) < 2:
        return []
    level = smooth(readings)
    events: list[dict] = []
    run: dict | None = None

    def close() -> None:
        nonlocal run
        if run is None:
            return
        first, last = run["start"], run["end"]
        litres = abs(run["total"])
        window = readings[first : last + 1]
        parked = all(r.get("speed") is None or r["speed"] < MOVING_KMH for r in window)
        minutes = (readings[last]["at"] - readings[first]["at"]).total_seconds() / 60
        kind = "refill" if run["sign"] > 0 else "drop"
        wanted = t.fuel_refill_litres if kind == "refill" else t.fuel_drop_litres
        if parked and litres >= wanted and (kind == "refill" or minutes <= DROP_WINDOW_MIN):
            events.append({"kind": kind, "litres": round(litres, 1), "before": round(level[first], 1), "after": round(level[last], 1), "start": readings[first]["at"], "end": readings[last]["at"], "lat": readings[first].get("lat"), "lng": readings[first].get("lng")})
        run = None

    for i in range(1, len(readings)):
        delta = level[i] - level[i - 1]
        at = readings[i]["at"]
        if run is not None and at - run["changed"] > timedelta(minutes=SETTLE_MIN):
            close()
        if abs(delta) < NOISE_L:
            continue
        sign = 1 if delta > 0 else -1
        if run is not None and run["sign"] == sign:
            run["total"] += delta
            run["end"], run["changed"] = i, at
        else:
            close()
            run = {"start": i - 1, "end": i, "sign": sign, "total": delta, "changed": at}
    close()
    return events


def refill_vs_paid(*, paid_litres: float, refilled_litres: float, t: Thresholds = DEFAULT) -> dict:
    """Fuel paid for against fuel that reached the tank. Flagged when the shortfall is at least 10 litres and the threshold's share of
    what was paid; red when less than half of it arrived."""
    gap = paid_litres - refilled_litres
    flagged = paid_litres > 0 and gap >= max(MIN_GAP_L, paid_litres * t.refill_paid_gap_pct / 100)
    return {"flagged": flagged, "gap_litres": round(gap, 1), "severity": ("red" if refilled_litres < paid_litres / 2 else "amber") if flagged else None}


def match_refills(refills: list[dict], purchases: list[dict], t: Thresholds = DEFAULT) -> dict:
    """Pairs each refill with the nearest fuel purchase made within three hours of it. Refills and purchases are {at, litres}. Returns,
    for each purchase, what was paid and what reached the tank, and the refills with no purchase to explain them."""
    window = timedelta(minutes=MATCH_WINDOW_MIN)
    filled = [0.0] * len(purchases)
    unmatched: list[int] = []
    for ri, r in enumerate(refills):
        near = [(abs(r["at"] - p["at"]), pi) for pi, p in enumerate(purchases) if abs(r["at"] - p["at"]) <= window]
        if near:
            filled[min(near)[1]] += r["litres"]
        else:
            unmatched.append(ri)
    rows = []
    for pi, p in enumerate(purchases):
        verdict = refill_vs_paid(paid_litres=p["litres"], refilled_litres=filled[pi], t=t)
        rows.append({"index": pi, "paid": p["litres"], "refilled": round(filled[pi], 1), **verdict})
    return {"purchases": rows, "unmatched_refills": unmatched}
