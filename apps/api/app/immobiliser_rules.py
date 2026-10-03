"""The remote engine immobiliser's safety rules (masterplan 5.28, Section 10). The same rules as
packages/business-rules/src/immobiliser.ts, tested against immobiliser-cases.json on both sides. Stopping an engine of a lorry that is
moving on a highway is dangerous, so it is refused unless the vehicle is known to be standing or crawling right now."""

MAX_SPEED_KMH = 5  # "stopped or below a very low speed"
MAX_POSITION_AGE_S = 180  # the speed we act on must be this fresh

REASONS = {
    "moving": "The vehicle is moving. The engine can only be stopped when it is standing or going very slowly.",
    "stale_position": "The vehicle has not reported its position in the last three minutes, so we cannot tell it is stopped.",
    "no_position": "The vehicle has never reported a position.",
    "offline": "The tracker is offline, so it cannot receive the command.",
    "unsupported": "This tracker does not support remote engine stop.",
}


def check(*, action: str, speed_kmh: float | None, position_age_s: float | None, online: bool, supported: bool) -> tuple[bool, str | None]:
    """(allowed, reason code if refused). Releasing the engine is always allowed to be tried; stopping it is not."""
    if not supported:
        return False, "unsupported"
    if action == "release":
        return True, None
    if not online:
        return False, "offline"
    if position_age_s is None:
        return False, "no_position"
    if position_age_s > MAX_POSITION_AGE_S:
        return False, "stale_position"
    if (speed_kmh or 0) > MAX_SPEED_KMH:
        return False, "moving"
    return True, None
