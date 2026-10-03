"""Driver scorecards (masterplan 5.25): safety, fuel, punctuality, inspections and alerts, each out of 100, and an overall score from
the ones that have data. The same as packages/business-rules/src/scorecard.ts, tested against scorecard-cases.json on both sides."""

import math

SAFETY_WEIGHTS = {"speeding": 3, "harsh_braking": 2, "harsh_acceleration": 1.5, "harsh_cornering": 2, "night_driving": 0.5, "long_driving": 2}
WEIGHTS = {"safety": 0.30, "fuel": 0.25, "punctuality": 0.15, "inspections": 0.15, "alerts": 0.15}
MIN_KM = 50  # a driver with fewer kilometres is scored as if they drove this far, so one event does not wreck a short week


def clamp(x: float) -> int:
    """Rounded half up (like JavaScript's Math.round, so both sides agree on a .5) and kept between 0 and 100."""
    return int(max(0, min(100, math.floor(x + 0.5))))


def safety_score(counts: dict[str, int], km: float) -> int | None:
    """100 minus a penalty for every weighted event per 100 km. Idling is a fuel matter, not a safety one. None with no distance."""
    if km <= 0:
        return None
    penalty = sum(SAFETY_WEIGHTS.get(k, 0) * n for k, n in counts.items()) * 100 / max(km, MIN_KM)
    return clamp(100 - penalty * 2)


def fuel_score(variances_pct: list[float]) -> int | None:
    """Average of how far above expected the driver's trips were (below expected counts as on target). 20 percent over scores 0."""
    if not variances_pct:
        return None
    avg = sum(max(v, 0) for v in variances_pct) / len(variances_pct)
    return clamp(100 - avg * 5)


def punctuality_score(on_time: int, total: int) -> int | None:
    return clamp(on_time / total * 100) if total > 0 else None


def inspection_score(clean: int, with_defects: int, total: int) -> int | None:
    """Trips begun after a clean inspection count fully, after one with defects half, and without a clean one not at all."""
    return clamp((clean + 0.5 * with_defects) / total * 100) if total > 0 else None


def alerts_score(confirmed: int, open_: int) -> int:
    """Confirmed fraud costs 25 points, an alert still waiting for an answer 10, an explained one nothing."""
    return clamp(100 - 25 * confirmed - 10 * open_)


def overall(parts: dict[str, int | None]) -> int | None:
    have = {k: v for k, v in parts.items() if v is not None and k in WEIGHTS}
    if not have:
        return None
    weight = sum(WEIGHTS[k] for k in have)
    return clamp(sum(WEIGHTS[k] * v for k, v in have.items()) / weight)


def band(score: int | None) -> str | None:
    if score is None:
        return None
    return "good" if score >= 80 else "watch" if score >= 60 else "poor"
