import pytest

from tests.helpers import bearer, driver_session, owner_session, staff_session
from tests.shots import ago, begin_trip, fleet, make_trip, my_balance, photo_id, send_float, sync


def spend(category="toll", cents=50000, **extra):
    return {"category": category, "amount_cents": cents, **extra}


async def add(client, tokens, category="toll", cents=50000, **extra):
    return await client.post("/expenses", headers=bearer(tokens), json=spend(category, cents, **extra))


async def test_driver_records_an_expense_that_comes_off_the_float_and_joins_the_trip(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    trip = await begin_trip(client, f)
    res = await add(client, f.driver, "toll", 50000, note="Mai Mahiu toll")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "recorded" and body["from_float"] is True
    assert body["vehicle_id"] == f.vehicle["id"] and body["trip_id"] == trip["id"]  # the driver's vehicle and trip, found for them
    assert body["flags"] == ["no_receipt"]
    assert await my_balance(client, f.driver) == 250000
    mine = (await client.get("/me/expenses", headers=bearer(f.driver))).json()
    assert [e["id"] for e in mine] == [body["id"]]
    assert "expense.added" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_expense_with_a_receipt_photo_or_mpesa_code_is_not_flagged(client):
    f = await fleet(client)
    receipt = await photo_id(client, f.driver, "receipt")
    with_photo = await add(client, f.driver, "parking", 20000, receipt_photo_id=receipt)
    assert with_photo.json()["flags"] == [] and with_photo.json()["has_receipt"] is True
    assert with_photo.json()["receipt"]["url"].startswith("/media/")
    with_code = await add(client, f.driver, "food", 30000, mpesa_code="abc7xyz999")
    assert with_code.json()["flags"] == [] and with_code.json()["mpesa_code"] == "ABC7XYZ999"


async def test_drivers_record_trip_expenses_and_the_office_records_the_rest(client):
    f = await fleet(client)
    denied = await add(client, f.driver, "repair", 500000)
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "category_not_allowed"
    assert (await add(client, f.driver, "other", 10000)).status_code == 201

    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    repair = await add(client, manager, "repair", 500000, vehicle_id=f.vehicle["id"])
    assert repair.status_code == 201 and repair.json()["from_float"] is False  # paid by the business, not from a float
    no_vehicle = await add(client, manager, "repair", 500000)
    assert no_vehicle.json()["detail"]["code"] == "vehicle_required"
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    overhead = await add(client, accountant, "overhead", 1200000, note="Office rent")
    assert overhead.status_code == 201 and overhead.json()["vehicle_id"] is None
    assert (await client.get("/expenses", headers=bearer(accountant))).status_code == 200
    assert (await client.get("/expenses", headers=bearer(f.driver))).status_code == 403  # drivers see their own only


async def test_a_manager_can_record_on_a_drivers_behalf_from_their_float(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    res = await add(client, manager, "toll", 40000, vehicle_id=f.vehicle["id"], driver_membership_id=f.ids["+254712345678"], from_float=True)
    assert res.status_code == 201 and res.json()["from_float"] is True
    assert await my_balance(client, f.driver) == 260000


async def test_an_expense_over_the_limit_waits_for_the_owner_and_does_not_count_until_approved(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    set_limits = await client.put("/spend-limits", headers=bearer(f.owner), json=[{"category": "toll", "limit_cents": 100000}])
    assert set_limits.status_code == 200
    ok = await add(client, f.driver, "toll", 100000)  # exactly at the limit is allowed
    assert ok.json()["status"] == "recorded"
    big = (await add(client, f.driver, "toll", 150000)).json()
    assert big["status"] == "awaiting_approval" and "over_limit" in big["flags"]
    assert await my_balance(client, f.driver) == 200000  # only the first one counts

    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    assert (await client.post(f"/expenses/{big['id']}/decision", headers=bearer(manager), json={"approve": True})).status_code == 403
    approved = await client.post(f"/expenses/{big['id']}/decision", headers=bearer(f.owner), json={"approve": True, "note": "Heavy load, extra toll"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert await my_balance(client, f.driver) == 50000  # now it counts
    again = await client.post(f"/expenses/{big['id']}/decision", headers=bearer(f.owner), json={"approve": False})
    assert again.status_code == 409
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert "expense.approved" in actions and "spend_limits.changed" in actions


async def test_a_rejected_expense_never_counts(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await client.put("/spend-limits", headers=bearer(f.owner), json=[{"limit_cents": 50000}])
    big = (await add(client, f.driver, "food", 90000)).json()
    assert big["status"] == "awaiting_approval"
    rejected = await client.post(f"/expenses/{big['id']}/decision", headers=bearer(f.owner), json={"approve": False, "note": "Not a business meal"})
    assert rejected.json()["status"] == "rejected" and rejected.json()["decision_note"] == "Not a business meal"
    assert await my_balance(client, f.driver) == 300000


async def test_the_most_specific_limit_wins_and_the_owner_is_never_held_up(client):
    f = await fleet(client)
    await client.put(
        "/spend-limits", headers=bearer(f.owner),
        json=[{"limit_cents": 50000}, {"category": "toll", "limit_cents": 200000}, {"role": "driver", "limit_cents": 30000}, {"category": "toll", "role": "driver", "limit_cents": 100000}],
    )  # fmt: skip
    assert (await add(client, f.driver, "toll", 100000)).json()["status"] == "recorded"  # toll + driver beats all the others
    assert (await add(client, f.driver, "toll", 100001)).json()["status"] == "awaiting_approval"
    assert (await add(client, f.driver, "food", 30000)).json()["status"] == "recorded"  # driver rule beats the general one
    assert (await add(client, f.driver, "food", 30001)).json()["status"] == "awaiting_approval"
    own = await add(client, f.owner, "overhead", 9_000_000, vehicle_id=None)
    assert own.json()["status"] == "recorded"  # the owner approves their own spending
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await add(client, accountant, "overhead", 60000)).json()["status"] == "awaiting_approval"  # general 50,000 applies


async def test_only_the_owner_sets_limits_and_each_rule_appears_once(client):
    f = await fleet(client)
    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    assert (await client.put("/spend-limits", headers=bearer(manager), json=[])).status_code == 403
    assert (await client.get("/spend-limits", headers=bearer(manager))).status_code == 200
    dup = await client.put("/spend-limits", headers=bearer(f.owner), json=[{"category": "toll", "limit_cents": 1000}, {"category": "toll", "limit_cents": 2000}])
    assert dup.status_code == 422 and dup.json()["detail"]["code"] == "duplicate_rule"
    assert (await client.put("/spend-limits", headers=bearer(f.owner), json=[{"limit_cents": 0}])).status_code == 422
    await client.put("/spend-limits", headers=bearer(f.owner), json=[{"limit_cents": 1000}])
    assert len((await client.get("/spend-limits", headers=bearer(f.owner))).json()) == 1
    await client.put("/spend-limits", headers=bearer(f.owner), json=[])
    assert (await client.get("/spend-limits", headers=bearer(f.owner))).json() == []


async def test_the_same_mpesa_code_cannot_be_claimed_twice_as_expense_or_fuel(client):
    f = await fleet(client)
    assert (await add(client, f.driver, "toll", 50000, mpesa_code="QGH7XYZ123")).status_code == 201
    dup = await add(client, f.driver, "parking", 20000, mpesa_code="QGH7XYZ123")
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "duplicate_mpesa_code"
    fuel = {"vehicle_id": f.vehicle["id"], "litres": "50", "price_per_litre_cents": 18500, "amount_cents": 925000, "mpesa_code": "QGH7XYZ123"}
    assert (await client.post("/fuel", headers=bearer(f.driver), json=fuel)).json()["detail"]["code"] == "duplicate_mpesa_code"
    fuel_first = {**fuel, "mpesa_code": "FUEL111111"}
    assert (await client.post("/fuel", headers=bearer(f.driver), json=fuel_first)).status_code == 201
    assert (await add(client, f.driver, "toll", 50000, mpesa_code="FUEL111111")).json()["detail"]["code"] == "duplicate_mpesa_code"
    assert (await add(client, f.driver, "toll", 50000, mpesa_code="12345")).json()["detail"]["code"] == "invalid_mpesa_code"


async def test_a_receipt_photo_cannot_be_claimed_twice(client):
    from tests.shots import jpeg, upload

    f = await fleet(client)
    data = jpeg()
    first = await upload(client, f.driver, "receipt", data=data)
    assert first.status_code == 201
    assert (await upload(client, f.driver, "receipt", data=data)).json()["detail"]["code"] == "duplicate_photo"  # the same picture again
    assert (await add(client, f.driver, "toll", 50000, receipt_photo_id=first.json()["id"])).status_code == 201
    reuse = await add(client, f.driver, "parking", 20000, receipt_photo_id=first.json()["id"])
    assert reuse.json()["detail"]["code"] == "photo_invalid"  # already backs an expense


async def test_unusual_claims_for_a_route_are_flagged(client):
    f = await fleet(client)
    route = {"origin": "Mombasa", "destination": "Nairobi", "category": "toll", "usual_cents": 50000, "tolerance_pct": 50}
    assert (await client.post("/route-costs", headers=bearer(f.owner), json=route)).status_code == 201
    await begin_trip(client, f, origin=" mombasa ", destination="NAIROBI")  # matching ignores case and spaces
    normal = (await add(client, f.driver, "toll", 75000, mpesa_code="TOLL000001")).json()
    assert normal["flags"] == []  # 50% above usual is still normal
    odd = (await add(client, f.driver, "toll", 75001, mpesa_code="TOLL000002")).json()
    assert odd["flags"] == ["unusual_for_route"] and odd["status"] == "recorded"  # flagged, not blocked
    assert (await add(client, f.driver, "parking", 900000, mpesa_code="PARK000001")).json()["flags"] == []  # no usual cost for parking
    rows = (await client.get("/route-costs", headers=bearer(f.owner))).json()
    row = rows[0]
    changed = await client.put(f"/route-costs/{row['id']}", headers=bearer(f.owner), json={**route, "usual_cents": 100000})
    assert changed.json()["usual_cents"] == 100000
    assert (await client.delete(f"/route-costs/{row['id']}", headers=bearer(f.owner))).status_code == 204
    assert (await client.get("/route-costs", headers=bearer(f.owner))).json() == []


async def test_route_costs_are_managed_by_the_office_only(client):
    f = await fleet(client)
    route = {"origin": "Nakuru", "destination": "Eldoret", "category": "toll", "usual_cents": 30000}
    assert (await client.post("/route-costs", headers=bearer(f.driver), json=route)).status_code == 403
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.post("/route-costs", headers=bearer(accountant), json=route)).status_code == 403
    assert (await client.get("/route-costs", headers=bearer(accountant))).status_code == 200


async def test_a_retried_expense_with_the_same_client_id_is_stored_once(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    body = {"client_id": "5a0c1c2e-6f0a-4a43-9d57-2f4a1c1f2222"}
    first = await add(client, f.driver, "toll", 50000, **body)
    again = await add(client, f.driver, "toll", 50000, **body)
    assert first.status_code == 201 and again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert await my_balance(client, f.driver) == 250000  # not deducted twice


async def test_expenses_work_offline_with_the_time_the_driver_spent_them(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    action = {"client_id": "6b0c1c2e-6f0a-4a43-9d57-2f4a1c1f3333", "type": "expense.add", "payload": {"category": "parking", "amount_cents": 20000, "captured_at": ago(hours=5), "client_id": "7c0c1c2e-6f0a-4a43-9d57-2f4a1c1f4444"}}
    first = (await sync(client, f.driver, [action])).json()["results"][0]
    again = (await sync(client, f.driver, [action])).json()["results"][0]
    assert first["status"] == "ok" and again["status"] == "duplicate"
    rows = (await client.get("/me/expenses", headers=bearer(f.driver))).json()
    assert len(rows) == 1 and rows[0]["amount_cents"] == 20000
    from datetime import UTC, datetime

    assert (datetime.fromisoformat(rows[0]["spent_at"]) - datetime.now(UTC)).total_seconds() < -4 * 3600  # five hours ago
    assert await my_balance(client, f.driver) == 280000


async def test_expense_validation_and_isolation(client):
    f = await fleet(client)
    for cents in (0, -5):
        assert (await add(client, f.driver, "toll", cents)).status_code == 422
    stranger = await driver_session(client, f.owner, "0733345678")
    assert (await add(client, stranger, "toll", 1000, vehicle_id=f.vehicle["id"])).json()["detail"]["code"] == "not_your_vehicle"
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    exp = (await add(client, f.driver, "toll", 50000)).json()
    assert (await client.get("/expenses", headers=bearer(other))).json() == []
    assert (await client.post(f"/expenses/{exp['id']}/decision", headers=bearer(other), json={"approve": True})).status_code == 404
    trip = await make_trip(client, f)
    other_vehicle_trip = await add(client, f.owner, "toll", 1000, vehicle_id=f.vehicle["id"], trip_id=trip["id"])
    assert other_vehicle_trip.status_code == 201


async def test_a_supervisor_sees_expenses_for_their_vehicles_only(client):
    from tests.fleet import add_vehicle
    from tests.helpers import PASSWORD, enable_2fa, login

    f = await fleet(client)
    other_vehicle = await add_vehicle(client, f.owner, "KCB 222B")
    await add(client, f.driver, "toll", 50000)
    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    await add(client, manager, "repair", 100000, vehicle_id=other_vehicle["id"])
    invite = await client.post("/users", headers=bearer(f.owner), json={"name": "Sup", "email": "sup@example.com", "roles": ["supervisor"], "vehicle_scope": [f.vehicle["id"]]})
    await client.post("/auth/accept-invite", json={"token": invite.json()["invite_token"], "password": PASSWORD})
    sup = (await login(client, "sup@example.com")).json()
    await enable_2fa(client, sup)
    seen = (await client.get("/expenses", headers=bearer(sup))).json()
    assert [e["category"] for e in seen] == ["toll"]


@pytest.mark.parametrize("field,value", [("category", "caviar"), ("amount_cents", "lots")])
async def test_bad_expense_fields_are_rejected(client, field, value):
    f = await fleet(client)
    res = await client.post("/expenses", headers=bearer(f.driver), json={**spend(), field: value})
    assert res.status_code == 422
