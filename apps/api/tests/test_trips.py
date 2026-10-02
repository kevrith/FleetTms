import pytest

from tests.helpers import PASSWORD, bearer, driver_session, enable_2fa, login, owner_session
from tests.shots import fleet, inspect, make_trip, photo_id, start, upload


async def ready_trip(client, f):
    """A scheduled trip whose vehicle passed today's inspection."""
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    return await make_trip(client, f)


async def test_manager_schedules_a_trip_for_the_vehicles_crew(client):
    f = await fleet(client)
    trip = await make_trip(client, f)
    assert trip["status"] == "scheduled" and trip["registration"] == "KCA 123A"
    assert trip["driver_membership_id"] == f.ids["+254712345678"]
    assert trip["turnboy_membership_id"] == f.ids["+254722345678"]
    listed = (await client.get("/trips", headers=bearer(f.owner))).json()
    assert [t["id"] for t in listed] == [trip["id"]]
    mine = (await client.get("/me/trips", headers=bearer(f.driver))).json()
    assert [t["id"] for t in mine] == [trip["id"]]
    assert (await client.get("/trips", headers=bearer(f.driver))).status_code == 403  # drivers see their own only
    assert (await client.post("/trips", headers=bearer(f.driver), json={"vehicle_id": f.vehicle["id"]})).status_code == 403


async def test_a_trip_needs_a_driver(client):
    from tests.fleet import add_vehicle

    owner, _ = await owner_session(client)
    v = await add_vehicle(client, owner, "KDD 111D")
    res = await client.post("/trips", headers=bearer(owner), json={"vehicle_id": v["id"]})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "no_driver"


async def test_trip_cannot_start_without_a_passed_inspection(client):
    f = await fleet(client)
    trip = await make_trip(client, f)
    res = await start(client, f.driver, trip["id"])
    assert res.status_code == 409 and res.json()["detail"]["code"] == "inspection_required"
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["status"] == "scheduled"


async def test_failed_brake_check_blocks_the_trip_until_a_manager_overrides_it(client):
    f = await fleet(client)
    inspection = (await inspect(client, f.driver, f.vehicle["id"], {"Brakes": "Pedal goes to the floor"})).json()
    trip = await make_trip(client, f)
    blocked = await start(client, f.driver, trip["id"])
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "inspection_blocked"

    await client.post(f"/inspections/{inspection['id']}/override", headers=bearer(f.owner), json={"reason": "Brakes bled and tested"})
    ok = await start(client, f.driver, trip["id"])
    assert ok.status_code == 200 and ok.json()["inspection"]["status"] == "overridden"
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert "inspection.overridden" in actions and "trip.started" in actions


async def test_trip_cannot_start_without_an_odometer_photo(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    url = f"/trips/{trip['id']}/start"
    assert (await client.post(url, headers=bearer(f.driver), json={"value": 125100})).status_code == 422
    wrong_kind = await photo_id(client, f.driver, "cargo")
    res = await client.post(url, headers=bearer(f.driver), json={"photo_id": wrong_kind, "value": 125100})
    assert res.json()["detail"]["code"] == "photo_invalid"
    ghost = await client.post(url, headers=bearer(f.driver), json={"photo_id": "00000000-0000-0000-0000-000000000001", "value": 125100})
    assert ghost.json()["detail"]["code"] == "photo_invalid"
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["status"] == "scheduled"


async def test_full_trip_from_inspection_to_completion(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)

    started = await start(client, f.driver, trip["id"], value=125100, auto_read_value=125100)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "in_progress" and body["start_reading"]["value"] == 125100
    assert body["start_reading"]["flags"] == []
    assert body["start_reading"]["photo"]["url"].startswith("/media/")
    assert (await client.get("/vehicles/" + f.vehicle["id"], headers=bearer(f.owner))).json()["odometer_km"] == 125100

    loading = await client.post(
        f"/trips/{trip['id']}/loading", headers=bearer(f.driver),
        json={"photo_id": await photo_id(client, f.driver, "cargo"), "loaded_weight_kg": 9800},
    )  # fmt: skip
    assert loading.status_code == 200 and loading.json()["loaded_weight_kg"] == 9800 and loading.json()["cargo_photo"]

    assert (await client.post(f"/trips/{trip['id']}/deliver", headers=bearer(f.driver))).json()["status"] == "delivered"
    end = await client.post(
        f"/trips/{trip['id']}/end", headers=bearer(f.driver),
        json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125580, "auto_read_value": 125580},
    )  # fmt: skip
    done = end.json()
    assert end.status_code == 200 and done["status"] == "completed" and done["distance_km"] == 480
    assert done["end_reading"]["value"] == 125580
    assert (await client.get("/vehicles/" + f.vehicle["id"], headers=bearer(f.owner))).json()["odometer_km"] == 125580
    assert (await client.get("/me/trips", headers=bearer(f.driver))).json() == []  # closed trips leave "my trips"

    # Both odometer photos can be opened through their links.
    for reading in (done["start_reading"], done["end_reading"]):
        assert (await client.get(reading["photo"]["url"])).status_code == 200
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert {"trip.created", "trip.started", "trip.loaded", "trip.delivered", "trip.completed"} <= set(actions)


