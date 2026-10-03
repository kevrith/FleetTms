import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import TyreSwapAlert
from app.notify import fake_email
from app.sms import get_sms_sender
from app.tracker_simulator import position, power_cut
from tests.fraud_scenarios import by_kind, drive, open_alerts, seeded, started, sweep
from tests.helpers import bearer, staff_session
from tests.leasing import in_db, set_phone
from tests.shots import fleet
from tests.test_trackers import IMEI, KEY, ago, post, tracked
from tests.test_tracking import running


@pytest.fixture(autouse=True)
def _outboxes():
    settings.traccar_forward_key = KEY
    fake_email().outbox.clear()
    yield
    settings.traccar_forward_key = ""


# ---- seeded scenarios: each dishonest thing raises the right alert with its evidence --------------------------------------


async def test_inflated_fuel_is_caught_against_the_vehicles_own_history(client):
    f = await seeded(client)
    await drive(client, f, litres=400, km=1000)  # a normal trip burns about 300
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_variance"]
    assert a["severity"] == "red" and a["registration"] == "KCA 123A" and a["driver"] == "driver user" and "33.3% more than expected" in a["title"]
    e = a["evidence"]
    assert e["litres"] == 400 and e["km"] == 1000 and e["expected_litres"] == 300 and e["variance_pct"] == 33.3 and e["baseline_l_per_km"] == 0.3
    assert e["baseline_source"] == "same route and load" and e["baseline_trips"] == 3 and e["threshold_pct"] == 10
    assert a["trust_level"] == "low" and a["trip_id"]  # a vehicle with no tracker and nothing else to go on is low


async def test_a_normal_trip_raises_nothing_at_all(client):
    f = await seeded(client)
    await drive(client, f, litres=305, km=1000, phone_km=1000)
    await sweep()
    assert await open_alerts(client, f.owner) == []
    assert [m for _, m in get_sms_sender().outbox if "Your FleetTms code" not in m] == []  # the driver's sign-in codes are not alerts


async def test_long_idling_explains_extra_fuel_so_it_is_not_a_false_alarm(client):
    f = await seeded(client)
    await drive(client, f, litres=360, km=1000, idle_minutes=1200)  # 20 hours idling at 3 litres an hour is 60 litres
    kinds = by_kind(await open_alerts(client, f.owner))
    assert "fuel_variance" not in kinds
    assert kinds["excess_idling"]["evidence"]["idle_minutes"] == 1200  # the idling itself is still worth knowing about


async def test_the_same_fuel_without_the_idling_is_flagged(client):
    f = await seeded(client)
    await drive(client, f, litres=360, km=1000)
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_variance"]
    assert a["severity"] == "amber" and a["evidence"]["variance_pct"] == 20


async def test_a_rolled_back_odometer_is_named_when_the_phone_says_otherwise(client):
    f = await seeded(client)
    await drive(client, f, km=40, phone_km=300)  # the odometer claims 40 km, the phone drove 300
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "odometer_mismatch"]
    assert a["severity"] in ("red", "amber") and a["evidence"]["odometer_km"] == 40 and a["evidence"]["sources_km"]["odometer"] == 40 and a["evidence"]["sources_km"]["phone"] > 250


async def test_a_side_trip_is_a_drive_much_longer_than_the_route(client):
    f = await seeded(client, km=480)
    await drive(client, f, litres=150, km=700, phone_km=700)  # trips from Mombasa to Nairobi come to 480 km
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "side_trip"]
    assert a["severity"] == "amber" and a["evidence"]["expected_km"] == 480 and a["evidence"]["extra_km"] > 200 and a["evidence"]["expected_from"] == "trips between the same places"


