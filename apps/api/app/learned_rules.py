"""Learned fuel model for one vehicle (masterplan 5.13, 5.14): how much fuel its trips take for their distance, their load and the time
spent idling, worked out from the vehicle's own finished trips by least squares. No libraries: three numbers, so every prediction can be
shown as a sum. Server side only (nothing on a phone or the web needs to recompute it), so there is no TypeScript mirror."""

import math

FEATURES = ("km", "tonne_km", "idle_hours")
MIN_FIT_TRIPS = 6  # fewer than this and nothing is learned at all
MIN_R2 = 0.6  # a model that explains less of the variation than this is not used
MIN_EXTRA_LITRES = 8  # a trip must also be this many litres over the prediction to be flagged
SIGMA_FLOOR_PCT = 2  # the usual miss is never taken as less than this share of the prediction


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting. None if the system has no unique answer."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            factor = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= factor * m[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))) / m[i][i]
    return x


def _least_squares(rows: list[list[float]], y: list[float]) -> list[float] | None:
    p = len(rows[0])
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(p)] for i in range(p)]
    xty = [sum(r[i] * v for r, v in zip(rows, y, strict=True)) for i in range(p)]
    plain = _solve(xtx, xty)
    if plain is not None:
        return plain
    ridge = 1e-9 * (sum(xtx[i][i] for i in range(p)) / p or 1)  # only if two columns repeat each other, so the solve cannot choose
    return _solve([[xtx[i][j] + (ridge if i == j else 0) for j in range(p)] for i in range(p)], xty)


def fit(samples: list[dict], min_trips: int = 12) -> dict | None:
    """Trips are {km, tonne_km, idle_hours, litres}. Each number is how many litres a kilometre, a tonne-kilometre or an idle hour
    adds, and none can be negative: a negative one is dropped and the rest refitted. Returns None when there are too few trips."""
    usable = [s for s in samples if s["km"] > 0 and s["litres"] > 0]
    if len(usable) < MIN_FIT_TRIPS:
        return None
    names = [f for f in FEATURES if any(s[f] > 0 for s in usable)]
    while names:
        rows = [[s[f] for f in names] for s in usable]
        beta = _least_squares(rows, [s["litres"] for s in usable])
        if beta is None:
            return None
        negative = [i for i, b in enumerate(beta) if b < 0]
        if not negative:
            break
        names.pop(min(negative, key=lambda i: beta[i]))  # the most negative goes
    if not names:
        return None
    coefs = {f: 0.0 for f in FEATURES} | dict(zip(names, beta, strict=True))
    predicted = [sum(coefs[f] * s[f] for f in FEATURES) for s in usable]
    mean = sum(s["litres"] for s in usable) / len(usable)
    ss_res = sum((s["litres"] - p) ** 2 for s, p in zip(usable, predicted, strict=True))
    ss_tot = sum((s["litres"] - mean) ** 2 for s in usable)
    r2 = max(0.0, 1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
    sigma = math.sqrt(ss_res / max(len(usable) - len(names), 1))
    return {
        "n": len(usable), "coefs": {f: round(c, 6) for f, c in coefs.items()}, "r2": round(r2, 3), "sigma": round(sigma, 2),
        "mean_idle_hours": round(sum(s["idle_hours"] for s in usable) / len(usable), 2), "reliable": len(usable) >= min_trips and r2 >= MIN_R2,
    }  # fmt: skip


def predict(model: dict, *, km: float, tonne_km: float = 0, idle_hours: float | None = None) -> float:
    """Litres for a trip. Idling not known in advance is taken as the vehicle's usual idling per trip."""
    idle = model["mean_idle_hours"] if idle_hours is None else idle_hours
    c = model["coefs"]
    return c["km"] * km + c["tonne_km"] * tonne_km + c["idle_hours"] * idle


def anomaly(model: dict, *, litres: float, km: float, tonne_km: float, idle_hours: float, z_limit: float) -> dict:
    """How far a trip's fuel is above what the model expects, in usual misses. Flagged when that is at least z_limit and at least 8
    litres, so a tight model does not raise an alert over a few litres."""
    expected = predict(model, km=km, tonne_km=tonne_km, idle_hours=idle_hours)
    sigma = max(model["sigma"], expected * SIGMA_FLOOR_PCT / 100, 1.0)
    extra = litres - expected
    z = extra / sigma
    return {"predicted": round(expected, 1), "extra_litres": round(extra, 1), "sigma": round(sigma, 1), "z": round(z, 1), "flagged": z >= z_limit and extra >= MIN_EXTRA_LITRES}
