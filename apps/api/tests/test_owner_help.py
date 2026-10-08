"""A driver makes their own trip, an SOS reaches the owner's phone as a push, and an open SOS shows on the live map."""

from app import push
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.shots import fleet, make_trip

TRIP = {"origin": "Mombasa", "destination": "Nairobi", "cargo_description": "Cement, 400 bags"}
TOKEN = "ExponentPushToken[abcdefghijklmnop]"


async def test_a_driver_makes_their_own_trip_on_the_vehicle_they_are_assigned_to(client):
    f = await fleet(client)
    res = await client.post("/me/trips", headers=bearer(f.driver), json=TRIP)
    assert res.status_code == 201, res.text
    trip = res.json()
    assert trip["status"] == "scheduled" and trip["vehicle_id"] == f.vehicle["id"] and trip["origin"] == "Mombasa"
    mine = (await client.get("/me/trips", headers=bearer(f.driver))).json()
    assert [t["id"] for t in mine] == [trip["id"]]  # it is the trip the phone now shows
    again = await client.post("/me/trips", headers=bearer(f.driver), json=TRIP)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_has_trip"


async def test_a_driver_with_a_trip_from_the_office_is_not_given_a_second_one(client):
    f = await fleet(client)
    await make_trip(client, f)
    res = await client.post("/me/trips", headers=bearer(f.driver), json=TRIP)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "already_has_trip"


async def test_nobody_without_a_vehicle_can_make_a_trip(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    res = await client.post("/me/trips", headers=bearer(owner), json=TRIP)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "no_vehicle"


async def test_a_trip_needs_a_place_to_start_and_end(client):
    f = await fleet(client)
    assert (await client.post("/me/trips", headers=bearer(f.driver), json={**TRIP, "destination": ""})).status_code == 422


async def test_an_owner_who_drives_makes_their_own_trip(client):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KCA 123A")
    assert (await client.post("/onboarding/drive-myself", headers=bearer(owner), json={"vehicle_id": vehicle["id"]})).status_code == 200
    res = await client.post("/me/trips", headers=bearer(owner), json=TRIP)
    assert res.status_code == 201, res.text
    assert res.json()["vehicle_id"] == vehicle["id"]


async def test_a_push_address_is_kept_checked_and_removed(client):
    owner, _ = await owner_session(client)
    assert (await client.put("/me/push-token", headers=bearer(owner), json={"token": "not-a-token-from-the-app"})).status_code == 422
    assert (await client.put("/me/push-token", headers=bearer(owner), json={"token": TOKEN})).status_code == 204
    assert (await client.delete("/me/push-token", headers=bearer(owner))).status_code == 204


async def test_an_sos_is_pushed_to_the_owner_and_not_to_the_driver_who_pressed_it(client, monkeypatch):
    f = await fleet(client)
    sent: list[dict] = []

    async def capture(messages):
        sent.extend(messages)

    monkeypatch.setattr(push, "_post", capture)
    assert (await client.put("/me/push-token", headers=bearer(f.owner), json={"token": TOKEN})).status_code == 204
    assert (await client.put("/me/push-token", headers=bearer(f.driver), json={"token": "ExponentPushToken[driverdriverdriver]"})).status_code == 204
    res = await client.post("/sos", headers=bearer(f.driver), json={"lat": -1.29, "lng": 36.82})
    assert res.status_code == 201, res.text
    assert [m["to"] for m in sent] == [TOKEN]
    assert sent[0]["channelId"] == "sos" and sent[0]["data"]["alert_id"] == res.json()["id"] and "KCA 123A" in sent[0]["body"]


async def test_a_push_service_that_is_down_never_stops_an_sos(client, monkeypatch):
    f = await fleet(client)

    async def down(messages):
        raise RuntimeError("the push service is down")

    monkeypatch.setattr(push, "_post", down)
    await client.put("/me/push-token", headers=bearer(f.owner), json={"token": TOKEN})
    assert (await client.post("/sos", headers=bearer(f.driver), json={"lat": -1.29, "lng": 36.82})).status_code == 201


async def test_an_open_sos_shows_on_the_live_map_until_it_is_resolved(client):
    f = await fleet(client)
    before = (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"]
    assert before[0]["sos"] is None
    sos = (await client.post("/sos", headers=bearer(f.driver), json={"lat": -1.29, "lng": 36.82})).json()
    mark = (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["sos"]
    assert mark["lat"] == -1.29 and mark["lng"] == 36.82 and mark["id"] == sos["id"] and mark["status"] == "active"
    await client.post(f"/sos/{sos['id']}/resolve", headers=bearer(f.owner), json={})
    assert (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["sos"] is None


async def test_a_phone_that_changes_hands_stops_telling_the_last_person(client, monkeypatch):
    f = await fleet(client)
    sent: list[dict] = []

    async def capture(messages):
        sent.extend(messages)

    monkeypatch.setattr(push, "_post", capture)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.put("/me/push-token", headers=bearer(f.owner), json={"token": TOKEN})).status_code == 204
    assert (await client.put("/me/push-token", headers=bearer(manager), json={"token": TOKEN})).status_code == 204  # the same phone, signed in by someone else
    await client.post("/sos", headers=bearer(f.driver), json={"lat": -1.29, "lng": 36.82})
    assert [m["to"] for m in sent] == [TOKEN]  # once, for the person who has the phone now
