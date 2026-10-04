"""The breach register and its 72-hour clock."""

import uuid
from datetime import UTC, datetime, timedelta

from app.sms import get_sms_sender
from tests.helpers import bearer, owner_session
from tests.test_support_and_privacy import make_platform_admin


def ago(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


async def business_id(client, tokens) -> str:
    return (await client.get("/auth/me", headers=bearer(tokens))).json()["business"]["id"]


def breach(**extra):
    return {"title": "A support laptop was stolen", "description": "A laptop that had been signed in to the platform console was stolen from a car.", "severity": "high", **extra}


async def test_a_breach_is_written_down_with_its_72_hour_deadline(client):
    admin = await make_platform_admin(client)
    res = await client.post("/platform/breaches", headers=bearer(admin), json=breach(discovered_at=ago(hours=10), people_affected=40, data_involved="Names and phone numbers of staff"))
    assert res.status_code == 201, res.text
    b = res.json()
    discovered = datetime.fromisoformat(b["discovered_at"])
    assert datetime.fromisoformat(b["odpc_deadline"]) == discovered + timedelta(hours=72)
    assert 61 < b["odpc_hours_left"] < 62.1 and b["odpc_overdue"] is False and b["status"] == "open" and b["risk_to_people"] is True
    assert [x["id"] for x in (await client.get("/platform/breaches", headers=bearer(admin))).json()] == [b["id"]]


async def test_a_breach_the_commissioner_has_not_been_told_of_in_72_hours_shows_as_overdue(client):
    admin = await make_platform_admin(client)
    late = (await client.post("/platform/breaches", headers=bearer(admin), json=breach(discovered_at=ago(hours=80)))).json()
    assert late["odpc_overdue"] is True and late["odpc_hours_left"] < 0
    assert (await client.get("/platform/overview", headers=bearer(admin))).json()["breaches_overdue"] == 1
    told = await client.post(f"/platform/breaches/{late['id']}/notify", headers=bearer(admin), json={"who": "odpc"})
    assert told.json()["odpc_overdue"] is False and told.json()["odpc_late"] is True  # told, but after the deadline: that is recorded too
    assert (await client.get("/platform/overview", headers=bearer(admin))).json()["breaches_overdue"] == 0
    on_time = (await client.post("/platform/breaches", headers=bearer(admin), json=breach(discovered_at=ago(hours=5)))).json()
    ok = (await client.post(f"/platform/breaches/{on_time['id']}/notify", headers=bearer(admin), json={"who": "odpc"})).json()
    assert ok["odpc_late"] is False and ok["odpc_notified_at"]


async def test_a_breach_that_puts_no_one_at_risk_has_no_commissioner_deadline(client):
    admin = await make_platform_admin(client)
    b = (await client.post("/platform/breaches", headers=bearer(admin), json=breach(risk_to_people=False, discovered_at=ago(hours=100)))).json()
    assert b["odpc_deadline"] is None and b["odpc_overdue"] is False and b["odpc_hours_left"] is None


async def test_the_affected_businesses_are_texted_and_it_is_written_in_their_own_audit_trail(client):
    admin = await make_platform_admin(client)
    owner_a, _ = await owner_session(client, "Alpha Haulage", "a@example.com", phone="0711111111")
    owner_b, _ = await owner_session(client, "Bravo Transporters", "b@example.com", phone="0722222222")
    a = await business_id(client, owner_a)
    b = (await client.post("/platform/breaches", headers=bearer(admin), json=breach(businesses_affected=[a]))).json()
    get_sms_sender().outbox.clear()
    message = "FleetTms found that some staff phone numbers were exposed. We are writing to you with what we know."
    res = await client.post(f"/platform/breaches/{b['id']}/notify", headers=bearer(admin), json={"who": "businesses", "message": message})
    assert res.status_code == 200 and res.json()["businesses_notified_at"]
    texted = [phone for phone, text in get_sms_sender().outbox if text == message]
    assert texted == ["+254711111111"]  # the owner of the affected business, and nobody else
    assert [x["note"] for x in (await client.get("/audit", params={"action": "platform.breach_notified"}, headers=bearer(owner_a))).json()] == [message[:200]]
    assert (await client.get("/audit", params={"action": "platform.breach_notified"}, headers=bearer(owner_b))).json() == []


async def test_telling_the_businesses_needs_a_message_and_a_list_of_businesses(client):
    admin = await make_platform_admin(client)
    none_named = (await client.post("/platform/breaches", headers=bearer(admin), json=breach())).json()
    res = await client.post(f"/platform/breaches/{none_named['id']}/notify", headers=bearer(admin), json={"who": "businesses", "message": "Something happened, here is what."})
    assert res.json()["detail"]["code"] == "no_businesses"
    named = (await client.post("/platform/breaches", headers=bearer(admin), json=breach(businesses_affected=[str(uuid.uuid4())]))).json()
    res = await client.post(f"/platform/breaches/{named['id']}/notify", headers=bearer(admin), json={"who": "businesses"})
    assert res.json()["detail"]["code"] == "message_needed"


async def test_containing_and_closing_a_breach_is_recorded_with_what_was_found(client):
    admin = await make_platform_admin(client)
    b = (await client.post("/platform/breaches", headers=bearer(admin), json=breach())).json()
    res = await client.patch(f"/platform/breaches/{b['id']}", headers=bearer(admin), json={"status": "contained", "root_cause": "The laptop had no disk encryption.", "actions_taken": "Sessions revoked; disk encryption now required."})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "contained" and body["contained_at"] and body["root_cause"].startswith("The laptop") and body["actions_taken"]
    assert (await client.post("/platform/breaches", headers=bearer(admin), json=breach(severity="bad"))).status_code == 422
    assert (await client.get(f"/platform/breaches/{uuid.uuid4()}", headers=bearer(admin))).status_code == 404


async def test_only_platform_admins_can_see_or_change_the_register(client):
    owner, _ = await owner_session(client)
    for method, path, body in (("GET", "/platform/breaches", None), ("POST", "/platform/breaches", breach()), ("GET", f"/platform/breaches/{uuid.uuid4()}", None)):
        assert (await client.request(method, path, headers=bearer(owner), json=body)).status_code == 403
        assert (await client.request(method, path, json=body)).status_code == 401
