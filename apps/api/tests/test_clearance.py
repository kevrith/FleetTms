"""A trip does not start while a required document of its driver or vehicle has run out (when the business has chosen to block)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.clearance_rules import assess, sentence, status_of
from app.reminders import nairobi_today
from tests.helpers import bearer, staff_session
from tests.shots import fleet, inspect, make_trip, photo_id, start

TODAY = date(2026, 10, 11)


@pytest.mark.parametrize(
    ("expires", "ends", "status", "left"),
    [
        (None, None, "missing", None),
        (date(2026, 10, 10), None, "expired", -1),
        (date(2026, 10, 11), None, "today", 0),  # valid through its expiry date
        (date(2026, 10, 20), None, "soon", 9),
        (date(2026, 10, 25), None, "soon", 14),
        (date(2026, 10, 26), None, "ok", 15),
        (date(2026, 10, 14), date(2026, 10, 16), "ends_during_trip", 3),
        (date(2026, 10, 16), date(2026, 10, 16), "soon", 5),  # still valid on the day the trip ends
    ],
)
def test_status_of(expires, ends, status, left):
    assert status_of(expires, TODAY, ends) == (status, left)


def test_only_block_mode_stops_a_trip_and_off_says_nothing():
    items = [{"doc_type": "insurance", "subject": "vehicle", "name": "KCA 123A", "expires_on": date(2026, 10, 1)}, {"doc_type": "driving_licence", "subject": "driver", "name": "Wafula", "expires_on": None}]
    block = assess(mode="block", today=TODAY, items=items)
    assert block["blocked"] and [i["blocking"] for i in block["issues"]] == [True, True]
    warn = assess(mode="warn", today=TODAY, items=items)
    assert not warn["blocked"] and len(warn["issues"]) == 2 and not any(i["blocking"] for i in warn["issues"])
    assert assess(mode="off", today=TODAY, items=items) == {"mode": "off", "blocked": False, "issues": []}
    soon = assess(mode="block", today=TODAY, items=[{**items[0], "expires_on": date(2026, 10, 15)}])
    assert not soon["blocked"] and soon["issues"][0]["status"] == "soon"  # said, not stopped


def test_sentences_read_plainly():
    issue = assess(mode="block", today=TODAY, items=[{"doc_type": "driving_licence", "subject": "driver", "name": "John Mwangi", "expires_on": date(2026, 10, 1)}])["issues"][0]
    assert sentence(issue) == "Driving licence for John Mwangi expired on 2026-10-01."


async def set_rule(client, f, mode="block", required=("driving_licence", "insurance")):
    res = await client.put("/document-rule", headers=bearer(f.owner), json={"mode": mode, "required": list(required)})
    assert res.status_code == 200, res.text


async def document(client, f, kind, days, *, driver=False):
    owner = {"membership_id": f.ids["+254712345678"]} if driver else {"vehicle_id": f.vehicle["id"]}
    res = await client.post("/documents", headers=bearer(f.owner), json={"doc_type": kind, **owner, "expires_on": (nairobi_today() + timedelta(days=days)).isoformat()})
    assert res.status_code == 201, res.text


async def valid_documents(client, f):
    await document(client, f, "insurance", 90)
    await document(client, f, "driving_licence", 400, driver=True)


async def ready_trip(client, f, **extra):
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    return await make_trip(client, f, **extra)


async def test_a_business_starts_on_warn_so_nothing_is_stopped_but_the_trip_says_what_has_run_out(client):
    f = await fleet(client)
    await document(client, f, "insurance", -3)
    assert (await client.get("/document-rule", headers=bearer(f.owner))).json()["mode"] == "warn"
    trip = await ready_trip(client, f)
    seen = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["compliance"]
    assert seen["mode"] == "warn" and not seen["blocked"]
    assert {i["doc_type"]: i["status"] for i in seen["issues"]} == {"insurance": "expired", "driving_licence": "missing"}
    assert (await start(client, f.driver, trip["id"])).status_code == 200


async def test_an_expired_insurance_or_licence_stops_the_trip_in_block_mode(client):
    f = await fleet(client)
    await set_rule(client, f)
    await document(client, f, "insurance", -1)
    await document(client, f, "driving_licence", 400, driver=True)
    trip = await ready_trip(client, f)
    res = await start(client, f.driver, trip["id"])
    assert res.status_code == 409 and res.json()["detail"]["code"] == "documents_expired"
    assert "Insurance for KCA 123A expired on" in res.json()["detail"]["message"]
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["status"] == "scheduled"
    await document(client, f, "insurance", 365)  # renewed: a later date on record
    assert (await start(client, f.driver, trip["id"])).status_code == 200


async def test_a_missing_licence_stops_the_trip_and_recording_it_lets_it_go(client):
    f = await fleet(client)
    await set_rule(client, f)
    await document(client, f, "insurance", 90)
    trip = await ready_trip(client, f)
    res = await start(client, f.driver, trip["id"])
    assert res.status_code == 409 and "not recorded" in res.json()["detail"]["message"]
    await document(client, f, "driving_licence", 30, driver=True)
    assert (await start(client, f.driver, trip["id"])).status_code == 200


async def test_a_document_is_valid_through_its_last_day_and_stops_trips_the_day_after(client):
    f = await fleet(client)
    await set_rule(client, f)
    await document(client, f, "insurance", 0)  # runs out today: still valid
    await document(client, f, "driving_licence", -1, driver=True)  # ran out yesterday
    trip = await ready_trip(client, f)
    res = await start(client, f.driver, trip["id"])
    assert res.status_code == 409 and "Driving licence" in res.json()["detail"]["message"] and "Insurance" not in res.json()["detail"]["message"]


async def test_the_owner_can_allow_one_trip_with_a_reason_and_nobody_else_can(client):
    f = await fleet(client)
    await set_rule(client, f)
    await document(client, f, "insurance", -5)
    await document(client, f, "driving_licence", 400, driver=True)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    trip = await ready_trip(client, f)
    assert (await start(client, f.driver, trip["id"])).status_code == 409
    for who in (manager, f.driver):
        assert (await client.post(f"/trips/{trip['id']}/compliance-override", headers=bearer(who), json={"reason": "Renewal paid today"})).status_code == 403
    assert (await client.post(f"/trips/{trip['id']}/compliance-override", headers=bearer(f.owner), json={"reason": "ok"})).status_code == 422  # a reason is needed
    ok = await client.post(f"/trips/{trip['id']}/compliance-override", headers=bearer(f.owner), json={"reason": "Renewal paid by M-Pesa this morning"})
    assert ok.status_code == 200, ok.text
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["compliance_override"]["reason"] == "Renewal paid by M-Pesa this morning"
    assert (await start(client, f.driver, trip["id"])).status_code == 200
    # it covered that trip only
    assert (await client.post(f"/trips/{trip['id']}/compliance-override", headers=bearer(f.owner), json={"reason": "Another go"})).status_code == 409  # already started
    ended = await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125200})
    assert ended.status_code == 200, ended.text
    again = await ready_trip(client, f)
    assert (await start(client, f.driver, again["id"])).status_code == 409


async def test_only_the_owner_changes_the_rule_and_it_is_checked(client):
    f = await fleet(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    body = {"mode": "block", "required": ["insurance"]}
    assert (await client.put("/document-rule", headers=bearer(manager), json=body)).status_code == 403
    assert (await client.put("/document-rule", headers=bearer(f.owner), json={**body, "mode": "strict"})).status_code == 422
    assert (await client.put("/document-rule", headers=bearer(f.owner), json={**body, "required": ["passport"]})).status_code == 422
    assert (await client.put("/document-rule", headers=bearer(f.owner), json=body)).json()["required"] == ["insurance"]
    assert (await client.get("/document-rule", headers=bearer(manager))).json()["mode"] == "block"
    assert (await client.get("/document-rule", headers=bearer(f.driver))).status_code == 403


async def test_a_driver_sees_what_is_wrong_on_their_own_trip_before_starting_it(client):
    f = await fleet(client)
    await set_rule(client, f)
    await document(client, f, "driving_licence", 5, driver=True)  # soon
    await document(client, f, "insurance", -2)
    await ready_trip(client, f)
    mine = (await client.get("/me/trips", headers=bearer(f.driver))).json()[0]["compliance"]
    assert mine["blocked"] and {i["doc_type"]: i["status"] for i in mine["issues"]} == {"driving_licence": "soon", "insurance": "expired"}
    assert all("text" in i for i in mine["issues"])


async def test_a_document_that_runs_out_before_the_planned_end_is_pointed_out_but_does_not_stop_the_trip(client):
    f = await fleet(client)
    await set_rule(client, f)
    await document(client, f, "insurance", 1)
    await document(client, f, "driving_licence", 400, driver=True)
    trip = await ready_trip(client, f, scheduled_for=(datetime.now(UTC) + timedelta(days=2)).isoformat())
    seen = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["compliance"]
    assert [i["status"] for i in seen["issues"]] == ["ends_during_trip"] and not seen["blocked"]
    assert (await start(client, f.driver, trip["id"])).status_code == 200
