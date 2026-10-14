"""The two halves of a round trip: the kilometres driven with the load, up to the delivery, and the empty kilometres of the return.

The odometer (or, for a lorry whose dial cannot be trusted, the GPS) gives the trip's distance; the GPS path says where along it the
delivery fell. The trip's distance is shared in that proportion, so the two parts always add up to it."""

from datetime import datetime

from app.gps_rules import MIN_POINTS_FOR_CHECK, path_distance_km

MIN_LEG_KM = 0.5  # a path shorter than this says nothing about where the delivery fell


def split_legs(distance_km: int | None, fixes: list[dict], delivered_at: datetime | None) -> tuple[int, int] | None:
    """(loaded km, empty km) of a finished trip, or None when it cannot be told: no distance, no delivery, or too few fixes on either side
    of the delivery to know where it fell. Each fix is {at, lat, lng, accuracy_m}."""
    if distance_km is None or delivered_at is None or distance_km < 0:
        return None
    total_km, used = path_distance_km(fixes)
    if used < MIN_POINTS_FOR_CHECK or total_km < MIN_LEG_KM:
        return None
    before = [f for f in fixes if f["at"] <= delivered_at]
    after = [f for f in fixes if f["at"] > delivered_at]
    if not before or not after:
        # The delivery was the last (or first) thing the phone saw: all the way there, or none of it, is loaded.
        loaded = distance_km if not after else 0
        return loaded, distance_km - loaded
    # The path up to the delivery includes the step from the last fix before it to the first after, split at the delivery time.
    bridge = after[0]
    km_before, _ = path_distance_km(before + [bridge])
    km_to_bridge, _ = path_distance_km(before)
    km_bridge_step = max(km_before - km_to_bridge, 0.0)
    span = (bridge["at"] - before[-1]["at"]).total_seconds()
    into = (delivered_at - before[-1]["at"]).total_seconds()
    part = km_bridge_step * (into / span) if span > 0 else 0.0
    share = min(max((km_to_bridge + part) / total_km, 0.0), 1.0)
    loaded = round(distance_km * share)
    return loaded, distance_km - loaded
