import uuid

from app.sms import get_sms_sender
from tests.helpers import bearer, driver_session, owner_session, staff_session
from tests.shots import fleet
from tests.test_clients import add_client, add_route


async def inbox(client, who):
    res = await client.get("/me/messages", headers=bearer(who))
    assert res.status_code == 200, res.text
    return res.json()


async def test_an_announcement_reaches_every_driver_and_each_read_is_recorded(client):
    f = await fleet(client)
    sent = await client.post("/messages", headers=bearer(f.owner), json={"body": "The weighbridge at Mlolongo is closed today. Use Athi River.", "all_drivers": True})
    assert sent.status_code == 201, sent.text
    m = sent.json()
    assert m["kind"] == "announcement" and m["recipients"] == 2 and m["read"] == 0 and m["from"]
    assert {r["name"] for r in m["receipts"]} == {"driver user", "turnboy user"} and all(r["read_at"] is None for r in m["receipts"])
    mine = await inbox(client, f.driver)
    assert mine["unread"] == 1 and mine["messages"][0]["body"].startswith("The weighbridge") and mine["messages"][0]["read_at"] is None and mine["messages"][0]["kind"] == "announcement"
    assert (await client.post(f"/me/messages/{m['id']}/read", headers=bearer(f.driver))).status_code == 204
    assert (await client.post(f"/me/messages/{m['id']}/read", headers=bearer(f.driver))).status_code == 204  # safe to repeat
    after = await inbox(client, f.driver)
    assert after["unread"] == 0 and after["messages"][0]["read_at"]
    first_read = after["messages"][0]["read_at"]
    await client.post(f"/me/messages/{m['id']}/read", headers=bearer(f.driver))
    assert (await inbox(client, f.driver))["messages"][0]["read_at"] == first_read  # the first time it was read is kept
    seen = (await client.get("/messages", headers=bearer(f.owner))).json()[0]
    assert seen["read"] == 1 and seen["recipients"] == 2 and next(r for r in seen["receipts"] if r["name"] == "driver user")["read_at"] and next(r for r in seen["receipts"] if r["name"] == "turnboy user")["read_at"] is None
    assert (await inbox(client, f.turnboy))["unread"] == 1


async def test_a_direct_message_goes_to_one_person_only(client):
    f = await fleet(client)
    sent = await client.post("/messages", headers=bearer(f.owner), json={"body": "Call me when you reach Voi.", "membership_ids": [f.ids["+254712345678"]]})
    assert sent.status_code == 201 and sent.json()["kind"] == "direct" and sent.json()["recipients"] == 1
    assert (await inbox(client, f.driver))["unread"] == 1 and (await inbox(client, f.turnboy))["unread"] == 0 and (await inbox(client, f.turnboy))["messages"] == []
    assert (await client.post(f"/me/messages/{sent.json()['id']}/read", headers=bearer(f.turnboy))).status_code == 404  # not theirs to read


async def test_a_message_can_be_about_a_job_so_the_instruction_is_on_record(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    r = await add_route(client, f.owner, c["id"])
    body = {"client_id": c["id"], "route_id": r["id"], "cargo_description": "Sugar", "weight_tonnes": "20", "trips": 1}
    job = (await client.post("/jobs", headers=bearer(f.owner), json=body)).json()
    other = (await client.post("/jobs", headers=bearer(f.owner), json=body)).json()
    sent = await client.post("/messages", headers=bearer(f.owner), json={"body": "Deliver to Gate 4, ask for Mr Otieno.", "membership_ids": [f.ids["+254712345678"]], "job_id": job["id"]})
    assert sent.status_code == 201 and sent.json()["job_id"] == job["id"]
    about = (await client.get("/messages", params={"job_id": job["id"]}, headers=bearer(f.owner))).json()
    assert [m["body"] for m in about] == ["Deliver to Gate 4, ask for Mr Otieno."]
    assert (await client.get("/messages", params={"job_id": other["id"]}, headers=bearer(f.owner))).json() == []
    assert (await inbox(client, f.driver))["messages"][0]["job_id"] == job["id"]
    assert "message.sent" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_what_may_be_sent_and_to_whom_is_checked(client):
    f = await fleet(client)
    send = lambda who, **body: client.post("/messages", headers=bearer(who), json=body)
    assert (await send(f.owner, body="", all_drivers=True)).status_code == 422
    assert (await send(f.owner, body="Hello")).status_code == 422  # to nobody
    assert (await send(f.owner, body="Hello", all_drivers=True, membership_ids=[f.ids["+254712345678"]])).status_code == 422  # to everyone and someone
    staff = (await client.get("/staff", headers=bearer(f.owner))).json()
    owner_membership = next(s["membership_id"] for s in staff if s["email"] == "owner@example.com")
    refused = await send(f.owner, body="Hello", membership_ids=[owner_membership])
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "not_a_driver"
    assert (await send(f.owner, body="Hello", membership_ids=[str(uuid.uuid4())])).json()["detail"]["code"] == "not_a_driver"
    assert (await send(f.owner, body="About a job", all_drivers=True, job_id=str(uuid.uuid4()))).status_code == 404
    assert (await send(f.owner, body="About a trip", all_drivers=True, trip_id=str(uuid.uuid4()))).status_code == 404
    assert (await send(f.driver, body="Hi", all_drivers=True)).status_code == 403
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await send(accountant, body="Hi", all_drivers=True)).status_code == 403
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await send(manager, body="From the manager", all_drivers=True)).status_code == 201
    alone, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await send(alone, body="Hello", all_drivers=True)).json()["detail"]["code"] == "nobody"


