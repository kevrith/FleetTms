import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.models import FuelEntry
from app.sms import get_sms_sender
from app.tracker_simulator import position, refuel, siphon
from tests.fraud_scenarios import open_alerts, sweep
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import in_db, set_phone
from tests.shots import fleet
from tests.test_trackers import IMEI, KEY, post


@pytest.fixture(autouse=True)
def _key():
    settings.traccar_forward_key = KEY
    yield
    settings.traccar_forward_key = ""


def hours_ago(**kw) -> datetime:
    return datetime.now(UTC) - timedelta(**kw)


async def with_sensor(client, unit="litres", sensor=True):
    f = await fleet(client)
    await set_phone("owner@example.com", "+254700111222")
    res = await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": IMEI, "has_fuel_sensor": sensor, "fuel_unit": unit})
    assert res.status_code == 201, res.text
    f.tracker = res.json()
    get_sms_sender().outbox.clear()
    return f


async def send_all(client, payloads):
    for body in payloads:
        assert (await post(client, body)).status_code == 200


async def bought(f, litres, at, station="Total Mlolongo"):
    async def go(db):
        db.add(FuelEntry(vehicle_id=uuid.UUID(f.vehicle["id"]), litres=litres, price_per_litre_cents=18000, amount_cents=int(litres * 18000), station=station, captured_at=at))

    await in_db(go)


def kinds(alerts):
    return sorted(a["kind"] for a in alerts)


# ---- fitting a sensor ----------------------------------------------------------------------------------------------------


