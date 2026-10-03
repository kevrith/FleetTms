import pytest

from tests.helpers import bearer, driver_session, owner_session, staff_session
from tests.shots import begin_trip, fleet, make_trip, photo_id


def fuel_body(f, **extra):
    return {
        "vehicle_id": f.vehicle["id"], "litres": "120.00", "price_per_litre_cents": 18500, "amount_cents": 2220000,
        "station": "Total Naivasha", "mpesa_code": "QGH7XYZ123", **extra,
    }  # fmt: skip


async def staff_ids(client, owner):
    return {r["phone"]: r["membership_id"] for r in (await client.get("/staff", headers=bearer(owner))).json() if r["phone"]}


# ---- fuel ----------------------------------------------------------------------------------------


async def test_driver_records_fuel_with_a_receipt_photo(client):
    f = await fleet(client)
    trip = await make_trip(client, f)
    receipt = await photo_id(client, f.driver, "receipt")
    res = await client.post(
        "/fuel", headers=bearer(f.driver), json=fuel_body(f, trip_id=trip["id"], receipt_photo_id=receipt)
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["has_receipt"] is True and body["flags"] == [] and body["mpesa_code"] == "QGH7XYZ123"
    listed = (await client.get("/fuel", headers=bearer(f.owner))).json()
    assert [e["id"] for e in listed] == [body["id"]]
    assert "fuel.added" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_fuel_without_a_receipt_or_with_odd_numbers_is_flagged_not_refused(client):
    f = await fleet(client)
    plain = (await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code=None))).json()
    assert plain["flags"] == ["no_receipt"]
    off = fuel_body(f, mpesa_code=None, amount_cents=3000000)  # 120 L at KES 185 is KES 22,200, not 30,000
    assert (await client.post("/fuel", headers=bearer(f.driver), json=off)).json()["flags"] == ["amount_mismatch", "no_receipt"]


async def test_fuel_rules(client):
    f = await fleet(client)
    assert (await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f))).status_code == 201
    dup = await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f))
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "duplicate_mpesa_code"
    bad_code = await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code="12345"))
    assert bad_code.json()["detail"]["code"] == "invalid_mpesa_code"
    lower = await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code="abc7xyz999"))
    assert lower.status_code == 201 and lower.json()["mpesa_code"] == "ABC7XYZ999"  # tidied to capitals
    for field, value in (("litres", "0"), ("litres", "5000"), ("amount_cents", -5), ("price_per_litre_cents", 0)):
        res = await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code=None, **{field: value}))
        assert res.status_code == 422, field


async def test_a_retried_fuel_entry_with_the_same_client_id_is_stored_once(client):
    f = await fleet(client)
    body = fuel_body(f, client_id="3f0c1c2e-6f0a-4a43-9d57-2f4a1c1f1111")
    first = await client.post("/fuel", headers=bearer(f.driver), json=body)
    again = await client.post("/fuel", headers=bearer(f.driver), json=body)
    assert first.status_code == 201 and again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert len((await client.get("/fuel", headers=bearer(f.owner))).json()) == 1


async def test_only_the_crew_or_a_manager_can_record_fuel_and_it_is_isolated(client):
    f = await fleet(client)
    stranger = await driver_session(client, f.owner, "0733345678")
    assert (await client.post("/fuel", headers=bearer(stranger), json=fuel_body(f))).json()["detail"]["code"] == "not_your_vehicle"
    assert (await client.post("/fuel", headers=bearer(f.owner), json=fuel_body(f))).status_code == 201
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/fuel", headers=bearer(other))).json() == []
    assert (await client.post("/fuel", headers=bearer(other), json=fuel_body(f, mpesa_code=None))).status_code == 404
    from tests.fleet import add_vehicle

    v2 = await add_vehicle(client, f.owner, "KCB 222B")
    wrong_trip = await make_trip(client, f)
    res = await client.post("/fuel", headers=bearer(f.owner), json={**fuel_body(f, mpesa_code=None), "vehicle_id": v2["id"], "trip_id": wrong_trip["id"]})
    assert res.json()["detail"]["code"] == "wrong_trip"