async def test_padded_parking_is_a_claim_far_above_the_routes_usual(client):
    f = await fleet(client)
    trip = await running(client, f)
    usual = await client.post("/route-costs", headers=bearer(f.owner), json={"origin": "Mombasa", "destination": "Nairobi", "category": "parking", "usual_cents": 100000, "tolerance_pct": 50})
    assert usual.status_code == 201, usual.text
    ok = await client.post("/expenses", headers=bearer(f.driver), json={"category": "parking", "amount_cents": 120000, "vehicle_id": f.vehicle["id"], "trip_id": trip["id"], "mpesa_code": "QWE1234567"})
    assert ok.status_code == 201
    padded = await client.post("/expenses", headers=bearer(f.driver), json={"category": "parking", "amount_cents": 500000, "vehicle_id": f.vehicle["id"], "trip_id": trip["id"], "mpesa_code": "QWE7654321"})
    assert padded.status_code == 201 and "unusual_for_route" in padded.json()["flags"]
    await sweep()
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "expense_above_norm"]
    assert a["evidence"]["amount_cents"] == 500000 and a["evidence"]["category"] == "parking" and a["evidence"]["route"] == "Mombasa to Nairobi" and a["driver"] == "driver user"


async def test_a_phone_running_a_fake_gps_app_is_flagged_red(client):
    f = await fleet(client)
    res = await client.post("/devices/integrity", headers=bearer(f.driver), json={"device_id": "pixel-1", "vehicle_id": f.vehicle["id"], "mock_location": True, "rooted": True})
    assert res.status_code == 200
    await sweep()
    kinds = by_kind(await open_alerts(client, f.owner))
    assert kinds["fake_gps"]["severity"] == "red" and kinds["fake_gps"]["evidence"]["device_id"] == "pixel-1" and kinds["rooted_phone"]["severity"] == "amber"
    assert kinds["fake_gps"]["driver"] == "driver user"


async def test_a_tracker_power_cut_is_mirrored_into_the_alert_list_without_texting_twice(client):
    f = await tracked(client)
    await post(client, position(IMEI, ago(seconds=60), -1.2921, 36.8219))
    await post(client, power_cut(IMEI, ago(seconds=1))[0])
    texts = len(get_sms_sender().outbox)
    assert texts == 1  # the tracker alert's own text
    await sweep()
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "power_cut"]
    assert a["severity"] == "red" and a["evidence"]["alarm"] == "powerCut" and a["notified"] == 0
    assert len(get_sms_sender().outbox) == texts
    again = await sweep()
    assert again == 0  # nothing new the second time


async def test_a_tyre_swap_is_mirrored_and_closing_it_closes_the_source(client):
    f = await fleet(client)

    async def seed(db):
        t = TyreSwapAlert(vehicle_id=uuid.UUID(f.vehicle["id"]), position="front_left", expected_serial="MICH-001", seen_serial="OLD-999", reason="mismatch")
        db.add(t)
        await db.flush()
        return str(t.id)

    source = await in_db(seed)
    await sweep()
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "tyre_swap"]
    assert a["severity"] == "red" and a["evidence"] == {"position": "front_left", "recorded_serial": "MICH-001", "serial_read": "OLD-999", "reason": "mismatch"}
    done = await client.post(f"/fraud/alerts/{a['id']}/handle", headers=bearer(f.owner), json={"note": "Retread swapped on purpose by the workshop", "outcome": "explained"})
    assert done.status_code == 200 and done.json()["status"] == "explained"
    async def check(db):
        return (await db.execute(select(TyreSwapAlert).where(TyreSwapAlert.id == uuid.UUID(source)))).scalar_one().status
    assert await in_db(check) == "resolved"


async def test_siphoning_after_a_tracker_power_cut_is_red_with_both_pieces_of_evidence(client):
    """The demo: the tracker is cut, then the lorry stands for an hour in the middle of nowhere."""
    f = await tracked(client)
    await set_phone("owner@example.com", "+254700111222")
    trip = await started(client, f, hours_ago=3)
    began = datetime.fromisoformat(trip["started_at"]) + timedelta(minutes=2)
    for i in range(8):  # driving
        await post(client, position(IMEI, began + timedelta(minutes=i), -1.0 + i * 0.01, 37.0, speed_kmh=60))
    cut = began + timedelta(minutes=9)
    await post(client, power_cut(IMEI, cut, lat=-0.92, lng=37.0)[0])
    for i in range(4):  # then standing, in the same spot, for an hour (on the backup battery)
        await post(client, position(IMEI, cut + timedelta(minutes=i * 20), -0.92, 37.0, speed_kmh=0, ignition=False))
    get_sms_sender().outbox.clear()
    await sweep()
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "tamper_then_stop"]
    assert a["severity"] == "red" and a["evidence"]["minutes"] == 60 and "tracker_cut_at" in a["evidence"] and abs(a["evidence"]["lat"] + 0.92) < 0.001
    assert "soon after the tracker was cut" in a["title"] and a["driver"] == "driver user" and a["trust_level"] == "low"
    assert any("soon after the tracker was cut" in m for _, m in get_sms_sender().outbox)  # red alerts text the owner by default
    assert "power_cut" in by_kind(await open_alerts(client, f.owner))


