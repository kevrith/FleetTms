import calendar
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.models import BehaviourEvent, FuelEntry, Trip, TripStatus
from app.reminders import NAIROBI
from tests.fleet import add_vehicle
from tests.fraud_scenarios import drive, open_alerts
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import in_db, lease_setup, make_lease, moment, seed_client, seed_trip
from tests.shots import fleet
from tests.test_clients import add_client, add_route
from tests.test_trackers import KEY


@pytest.fixture(autouse=True)
def _key():
    settings.traccar_forward_key = KEY
    yield
    settings.traccar_forward_key = ""


def quote_body(c, r, vehicle, **extra):
    return {"client_id": c["id"], "route_id": r["id"], "vehicle_id": vehicle["id"], "weight_tonnes": "30", "trips": 2, "billing_method": "per_trip", "rate_cents": 12_000_000, "fuel_price_cents": 18000, **extra}


async def history(f, rows, origin="Mombasa", destination="Nairobi"):
    """Finished trips with fuel and idling already on record. Each row is (km, litres, idle_hours, loaded_kg)."""
    vehicle_id = uuid.UUID(f.vehicle["id"])

    async def go(db):
        for i, (km, litres, idle, kg) in enumerate(rows):
            began = datetime.now(UTC) - timedelta(days=20 + i)
            trip = Trip(vehicle_id=vehicle_id, status=TripStatus.COMPLETED, origin=origin, destination=destination, started_at=began, ended_at=began + timedelta(hours=14), distance_km=km, loaded_weight_kg=kg)
            db.add(trip)
            await db.flush()
            db.add(FuelEntry(vehicle_id=vehicle_id, trip_id=trip.id, litres=litres, price_per_litre_cents=18000, amount_cents=int(litres * 18000), captured_at=began + timedelta(hours=2)))
            if idle:
                db.add(BehaviourEvent(vehicle_id=vehicle_id, trip_id=trip.id, kind="idling", at=began + timedelta(hours=3), ended_at=began + timedelta(hours=3 + idle), value=idle * 60, source="tracker"))

    await in_db(go)


def varied(n=14, per_km=0.30, per_tonne_km=0.004, per_idle=3.0):
    rows = []
    for i in range(n):
        km, tonnes, idle = 200 + 70 * (i % 7), 5 + 4 * (i % 5), 0.5 + 0.7 * (i % 4)
        rows.append((km, round(per_km * km + per_tonne_km * tonnes * km + per_idle * idle, 1), idle, tonnes * 1000))
    return rows


# ---- a quote for a leased lorry shows the profit after the lease (acceptance) ------------------------------------------------


async def test_a_quote_for_a_leased_in_lorry_shows_expected_profit_after_the_lease_charge(client):
    owner, vehicle, party = await lease_setup(client)
    await make_lease(client, owner, vehicle, party, revenue_pct=10, fixed_cents=3_000_000, fixed_period="month", per_km_cents=500)
    c = await add_client(client, owner)
    r = await add_route(client, owner, c["id"])  # 480 km, 14 hours one way
    res = await client.post("/quotes", headers=bearer(owner), json=quote_body(c, r, vehicle))
    assert res.status_code == 201, res.text
    q = res.json()
    # price 2 trips x 120,000 = 240,000. Fuel per trip: 480/4.5 + 480/6 = 186.67 litres at 180 = 33,600; plus tolls 6,000, crew 7,000, other 2,000 = 48,600 a trip, 97,200 for two.
    assert q["price_cents"] == 24_000_000 and q["total_cost_cents"] == 9_720_000 and q["expected_profit_cents"] == 14_280_000
    # the lease: 2 trips of 14 h out and back is 56 h, so 3 days of the 30,000 monthly charge = 3,000; 5 a km over 1,920 km = 9,600; 10 percent of the price = 24,000
    assert q["lease_charge_cents"] == 300_000 + 960_000 + 2_400_000 == 3_660_000
    assert q["net_profit_cents"] == 14_280_000 - 3_660_000 == 10_620_000
    labels = [x["label"] for x in q["lease_detail"]["lines"]]
    assert len(labels) == 3 and "3 days of use" in labels[0] and "1,920 km" in labels[1] and labels[2].startswith("10% of the price")
    assert "monthly minimum guarantee" in q["lease_detail"]["note"]
    again = (await client.get(f"/quotes/{q['id']}", headers=bearer(owner))).json()
    assert again["net_profit_cents"] == 10_620_000 and again["fuel_source"] == "declared"  # kept with the quote, so it can always be explained


