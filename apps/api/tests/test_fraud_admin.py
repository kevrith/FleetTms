import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.config import settings
from app.models import BehaviourEvent, Vehicle
from app.reminders import NAIROBI
from tests.fraud_scenarios import drive, open_alerts, seeded
from tests.helpers import PASSWORD, bearer, enable_2fa, login, owner_session, staff_session
from tests.leasing import in_db
from tests.test_trackers import KEY


@pytest.fixture(autouse=True)
def _key():
    settings.traccar_forward_key = KEY
    yield
    settings.traccar_forward_key = ""


def TODAY():
    day = datetime.now(NAIROBI).date().isoformat()
    return {"start": day, "end": day}


async def one_alert(client, f):
    await drive(client, f, litres=400, km=1000)
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_variance"]
    return a


# ---- answering an alert --------------------------------------------------------------------------------------------------


async def test_an_alert_is_explained_or_confirmed_with_a_note_and_only_once(client):
    f = await seeded(client)
    a = await one_alert(client, f)
    handle = lambda who, **kw: client.post(f"/fraud/alerts/{a['id']}/handle", headers=bearer(who), json={"note": "Fuel for the generator was bought as well", **kw})
    assert (await handle(f.driver)).status_code == 403
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    short = await client.post(f"/fraud/alerts/{a['id']}/handle", headers=bearer(manager), json={"note": "x"})
    assert short.status_code == 422
    done = await handle(manager)
    assert done.status_code == 200 and done.json()["status"] == "explained" and done.json()["handled_at"] and done.json()["note"].startswith("Fuel for the generator")
    again = await handle(f.owner, outcome="confirmed")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_handled"
    assert [x for x in await open_alerts(client, f.owner, status_filter="open") if x["kind"] == "fuel_variance"] == []
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert "fraud_alert.explained" in actions and "fraud_alert.fuel_variance" in actions
    assert "fraud_fuel_variance" not in [x["kind"] for x in (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"]]  # answered, so gone from the dashboard


async def test_confirming_an_alert_lowers_the_drivers_score(client):
    f = await seeded(client)
    a = await one_alert(client, f)
    before = (await client.get("/scorecards", params=TODAY(), headers=bearer(f.owner))).json()["drivers"][0]
    assert before["alerts"] == 90 and before["detail"]["alerts_open"] == 1  # an open alert costs 10 points
    await client.post(f"/fraud/alerts/{a['id']}/handle", headers=bearer(f.owner), json={"note": "Siphoned, the driver admitted it", "outcome": "confirmed"})
    after = (await client.get("/scorecards", params=TODAY(), headers=bearer(f.owner))).json()["drivers"][0]
    assert after["alerts"] == 75 and after["detail"]["alerts_confirmed"] == 1  # a confirmed one costs 25


async def test_alerts_are_filtered_and_belong_to_one_business(client):
    f = await seeded(client)
    await one_alert(client, f)
    assert len(await open_alerts(client, f.owner, kind="fuel_variance")) == 1
    assert await open_alerts(client, f.owner, kind="side_trip") == []
    assert len(await open_alerts(client, f.owner, severity="red")) == 1 and await open_alerts(client, f.owner, severity="amber") == []
    assert len(await open_alerts(client, f.owner, vehicle_id=f.vehicle["id"])) == 1
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert await open_alerts(client, other) == []
    a = (await open_alerts(client, f.owner))[0]
    assert (await client.get(f"/fraud/alerts/{a['id']}", headers=bearer(other))).status_code == 404
    assert (await client.get(f"/fraud/alerts/{a['id']}", headers=bearer(f.owner))).json()["evidence"]["litres"] == 400
    assert (await client.get(f"/fraud/alerts/{uuid.uuid4()}", headers=bearer(f.owner))).status_code == 404


async def scoped_supervisor(client, owner, vehicle_id, email="sup@example.com"):
    res = await client.post("/users", headers=bearer(owner), json={"name": "Sup", "email": email, "roles": ["supervisor"], "vehicle_scope": [vehicle_id]})
    assert res.status_code == 201, res.text
    await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
    tokens = (await login(client, email)).json()
    await enable_2fa(client, tokens)
    return tokens


async def test_a_supervisor_sees_only_the_alerts_of_their_own_vehicles(client):
    f = await seeded(client)
    await one_alert(client, f)
    elsewhere = (await client.post("/vehicles", headers=bearer(f.owner), json={"registration": "KCB 222B", "fuel_type": "diesel"})).json()
    other_sup = await scoped_supervisor(client, f.owner, elsewhere["id"], "sup2@example.com")
    assert await open_alerts(client, other_sup) == []  # the fuel alert is about a vehicle they do not have
    assert (await client.get("/fraud/summary", headers=bearer(other_sup))).json()["open"]["total"] == 0
    mine = await scoped_supervisor(client, f.owner, f.vehicle["id"])
    [a] = await open_alerts(client, mine)
    assert a["kind"] == "fuel_variance"
    assert (await client.get(f"/fraud/alerts/{a['id']}", headers=bearer(other_sup))).status_code == 404
    assert (await client.post(f"/fraud/alerts/{a['id']}/handle", headers=bearer(mine), json={"note": "Looks fine to me"})).status_code == 403  # they can look, not answer


async def test_the_summary_shows_how_often_each_kind_turns_out_to_be_real(client):
    f = await seeded(client)
    a = await one_alert(client, f)
    s = (await client.get("/fraud/summary", headers=bearer(f.owner))).json()
    assert s["open"] == {"red": 1, "amber": 0, "total": 1} and s["kinds"][0]["kind"] == "fuel_variance" and s["kinds"][0]["confirmed_pct"] is None
    await client.post(f"/fraud/alerts/{a['id']}/handle", headers=bearer(f.owner), json={"note": "Confirmed with the pump attendant", "outcome": "confirmed"})
    s = (await client.get("/fraud/summary", headers=bearer(f.owner))).json()
    assert s["open"]["total"] == 0 and s["kinds"][0]["confirmed"] == 1 and s["kinds"][0]["confirmed_pct"] == 100


async def test_scanning_now_runs_the_checks_and_is_for_owners_and_managers(client):
    f = await seeded(client)
    await client.post("/devices/integrity", headers=bearer(f.driver), json={"device_id": "pixel-1", "vehicle_id": f.vehicle["id"], "mock_location": True})
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    supervisor, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    assert (await client.post("/fraud/scan", headers=bearer(supervisor))).status_code == 403
    res = await client.post("/fraud/scan", headers=bearer(manager))
    assert res.status_code == 200 and res.json()["raised"] >= 1
    assert (await client.post("/fraud/scan", headers=bearer(f.owner))).json()["raised"] == 0


# ---- thresholds and channels ---------------------------------------------------------------------------------------------


async def test_settings_show_the_defaults_and_limits_and_are_checked_on_the_way_in(client):
    f = await seeded(client)
    s = (await client.get("/fraud/settings", headers=bearer(f.owner))).json()
    assert s["thresholds"]["fuel_variance_pct"] == 10 and s["defaults"]["long_stop_minutes"] == 45 and s["limits"]["fuel_variance_pct"] == [3, 50]
    assert s["channels"]["red"] == {"roles": ["owner", "manager"], "channels": ["sms"]} and s["channels"]["amber"]["channels"] == []
    put = lambda **body: client.put("/fraud/settings", headers=bearer(f.owner), json=body)
    assert (await put(thresholds={"fuel_variance_pct": 1})).json()["detail"]["code"] == "threshold_out_of_range"
    assert (await put(thresholds={"nonsense": 5})).json()["detail"]["code"] == "unknown_threshold"
    assert (await put(channels={"purple": {"roles": [], "channels": []}})).json()["detail"]["code"] == "unknown_severity"
    assert (await put(channels={"red": {"roles": ["owner"], "channels": ["pigeon"]}})).json()["detail"]["code"] == "unknown_channel"
    assert (await put(channels={"red": {"roles": ["janitor"], "channels": ["sms"]}})).json()["detail"]["code"] == "unknown_channel"
    ok = await put(thresholds={"long_stop_minutes": 90, "idle_litres_per_hour": 2.5})
    assert ok.json()["thresholds"]["long_stop_minutes"] == 90 and ok.json()["thresholds"]["idle_litres_per_hour"] == 2.5 and ok.json()["thresholds"]["fuel_variance_pct"] == 10
    later = await put(thresholds={"fuel_variance_pct": 15})  # earlier changes are kept
    assert later.json()["thresholds"]["long_stop_minutes"] == 90 and later.json()["thresholds"]["fuel_variance_pct"] == 15
    assert "alert_settings.changed" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_only_the_owner_sets_thresholds_and_managers_can_only_look_at_alerts(client):
    f = await seeded(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.get("/fraud/settings", headers=bearer(manager))).status_code == 403
    assert (await client.put("/fraud/settings", headers=bearer(manager), json={})).status_code == 403
    assert (await client.get("/fraud/alerts", headers=bearer(manager))).status_code == 200
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.get("/fraud/alerts", headers=bearer(accountant))).status_code == 403
    assert (await client.get("/fraud/alerts", headers=bearer(f.driver))).status_code == 403


# ---- baselines -----------------------------------------------------------------------------------------------------------


async def test_a_vehicles_baselines_are_by_route_and_load_with_the_idling_taken_out(client):
    f = await seeded(client, history=4, km=500, litres=150)
    b = (await client.get(f"/vehicles/{f.vehicle['id']}/baselines", headers=bearer(f.owner))).json()
    assert b["registration"] == "KCA 123A" and b["needed_trips"] == 3
    [row] = b["baselines"]
    assert row == {"route": "Mombasa to Nairobi", "load_band": "empty", "l_per_km": 0.3, "km_per_litre": 3.33, "trips": 4, "established": True}
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/baselines", headers=bearer(other))).status_code == 404
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/baselines", headers=bearer(f.driver))).status_code == 403


async def test_with_no_history_the_declared_consumption_is_the_baseline_and_with_none_nothing_is_judged(client):
    f = await seeded(client, history=0)

    async def declare(loaded, empty):
        async def go(db):
            await db.execute(update(Vehicle).where(Vehicle.id == uuid.UUID(f.vehicle["id"])).values(expected_kmpl_loaded=loaded, expected_kmpl_empty=empty))

        await in_db(go)

    await declare(None, None)
    await drive(client, f, litres=900, km=1000)  # no history and no declared consumption: nothing to compare with
    assert [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_variance"] == []
    await declare(3.5, 3.5)
    await drive(client, f, litres=900, km=1000)  # 3.5 km per litre expects about 286 litres
    [a] = [x for x in await open_alerts(client, f.owner) if x["kind"] == "fuel_variance"]
    assert a["evidence"]["baseline_source"] == "the consumption entered for the vehicle" and a["severity"] == "red" and a["evidence"]["baseline_trips"] == 0


# ---- scorecards ----------------------------------------------------------------------------------------------------------


async def test_a_driver_scorecard_has_each_part_and_an_overall(client):
    f = await seeded(client)
    await drive(client, f, litres=305, km=1000)
    me = uuid.UUID(f.ids["+254712345678"])

    async def seed(db):
        vid = uuid.UUID(f.vehicle["id"])
        for i in range(5):
            db.add(BehaviourEvent(vehicle_id=vid, driver_membership_id=me, kind="speeding", at=datetime.now(UTC) - timedelta(minutes=10 + i), value=95, source="tracker"))

    await in_db(seed)
    res = await client.get("/scorecards", params=TODAY(), headers=bearer(f.owner))
    assert res.status_code == 200
    [d] = res.json()["drivers"]
    assert d["name"] == "driver user" and d["trips"] == 1 and d["km"] == 1000
    assert d["safety"] == 97  # five speeding events at weight 3 over 1000 km: 15 * 100 / 1000 = 1.5, times 2, off 100
    assert d["fuel"] == 92 and d["detail"]["trips_with_fuel_checked"] == 1 and d["detail"]["avg_fuel_variance_pct"] == 1.7  # 305 litres against the 300 expected
    assert d["alerts"] == 100 and d["inspections"] == 100 and d["punctuality"] is None
    assert d["overall"] == 97 and d["band"] == "good" and d["detail"]["behaviour"] == {"speeding": 5}  # no punctuality to score, so the other four are weighted up
    assert res.json()["weights"]["safety"] == 0.3


async def test_scorecards_check_the_period_and_are_for_those_who_see_reports(client):
    f = await seeded(client)
    bad = await client.get("/scorecards", params={"start": "2026-10-10", "end": "2026-10-01"}, headers=bearer(f.owner))
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_range"
    long = await client.get("/scorecards", params={"start": "2024-01-01", "end": "2026-10-01"}, headers=bearer(f.owner))
    assert long.json()["detail"]["code"] == "range_too_long"
    assert (await client.get("/scorecards", headers=bearer(f.driver))).status_code == 403
    supervisor, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    assert (await client.get("/scorecards", headers=bearer(supervisor))).status_code == 403
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.get("/scorecards", params=TODAY(), headers=bearer(manager))).json()["drivers"] == []  # nobody drove today