async def test_fuel_goes_on_the_trip_that_was_running_when_it_was_bought(client):
    f = await fleet(client)
    before = (await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code=None))).json()
    assert before["trip_id"] is None  # no trip running: the lorry's own cost
    trip = await begin_trip(client, f)
    during = await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code=None))
    assert during.status_code == 201 and during.json()["trip_id"] == trip["id"]
    by_the_office = await client.post("/fuel", headers=bearer(f.owner), json=fuel_body(f, mpesa_code=None))
    assert by_the_office.json()["trip_id"] == trip["id"]  # whoever types it in
    other = await make_trip(client, f)
    named = await client.post("/fuel", headers=bearer(f.owner), json=fuel_body(f, mpesa_code=None, trip_id=other["id"]))
    assert named.json()["trip_id"] == other["id"]  # a trip that is named is the one used


# ---- floats --------------------------------------------------------------------------------------


async def test_owner_sends_floats_and_the_driver_sees_the_balance(client):
    f = await fleet(client)
    driver = f.ids["+254712345678"]
    for amount, code in ((300000, "AAA1111111"), (150000, None)):
        res = await client.post(
            "/floats", headers=bearer(f.owner),
            json={"driver_membership_id": driver, "amount_cents": amount, "mpesa_code": code, "note": "Tolls to Nairobi"},
        )  # fmt: skip
        assert res.status_code == 201, res.text
    mine = (await client.get("/me/float", headers=bearer(f.driver))).json()
    assert mine["balance_cents"] == 450000 and len(mine["recent"]) == 2
    assert (await client.get("/me/float", headers=bearer(f.turnboy))).json()["balance_cents"] == 0  # not theirs
    listed = (await client.get("/floats", headers=bearer(f.owner))).json()
    assert sorted(x["amount_cents"] for x in listed) == [150000, 300000]
    assert "float.sent" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_float_rules_and_permissions(client):
    f = await fleet(client)
    driver = f.ids["+254712345678"]
    body = {"driver_membership_id": driver, "amount_cents": 100000, "mpesa_code": "BBB2222222"}
    assert (await client.post("/floats", headers=bearer(f.owner), json=body)).status_code == 201
    assert (await client.post("/floats", headers=bearer(f.owner), json=body)).json()["detail"]["code"] == "duplicate_mpesa_code"
    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    owner_id = next(r["membership_id"] for r in (await client.get("/staff", headers=bearer(f.owner))).json() if r["email"] == "owner@example.com")
    to_manager = await client.post("/floats", headers=bearer(f.owner), json={"driver_membership_id": owner_id, "amount_cents": 5000})
    assert to_manager.json()["detail"]["code"] == "wrong_recipient"  # floats go to drivers and turnboys
    assert (await client.post("/floats", headers=bearer(manager), json={"driver_membership_id": driver, "amount_cents": 5000})).status_code == 201
    assert (await client.post("/floats", headers=bearer(f.driver), json={**body, "mpesa_code": None})).status_code == 403
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.get("/floats", headers=bearer(accountant))).status_code == 200  # money access: can see
    assert (await client.post("/floats", headers=bearer(accountant), json={**body, "mpesa_code": None})).status_code == 403
    for bad in (0, -1, 200_000_000):
        assert (await client.post("/floats", headers=bearer(f.owner), json={**body, "mpesa_code": None, "amount_cents": bad})).status_code == 422


async def test_floats_are_isolated_between_businesses(client):
    f = await fleet(client)
    await client.post("/floats", headers=bearer(f.owner), json={"driver_membership_id": f.ids["+254712345678"], "amount_cents": 100000})
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/floats", headers=bearer(other))).json() == []
    res = await client.post("/floats", headers=bearer(other), json={"driver_membership_id": f.ids["+254712345678"], "amount_cents": 100})
    assert res.status_code == 422  # their driver, not yours


