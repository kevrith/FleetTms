import pytest

from app import learned_rules as lr

TRUE = {"km": 0.30, "tonne_km": 0.004, "idle_hours": 3.0}
# deterministic "noise" in litres, so a test never depends on a random number
NOISE = [1.2, -0.8, 0.5, -1.5, 0.9, -0.3, 1.1, -1.0, 0.2, -0.6, 0.8, -1.2, 0.4, -0.2, 1.0, -0.9]


def trips(n=16, noise=True):
    out = []
    for i in range(n):
        km = 200 + 70 * (i % 7)
        tonnes = 5 + 4 * (i % 5)
        idle = 0.5 + 0.7 * (i % 4)
        litres = TRUE["km"] * km + TRUE["tonne_km"] * tonnes * km + TRUE["idle_hours"] * idle + (NOISE[i % len(NOISE)] if noise else 0)
        out.append({"km": km, "tonne_km": tonnes * km, "idle_hours": idle, "litres": litres})
    return out


def test_it_recovers_what_a_vehicles_trips_are_made_of():
    model = lr.fit(trips(noise=False))
    assert model["n"] == 16 and model["r2"] == 1.0 and model["reliable"] is True
    for name, value in TRUE.items():
        assert model["coefs"][name] == pytest.approx(value, abs=1e-4)


def test_a_little_noise_still_gives_a_reliable_model_with_a_usual_miss_of_about_a_litre():
    model = lr.fit(trips())
    assert model["reliable"] is True and model["r2"] > 0.99 and 0.4 < model["sigma"] < 2
    assert model["coefs"]["km"] == pytest.approx(0.30, abs=0.03) and model["coefs"]["idle_hours"] == pytest.approx(3.0, abs=1.0)


def test_too_few_trips_learn_nothing_and_a_short_history_is_not_called_reliable():
    assert lr.fit(trips(5)) is None
    short = lr.fit(trips(8), min_trips=12)
    assert short is not None and short["reliable"] is False
    assert lr.fit(trips(8), min_trips=6)["reliable"] is True  # the business may decide six is enough


def test_a_negative_effect_is_dropped_and_the_rest_refitted():
    rows = trips(noise=False)
    for r in rows:  # make idling look like it saves fuel: it cannot, so it must be set aside
        r["litres"] = 0.35 * r["km"] - 5.0 * r["idle_hours"]
    model = lr.fit(rows)
    assert model["coefs"]["idle_hours"] == 0.0 and all(c >= 0 for c in model["coefs"].values())


def test_unrelated_fuel_is_not_reliable():
    rows = trips()
    for i, r in enumerate(rows):
        r["litres"] = 100 + (37 * i % 11) * 9  # nothing to do with the trip
    model = lr.fit(rows)
    assert model is None or model["reliable"] is False


def test_missing_columns_are_left_out_instead_of_breaking_the_fit():
    rows = [{**r, "idle_hours": 0.0} for r in trips(noise=False)]
    model = lr.fit(rows)
    assert model["coefs"]["idle_hours"] == 0.0 and model["coefs"]["km"] > 0


def test_a_trip_far_above_the_prediction_is_flagged_and_an_ordinary_one_is_not():
    model = lr.fit(trips())
    km, tonnes, idle = 500, 20, 1.5
    normal = TRUE["km"] * km + TRUE["tonne_km"] * tonnes * km + TRUE["idle_hours"] * idle
    ok = lr.anomaly(model, litres=normal + 2, km=km, tonne_km=tonnes * km, idle_hours=idle, z_limit=3)
    assert ok["flagged"] is False and abs(ok["extra_litres"] - 2) < 1.5
    stolen = lr.anomaly(model, litres=normal * 1.4, km=km, tonne_km=tonnes * km, idle_hours=idle, z_limit=3)
    assert stolen["flagged"] is True and stolen["z"] >= 3 and stolen["extra_litres"] > 50


def test_a_tight_model_does_not_flag_a_few_litres_and_the_limit_can_be_loosened():
    model = lr.fit(trips(noise=False))  # sigma is almost nothing
    normal = lr.predict(model, km=500, tonne_km=10_000, idle_hours=1.0)
    assert lr.anomaly(model, litres=normal + 5, km=500, tonne_km=10_000, idle_hours=1.0, z_limit=3)["flagged"] is False  # under 8 litres
    assert lr.anomaly(model, litres=normal + 20, km=500, tonne_km=10_000, idle_hours=1.0, z_limit=3)["flagged"] is True
    assert lr.anomaly(model, litres=normal + 20, km=500, tonne_km=10_000, idle_hours=1.0, z_limit=20)["flagged"] is False


def test_prediction_uses_the_usual_idling_when_it_is_not_known():
    model = lr.fit(trips(noise=False))
    known = lr.predict(model, km=400, tonne_km=4000, idle_hours=model["mean_idle_hours"])
    assert lr.predict(model, km=400, tonne_km=4000) == pytest.approx(known)