async def test_a_long_stop_in_an_unknown_place_is_amber_and_at_a_depot_is_nothing(client):
    f = await tracked(client)
    trip = await started(client, f, hours_ago=3)
    began = datetime.fromisoformat(trip["started_at"]) + timedelta(minutes=2)
    for i in range(3):
        await post(client, position(IMEI, began + timedelta(minutes=i * 30), -0.5, 36.5, speed_kmh=0, ignition=False))
    await post(client, position(IMEI, began + timedelta(minutes=95), -0.4, 36.5, speed_kmh=60))
    await sweep()
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] in ("long_stop", "tamper_then_stop")]
    assert a["kind"] == "long_stop" and a["severity"] == "amber" and a["evidence"]["minutes"] == 60


async def test_a_stop_at_a_known_place_is_not_flagged(client):
    f = await tracked(client)
    made = await client.post("/geofences", headers=bearer(f.owner), json={"name": "Weighbridge", "kind": "depot", "shape": {"type": "circle", "lat": -0.5, "lng": 36.5, "radius_m": 300}, "alert_on": []})
    assert made.status_code == 201
    trip = await started(client, f, hours_ago=3)
    began = datetime.fromisoformat(trip["started_at"]) + timedelta(minutes=2)
    for i in range(3):
        await post(client, position(IMEI, began + timedelta(minutes=i * 30), -0.5, 36.5, speed_kmh=0, ignition=False))
    await sweep()
    assert [x for x in await open_alerts(client, f.owner) if x["kind"] in ("long_stop", "tamper_then_stop")] == []


# ---- repeats, going dark, duplicates, sensitive changes -----------------------------------------------------------------


async def test_a_finding_is_raised_once_however_often_the_checks_run(client):
    f = await seeded(client)
    await drive(client, f, litres=400, km=1000)
    first = len(await open_alerts(client, f.owner))
    await sweep()
    await sweep()
    assert len(await open_alerts(client, f.owner)) == first


async def test_claiming_the_same_mpesa_code_twice_is_refused_and_the_owner_can_see_the_attempt(client):
    f = await fleet(client)
    trip = await running(client, f)
    body = {"vehicle_id": f.vehicle["id"], "trip_id": trip["id"], "litres": "100", "price_per_litre_cents": 18000, "amount_cents": 1800000, "mpesa_code": "ABC1234567"}
    assert (await client.post("/fuel", headers=bearer(f.driver), json=body)).status_code == 201
    again = await client.post("/fuel", headers=bearer(f.driver), json={**body, "litres": "50", "amount_cents": 900000})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "duplicate_mpesa_code"
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "duplicate_mpesa"]
    assert a["evidence"]["code"] == "ABC1234567" and a["evidence"]["first_use"]["used_on"] == "a fuel entry" and a["driver"] == "driver user" and "tried to claim an M-Pesa code that was already used" in a["title"]
    await client.post("/fuel", headers=bearer(f.driver), json={**body, "litres": "60", "amount_cents": 1080000})
    assert len([x for x in await open_alerts(client, f.owner) if x["kind"] == "duplicate_mpesa"]) == 1  # the same attempt again is the same alert
    shown = (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"]
    assert [a["kind"] for a in shown].count("fraud_duplicate_mpesa") == 1


async def test_using_the_same_receipt_photo_twice_is_refused_and_shown(client):
    from tests.shots import jpeg, upload

    f = await fleet(client)
    data = jpeg()
    assert (await upload(client, f.driver, "receipt", data=data)).status_code == 201
    again = await upload(client, f.driver, "receipt", data=data)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "duplicate_photo"
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "duplicate_receipt"]
    assert len(a["evidence"]["sha_prefix"]) == 12 and a["evidence"]["first_use"]["kind"] == "receipt"