# ---- device integrity and vehicle trust ------------------------------------------------------------


@pytest.mark.parametrize("flag,field", [("mock_location", {"mock_location": True}), ("rooted", {"rooted": True})])
async def test_a_flagged_phone_is_recorded_and_lowers_the_vehicles_trust(client, flag, field):
    f = await fleet(client)
    vid = f.vehicle["id"]
    base = (await client.get(f"/vehicles/{vid}/trust", headers=bearer(f.owner))).json()
    assert base["level"] == "low" and base["flags"] == [] and base["tier"] == "basic"
    res = await client.post("/devices/integrity", headers=bearer(f.driver), json={"device_id": "pixel-1", "vehicle_id": vid, **field})
    assert res.status_code == 200 and res.json()["flags"] == [flag]
    trust = (await client.get(f"/vehicles/{vid}/trust", headers=bearer(f.owner))).json()
    assert [x["flag"] for x in trust["flags"]] == [flag] and trust["flags"][0]["count"] == 1
    listed = (await client.get("/vehicles", headers=bearer(f.owner))).json()
    assert listed[0]["trust_level"] == "low"
    entry = next(e for e in (await client.get("/audit", headers=bearer(f.owner))).json() if e["action"] == "device.flagged")
    assert entry["after"]["flags"] == [flag]


async def test_trust_starts_from_the_tracking_tier_and_drops_with_each_kind_of_flag(client):
    f = await fleet(client)
    vid = f.vehicle["id"]
    body = {**f.vehicle, "tracking_tier": "premium"}
    body.pop("id")
    await client.put(f"/vehicles/{vid}", headers=bearer(f.owner), json=body)
    level = lambda: client.get(f"/vehicles/{vid}/trust", headers=bearer(f.owner))
    assert (await level()).json()["level"] == "high"
    report = lambda **kw: client.post("/devices/integrity", headers=bearer(f.driver), json={"device_id": "pixel-1", "vehicle_id": vid, **kw})
    await report(mock_location=True)
    await report(mock_location=True)  # the same flag again lowers it no further
    assert (await level()).json()["level"] == "medium"
    await report(rooted=True)
    assert (await level()).json()["level"] == "low"


async def test_a_wrong_clock_is_flagged_and_a_clean_phone_leaves_no_trace(client):
    from tests.shots import ago

    f = await fleet(client)
    vid = f.vehicle["id"]
    clean = await client.post("/devices/integrity", headers=bearer(f.driver), json={"device_id": "pixel-1", "vehicle_id": vid, "device_time": ago(seconds=20)})
    assert clean.json()["flags"] == []
    skewed = await client.post("/devices/integrity", headers=bearer(f.driver), json={"device_id": "pixel-1", "vehicle_id": vid, "device_time": ago(hours=2)})
    assert skewed.json()["flags"] == ["clock_changed"]
    flags = (await client.get(f"/vehicles/{vid}/trust", headers=bearer(f.owner))).json()["flags"]
    assert [x["flag"] for x in flags] == ["clock_changed"] and flags[0]["count"] == 1  # only the bad report was kept


async def test_sync_carries_the_device_report_and_flags_are_recorded_never_blocking(client):
    from tests.shots import sync

    f = await fleet(client)
    res = await sync(client, f.driver, [], device={"device_id": "pixel-1", "mock_location": True, "vehicle_id": f.vehicle["id"]})
    assert res.status_code == 200 and res.json()["device_flags"] == ["mock_location"]
    # A flagged phone can still do its work.
    assert (await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code=None))).status_code == 201


async def test_trust_respects_vehicle_scope_and_business_isolation(client):
    f = await fleet(client)
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/trust", headers=bearer(other))).status_code == 404
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/trust", headers=bearer(f.driver))).status_code == 403
    res = await client.post("/devices/integrity", headers=bearer(other), json={"device_id": "x-1", "vehicle_id": f.vehicle["id"], "rooted": True})
    assert res.status_code == 404
