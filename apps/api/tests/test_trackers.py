import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.config import settings
from app.models import ImmobiliserCommand, Trip
from app.sms import get_sms_sender
from app.traccar import fake_traccar, parse_forward
from app.tracker_simulator import event, jamming, offline, position, power_cut, trip
from app.tracking_jobs import watch_devices
from tests.fleet import add_vehicle
from tests.helpers import PASSWORD, bearer, owner_session, staff_session
from tests.leasing import in_db, set_phone
from tests.shots import fleet
from tests.test_dashboard import finish_trip
from tests.test_tracking import running, send

KEY = secrets.token_hex(16)
IMEI = "356938035643809"


@pytest.fixture(autouse=True)
def _traccar():
    settings.traccar_forward_key = KEY
    fake_traccar().commands.clear()
    fake_traccar().fail_with = None
    yield
    settings.traccar_forward_key = ""


def ago(**kw) -> datetime:
    return datetime.now(UTC) - timedelta(**kw)


async def post(client, body, key=KEY):
    return await client.post(f"/hooks/traccar/{key}", json=body)


async def tracked(client, supports=True, imei=IMEI):
    """A fleet whose owner can be texted, with a tracker fitted to its vehicle."""
    f = await fleet(client)
    await set_phone("owner@example.com", "+254700111222")
    res = await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": imei, "brand": "Teltonika", "model": "FMB920", "supports_immobiliser": supports})
    assert res.status_code == 201, res.text
    f.tracker = res.json()
    get_sms_sender().outbox.clear()
    return f


def sms_to_owner():
    return [m for p, m in get_sms_sender().outbox if p == "+254700111222"]


async def alerts_of(client, who, status=None):
    res = await client.get(f"/tracker/alerts{'?status_filter=' + status if status else ''}", headers=bearer(who))
    assert res.status_code == 200, res.text
    return res.json()


# ---- fitting trackers --------------------------------------------------------------------------------------------------


async def test_a_tracker_is_fitted_to_a_vehicle_and_the_vehicle_moves_up_a_tier(client):
    f = await tracked(client)
    assert f.tracker["imei"] == IMEI and f.tracker["registration"] == "KCA 123A" and f.tracker["online_state"] == "unknown"
    assert (await client.get(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner))).json()["tracking_tier"] == "standard"
    listed = (await client.get("/trackers", headers=bearer(f.owner))).json()
    assert [t["imei"] for t in listed] == [IMEI]
    assert "tracker.added" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_an_imei_belongs_to_one_tracker_across_the_whole_platform(client):
    f = await tracked(client)
    again = await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": IMEI.lower()})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "duplicate_imei"
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    v = await add_vehicle(client, other, "KXX 111X")
    assert (await client.post("/trackers", headers=bearer(other), json={"vehicle_id": v["id"], "imei": IMEI})).status_code == 409
    assert (await client.post("/trackers", headers=bearer(other), json={"vehicle_id": f.vehicle["id"], "imei": "111111111111111"})).status_code == 404  # not their vehicle
    assert (await client.get("/trackers", headers=bearer(other))).json() == []