async def test_a_manager_changing_a_routes_usual_cost_is_flagged_but_the_owner_doing_it_is_not(client):
    f = await fleet(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    cost = {"origin": "Mombasa", "destination": "Nairobi", "category": "parking", "usual_cents": 100000, "tolerance_pct": 50}
    row = (await client.post("/route-costs", headers=bearer(f.owner), json=cost)).json()
    assert (await client.put(f"/route-costs/{row['id']}", headers=bearer(f.owner), json={**cost, "usual_cents": 120000})).status_code == 200
    await sweep()
    assert [x for x in await open_alerts(client, f.owner) if x["kind"] == "sensitive_change"] == []
    res = await client.put(f"/route-costs/{row['id']}", headers=bearer(manager), json={**cost, "usual_cents": 900000})
    assert res.status_code == 200, res.text
    await sweep()
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "sensitive_change"]
    assert a["evidence"]["action"] == "route_cost.updated" and a["evidence"]["by"] and "usual cost was changed" in a["title"]


async def test_the_dashboard_lists_what_the_engine_found_that_it_has_no_line_for(client):
    f = await seeded(client)
    await drive(client, f, litres=400, km=1000)
    shown = (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"]
    mine = [a for a in shown if a["kind"] == "fraud_fuel_variance"]
    assert len(mine) == 1 and mine[0]["severity"] == "red" and mine[0]["link"] == "/alerts" and "more than expected" in mine[0]["title"]


# ---- who is told, and how ------------------------------------------------------------------------------------------------


async def test_red_alerts_text_the_owner_by_default_and_amber_ones_stay_in_the_app(client):
    f = await seeded(client)
    await set_phone("owner@example.com", "+254700111222")
    get_sms_sender().outbox.clear()
    await drive(client, f, litres=400, km=1000)  # red
    texts = [m for p, m in get_sms_sender().outbox if p == "+254700111222"]
    assert any("more than expected" in m for m in texts)
    get_sms_sender().outbox.clear()
    await drive(client, f, litres=360, km=1000)  # amber: 20 percent over
    assert [m for _, m in get_sms_sender().outbox if "more than expected" in m] == []
    assert fake_email().outbox == []  # amber alerts go to nobody by text or email unless the owner chooses


async def test_the_owner_can_choose_email_and_widen_who_is_told(client):
    f = await seeded(client)
    await staff_session(client, f.owner, "manager", "mgr@example.com")
    res = await client.put("/fraud/settings", headers=bearer(f.owner), json={"channels": {"amber": {"roles": ["owner", "manager"], "channels": ["email"]}}})
    assert res.status_code == 200 and res.json()["channels"]["amber"] == {"roles": ["owner", "manager"], "channels": ["email"]}
    fake_email().outbox.clear()
    await drive(client, f, litres=360, km=1000)  # amber
    sent = fake_email().outbox
    assert {to for to, _, _ in sent} == {"owner@example.com", "mgr@example.com"} and all("FleetTms alert" in subject for _, subject, _ in sent)
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_variance"]
    assert a["notified"] == 2


async def test_a_stricter_threshold_catches_what_the_default_lets_through(client):
    f = await seeded(client)
    assert (await client.put("/fraud/settings", headers=bearer(f.owner), json={"thresholds": {"fuel_variance_pct": 40}})).status_code == 200
    await drive(client, f, litres=400, km=1000)  # 33 percent over: fine at 40
    assert [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_variance"] == []
    assert (await client.put("/fraud/settings", headers=bearer(f.owner), json={"thresholds": {"fuel_variance_pct": 5}})).status_code == 200
    await drive(client, f, litres=320, km=1000)  # 6.7 percent over: caught at 5
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_variance"]
    assert a["evidence"]["threshold_pct"] == 5 and a["severity"] == "amber"  # red starts at twice the threshold

