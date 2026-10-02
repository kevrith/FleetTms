"""Tyre rules (masterplan 5.20): positions, kilometres run, cost per km, and when a tyre is due."""

import re
from decimal import Decimal

ROTATE_EVERY_KM = 15_000  # kilometres since the tyre was fitted or last moved
REPLACE_AT_KM = 100_000  # kilometres run, over all fittings
REPLACE_AT_TREAD_MM = Decimal("3.0")

_AXLE = r"(?:drive[1-3]|trailer[1-4])_(?:left|right)_(?:inner|outer)"
_POSITION = re.compile(rf"^(?:steer_(?:left|right)|{_AXLE}|spare[1-2]?)$")


def valid_position(position: str) -> bool:
    return bool(_POSITION.match(position))


def clean_serial(raw: str) -> str:
    """Upper case with no spaces or dashes, so 'ab-123 4' and 'AB1234' are the same tyre."""
    return re.sub(r"[\s\-]", "", raw).upper()


def km_run(km_before: int, fitted_odometer_km: int | None, odometer_km: int, fitted: bool) -> int:
    if not fitted or fitted_odometer_km is None:
        return km_before
    return km_before + max(0, odometer_km - fitted_odometer_km)


def cost_per_km_cents(total_cost_cents: int, km: int) -> float | None:
    return round(total_cost_cents / km, 2) if km > 0 else None


def due_status(*, fitted: bool, km: int, since_moved_km: int, tread_mm: Decimal | None) -> list[str]:
    """What a tyre needs next: 'replace' (worn or high mileage) and, for a fitted tyre, 'rotate'."""
    out: list[str] = []
    if km >= REPLACE_AT_KM or (tread_mm is not None and tread_mm <= REPLACE_AT_TREAD_MM):
        out.append("replace")
    if fitted and since_moved_km >= ROTATE_EVERY_KM:
        out.append("rotate")
    return out