async def test_a_supervisor_can_only_message_the_drivers_on_their_own_vehicles(client):
    f = await fleet(client)
    other_vehicle = (await client.post("/vehicles", headers=bearer(f.owner), json={"registration": "KCB 222B", "fuel_type": "diesel"})).json()
    second = await driver_session(client, f.owner, "0733000111")
    staff = (await client.get("/staff", headers=bearer(f.owner))).json()
    second_id = next(s["membership_id"] for s in staff if s["phone"] == "+254733000111")
    await client.post(f"/vehicles/{other_vehicle['id']}/crew", headers=bearer(f.owner), json={"membership_id": second_id, "role": "driver"})
    res = await client.post("/users", headers=bearer(f.owner), json={"name": "Sup", "email": "sup@example.com", "roles": ["supervisor"], "vehicle_scope": [f.vehicle["id"]]})
    from tests.helpers import PASSWORD, enable_2fa, login

    await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
    sup = (await login(client, "sup@example.com")).json()
    await enable_2fa(client, sup)
    everyone = await client.post("/messages", headers=bearer(sup), json={"body": "Safe driving", "all_drivers": True})
    assert everyone.status_code == 201 and {r["name"] for r in everyone.json()["receipts"]} == {"driver user", "turnboy user"}  # theirs, not the other vehicle's driver
    assert (await inbox(client, second))["messages"] == []
    refused = await client.post("/messages", headers=bearer(sup), json={"body": "Hi", "membership_ids": [second_id]})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "not_a_driver"
    mine = (await client.get("/messages", headers=bearer(sup))).json()
    assert len(mine) == 1
    await client.post("/messages", headers=bearer(f.owner), json={"body": "From the owner", "all_drivers": True})
    assert len((await client.get("/messages", headers=bearer(sup))).json()) == 1 and len((await client.get("/messages", headers=bearer(f.owner))).json()) == 2


async def test_a_text_can_go_with_the_message_for_a_driver_not_looking_at_the_app(client):
    f = await fleet(client)
    get_sms_sender().outbox.clear()
    sent = await client.post("/messages", headers=bearer(f.owner), json={"body": "Load at Gate 4, not Gate 2.", "membership_ids": [f.ids["+254712345678"]], "also_sms": True})
    assert sent.status_code == 201 and sent.json()["receipts"][0]["sms_sent"] is True
    assert ("+254712345678", "Kamau Haulage: Load at Gate 4, not Gate 2.") in get_sms_sender().outbox
    none = await client.post("/messages", headers=bearer(f.owner), json={"body": "No text this time", "all_drivers": True})
    assert all(r["sms_sent"] is False for r in none.json()["receipts"])


async def test_businesses_do_not_see_each_others_messages_and_every_plan_can_send(client):
    f = await fleet(client)
    await client.post("/messages", headers=bearer(f.owner), json={"body": "Ours", "all_drivers": True})
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/messages", headers=bearer(other))).json() == []
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "starter"}]})
    assert (await client.post("/messages", headers=bearer(f.owner), json={"body": "Starter too", "all_drivers": True})).status_code == 201
    assert (await client.get("/me/messages")).status_code == 401