async def test_who_may_fit_and_see_trackers(client):
    f = await tracked(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.get("/trackers", headers=bearer(manager))).status_code == 200
    assert (await client.post("/trackers", headers=bearer(manager), json={"vehicle_id": f.vehicle["id"], "imei": "222222222222222"})).status_code == 201
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.get("/trackers", headers=bearer(accountant))).status_code == 403
    assert (await client.post("/trackers", headers=bearer(f.driver), json={"vehicle_id": f.vehicle["id"], "imei": "333333333333333"})).status_code == 403
    assert (await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": "x"})).status_code == 422
    changed = await client.put(f"/trackers/{f.tracker['id']}", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": IMEI, "is_active": False})
    assert changed.json()["is_active"] is False


# ---- what Traccar posts ------------------------------------------------------------------------------------------------


async def test_the_webhook_needs_the_secret_and_ignores_devices_nobody_registered(client):
    f = await tracked(client)
    body = position(IMEI, ago(seconds=10), -1.29, 36.82)
    assert (await post(client, body, key="wrong")).status_code == 403
    settings.traccar_forward_key = ""
    assert (await post(client, body, key="")).status_code in (403, 404, 405)  # switched off
    assert (await post(client, body, key="anything")).status_code == 403
    settings.traccar_forward_key = KEY
    assert (await post(client, {"nonsense": True})).json() == {"accepted": False, "reason": "unknown_device"}
    assert (await post(client, position("999999999999999", ago(seconds=10), -1.29, 36.82))).json()["accepted"] is False
    await client.put(f"/trackers/{f.tracker['id']}", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": IMEI, "is_active": False})
    assert (await post(client, body)).json()["accepted"] is False  # switched off by the owner
    assert (await client.post(f"/hooks/traccar/{KEY}", content=b"not json", headers={"content-type": "application/json"})).status_code == 422


def test_traccar_speeds_in_knots_become_kilometres_an_hour():
    parsed = parse_forward(position(IMEI, datetime(2026, 10, 2, 8, 0, tzinfo=UTC), -1.0, 36.0, speed_kmh=60, course=90, alarm="hardBraking"))
    p = parsed["position"]
    assert parsed["imei"] == IMEI and abs(p["speed_kmh"] - 60) < 0.1 and p["heading"] == 90 and p["alarm"] == "hardBraking" and p["ignition"] is True and p["power_v"] == 12.6
    assert parse_forward(event(IMEI, "deviceOffline", datetime(2026, 10, 2, 8, 0, tzinfo=UTC)))["event"]["type"] == "deviceOffline"


async def test_a_position_is_stored_shown_on_the_map_and_keeps_the_devices_status(client):
    f = await tracked(client)
    res = await post(client, position(IMEI, ago(seconds=20), -1.2921, 36.8219, speed_kmh=62, course=90, battery=88))
    assert res.json()["accepted"] is True and res.json()["position"]["stored"] is True
    [v] = (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"]
    assert v["position"]["lat"] == -1.2921 and abs(v["position"]["speed_kmh"] - 62) < 0.1 and v["source"] == "tracker"
    assert v["tracker"] == {"online": True, "power_ok": True, "battery_pct": 88.0, "ignition": True, "immobilised": False}
    [t] = (await client.get("/trackers", headers=bearer(f.owner))).json()
    assert t["online_state"] == "online" and t["gps_ok"] is True and t["power_v"] == 12.6 and t["quiet_seconds"] < 60
    body = position(IMEI, datetime(2026, 10, 2, 7, 0, tzinfo=UTC), -1.3, 36.9)
    assert (await post(client, body)).json()["position"]["stored"] is True
    assert (await post(client, body)).json()["position"]["stored"] is False  # the same fix again changes nothing


async def test_a_fix_with_no_gps_lock_is_not_stored_but_the_device_is_still_heard(client):
    f = await tracked(client)
    res = await post(client, position(IMEI, ago(seconds=5), 0.0, 0.0, valid=False))
    assert res.json()["position"]["stored"] is False
    [t] = (await client.get("/trackers", headers=bearer(f.owner))).json()
    assert t["gps_ok"] is False and t["online_state"] == "online" and (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["position"] is None


# Posts captured from a real Traccar 6 server (traccar/traccar image, an OsmAnd-protocol device, JSON forwarding configured with
# FORWARD_TYPE=json and EVENT_FORWARD_TYPE=json). Traccar sends a position on its own and again inside the event it raised.
REAL_ALARM_EVENT = {"event": {"id": 1, "attributes": {"alarm": "hardBraking"}, "deviceId": 1, "type": "alarm", "eventTime": "2026-10-03T04:29:46.922+00:00", "positionId": 1, "geofenceId": 0, "maintenanceId": 0}, "position": {"id": 1, "attributes": {"batteryLevel": 88.0, "alarm": "hardBraking", "ignition": True, "distance": 0.0, "totalDistance": 0.0, "motion": True}, "deviceId": 1, "protocol": "osmand", "serverTime": "2026-10-03T04:29:46.851+00:00", "deviceTime": "2026-10-03T04:29:46.922+00:00", "fixTime": "2026-10-03T04:29:46.922+00:00", "valid": True, "latitude": -1.291, "longitude": 36.82, "altitude": 0.0, "speed": 40.0, "course": 90.0, "address": None, "accuracy": 0.0, "network": None, "geofenceIds": None}, "device": {"id": 1, "attributes": {}, "groupId": 0, "calendarId": 0, "name": "356938035643809", "uniqueId": "356938035643809", "status": "online", "lastUpdate": "2026-10-03T04:29:48.978+00:00", "positionId": 0, "phone": None, "model": None, "contact": None, "category": None, "disabled": False, "expirationTime": None}}


async def test_a_post_captured_from_a_real_traccar_is_understood_and_its_repeat_changes_nothing(client):
    f = await tracked(client)
    body = REAL_ALARM_EVENT
    parsed = parse_forward(body)
    assert parsed["imei"] == IMEI and parsed["event"]["type"] == "alarm" and abs(parsed["position"]["speed_kmh"] - 74.1) < 0.1
    first = await post(client, body)
    assert first.json()["accepted"] is True and first.json()["position"]["stored"] is True
    await post(client, {"position": body["position"], "device": body["device"]})  # the plain position post that comes with it
    await post(client, body)
    assert len([e for e in (await client.get("/behaviour/events", headers=bearer(f.owner))).json() if e["kind"] == "harsh_braking"]) == 1
    [v] = (await client.get("/trackers", headers=bearer(f.owner))).json()
    assert v["battery_pct"] == 88.0 and v["ignition"] is True


async def test_the_engine_command_finds_the_device_even_when_the_token_user_has_none_linked(monkeypatch):
    """Traccar's uniqueId lookup only sees devices linked to the user; checked against a real server, so the fallback lists them all."""
    import httpx

    from app.traccar import RestTraccar

    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/api/devices":
            return httpx.Response(200, json=[] if "uniqueId" in request.url.params else [{"id": 7, "uniqueId": IMEI}, {"id": 8, "uniqueId": "other"}])
        return httpx.Response(202, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr("app.traccar.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "traccar_url", "http://traccar.test")
    monkeypatch.setattr(settings, "traccar_token", "placeholder")
    await RestTraccar().send_command(IMEI, "engineStop")
    assert seen[-1][:2] == ("POST", "/api/commands/send") and [c[1] for c in seen] == ["/api/devices", "/api/devices", "/api/commands/send"]
    with pytest.raises(Exception, match="does not know"):
        await RestTraccar().send_command("123456789", "engineStop")


# ---- tamper alerts (acceptance) ------------------------------------------------------------------------------------------


async def test_a_simulated_power_cut_raises_a_red_alert_and_texts_the_owner_at_once(client):
    f = await tracked(client)
    await post(client, position(IMEI, ago(seconds=60), -1.2921, 36.8219))
    res = await post(client, power_cut(IMEI, ago(seconds=1))[0])
    assert res.json()["position"]["alarms"] == ["power_cut"]
    [alert] = await alerts_of(client, f.owner, "open")
    assert alert["kind"] == "power_cut" and alert["severity"] == "red" and alert["registration"] == "KCA 123A" and alert["notified"] == 1
    [text] = sms_to_owner()
    assert "KCA 123A" in text and "lost power" in text
    dash = (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"]
    assert any(a["kind"] == "tracker_power_cut" and a["severity"] == "red" and "KCA 123A" in a["title"] for a in dash)
    [t] = (await client.get("/trackers", headers=bearer(f.owner))).json()
    assert t["power_ok"] is False
    # the same fault reported again is the same alert
    await post(client, power_cut(IMEI, ago(seconds=0))[0])
    assert len(await alerts_of(client, f.owner)) == 1 and len(sms_to_owner()) == 1
    assert "tracker_alert.power_cut" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_power_coming_back_closes_the_alert_and_a_cut_tracker_lowers_the_vehicles_trust(client):
    f = await tracked(client)
    before = next(v for v in (await client.get("/vehicles", headers=bearer(f.owner))).json() if v["id"] == f.vehicle["id"])
    await post(client, power_cut(IMEI, ago(seconds=30))[0])
    after = next(v for v in (await client.get("/vehicles", headers=bearer(f.owner))).json() if v["id"] == f.vehicle["id"])
    assert before["trust_level"] == "medium" and after["trust_level"] == "low"
    shown = (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["trust"]
    assert shown["level"] == "low" and shown["flags"][0]["flag"] == "tracker_power_cut"
    await post(client, position(IMEI, ago(seconds=2), -1.2921, 36.8219, alarm="powerRestored", ignition=True))
    [alert] = await alerts_of(client, f.owner)
    assert alert["status"] == "resolved"
    assert (await client.get("/trackers", headers=bearer(f.owner))).json()[0]["power_ok"] is True


async def test_jamming_and_other_tamper_alarms_alert_too(client):
    f = await tracked(client)
    assert (await post(client, jamming(IMEI, ago(seconds=3))[0])).json()["position"]["alarms"] == ["gps_jamming"]
    assert (await post(client, position(IMEI, ago(seconds=2), -1.0, 36.0, alarm="tampering"))).json()["position"]["alarms"] == ["tamper"]
    assert (await post(client, position(IMEI, ago(seconds=1), -1.0, 36.0, alarm="lowBattery"))).json()["position"]["alarms"] == ["low_battery"]
    kinds = {a["kind"]: a["severity"] for a in await alerts_of(client, f.owner)}
    assert kinds == {"gps_jamming": "red", "tamper": "red", "low_battery": "amber"}
    assert len(sms_to_owner()) == 3


async def test_an_alert_is_explained_or_confirmed_with_a_note_by_those_who_may(client):
    f = await tracked(client)
    await post(client, power_cut(IMEI, ago(seconds=5))[0])
    [alert] = await alerts_of(client, f.owner)
    handle = lambda who, **kw: client.post(f"/tracker/alerts/{alert['id']}/handle", headers=bearer(who), json={"note": "The mechanic unplugged it for a repair", **kw})
    assert (await handle(f.driver)).status_code == 403
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    ok = await handle(manager)
    assert ok.status_code == 200 and ok.json()["status"] == "explained" and ok.json()["handled_at"]
    assert (await client.post(f"/tracker/alerts/{alert['id']}/handle", headers=bearer(f.owner), json={"note": "x"})).status_code == 422
    confirmed = await client.post(f"/tracker/alerts/{alert['id']}/handle", headers=bearer(f.owner), json={"note": "It was a theft attempt", "outcome": "confirmed"})
    assert confirmed.json()["status"] == "confirmed"
    assert {"tracker_alert.explained", "tracker_alert.confirmed"} <= {e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()}
    assert (await alerts_of(client, f.owner, "open")) == []


async def test_a_tracker_that_goes_offline_alerts_and_closes_when_it_is_back(client):
    f = await tracked(client)
    await post(client, position(IMEI, ago(seconds=30), -1.2921, 36.8219))
    assert (await post(client, offline(IMEI, ago(seconds=1))[0])).json()["event"]["events"] == ["device_offline"]
    [alert] = await alerts_of(client, f.owner, "open")
    assert alert["kind"] == "device_offline" and alert["severity"] == "amber"
    assert (await client.get("/trackers", headers=bearer(f.owner))).json()[0]["online_state"] == "offline"
    await post(client, event(IMEI, "deviceOnline", ago(seconds=0)))
    assert (await alerts_of(client, f.owner, "open")) == []
    assert (await client.get("/trackers", headers=bearer(f.owner))).json()[0]["online_state"] == "online"


async def test_the_watcher_finds_a_tracker_gone_quiet_once_and_it_is_red_on_a_trip(client):
    f = await tracked(client)
    await post(client, position(IMEI, ago(seconds=30), -1.2921, 36.8219))

    async def go(db, now=None):
        return await watch_devices(db, now)

    soon = datetime.now(UTC) + timedelta(minutes=settings.tracker_offline_minutes - 5)
    late = datetime.now(UTC) + timedelta(minutes=settings.tracker_offline_minutes + 5)
    assert await in_db(lambda db: go(db, soon)) == 0
    assert await in_db(lambda db: go(db, late)) == 1
    assert await in_db(lambda db: go(db, late + timedelta(hours=1))) == 0  # once
    [alert] = await alerts_of(client, f.owner, "open")
    assert alert["kind"] == "device_offline" and alert["details"]["quiet_minutes"] >= settings.tracker_offline_minutes and any("has not reported" in m for m in sms_to_owner())


# ---- driving behaviour ---------------------------------------------------------------------------------------------------


async def test_a_simulated_trip_produces_speeding_a_hard_stop_and_idling_with_the_driver(client):
    f = await tracked(client)
    for body in trip(IMEI, ago(minutes=20)):
        assert (await post(client, body)).status_code == 200
    events = (await client.get("/behaviour/events", headers=bearer(f.owner))).json()
    kinds = {e["kind"]: e for e in events}
    assert {"speeding", "harsh_braking", "idling"} <= set(kinds)
    assert kinds["speeding"]["value"] >= 95 and kinds["speeding"]["limit"] == 80 and kinds["speeding"]["ended_at"]
    assert kinds["idling"]["value"] >= 10 and kinds["harsh_braking"]["value"] >= 9
    assert all(e["registration"] == "KCA 123A" and e["driver"] == "driver user" and e["source"] == "tracker" for e in events)
    summary = (await client.get("/behaviour/summary", headers=bearer(f.owner))).json()
    assert summary["vehicles"][0]["counts"]["speeding"] == 1 and summary["drivers"][0]["name"] == "driver user" and summary["drivers"][0]["total"] == len(events)
    only = (await client.get(f"/behaviour/events?kind=idling&vehicle_id={f.vehicle['id']}", headers=bearer(f.owner))).json()
    assert [e["kind"] for e in only] == ["idling"]
    supervisor, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    assert (await client.get("/behaviour/events", headers=bearer(supervisor))).status_code == 200
    assert (await client.get("/behaviour/events", headers=bearer(f.driver))).status_code == 403


async def test_a_device_alarm_and_our_own_reading_of_the_same_hard_stop_count_once(client):
    f = await tracked(client)
    t = ago(minutes=5)
    await post(client, position(IMEI, t, -1.0, 36.0, speed_kmh=60))
    await post(client, position(IMEI, t + timedelta(seconds=2), -1.0, 36.0, speed_kmh=20, alarm="hardBraking"))
    events = [e for e in (await client.get("/behaviour/events", headers=bearer(f.owner))).json() if e["kind"] == "harsh_braking"]
    assert len(events) == 1


async def test_the_phones_fixes_are_scored_when_there_is_no_tracker_and_not_twice_when_there_is(client):
    f = await fleet(client)  # no tracker
    trip_ = await running(client, f)
    base = datetime.fromisoformat(trip_["started_at"])
    fixes = [{"recorded_at": (base + timedelta(seconds=i * 10)).isoformat(), "lat": -1.0 + i * 0.002, "lng": 36.0, "speed_kmh": 95, "accuracy_m": 5} for i in range(6)]
    fixes.append({"recorded_at": (base + timedelta(seconds=60)).isoformat(), "lat": -0.99, "lng": 36.0, "speed_kmh": 50, "accuracy_m": 5})
    assert (await send(client, f.driver, trip_, fixes)).json()["accepted"] == 7
    [e] = [e for e in (await client.get("/behaviour/events", headers=bearer(f.owner))).json() if e["kind"] == "speeding"]
    assert e["source"] == "phone" and e["value"] == 95
    # with a tracker reporting, the phone is not scored as well
    await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": IMEI})
    await post(client, position(IMEI, ago(seconds=5), -1.0, 36.0, speed_kmh=40))
    more = [{"recorded_at": (base + timedelta(seconds=300 + i * 10)).isoformat(), "lat": -0.5 + i * 0.002, "lng": 36.0, "speed_kmh": 99, "accuracy_m": 5} for i in range(6)]
    more.append({"recorded_at": (base + timedelta(seconds=360)).isoformat(), "lat": -0.49, "lng": 36.0, "speed_kmh": 50, "accuracy_m": 5})
    await send(client, f.driver, trip_, more)
    speeding = [e for e in (await client.get("/behaviour/events", headers=bearer(f.owner))).json() if e["kind"] == "speeding"]
    assert len(speeding) == 1


# ---- mapped areas --------------------------------------------------------------------------------------------------------


def circle(**kw):
    return {"name": "Mombasa Yard", "kind": "depot", "shape": {"type": "circle", "lat": -1.2921, "lng": 36.8219, "radius_m": 300}, "alert_on": ["enter", "exit"], **kw}


async def test_a_geofence_notices_a_vehicle_entering_and_leaving_once_each(client):
    f = await tracked(client)
    made = await client.post("/geofences", headers=bearer(f.owner), json=circle())
    assert made.status_code == 201, made.text
    inside, outside = (-1.2921, 36.8219), (-1.3200, 36.8219)
    t0 = ago(minutes=10)
    for n, (lat, lng) in enumerate([outside, outside, inside, inside, inside, outside, outside, outside]):
        await post(client, position(IMEI, t0 + timedelta(seconds=n * 30), lat, lng, speed_kmh=30))
    events = (await client.get("/geofences/events", headers=bearer(f.owner))).json()
    assert [e["kind"] for e in reversed(events)] == ["enter", "exit"] and events[0]["geofence"] == "Mombasa Yard" and events[0]["registration"] == "KCA 123A"
    names = {a["kind"] + ":" + a["details"]["event"] for a in await alerts_of(client, f.owner)}
    assert names == {"geofence:enter", "geofence:exit"}
    assert sms_to_owner() == []  # a depot is not worth a text


async def test_a_restricted_area_texts_the_owner_when_a_lorry_goes_in(client):
    f = await tracked(client)
    await client.post("/geofences", headers=bearer(f.owner), json=circle(name="Do not enter", kind="restricted", alert_on=["enter"]))
    t0 = ago(minutes=5)
    for n, (lat, lng) in enumerate([(-1.3200, 36.8219), (-1.3200, 36.8219), (-1.2921, 36.8219), (-1.2921, 36.8219)]):
        await post(client, position(IMEI, t0 + timedelta(seconds=n * 30), lat, lng, speed_kmh=30))
    [alert] = [a for a in await alerts_of(client, f.owner) if a["kind"] == "geofence"]
    assert alert["severity"] == "red" and any("Do not enter" in m for m in sms_to_owner())


async def test_a_geofence_can_be_a_polygon_limited_to_some_vehicles_and_is_checked_on_entry(client):
    f = await tracked(client)
    other = await add_vehicle(client, f.owner, "KCB 222B")
    poly = {"name": "Quarry", "kind": "client_site", "shape": {"type": "polygon", "points": [[-1.0, 36.0], [-1.0, 36.1], [-1.1, 36.1], [-1.1, 36.0]]}, "alert_on": ["enter"], "vehicle_ids": [other["id"]]}
    assert (await client.post("/geofences", headers=bearer(f.owner), json=poly)).status_code == 201
    for n, lat in enumerate([-1.2, -1.2, -1.05, -1.05]):
        await post(client, position(IMEI, ago(minutes=5) + timedelta(seconds=n * 30), lat, 36.05, speed_kmh=30))
    assert (await client.get("/geofences/events", headers=bearer(f.owner))).json() == []  # not this vehicle's area
    bad = [
        {**poly, "shape": {"type": "polygon", "points": [[0, 0], [1, 1]]}},
        {**poly, "shape": {"type": "circle", "lat": 0, "lng": 0, "radius_m": 5}},
        {**poly, "shape": {"type": "polygon", "points": [[91, 0], [0, 1], [1, 1]]}},
        {**poly, "vehicle_ids": [str(uuid.uuid4())]},
        {**poly, "kind": "castle"},
    ]
    for body in bad:
        assert (await client.post("/geofences", headers=bearer(f.owner), json=body)).status_code == 422
    assert (await client.post("/geofences", headers=bearer(f.owner), json=poly)).status_code == 409  # the name is taken


async def test_geofences_are_managed_by_owner_and_manager_and_seen_by_the_map_roles(client):
    f = await tracked(client)
    g = (await client.post("/geofences", headers=bearer(f.owner), json=circle())).json()
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.put(f"/geofences/{g['id']}", headers=bearer(manager), json=circle(alert_on=["enter"]))).json()["alert_on"] == ["enter"]
    supervisor, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    assert len((await client.get("/geofences", headers=bearer(supervisor))).json()) == 1
    assert (await client.post("/geofences", headers=bearer(supervisor), json=circle(name="Other"))).status_code == 403
    assert (await client.delete(f"/geofences/{g['id']}", headers=bearer(supervisor))).status_code == 403
    assert (await client.delete(f"/geofences/{g['id']}", headers=bearer(manager))).status_code == 204
    assert (await client.get("/geofences", headers=bearer(f.owner))).json() == []
    assert {"geofence.added", "geofence.updated", "geofence.deleted"} <= {e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()}
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/geofences", headers=bearer(other))).json() == []


# ---- three-way distance --------------------------------------------------------------------------------------------------


async def earlier(trip_, hours):
    """Move a running trip's start back, so a long drive fits between then and now."""
    started = datetime.fromisoformat(trip_["started_at"]) - timedelta(hours=hours)

    async def move(db):
        await db.execute(update(Trip).where(Trip.id == uuid.UUID(trip_["id"])).values(started_at=started))

    await in_db(move)
    return {**trip_, "started_at": started.isoformat()}


def drive_at(trip_, i, gap):  # a second after the trip began, as the simulator stamps to the millisecond
    return datetime.fromisoformat(trip_["started_at"]) + timedelta(seconds=1 + i * gap)


def drive_fixes(trip_, n=11, step=0.01, gap=60):
    return [{"recorded_at": drive_at(trip_, i, gap).isoformat(), "lat": -1.0 + i * step, "lng": 36.0, "speed_kmh": 60, "accuracy_m": 5} for i in range(n)]


async def tracker_drive(trip_, n=11, step=0.01, gap=60):
    return [position(IMEI, drive_at(trip_, i, gap), -1.0 + i * step, 36.0, speed_kmh=60) for i in range(n)]


async def test_the_odometer_the_phone_and_the_tracker_agree_or_one_is_named(client):
    f = await tracked(client)
    trip_ = await running(client, f)
    await send(client, f.driver, trip_, drive_fixes(trip_))
    for body in await tracker_drive(trip_):
        await post(client, body)
    await finish_trip(client, f, trip_, end=125111)  # 11 km on the odometer, 11.1 on both GPS sources
    done = (await client.get(f"/trips/{trip_['id']}", headers=bearer(f.owner))).json()
    assert done["distance_check"] == "ok" and abs(done["tracker_distance_km"] - 11.119) < 0.01 and abs(done["gps_distance_km"] - 11.119) < 0.01
    assert done["distance_detail"]["suspect"] is None and set(done["distance_detail"]["sources"]) == {"odometer", "phone", "tracker"}
    assert done["trust"]["tier"] == "standard"


async def test_a_wound_back_odometer_is_named_when_the_phone_and_the_tracker_agree(client):
    f = await tracked(client)
    trip_ = await earlier(await running(client, f), 3)
    await send(client, f.driver, trip_, drive_fixes(trip_, n=21, step=0.05, gap=300))  # about 111 km by both, at 66 km/h
    for body in await tracker_drive(trip_, n=21, step=0.05, gap=300):
        await post(client, body)
    await finish_trip(client, f, trip_, end=125110 + 40)  # the odometer claims 40
    done = (await client.get(f"/trips/{trip_['id']}", headers=bearer(f.owner))).json()
    assert done["distance_check"] == "mismatch" and done["distance_detail"]["suspect"] == "odometer"
    alert = next(a for a in (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"] if a["kind"] == "distance_mismatch")
    assert "odometer looks wrong" in alert["detail"] and "odometer says 50 km but the GPS says 111 km" in alert["title"]


async def test_late_tracker_points_for_an_ended_trip_are_found_by_time(client):
    f = await tracked(client)
    trip_ = await running(client, f)
    await finish_trip(client, f, trip_, end=125111)
    assert (await client.get(f"/trips/{trip_['id']}", headers=bearer(f.owner))).json()["tracker_distance_km"] is None
    # the tracker was offline and hands in its fixes later: they belong to the trip by when they were taken
    base = datetime.fromisoformat(trip_["started_at"])
    ended = datetime.fromisoformat((await client.get(f"/trips/{trip_['id']}", headers=bearer(f.owner))).json()["ended_at"])
    span = (ended - base).total_seconds()
    assert span > 1000
    for i in range(11):
        await post(client, position(IMEI, base + timedelta(seconds=1 + span * i / 12), -1.0 + i * 0.01, 36.0, speed_kmh=60))
    point = (await client.get(f"/trips/{trip_['id']}/replay", headers=bearer(f.owner))).json()
    assert point["source"] == "tracker" and point["fixes"] == 11


# ---- replay --------------------------------------------------------------------------------------------------------------


async def test_a_trips_replay_shows_the_path_with_its_events_marked(client):
    f = await tracked(client)
    trip_ = await running(client, f)
    await client.post("/geofences", headers=bearer(f.owner), json=circle(name="Start", kind="depot", shape={"type": "circle", "lat": -4.0435, "lng": 39.6682, "radius_m": 200}))
    for body in trip(IMEI, datetime.fromisoformat(trip_["started_at"])):
        await post(client, body)
    await post(client, power_cut(IMEI, datetime.fromisoformat(trip_["started_at"]) + timedelta(minutes=15))[0])
    await finish_trip(client, f, trip_, end=125111)
    r = (await client.get(f"/trips/{trip_['id']}/replay", headers=bearer(f.owner))).json()
    assert r["source"] == "tracker" and r["fixes"] > 80 and len(r["points"]) == r["fixes"] and r["points"][0]["lat"] < r["points"][-1]["lat"]
    kinds = [e["kind"] for e in r["events"]]
    assert {"speeding", "harsh_braking", "idling", "power_cut", "geofence_exit"} <= set(kinds)
    assert [e["at"] for e in r["events"]] == sorted(e["at"] for e in r["events"])
    assert next(e for e in r["events"] if e["kind"] == "power_cut")["group"] == "alert"
    assert next(e for e in r["events"] if e["kind"] == "harsh_braking")["label"] == "Harsh braking"
    window = (await client.get(f"/vehicles/{f.vehicle['id']}/replay", params={"start": trip_["started_at"], "end": datetime.now(UTC).isoformat()}, headers=bearer(f.owner))).json()
    assert window["fixes"] == r["fixes"]


async def test_replay_checks_the_range_and_the_callers_scope(client):
    f = await tracked(client)
    now = datetime.now(UTC)
    url = f"/vehicles/{f.vehicle['id']}/replay"

    def window(start, end, who=f.owner):
        return client.get(url, params={"start": start.isoformat(), "end": end.isoformat()}, headers=bearer(who))

    assert (await window(now, now - timedelta(hours=1))).json()["detail"]["code"] == "bad_range"
    assert (await window(now - timedelta(days=5), now)).json()["detail"]["code"] == "range_too_long"
    assert (await window(now - timedelta(hours=1), now, f.driver)).status_code == 403
    scheduled = (await client.post("/trips", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "origin": "A", "destination": "B"})).json()
    assert (await client.get(f"/trips/{scheduled['id']}/replay", headers=bearer(f.owner))).json()["detail"]["code"] == "not_started"
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await window(now - timedelta(hours=1), now, other)).status_code == 404


# ---- the immobiliser (acceptance) ----------------------------------------------------------------------------------------


async def standing(client, seconds_ago=10, speed=0.0):
    await post(client, position(IMEI, ago(seconds=seconds_ago), -1.2921, 36.8219, speed_kmh=speed, ignition=False))


async def ask(client, f, action="immobilise", reason="Theft: the lorry is parked at the wrong place"):
    return await client.post(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner), json={"action": action, "reason": reason})


async def test_the_immobiliser_refuses_to_act_on_a_moving_vehicle(client):
    f = await tracked(client)
    await standing(client, speed=72)
    res = await ask(client, f)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "moving" and "moving" in res.json()["detail"]["message"]
    assert fake_traccar().commands == []
    state = (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))).json()
    assert state["can_immobilise"] is False and state["reason"] == "moving" and state["history"][0]["status"] == "refused" and state["history"][0]["speed_kmh"] > 70
    assert "immobiliser.refused" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_it_refuses_when_the_position_is_old_the_tracker_is_offline_or_cannot_do_it(client):
    f = await tracked(client)
    await standing(client, seconds_ago=400)
    assert (await ask(client, f)).json()["detail"]["code"] == "stale_position"
    await standing(client, seconds_ago=5)
    await post(client, offline(IMEI, ago(seconds=1))[0])
    assert (await ask(client, f)).json()["detail"]["code"] == "offline"
    g = await tracked_other_vehicle(client, f)
    assert (await client.post(f"/vehicles/{g['id']}/immobiliser", headers=bearer(f.owner), json={"action": "immobilise", "reason": "test reason"})).json()["detail"]["code"] == "unsupported"
    third = await add_vehicle(client, f.owner, "KCC 333C")
    assert (await client.post(f"/vehicles/{third['id']}/immobiliser", headers=bearer(f.owner), json={"action": "immobilise", "reason": "test reason"})).json()["detail"]["code"] == "no_tracker"
    assert fake_traccar().commands == []


async def tracked_other_vehicle(client, f):
    v = await add_vehicle(client, f.owner, "KCB 222B")
    assert (await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": v["id"], "imei": "444444444444444", "supports_immobiliser": False})).status_code == 201
    await post(client, position("444444444444444", ago(seconds=5), -1.0, 36.0, speed_kmh=0))
    return v


async def test_stopping_an_engine_takes_a_request_then_the_registration_and_the_owners_password(client):
    f = await tracked(client)
    await standing(client)
    asked = await ask(client, f)
    assert asked.status_code == 201 and asked.json()["status"] == "awaiting_confirmation" and asked.json()["registration"] == "KCA 123A"
    assert fake_traccar().commands == []  # nothing is sent by the first step
    cid = asked.json()["id"]
    confirm = lambda **kw: client.post(f"/immobiliser/{cid}/confirm", headers=bearer(f.owner), json={"registration": "KCA 123A", "password": PASSWORD, **kw})
    assert (await confirm(registration="KCB 999Z")).json()["detail"]["code"] == "wrong_registration"
    assert (await confirm(password="not the password")).json()["detail"]["code"] == "wrong_password"
    assert fake_traccar().commands == []
    done = await confirm(registration="kca123a")  # spacing and case do not matter
    assert done.status_code == 200 and done.json()["status"] == "sent" and done.json()["sent_at"]
    assert fake_traccar().commands == [(IMEI, "engineStop")]
    assert (await confirm()).json()["detail"]["code"] == "not_waiting"
    # the tracker answers; the vehicle shows as immobilised
    await post(client, event(IMEI, "commandResult", ago(seconds=0), result="Engine stopped"))
    state = (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))).json()
    assert state["immobilised"] is True and state["history"][0]["status"] == "acknowledged" and state["history"][0]["result_note"] == "Engine stopped"
    assert (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["tracker"]["immobilised"] is True
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert {"immobiliser.immobilise_requested", "immobiliser.wrong_password", "immobiliser.immobilise_sent"} <= set(actions)
    # and can be released, even at speed
    await post(client, position(IMEI, ago(seconds=1), -1.0, 36.0, speed_kmh=40))
    rel = await ask(client, f, action="release", reason="The police have the lorry back")
    assert rel.status_code == 201
    sent = await client.post(f"/immobiliser/{rel.json()['id']}/confirm", headers=bearer(f.owner), json={"registration": "KCA 123A", "password": PASSWORD})
    assert sent.status_code == 200 and fake_traccar().commands[-1] == (IMEI, "engineResume")


async def test_the_safety_check_is_made_again_at_confirmation_with_the_newest_position(client):
    f = await tracked(client)
    await standing(client)
    cid = (await ask(client, f)).json()["id"]
    await post(client, position(IMEI, ago(seconds=1), -1.2921, 36.8219, speed_kmh=55))  # it drove off in the meantime
    res = await client.post(f"/immobiliser/{cid}/confirm", headers=bearer(f.owner), json={"registration": "KCA 123A", "password": PASSWORD})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "moving"
    assert fake_traccar().commands == []
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))).json()["history"][0]["status"] == "refused"


async def test_a_request_expires_can_be_cancelled_and_a_traccar_failure_is_shown(client):
    f = await tracked(client)
    await standing(client)
    old = (await ask(client, f)).json()["id"]
    await in_db(lambda db: db.execute(update(ImmobiliserCommand).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))))
    expired = await client.post(f"/immobiliser/{old}/confirm", headers=bearer(f.owner), json={"registration": "KCA 123A", "password": PASSWORD})
    assert expired.status_code == 410 and expired.json()["detail"]["code"] == "expired"
    nxt = (await ask(client, f)).json()["id"]
    assert (await client.post(f"/immobiliser/{nxt}/cancel", headers=bearer(f.owner))).json()["status"] == "cancelled"
    assert (await client.post(f"/immobiliser/{nxt}/cancel", headers=bearer(f.owner))).status_code == 409
    last = (await ask(client, f)).json()["id"]
    fake_traccar().fail_with = "Traccar did not accept the command: ConnectError"
    failed = await client.post(f"/immobiliser/{last}/confirm", headers=bearer(f.owner), json={"registration": "KCA 123A", "password": PASSWORD})
    assert failed.status_code == 502 and "Traccar" in failed.json()["detail"]["message"]
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))).json()["history"][0]["status"] == "failed"
    assert "immobiliser.failed" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_only_the_owner_can_use_the_immobiliser_and_other_businesses_cannot_reach_it(client):
    f = await tracked(client)
    await standing(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    for who in (manager, f.driver):
        assert (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(who))).status_code == 403
        assert (await client.post(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(who), json={"action": "immobilise", "reason": "no reason"})).status_code == 403
    cid = (await ask(client, f)).json()["id"]
    assert (await client.post(f"/immobiliser/{cid}/confirm", headers=bearer(manager), json={"registration": "KCA 123A", "password": PASSWORD})).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(other))).status_code == 404
    assert (await client.post(f"/immobiliser/{cid}/confirm", headers=bearer(other), json={"registration": "KCA 123A", "password": PASSWORD})).status_code == 404
    assert (await client.post(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner), json={"action": "immobilise", "reason": "x"})).status_code == 422  # a reason is needed
