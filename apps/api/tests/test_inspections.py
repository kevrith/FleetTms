from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Defect
from app.tenancy import current_business_id
from tests.helpers import bearer, owner_session, staff_session
from tests.shots import checklist, fleet, inspect, photo_id


async def test_business_gets_the_standard_checklist_with_brakes_and_tyres_critical(client):
    owner, _ = await owner_session(client)
    items = await checklist(client, owner)
    labels = {i["label"]: i["critical"] for i in items}
    assert len(items) == 8 and labels["Brakes"] and labels["Tyres: condition and pressure"]
    assert not labels["Oil level"]
    assert await checklist(client, owner) == items  # seeded once, not on every call


async def test_manager_can_reword_add_and_retire_checklist_items(client):
    owner, _ = await owner_session(client)
    items = await checklist(client, owner)
    oil = next(i for i in items if i["label"] == "Oil level")
    res = await client.put(
        f"/inspection/checklist/{oil['id']}", headers=bearer(owner),
        json={"label": "Engine oil level", "critical": True, "photo_on_fault": True},
    )  # fmt: skip
    assert res.status_code == 200 and res.json()["critical"] is True
    added = await client.post("/inspection/checklist", headers=bearer(owner), json={"label": "Fire extinguisher present"})
    assert added.status_code == 201
    await client.put(
        f"/inspection/checklist/{added.json()['id']}", headers=bearer(owner),
        json={"label": "Fire extinguisher present", "is_active": False},
    )  # fmt: skip
    active = [i["label"] for i in await checklist(client, owner)]
    assert "Fire extinguisher present" not in active and "Engine oil level" in active
    everything = await client.get("/inspection/checklist?include_inactive=true", headers=bearer(owner))
    assert "Fire extinguisher present" in [i["label"] for i in everything.json()]
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert "checklist.item_updated" in actions and "checklist.item_added" in actions


async def test_clean_inspection_passes_and_clears_the_vehicle_for_today(client):
    f = await fleet(client)
    today = await client.get(f"/vehicles/{f.vehicle['id']}/inspections/today", headers=bearer(f.driver))
    assert today.json() == {"inspection": None, "can_start_trip": False}
    res = await inspect(client, f.driver, f.vehicle["id"])
    assert res.status_code == 201 and res.json()["status"] == "passed"
    today = (await client.get(f"/vehicles/{f.vehicle['id']}/inspections/today", headers=bearer(f.driver))).json()
    assert today["can_start_trip"] is True and len(today["inspection"]["results"]) == 8


async def test_minor_fault_passes_and_becomes_a_work_order(client):
    f = await fleet(client)
    res = await inspect(client, f.driver, f.vehicle["id"], {"Body damage": "Dent on the left door"})
    body = res.json()
    assert res.status_code == 201 and body["status"] == "passed_with_defects"
    fault = next(r for r in body["results"] if not r["ok"])
    assert fault["note"] == "Dent on the left door" and fault["photo"]["url"].startswith("/media/")
    async with get_sessionmaker()() as db:
        from app.models import Business

        current_business_id.set((await db.execute(select(Business.id))).scalars().first())
        defects = (await db.execute(select(Defect))).scalars().all()
        current_business_id.set(None)
    assert [(d.label, d.critical, d.status) for d in defects] == [("Body damage", False, "work_order")]
    assert defects[0].work_order_id is not None  # a work order was raised for it automatically


async def test_critical_fault_blocks_and_only_a_manager_with_a_reason_can_override(client):
    f = await fleet(client)
    res = await inspect(client, f.driver, f.vehicle["id"], {"Brakes": "Pedal goes to the floor"})
    inspection = res.json()
    assert inspection["status"] == "blocked"
    today = (await client.get(f"/vehicles/{f.vehicle['id']}/inspections/today", headers=bearer(f.driver))).json()
    assert today["can_start_trip"] is False

    url = f"/inspections/{inspection['id']}/override"
    assert (await client.post(url, headers=bearer(f.driver), json={"reason": "I say it is fine"})).status_code == 403
    assert (await client.post(url, headers=bearer(f.owner), json={"reason": "no"})).status_code == 422
    ok = await client.post(url, headers=bearer(f.owner), json={"reason": "Mechanic bled the brakes on site"})
    assert ok.status_code == 200 and ok.json()["status"] == "overridden"
    assert ok.json()["override_reason"] == "Mechanic bled the brakes on site"
    again = await client.post(url, headers=bearer(f.owner), json={"reason": "Trying a second time"})
    assert again.status_code == 409
    today = (await client.get(f"/vehicles/{f.vehicle['id']}/inspections/today", headers=bearer(f.driver))).json()
    assert today["can_start_trip"] is True

    audit = (await client.get("/audit", headers=bearer(f.owner))).json()
    entry = next(e for e in audit if e["action"] == "inspection.overridden")
    assert entry["note"] == "Mechanic bled the brakes on site" and entry["after"]["status"] == "overridden"


async def test_incomplete_or_unexplained_inspections_are_rejected(client):
    f = await fleet(client)
    items = await checklist(client, f.driver)
    all_ok = [{"item_id": i["id"], "ok": True} for i in items]
    url = f"/vehicles/{f.vehicle['id']}/inspections"

    missing = await client.post(url, headers=bearer(f.driver), json={"results": all_ok[:-1]})
    assert missing.json()["detail"]["code"] == "checklist_incomplete"
    twice = await client.post(url, headers=bearer(f.driver), json={"results": all_ok + [all_ok[0]]})
    assert twice.json()["detail"]["code"] == "checklist_incomplete"

    no_note = [{"item_id": items[0]["id"], "ok": False}, *all_ok[1:]]
    assert (await client.post(url, headers=bearer(f.driver), json={"results": no_note})).json()["detail"]["code"] == "fault_needs_note"
    no_photo = [{"item_id": items[0]["id"], "ok": False, "note": "Soft pedal"}, *all_ok[1:]]
    assert (await client.post(url, headers=bearer(f.driver), json={"results": no_photo})).json()["detail"]["code"] == "photo_required"
    wrong_kind = await photo_id(client, f.driver, "odometer")
    bad_photo = [{"item_id": items[0]["id"], "ok": False, "note": "Soft pedal", "photo_id": wrong_kind}, *all_ok[1:]]
    assert (await client.post(url, headers=bearer(f.driver), json={"results": bad_photo})).json()["detail"]["code"] == "photo_invalid"


async def test_only_the_crew_or_a_manager_can_inspect_a_vehicle(client):
    from tests.helpers import driver_session

    f = await fleet(client)
    stranger = await driver_session(client, f.owner, "0733345678")  # a driver not assigned to this vehicle
    res = await inspect(client, stranger, f.vehicle["id"])
    assert res.status_code == 403 and res.json()["detail"]["code"] == "not_your_vehicle"
    assert (await inspect(client, f.turnboy, f.vehicle["id"])).status_code == 201  # the turnboy crews it too
    assert (await inspect(client, f.owner, f.vehicle["id"])).status_code == 201  # managers can act for the crew


async def test_inspections_are_isolated_between_businesses(client):
    f = await fleet(client)
    inspection = (await inspect(client, f.driver, f.vehicle["id"], {"Brakes": "Soft"})).json()
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.post(f"/inspections/{inspection['id']}/override", headers=bearer(other), json={"reason": "Not my truck"})).status_code == 404
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/inspections", headers=bearer(other))).status_code == 404
    assert (await inspect(client, other, f.vehicle["id"])).status_code == 404
    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    assert len((await client.get(f"/vehicles/{f.vehicle['id']}/inspections", headers=bearer(manager))).json()) == 1