async def test_the_preview_shows_how_the_quote_was_worked_out_without_saving_it(client):
    owner, vehicle, party = await lease_setup(client)
    await make_lease(client, owner, vehicle, party, revenue_pct=10, fixed_cents=3_000_000, fixed_period="month", per_km_cents=500)
    c = await add_client(client, owner)
    r = await add_route(client, owner, c["id"])
    p = (await client.post("/quotes/preview", headers=bearer(owner), json=quote_body(c, r, vehicle))).json()
    assert p["net_profit_cents"] == 10_620_000 and p["expected_profit_cents"] == 14_280_000 and p["fuel_source"] == "declared"
    lines = {x["label"]: x["cents"] for x in p["lines"]}
    assert lines["Price to the client"] == 24_000_000 and lines["Expected profit"] == 14_280_000 and lines["Expected profit after the lease"] == 10_620_000
    assert any(k.startswith("Lease: 10% of the price") and v == -2_400_000 for k, v in lines.items()) and p["lease_note"]
    assert (await client.get("/quotes", headers=bearer(owner))).json() == []  # nothing was saved
    assert (await client.post("/quotes/preview", headers=bearer(owner), json={"client_id": str(uuid.uuid4())})).status_code == 404


async def test_a_quote_for_a_lorry_that_is_not_leased_in_has_no_lease_charge(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    r = await add_route(client, f.owner, c["id"])
    q = (await client.post("/quotes", headers=bearer(f.owner), json=quote_body(c, r, f.vehicle))).json()
    assert q["lease_charge_cents"] == 0 and q["net_profit_cents"] is None and q["lease_detail"] is None and q["expected_profit_cents"] == 14_280_000
    p = (await client.post("/quotes/preview", headers=bearer(f.owner), json=quote_body(c, r, f.vehicle))).json()
    assert p["lease_note"] is None and "Expected profit after the lease" not in [x["label"] for x in p["lines"]]
    lessee = (await client.post("/parties", headers=bearer(f.owner), json={"kind": "lessee", "name": "Hire Co", "phone": "0711000222"})).json()
    leased_out = await add_vehicle(client, f.owner, "KZZ 999Z", ownership_type="leased_out", party_id=lessee["id"])
    q2 = (await client.post("/quotes", headers=bearer(f.owner), json=quote_body(c, r, leased_out))).json()
    assert q2["net_profit_cents"] is None  # a lorry hired out earns from its lessee, it is not charged by anyone


# ---- expected fuel -------------------------------------------------------------------------------------------------------


async def test_expected_fuel_comes_from_the_vehicles_own_trips_once_there_are_enough_and_says_so(client):
    f = await fleet(client)
    await history(f, [(1000, 300, 0, None)] * 3)
    c = await add_client(client, f.owner)
    r = await add_route(client, f.owner, c["id"], distance_km=1000)
    q = (await client.post("/quotes", headers=bearer(f.owner), json=quote_body(c, r, f.vehicle, weight_tonnes="0"))).json()
    assert q["fuel_source"] == "history" and q["kmpl_loaded"] == 3.33 and q["kmpl_empty"] == 3.33
    assert any("3 finished trips on same route and load averaged 3.33 km a litre" in s for s in q["fuel_detail"])
    got = (await client.get("/predictions/fuel", params={"vehicle_id": f.vehicle["id"], "distance_km": 1000, "origin": "Mombasa", "destination": "Nairobi"}, headers=bearer(f.owner))).json()
    assert got["source"] == "history" and got["litres_loaded"] == 300 and got["litres_return"] == 300 and abs(got["litres"] - 600) <= 1 and any(x.startswith("Fuel for the trip: 300 litres out and 300 back") for x in got["steps"])
    typed = (await client.post("/quotes", headers=bearer(f.owner), json=quote_body(c, r, f.vehicle, weight_tonnes="0", kmpl_loaded="2.5", kmpl_empty="2.5"))).json()
    assert typed["fuel_source"] == "typed in" and typed["kmpl_loaded"] == 2.5  # what was typed wins


async def test_with_no_history_expected_fuel_falls_back_to_what_was_declared_and_says_so(client):
    f = await fleet(client)
    got = (await client.get("/predictions/fuel", params={"vehicle_id": f.vehicle["id"], "distance_km": 480}, headers=bearer(f.owner))).json()
    assert got["source"] == "declared" and got["litres_loaded"] == 107 and got["litres_return"] == 80 and "own trip history is not enough" in got["steps"][0]
    assert (await client.get("/predictions/fuel", params={"vehicle_id": f.vehicle["id"], "distance_km": 0}, headers=bearer(f.owner))).status_code == 422
    assert (await client.get("/predictions/fuel", params={"vehicle_id": f.vehicle["id"], "distance_km": 480}, headers=bearer(f.driver))).status_code == 403


# ---- the learned model ---------------------------------------------------------------------------------------------------


async def test_a_vehicle_with_enough_trips_gets_a_model_that_says_what_it_learned(client):
    f = await fleet(client)
    empty = (await client.get(f"/vehicles/{f.vehicle['id']}/model", headers=bearer(f.owner))).json()
    assert empty["trained"] is False and "Fewer than 6" in empty["message"]
    await history(f, varied())
    m = (await client.get(f"/vehicles/{f.vehicle['id']}/model", headers=bearer(f.owner))).json()
    assert m["trained"] is True and m["trips"] == 14 and m["reliable"] is True and m["r2"] >= 0.99
    assert abs(m["litres_per_km"] - 0.30) < 0.01 and abs(m["litres_per_tonne_km"] - 0.004) < 0.0005 and abs(m["litres_per_idle_hour"] - 3.0) < 0.3
    assert "alongside the rules" in m["message"]
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/model", headers=bearer(other))).status_code == 404
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/model", headers=bearer(f.driver))).status_code == 403


async def test_a_few_trips_are_learned_from_but_not_trusted_yet(client):
    f = await fleet(client)
    await history(f, varied(8))
    m = (await client.get(f"/vehicles/{f.vehicle['id']}/model", headers=bearer(f.owner))).json()
    assert m["trained"] is True and m["reliable"] is False and m["needed_trips"] == 12 and "needs at least 12 trips" in m["message"]


async def test_a_quote_uses_the_learned_model_and_shows_its_working(client):
    f = await fleet(client)
    await history(f, varied())
    c = await add_client(client, f.owner)
    r = await add_route(client, f.owner, c["id"], distance_km=500)
    m = (await client.get(f"/vehicles/{f.vehicle['id']}/model", headers=bearer(f.owner))).json()
    q = (await client.post("/quotes", headers=bearer(f.owner), json=quote_body(c, r, f.vehicle, weight_tonnes="20", trips=1))).json()
    loaded = m["litres_per_km"] * 500 + m["litres_per_tonne_km"] * 20 * 500 + m["litres_per_idle_hour"] * m["usual_idle_hours"]
    empty = m["litres_per_km"] * 500
    assert q["fuel_source"] == "learned" and abs(q["kmpl_loaded"] - 500 / loaded) < 0.02 and abs(q["kmpl_empty"] - 500 / empty) < 0.02
    assert q["fuel_detail"][0].startswith("Learned from 14 of this vehicle's finished trips") and any(s.startswith("Loaded leg: 500 km with 20 tonnes") for s in q["fuel_detail"])


async def flat_history(f, n=14):
    """Fourteen ordinary trips of 200 to 620 km with a little idling, burning 0.3 litres a kilometre and 3 an idle hour exactly."""
    rows = [(200 + 70 * (i % 7), round(0.3 * (200 + 70 * (i % 7)) + 3 * (0.5 + 0.7 * (i % 4)), 1), 0.5 + 0.7 * (i % 4), None) for i in range(n)]
    await history(f, rows, origin="Nairobi", destination="Kisumu")  # a different route from the trips being judged, so route distances play no part


async def test_the_model_catches_fuel_the_plain_rule_lets_through(client):
    f = await fleet(client)
    await flat_history(f)
    await drive(client, f, litres=327, km=1000, phone_km=1000, idle_minutes=60)  # expected 0.3 x 1000 + 3 x 1 = 303: 8 percent over, under the 10 percent rule
    kinds = sorted(a["kind"] for a in await open_alerts(client, f.owner))
    assert kinds == ["fuel_model_anomaly"]
    [a] = await open_alerts(client, f.owner)
    e = a["evidence"]
    assert a["severity"] == "amber" and e["litres"] == 327 and abs(e["predicted_litres"] - 303) < 3 and e["extra_litres"] > 18 and e["z"] >= 3 and e["model_trips"] == 14 and e["z_limit"] == 3
    assert "more than this vehicle usually needs" in a["title"] and "This vehicle's own trips say about" in a["detail"]


async def test_an_ordinary_trip_raises_nothing_and_a_big_overrun_is_the_rules_alert_not_two(client):
    f = await fleet(client)
    await flat_history(f)
    await drive(client, f, litres=305, km=1000, phone_km=1000, idle_minutes=60)
    assert await open_alerts(client, f.owner) == []
    await drive(client, f, litres=450, km=1000, phone_km=1000, idle_minutes=60)  # 48 percent over
    assert sorted(a["kind"] for a in await open_alerts(client, f.owner)) == ["fuel_variance"]


async def test_the_owner_can_make_the_model_stricter_or_looser(client):
    f = await fleet(client)
    await flat_history(f)
    assert (await client.put("/fraud/settings", headers=bearer(f.owner), json={"thresholds": {"model_z": 6}})).status_code == 200
    await drive(client, f, litres=327, km=1000, phone_km=1000, idle_minutes=60)
    assert await open_alerts(client, f.owner) == []  # 8 percent over is not six usual misses
    assert (await client.put("/fraud/settings", headers=bearer(f.owner), json={"thresholds": {"model_min_trips": 40}})).status_code == 200
    await drive(client, f, litres=325, km=1000, phone_km=1000, idle_minutes=60)  # 7 percent over: the model would flag it, the rule would not
    assert await open_alerts(client, f.owner) == []  # 14 trips are not enough for a business that wants 40


# ---- the monthly forecast -------------------------------------------------------------------------------------------------


async def test_the_forecast_is_this_month_so_far_plus_the_usual_daily_average_for_the_days_left(client):
    owner, vehicle, _ = await lease_setup(client)
    c = await seed_client()
    for offset in (-3, -2, -1):
        await seed_trip(vehicle["id"], revenue_cents=10_000_000, client_id=c, at=moment(offset, 15))
    await seed_trip(vehicle["id"], revenue_cents=4_000_000, client_id=c, at=moment(0, 1))
    res = await client.get("/predictions/forecast", headers=bearer(owner))
    assert res.status_code == 200, res.text
    f = res.json()
    today = datetime.now(NAIROBI).date()
    history_days = sum(calendar.monthrange(*((today.year, today.month - k) if today.month > k else (today.year - 1, today.month - k + 12)))[1] for k in (3, 2, 1))
    per_day = round(30_000_000 / history_days)
    remaining = calendar.monthrange(today.year, today.month)[1] - today.day
    b = f["business"]
    assert b["gross_to_date_cents"] == 4_000_000 and b["gross_per_day_cents"] == per_day and b["remaining_days"] == remaining
    assert b["projected_gross_cents"] == 4_000_000 + per_day * remaining and b["projected_net_cents"] == b["projected_gross_cents"] - b["fixed_charges_cents"]
    [v] = f["vehicles"]
    assert v["registration"] == "KDB 404D" and v["gross_to_date_cents"] == 4_000_000 and v["projected_gross_cents"] == b["projected_gross_cents"]
    assert f["days_elapsed"] == today.day and len(f["history_months"]) == 3 and len(f["steps"]) >= 2 and "So far this month" in f["steps"][0]


async def test_a_business_with_no_history_gets_no_forecast_and_is_told_why(client):
    f = await fleet(client)
    res = (await client.get("/predictions/forecast", headers=bearer(f.owner))).json()
    assert res["business"]["projected_gross_cents"] is None and res["business"]["projected_net_cents"] is None
    assert any("no earlier months" in s for s in res["steps"])
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.get("/predictions/forecast", headers=bearer(accountant))).status_code == 200
    supervisor, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    assert (await client.get("/predictions/forecast", headers=bearer(supervisor))).status_code == 403
    assert (await client.get("/predictions/forecast", headers=bearer(f.driver))).status_code == 403