async def test_a_start_reading_below_the_vehicles_last_reading_is_refused_and_the_photo_is_kept(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    pid = await photo_id(client, f.driver, "odometer")
    low = await client.post(f"/trips/{trip['id']}/start", headers=bearer(f.driver), json={"photo_id": pid, "value": 124000})
    assert low.status_code == 422 and low.json()["detail"]["code"] == "odometer_backward" and "125,000" in low.json()["detail"]["message"]
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.driver))).json()["status"] == "scheduled"
    same = await client.post(f"/trips/{trip['id']}/start", headers=bearer(f.driver), json={"photo_id": pid, "value": 125000})
    assert same.status_code == 200  # the same number as last time is fine, and the same photo can be used again
    assert (await client.get("/vehicles/" + f.vehicle["id"], headers=bearer(f.owner))).json()["odometer_km"] == 125000


async def test_the_next_trip_starts_where_the_last_one_ended_and_cannot_start_lower(client):
    f = await fleet(client)
    first = await ready_trip(client, f)
    await start(client, f.driver, first["id"], value=125100)
    end = await client.post(f"/trips/{first['id']}/end", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125580})
    assert end.status_code == 200
    assert (await client.get("/me/vehicle", headers=bearer(f.driver))).json()["vehicle"]["odometer_km"] == 125580  # what the phone starts from
    second = await make_trip(client, f)
    below = await start(client, f.driver, second["id"], value=125100)  # the old start reading
    assert below.status_code == 422 and below.json()["detail"]["code"] == "odometer_backward"
    assert (await start(client, f.driver, second["id"], value=125580)).status_code == 200


async def test_odometer_flags_for_mismatched_and_jumping_readings(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    res = await start(client, f.driver, trip["id"], value=125000, auto_read_value=125900)
    assert res.json()["start_reading"]["flags"] == ["mismatch"]

    f2 = await fleet_second_trip(client, f)
    jump = await start(client, f.driver, f2["id"], value=130000)
    assert jump.json()["start_reading"]["flags"] == ["large_jump"]


async def fleet_second_trip(client, f):
    """Closes the open trip, then schedules another on the same vehicle."""
    open_trip = (await client.get("/me/trips", headers=bearer(f.driver))).json()[0]
    pid = await photo_id(client, f.driver, "odometer")
    await client.post(f"/trips/{open_trip['id']}/end", headers=bearer(f.driver), json={"photo_id": pid, "value": 125000})
    return await make_trip(client, f)


async def test_reading_without_gps_is_flagged_not_blocked(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    pid = await photo_id(client, f.driver, "odometer", lat=None, lng=None)
    res = await start(client, f.driver, trip["id"], photo_id=pid)
    assert res.status_code == 200 and res.json()["start_reading"]["flags"] == ["no_location"]


async def test_end_reading_below_start_is_rejected_and_the_photo_is_not_wasted(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    await start(client, f.driver, trip["id"], value=125100)
    pid = await photo_id(client, f.driver, "odometer")
    low = await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": pid, "value": 125000})
    assert low.status_code == 422 and low.json()["detail"]["code"] == "odometer_backward"
    retry = await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": pid, "value": 125400})
    assert retry.status_code == 200 and retry.json()["distance_km"] == 300  # same photo, corrected number


async def test_a_photo_backs_only_one_record_and_only_its_uploader_can_use_it(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    pid = await photo_id(client, f.driver, "odometer")
    assert (await start(client, f.driver, trip["id"], photo_id=pid)).status_code == 200
    reuse = await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": pid, "value": 125500})
    assert reuse.json()["detail"]["code"] == "photo_invalid"  # already used for the start reading

    trip2 = await make_trip(client, f)
    others = await photo_id(client, f.turnboy, "odometer")
    await client.post(f"/trips/{trip['id']}/deliver", headers=bearer(f.driver))
    await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125500})
    stolen = await client.post(f"/trips/{trip2['id']}/start", headers=bearer(f.driver), json={"photo_id": others, "value": 125500})
    assert stolen.json()["detail"]["code"] == "photo_invalid"  # the turnboy's photo is not the driver's to use


async def test_trip_state_machine_and_conflicts(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    tid = trip["id"]
    assert (await client.post(f"/trips/{tid}/deliver", headers=bearer(f.driver))).status_code == 409  # not started
    assert (await start(client, f.driver, tid)).status_code == 200
    assert (await start(client, f.driver, tid)).json()["detail"]["code"] == "wrong_status"  # cannot start twice
    second = await make_trip(client, f)
    clash = await start(client, f.driver, second["id"])
    assert clash.json()["detail"]["code"] == "already_on_trip"  # one trip at a time per vehicle
    assert (await client.post(f"/trips/{tid}/cancel", headers=bearer(f.owner))).status_code == 409  # already started
    cancelled = await client.post(f"/trips/{second['id']}/cancel", headers=bearer(f.owner))
    assert cancelled.json()["status"] == "cancelled"
    # Cargo can be loaded and weighed before the lorry leaves or on the road, but not onto a cancelled trip.
    assert (await client.post(f"/trips/{second['id']}/loading", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "cargo")})).status_code == 409


async def test_only_the_trips_crew_or_a_manager_can_move_it(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    stranger = await driver_session(client, f.owner, "0733345678")
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(stranger))).status_code == 404
    assert (await start(client, stranger, trip["id"])).status_code == 404
    assert (await start(client, f.turnboy, trip["id"])).status_code == 200  # the turnboy is on the crew


