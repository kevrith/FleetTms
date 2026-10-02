"""Load compliance (masterplan 5.22). The same rule as packages/business-rules/src/load.ts, tested against the same cases."""


def overload_kg(*, cargo_kg: int, tare_kg: int | None, gvw_limit_kg: int | None, capacity_tonnes: float | None) -> int | None:
    """Kilograms over the limit (0 when within it), or None when there is nothing to judge the load against."""
    if gvw_limit_kg is not None and tare_kg is not None:
        return max(0, tare_kg + cargo_kg - gvw_limit_kg)
    if capacity_tonnes is not None:
        return max(0, cargo_kg - round(float(capacity_tonnes) * 1000))
    return None
