"""Odometer reading rules (masterplan 5.4). The web and mobile clients apply the same rules from
packages/business-rules/src/odometer.ts so people see problems before they submit; this is the enforcing copy.
"""

MAX_ODOMETER_KM = 9_999_999
# More than this since the last known reading is suspicious for one trip (Mombasa to Kampala and back is ~2,200).
LARGE_JUMP_KM = 3_000


class OdometerError(ValueError):
    pass


def check_value(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > MAX_ODOMETER_KM:
        raise OdometerError("Enter the odometer as a whole number of kilometres.")
    return value


def reading_flags(
    confirmed: int, auto_read: int | None, last_known_km: int, *, has_location: bool
) -> list[str]:
    """Reasons a reading deserves a second look. Flags never block the trip; fraud alerts use them in Sprint 13."""
    flags = []
    if auto_read is not None and auto_read != confirmed:
        flags.append("mismatch")  # what the number reader saw is not what was typed
    if confirmed < last_known_km:
        flags.append("backward")
    elif confirmed - last_known_km > LARGE_JUMP_KM:
        flags.append("large_jump")
    if not has_location:
        flags.append("no_location")
    return flags


def trip_distance_km(start: int, end: int) -> int:
    if end < start:
        raise OdometerError("The end reading cannot be lower than the start reading.")
    return end - start