async def test_manager_can_record_readings_from_the_web_with_a_fresh_camera_photo(client):
    from datetime import UTC, datetime

    from tests.shots import jpeg

    f = await fleet(client)
    trip = await ready_trip(client, f)
    web = await upload(client, f.owner, source="web", captured_at=None, data=jpeg(taken=datetime.now(UTC)))
    assert web.status_code == 201
    res = await client.post(f"/trips/{trip['id']}/start", headers=bearer(f.owner), json={"photo_id": web.json()["id"], "value": 125100})
    assert res.status_code == 200 and res.json()["start_reading"]["photo"]["source"] == "web"


async def test_trips_are_isolated_between_businesses(client):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/trips", headers=bearer(other))).json() == []
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(other))).status_code == 404
    assert (await start(client, other, trip["id"])).status_code == 404
    assert (await client.post(f"/trips/{trip['id']}/cancel", headers=bearer(other))).status_code == 404


async def test_supervisor_sees_trips_only_for_assigned_vehicles(client):
    from tests.fleet import add_vehicle

    f = await fleet(client)
    other_vehicle = await add_vehicle(client, f.owner, "KCB 222B")
    mine = await make_trip(client, f)
    d2 = await driver_session(client, f.owner, "0744345678")
    ids = {r["phone"]: r["membership_id"] for r in (await client.get("/staff", headers=bearer(f.owner))).json() if r["phone"]}
    await client.post(f"/vehicles/{other_vehicle['id']}/crew", headers=bearer(f.owner), json={"membership_id": ids["+254744345678"], "role": "driver"})
    theirs = (await client.post("/trips", headers=bearer(f.owner), json={"vehicle_id": other_vehicle["id"]})).json()
    del d2

    res = await client.post(
        "/users", headers=bearer(f.owner),
        json={"name": "Sup", "email": "sup@example.com", "roles": ["supervisor"], "vehicle_scope": [f.vehicle["id"]]},
    )  # fmt: skip
    await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
    tokens = (await login(client, "sup@example.com")).json()
    await enable_2fa(client, tokens)
    seen = [t["id"] for t in (await client.get("/trips", headers=bearer(tokens))).json()]
    assert seen == [mine["id"]]
    assert (await client.get(f"/trips/{theirs['id']}", headers=bearer(tokens))).status_code == 404


@pytest.mark.parametrize("value", [-1, 10_000_000])
async def test_absurd_odometer_values_are_rejected(client, value):
    f = await fleet(client)
    trip = await ready_trip(client, f)
    res = await start(client, f.driver, trip["id"], value=value)
    assert res.status_code == 422
