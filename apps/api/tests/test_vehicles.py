import pytest

from tests.fleet import add_party, add_vehicle, vehicle_body
from tests.helpers import bearer, owner_session, staff_session


async def test_owner_adds_edits_and_lists_a_vehicle(client):
    owner, _ = await owner_session(client)
    depot = (await client.post("/depots", headers=bearer(owner), json={"name": "Nairobi Yard"})).json()
    v = await add_vehicle(client, owner, "kca  123a", depot_id=depot["id"], tracking_tier="standard")
    assert v["registration"] == "KCA 123A"  # tidied to one canonical form
    assert v["tracking_tier"] == "standard" and v["gvw_limit_kg"] == 16000

    res = await client.put(
        f"/vehicles/{v['id']}", headers=bearer(owner), json=vehicle_body("KCA 123A", odometer_km=130000)
    )
    assert res.status_code == 200 and res.json()["odometer_km"] == 130000
    listed = (await client.get("/vehicles", headers=bearer(owner))).json()
    assert [x["registration"] for x in listed] == ["KCA 123A"]


async def test_duplicate_registration_is_rejected(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    res = await client.post("/vehicles", headers=bearer(owner), json=vehicle_body("kca 123a"))
    assert res.status_code == 409 and res.json()["detail"]["code"] == "duplicate_registration"


async def test_same_registration_is_allowed_in_different_businesses(client):
    a, _ = await owner_session(client, "Alpha", "a@example.com")
    b, _ = await owner_session(client, "Bravo", "b@example.com")
    await add_vehicle(client, a, "KCA 123A")
    await add_vehicle(client, b, "KCA 123A")


async def test_leased_in_needs_a_lessor_and_owned_must_not_have_one(client):
    owner, _ = await owner_session(client)
    lessor = await add_party(client, owner, "lessor")
    lender = await add_party(client, owner, "lender", "Equity Bank")

    ok = await add_vehicle(client, owner, "KCA 111A", ownership_type="leased_in", party_id=lessor["id"])
    assert ok["ownership_type"] == "leased_in" and ok["party_id"] == lessor["id"]
    await add_vehicle(client, owner, "KCA 222A", ownership_type="asset_financed", party_id=lender["id"])

    missing = await client.post("/vehicles", headers=bearer(owner), json=vehicle_body("KCA 333A", ownership_type="leased_in"))
    assert missing.json()["detail"]["code"] == "party_required"
    wrong_kind = await client.post(
        "/vehicles", headers=bearer(owner),
        json=vehicle_body("KCA 444A", ownership_type="leased_in", party_id=lender["id"]),
    )  # fmt: skip
    assert wrong_kind.json()["detail"]["code"] == "party_kind_mismatch"
    owned_with_party = await client.post(
        "/vehicles", headers=bearer(owner), json=vehicle_body("KCA 555A", party_id=lessor["id"])
    )
    assert owned_with_party.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [("capacity_tonnes", "-1"), ("tank_litres", 0), ("odometer_km", -5), ("tracking_tier", "gold"), ("registration", "A")],
)
async def test_bad_vehicle_values_are_rejected(client, field, value):
    owner, _ = await owner_session(client)
    res = await client.post("/vehicles", headers=bearer(owner), json={**vehicle_body("KCA 123A"), field: value})
    assert res.status_code == 422


async def test_vehicle_changes_are_audited(client):
    owner, _ = await owner_session(client)
    v = await add_vehicle(client, owner)
    await client.put(f"/vehicles/{v['id']}", headers=bearer(owner), json=vehicle_body(odometer_km=1))
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert "vehicle.created" in actions and "vehicle.updated" in actions


async def test_vehicles_are_isolated_between_businesses(client):
    a, _ = await owner_session(client, "Alpha", "a@example.com")
    b, _ = await owner_session(client, "Bravo", "b@example.com")
    v = await add_vehicle(client, b, "KBB 001B")
    assert (await client.get("/vehicles", headers=bearer(a))).json() == []
    assert (await client.get(f"/vehicles/{v['id']}", headers=bearer(a))).status_code == 404
    assert (await client.put(f"/vehicles/{v['id']}", headers=bearer(a), json=vehicle_body("KBB 001B"))).status_code == 404
    # A vehicle from another business cannot be used for a depot, party or crew link either.
    lessor_b = await add_party(client, b)
    res = await client.post(
        "/vehicles", headers=bearer(a), json=vehicle_body("KAA 001A", ownership_type="leased_in", party_id=lessor_b["id"])
    )
    assert res.status_code == 404


async def test_manager_can_manage_but_accountant_cannot_even_view(client):
    owner, _ = await owner_session(client)
    manager, _ = await staff_session(client, owner, "manager", "m@example.com")
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.post("/vehicles", headers=bearer(manager), json=vehicle_body())).status_code == 201
    assert (await client.get("/vehicles", headers=bearer(accountant))).status_code == 403


async def test_supervisor_sees_only_assigned_vehicles(client):
    owner, _ = await owner_session(client)
    mine = await add_vehicle(client, owner, "KCA 111A")
    other = await add_vehicle(client, owner, "KCA 222A")
    res = await client.post(
        "/users", headers=bearer(owner),
        json={"name": "Sup", "email": "sup@example.com", "roles": ["supervisor"], "vehicle_scope": [mine["id"]]},
    )  # fmt: skip
    from tests.helpers import PASSWORD, enable_2fa, login

    await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
    tokens = (await login(client, "sup@example.com")).json()
    await enable_2fa(client, tokens)

    listed = (await client.get("/vehicles", headers=bearer(tokens))).json()
    assert [v["id"] for v in listed] == [mine["id"]]
    assert (await client.get(f"/vehicles/{mine['id']}", headers=bearer(tokens))).status_code == 200
    assert (await client.get(f"/vehicles/{other['id']}", headers=bearer(tokens))).status_code == 404
    assert (await client.get(f"/vehicles/{other['id']}/crew", headers=bearer(tokens))).status_code == 404
