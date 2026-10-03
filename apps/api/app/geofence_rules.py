"""Mapped areas (masterplan 5.12): is a position inside a circle or a polygon, and when has a vehicle really entered or left.
The same rules as packages/business-rules/src/geofence.ts, tested against geofence-cases.json on both sides."""

from app.gps_rules import haversine_km

CONFIRM_FIXES = 2  # a change of side must be seen on this many fixes in a row, so GPS jitter at an edge is not an exit and an entry


def in_circle(lat: float, lng: float, centre_lat: float, centre_lng: float, radius_m: float) -> bool:
    return haversine_km(lat, lng, centre_lat, centre_lng) * 1000 <= radius_m


def in_polygon(lat: float, lng: float, ring: list[list[float]]) -> bool:
    """Ray casting over [lat, lng] corners. Flat geometry is fine for areas the size of a yard or a town."""
    inside = False
    n = len(ring)
    for i in range(n):
        la1, ln1 = ring[i]
        la2, ln2 = ring[(i + 1) % n]
        if (ln1 > lng) != (ln2 > lng) and lat < (la2 - la1) * (lng - ln1) / (ln2 - ln1) + la1:
            inside = not inside
    return inside


def inside(shape: dict, lat: float, lng: float) -> bool:
    if shape["type"] == "circle":
        return in_circle(lat, lng, shape["lat"], shape["lng"], shape["radius_m"])
    return in_polygon(lat, lng, shape["points"])


def step(state: dict | None, now_inside: bool) -> tuple[dict, str | None]:
    """Moves a vehicle's side-of-the-fence state on by one fix. State is {inside: bool|None, pending: int}. The first sighting
    sets the side without an event (a lorry parked in its depot is not "entering" it). Returns (state, "enter" | "exit" | None)."""
    state = state or {"inside": None, "pending": 0}
    if state["inside"] is None:
        return {"inside": now_inside, "pending": 0}, None
    if now_inside == state["inside"]:
        return {"inside": state["inside"], "pending": 0}, None
    pending = state["pending"] + 1
    if pending >= CONFIRM_FIXES:
        return {"inside": now_inside, "pending": 0}, "enter" if now_inside else "exit"
    return {"inside": state["inside"], "pending": pending}, None
