"""Litres per 100 km, km per litre and money per km, per lorry, driver and route."""

import pytest

from app.fuel_efficiency import against_expected, expected_kmpl, ratios
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session
from tests.shots import begin_trip, fleet
from tests.test_dashboard import finish_trip


def test_ratios():
    assert ratios(480, 120, 2_220_000) == {"km_per_litre": 4.0, "l_per_100km": 25.0, "cost_per_km_cents": 4625}
    assert ratios(0, 50, 900_000) == {"km_per_litre": None, "l_per_100km": None, "cost_per_km_cents": None}  # fuel but no distance
    assert ratios(100, 0, 0) == {"km_per_litre": None, "l_per_100km": None, "cost_per_km_cents": None}  # distance but no fuel recorded


def test_the_expected_figure_is_the_mean_of_loaded_and_empty():
    assert expected_kmpl(4.0, 6.0) == 5.0 and expected_kmpl(4.5, None) == 4.5 and expected_kmpl(None, None) is None


@pytest.mark.parametrize(("l_per_100", "kmpl", "pct", "above"), [(25.0, 4.0, 0.0, False), (27.5, 4.0, 10.0, False), (30.0, 4.0, 20.0, True), (20.0, 4.0, -20.0, False), (None, 4.0, None, False), (25.0, None, None, False)])
def test_against_expected(l_per_100, kmpl, pct, above):
    assert against_expected(l_per_100, kmpl, 10) == {"vs_expected_pct": pct, "above_expected": above}


async def test_an_owner_sees_each_lorrys_consumption_and_whether_it_is_above_what_is_expected(client):
    f = await fleet(client)
    trip = await begin_trip(client, f)
    await finish_trip(client, f, trip)  # 480 km on the odometer
    fuel = {"vehicle_id": f.vehicle["id"], "trip_id": trip["id"], "litres": "120", "price_per_litre_cents": 18500, "amount_cents": 2_220_000}
    assert (await client.post("/fuel", headers=bearer(f.driver), json=fuel)).status_code == 201
    res = await client.get("/fuel-efficiency?months=2", headers=bearer(f.owner))
    assert res.status_code == 200, res.text
    body = res.json()
    row = next(v for v in body["vehicles"] if v["registration"] == f.vehicle["registration"])
    assert row["km"] == 480 and row["litres"] == 120.0 and row["l_per_100km"] == 25.0 and row["km_per_litre"] == 4.0 and row["cost_per_km_cents"] == 4625
    assert row["trips"] == 1 and len(row["monthly"]) == 2 and row["monthly"][-1]["l_per_100km"] == 25.0 and row["monthly"][0]["km"] == 0
    assert body["drivers"][0]["l_per_100km"] == 25.0 and body["drivers"][0]["trips_counted"] == 1
    assert body["routes"][0]["route"] == "Mombasa to Nairobi" and body["routes"][0]["km_per_litre"] == 4.0
    # a lorry expected to do 5 km a litre (20 per 100 km) is 25 percent over; one expected to do 4 is on target
    body_v = (await client.get(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner))).json()
    body_v.pop("id")
    await client.put(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner), json={**body_v, "expected_kmpl_loaded": "5", "expected_kmpl_empty": "5"})
    row = (await client.get("/fuel-efficiency", headers=bearer(f.owner))).json()["vehicles"][0]
    assert row["expected_km_per_litre"] == 5.0 and row["vs_expected_pct"] == 25.0 and row["above_expected"] is True


async def test_a_lorry_with_nothing_recorded_is_left_out_and_the_period_is_bounded(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 999Z")
    assert (await client.get("/fuel-efficiency", headers=bearer(owner))).json()["vehicles"] == []
    assert (await client.get("/fuel-efficiency?months=13", headers=bearer(owner))).status_code == 422
    assert (await client.get("/fuel-efficiency?months=0", headers=bearer(owner))).status_code == 422


async def test_one_business_never_sees_anothers_fuel(client):
    f = await fleet(client)
    trip = await begin_trip(client, f)
    await finish_trip(client, f, trip)
    other, _ = await owner_session(client, business="Other Haulage", email="someone.else@example.com")
    assert (await client.get("/fuel-efficiency", headers=bearer(other))).json()["vehicles"] == []
    assert (await client.get(f"/fuel-efficiency?vehicle_id={f.vehicle['id']}", headers=bearer(other))).json()["vehicles"] == []
