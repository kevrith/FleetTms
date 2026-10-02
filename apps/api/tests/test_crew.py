from tests.fleet import add_vehicle
from tests.helpers import bearer, driver_session, owner_session


async def setup(client):
    owner, _ = await owner_session(client)
    v1 = await add_vehicle(client, owner, "KCA 111A")
    v2 = await add_vehicle(client, owner, "KCA 222A")
    d1 = await driver_session(client, owner, "0712345678")
    d2 = await driver_session(client, owner, "0722345678")
    t1 = await driver_session(client, owner, "0733345678", role="turnboy")
    return owner, v1, v2, d1, d2, t1


async def ids(client, owner):
    rows = (await client.get("/staff", headers=bearer(owner))).json()
    by_role = {}
    for r in rows:
        if "driver" in r["roles"]:
            by_role.setdefault("drivers", []).append(r["membership_id"])
        if "turnboy" in r["roles"]:
            by_role["turnboy"] = r["membership_id"]
    return by_role


async def test_assign_driver_and_turnboy_then_driver_sees_my_vehicle(client):
    owner, v1, _, d1, _, _ = await setup(client)
    who = await ids(client, owner)
    for membership, role in ((who["drivers"][0], "driver"), (who["turnboy"], "turnboy")):
        res = await client.post(f"/vehicles/{v1['id']}/crew", headers=bearer(owner), json={"membership_id": membership, "role": role})
        assert res.status_code == 201, res.text

    card = (await client.get("/me/vehicle", headers=bearer(d1))).json()
    assert card["vehicle"]["registration"] == "KCA 111A" and card["my_role"] == "driver"
    assert sorted(c["role"] for c in card["crew"]) == ["driver", "turnboy"]


async def test_driver_with_no_vehicle_gets_nothing(client):
    _, _, _, d1, _, _ = await setup(client)
    assert (await client.get("/me/vehicle", headers=bearer(d1))).json() is None


async def test_reassigning_crew_keeps_history(client):
    owner, v1, v2, _, _, _ = await setup(client)
    first, second = (await ids(client, owner))["drivers"]
    base = lambda m: {"membership_id": m, "role": "driver"}

    await client.post(f"/vehicles/{v1['id']}/crew", headers=bearer(owner), json=base(first))
    await client.post(f"/vehicles/{v1['id']}/crew", headers=bearer(owner), json=base(second))  # replaces first
    history = (await client.get(f"/vehicles/{v1['id']}/crew", headers=bearer(owner))).json()
    assert len(history) == 2
    current = [h for h in history if h["ended_at"] is None]
    assert [h["membership_id"] for h in current] == [second]
    ended = [h for h in history if h["ended_at"] is not None]
    assert [h["membership_id"] for h in ended] == [first]

    # Moving the second driver to another vehicle closes the first vehicle's slot too.
    await client.post(f"/vehicles/{v2['id']}/crew", headers=bearer(owner), json=base(second))
    v1_history = (await client.get(f"/vehicles/{v1['id']}/crew", headers=bearer(owner))).json()
    assert all(h["ended_at"] is not None for h in v1_history) and len(v1_history) == 2
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert "crew.assigned" in actions and "crew.ended" in actions


async def test_wrong_role_unknown_person_and_double_assignment_are_rejected(client):
    owner, v1, _, _, _, _ = await setup(client)
    who = await ids(client, owner)
    wrong = await client.post(f"/vehicles/{v1['id']}/crew", headers=bearer(owner), json={"membership_id": who["turnboy"], "role": "driver"})
    assert wrong.json()["detail"]["code"] == "wrong_role"
    ghost = await client.post(
        f"/vehicles/{v1['id']}/crew", headers=bearer(owner),
        json={"membership_id": "00000000-0000-0000-0000-000000000001", "role": "driver"},
    )  # fmt: skip
    assert ghost.status_code == 404
    body = {"membership_id": who["drivers"][0], "role": "driver"}
    await client.post(f"/vehicles/{v1['id']}/crew", headers=bearer(owner), json=body)
    again = await client.post(f"/vehicles/{v1['id']}/crew", headers=bearer(owner), json=body)
    assert again.json()["detail"]["code"] == "already_assigned"


async def test_unassign_closes_the_slot(client):
    owner, v1, _, _, _, _ = await setup(client)
    who = await ids(client, owner)
    await client.post(f"/vehicles/{v1['id']}/crew", headers=bearer(owner), json={"membership_id": who["drivers"][0], "role": "driver"})
    assert (await client.delete(f"/vehicles/{v1['id']}/crew/driver", headers=bearer(owner))).status_code == 204
    assert (await client.delete(f"/vehicles/{v1['id']}/crew/driver", headers=bearer(owner))).status_code == 404
    history = (await client.get(f"/vehicles/{v1['id']}/crew", headers=bearer(owner))).json()
    assert len(history) == 1 and history[0]["ended_at"] is not None


async def test_cannot_crew_another_businesss_vehicle_or_person(client):
    owner, v1, _, _, _, _ = await setup(client)
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    who = await ids(client, owner)
    res = await client.post(f"/vehicles/{v1['id']}/crew", headers=bearer(other), json={"membership_id": who["drivers"][0], "role": "driver"})
    assert res.status_code == 404