async def test_a_fuel_sensor_makes_a_vehicle_premium_and_taking_it_off_does_not_remove_the_tracker(client):
    f = await with_sensor(client)
    assert f.tracker["has_fuel_sensor"] is True and f.tracker["fuel_unit"] == "litres"
    tier = lambda: client.get(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner))
    assert (await tier()).json()["tracking_tier"] == "premium"
    changed = await client.put(f"/trackers/{f.tracker['id']}", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": IMEI, "has_fuel_sensor": False})
    assert changed.status_code == 200 and changed.json()["has_fuel_sensor"] is False
    assert (await tier()).json()["tracking_tier"] == "standard"
    assert (await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": "999999999999999", "fuel_unit": "gallons"})).status_code == 422


async def test_fuel_from_a_tracker_without_a_sensor_is_ignored_and_a_percent_sensor_is_turned_into_litres(client):
    f = await with_sensor(client, sensor=False)
    await send_all(client, [position(IMEI, hours_ago(minutes=30), -1.29, 36.82, speed_kmh=0, fuel=250)])
    res = (await client.get(f"/vehicles/{f.vehicle['id']}/fuel-level", headers=bearer(f.owner))).json()
    assert res["has_sensor"] is False and res["points"] == []
    await client.put(f"/trackers/{f.tracker['id']}", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": IMEI, "has_fuel_sensor": True, "fuel_unit": "percent"})
    await send_all(client, [position(IMEI, hours_ago(minutes=20), -1.29, 36.82, speed_kmh=0, fuel=50), position(IMEI, hours_ago(minutes=10), -1.29, 36.82, speed_kmh=0, fuel=150)])
    res = (await client.get(f"/vehicles/{f.vehicle['id']}/fuel-level", headers=bearer(f.owner))).json()
    assert res["unit"] == "percent" and [p["litres"] for p in res["points"]] == [100.0]  # 50 percent of the 200 litre tank; 150 percent is nonsense and dropped


# ---- siphoning (acceptance) ----------------------------------------------------------------------------------------------


async def test_a_simulated_overnight_fuel_drop_raises_a_siphoning_alert_at_once(client):
    f = await with_sensor(client)
    await send_all(client, siphon(IMEI, hours_ago(minutes=125)))
    await sweep()
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_siphoning"]
    assert a["severity"] == "red" and a["registration"] == "KCA 123A" and "50 litres left the tank while the lorry was parked" in a["title"]
    e = a["evidence"]
    assert e["litres"] == 50 and e["before_litres"] == 280 and e["after_litres"] == 230 and e["parked"] is True and abs(e["lat"] + 1.2921) < 0.001
    assert any("50 litres left the tank" in m for p, m in get_sms_sender().outbox if p == "+254700111222")
    assert await sweep() == 0  # the same drop is not raised twice
    shown = (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"]
    assert [x["kind"] for x in shown].count("fraud_fuel_siphoning") == 1


async def test_fuel_falling_while_the_lorry_drives_is_not_siphoning(client):
    f = await with_sensor(client)
    start = hours_ago(minutes=60)
    levels = [280, 270, 255, 240, 238]
    await send_all(client, [position(IMEI, start + timedelta(minutes=i), -1.0 + i * 0.01, 36.0, speed_kmh=60, fuel=level) for i, level in enumerate(levels)])
    await sweep()
    assert await open_alerts(client, f.owner) == []


async def test_a_small_drop_and_a_sensor_spike_are_not_alerts(client):
    f = await with_sensor(client)
    start = hours_ago(minutes=60)
    levels = [200, 200, 190, 190, 190, 120, 190, 190]  # a 10 litre drop, then one wild reading
    await send_all(client, [position(IMEI, start + timedelta(minutes=i), -1.29, 36.82, speed_kmh=0, fuel=level) for i, level in enumerate(levels)])
    await sweep()
    assert await open_alerts(client, f.owner) == []


# ---- refills against what was paid ---------------------------------------------------------------------------------------


async def test_a_refill_that_matches_the_fuel_paid_for_raises_nothing(client):
    f = await with_sensor(client)
    began = hours_ago(hours=5)
    await send_all(client, refuel(IMEI, began))
    await bought(f, 100, began + timedelta(minutes=12))
    await sweep()
    assert await open_alerts(client, f.owner) == []


async def test_a_refill_with_no_purchase_recorded_is_amber(client):
    f = await with_sensor(client)
    await send_all(client, refuel(IMEI, hours_ago(hours=5)))
    await sweep()
    [a] = await open_alerts(client, f.owner)
    assert a["kind"] == "unrecorded_refill" and a["severity"] == "amber" and a["evidence"]["litres"] == 100
    assert not any("went into the tank" in m for _, m in get_sms_sender().outbox)  # amber stays in the app


async def test_fuel_paid_for_that_never_reached_the_tank_is_red_with_both_numbers(client):
    f = await with_sensor(client)
    began = hours_ago(hours=6)
    await send_all(client, refuel(IMEI, began, added=40))  # only 40 litres went in
    await bought(f, 100, began + timedelta(minutes=12))  # but 100 were paid for
    await sweep()
    [a] = await open_alerts(client, f.owner)
    assert a["kind"] == "fuel_not_in_tank" and a["severity"] == "red" and a["evidence"] == {"paid_litres": 100.0, "refilled_litres": 40.0, "gap_litres": 60.0, "amount_cents": 1800000, "station": "Total Mlolongo", "bought_at": a["evidence"]["bought_at"]}
    assert "paid for 100 litres but only 40 reached the tank" in a["title"]
    await sweep()
    assert len(await open_alerts(client, f.owner)) == 1


async def test_fuel_paid_for_with_no_refill_seen_while_the_sensor_was_reporting_is_red_and_too_recent_is_waited_for(client):
    f = await with_sensor(client)
    began = hours_ago(hours=6)
    await send_all(client, [position(IMEI, began + timedelta(minutes=m), -1.29, 36.82, speed_kmh=0, fuel=120) for m in range(0, 241, 20)])  # steady all the time
    await bought(f, 80, began + timedelta(minutes=30))
    await bought(f, 60, hours_ago(minutes=20))  # bought just now: the tank has had no time to show it
    await sweep()
    [a] = await open_alerts(client, f.owner)
    assert a["kind"] == "fuel_not_in_tank" and a["evidence"]["paid_litres"] == 80.0 and a["evidence"]["refilled_litres"] == 0.0 and a["severity"] == "red"


async def test_fuel_bought_while_the_sensor_was_not_reporting_is_not_judged(client):
    f = await with_sensor(client)
    await bought(f, 100, hours_ago(hours=6))
    await send_all(client, [position(IMEI, hours_ago(hours=1), -1.29, 36.82, speed_kmh=0, fuel=120), position(IMEI, hours_ago(minutes=50), -1.29, 36.82, speed_kmh=0, fuel=120)])
    await sweep()
    assert await open_alerts(client, f.owner) == []


async def test_the_owner_can_set_how_much_fuel_counts_as_a_drop(client):
    f = await with_sensor(client)
    assert (await client.put("/fraud/settings", headers=bearer(f.owner), json={"thresholds": {"fuel_drop_litres": 80}})).status_code == 200
    await send_all(client, siphon(IMEI, hours_ago(minutes=125)))  # 50 litres: under the new 80
    await sweep()
    assert await open_alerts(client, f.owner) == []
    assert (await client.put("/fraud/settings", headers=bearer(f.owner), json={"thresholds": {"fuel_drop_litres": 5000}})).json()["detail"]["code"] == "threshold_out_of_range"


# ---- the chart -----------------------------------------------------------------------------------------------------------


async def test_the_fuel_level_chart_shows_the_level_the_events_and_the_purchases(client):
    f = await with_sensor(client)
    began = hours_ago(hours=3)
    await send_all(client, siphon(IMEI, began))
    await bought(f, 50, began + timedelta(minutes=30))
    res = await client.get(f"/vehicles/{f.vehicle['id']}/fuel-level", params={"start": (began - timedelta(minutes=5)).isoformat(), "end": datetime.now(UTC).isoformat()}, headers=bearer(f.owner))
    assert res.status_code == 200, res.text
    chart = res.json()
    assert chart["has_sensor"] is True and chart["unit"] == "litres" and chart["tank_litres"] == 200 and chart["readings"] == len(chart["points"]) == 16
    assert chart["points"][0]["litres"] == 280 and chart["points"][-1]["litres"] == 230
    assert [(e["kind"], e["litres"]) for e in chart["events"]] == [("drop", 50.0)] and chart["purchases"][0]["litres"] == 50 and chart["purchases"][0]["station"] == "Total Mlolongo"


async def test_the_chart_checks_the_range_the_vehicle_and_who_may_look(client):
    f = await with_sensor(client)
    url = f"/vehicles/{f.vehicle['id']}/fuel-level"
    now = datetime.now(UTC)
    assert (await client.get(url, params={"start": now.isoformat(), "end": (now - timedelta(hours=1)).isoformat()}, headers=bearer(f.owner))).json()["detail"]["code"] == "bad_range"
    assert (await client.get(url, params={"start": (now - timedelta(days=9)).isoformat(), "end": now.isoformat()}, headers=bearer(f.owner))).json()["detail"]["code"] == "range_too_long"
    assert (await client.get(url, headers=bearer(f.driver))).status_code == 403
    supervisor, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    assert (await client.get(url, headers=bearer(supervisor))).status_code == 404  # a supervisor sees only the vehicles assigned to them, and has none
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get(url, headers=bearer(other))).status_code == 404
    assert (await client.get(f"/vehicles/{uuid.uuid4()}/fuel-level", headers=bearer(f.owner))).status_code == 404

