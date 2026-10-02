from datetime import date, timedelta

import pytest

from app.reminders import nairobi_today
from app.service_reminders import send_service_reminders
from app.service_rules import add_months, service_due
from app.sms import get_sms_sender
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.shots import fleet, inspect


async def work_orders(client, tokens, query=""):
    res = await client.get(f"/work-orders{query}", headers=bearer(tokens))
    assert res.status_code == 200, res.text
    return res.json()


async def set_odometer(client, f, km):
    body = {k: v for k, v in f.vehicle.items() if k != "id"}
    res = await client.put(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner), json={**body, "odometer_km": km})
    assert res.status_code == 200, res.text


# ---- the rules on their own ---------------------------------------------------------------------------


def due(**kw):
    base = dict(every_km=10000, every_months=None, last_done_km=120000, last_done_on=None, advance_km=500, advance_days=14, odometer_km=125000, today=date(2026, 10, 2), started_on=date(2026, 1, 1))  # noqa: C408
    return service_due(**{**base, **kw})


def test_a_service_by_kilometres_is_ok_then_due_soon_then_overdue():
    assert due(odometer_km=125000).status == "ok" and due(odometer_km=125000).km_left == 5000
    assert due(odometer_km=129500).status == "due_soon"
    assert due(odometer_km=129499).status == "ok"
    assert due(odometer_km=130000).status == "overdue" and due(odometer_km=130001).km_left == -1


def test_a_service_by_time_uses_the_last_done_date_or_the_schedule_start():
    by_time = dict(every_km=None, every_months=3, last_done_on=date(2026, 7, 2))  # noqa: C408
    assert due(**by_time).next_due_on == date(2026, 10, 2) and due(**by_time).status == "overdue"
    assert due(**{**by_time, "today": date(2026, 9, 18)}).status == "due_soon"
    assert due(**{**by_time, "today": date(2026, 9, 17)}).status == "ok"
    assert due(every_km=None, every_months=6, last_done_on=None, started_on=date(2026, 4, 2)).next_due_on == date(2026, 10, 2)


def test_whichever_comes_first_decides():
    both = dict(every_km=10000, every_months=3, last_done_on=date(2026, 7, 2))  # noqa: C408
    assert due(**both, odometer_km=125000).status == "overdue"  # the time ran out first
    assert due(**{**both, "last_done_on": date(2026, 9, 1)}, odometer_km=129600).status == "due_soon"  # the distance is close first


def test_adding_months_stays_inside_the_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


# ---- work orders --------------------------------------------------------------------------------------


async def test_every_inspection_defect_becomes_a_work_order_at_once(client):
    f = await fleet(client)
    res = await inspect(client, f.driver, f.vehicle["id"], {"Brakes": "Pedal goes to the floor", "Body damage": "Dent on the door"})
    assert res.status_code == 201
    orders = await work_orders(client, f.owner)
    by_title = {w["title"].split(":")[0]: w for w in orders}
    assert set(by_title) == {"Brakes", "Body damage"}
    assert by_title["Brakes"]["priority"] == "urgent" and by_title["Body damage"]["priority"] == "normal"
    assert all(w["source"] == "defect" and w["status"] == "open" and w["defect_id"] for w in orders)
    assert by_title["Brakes"]["description"] == "Pedal goes to the floor"


async def test_a_work_order_is_assigned_costed_and_completed_into_an_expense(client):
    f = await fleet(client)
    await inspect(client, f.driver, f.vehicle["id"], {"Brakes": "Soft pedal"})
    wo = (await work_orders(client, f.owner))[0]
    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    updated = await client.put(
        f"/work-orders/{wo['id']}", headers=bearer(manager),
        json={"status": "in_progress", "assignee_kind": "garage", "assignee_name": "Kamau Motors", "labour_cents": 300000,
              "parts": [{"name": "Brake pads", "quantity": 2, "unit_cost_cents": 450000}, {"name": "Brake fluid", "quantity": 1, "unit_cost_cents": 80000}]},
    )  # fmt: skip
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["status"] == "in_progress" and body["assignee_name"] == "Kamau Motors"
    assert body["parts_cents"] == 980000 and body["total_cents"] == 1280000

    done = await client.post(f"/work-orders/{wo['id']}/complete", headers=bearer(manager), json={"odometer_km": 125400, "notes": "Pads and fluid replaced"})
    assert done.status_code == 200 and done.json()["status"] == "done" and done.json()["odometer_km"] == 125400
    expenses = (await client.get("/expenses", headers=bearer(f.owner))).json()
    repair = next(e for e in expenses if e["category"] == "repair")
    assert repair["amount_cents"] == 1280000 and repair["vehicle_id"] == f.vehicle["id"] and repair["status"] == "recorded"
    assert (await client.get("/vehicles/" + f.vehicle["id"], headers=bearer(f.owner))).json()["odometer_km"] == 125400
    # Closed work orders stay closed.
    assert (await client.post(f"/work-orders/{wo['id']}/complete", headers=bearer(manager), json={})).status_code == 409
    assert (await client.put(f"/work-orders/{wo['id']}", headers=bearer(manager), json={"title": "Changed my mind"})).status_code == 409
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert {"work_order.updated", "work_order.completed"} <= set(actions)


async def test_finishing_must_go_through_complete_so_the_cost_is_recorded(client):
    f = await fleet(client)
    created = await client.post("/work-orders", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "title": "Replace wiper blades", "priority": "low"})
    assert created.status_code == 201 and created.json()["source"] == "manual"
    res = await client.put(f"/work-orders/{created.json()['id']}", headers=bearer(f.owner), json={"status": "done"})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "use_complete"
    nothing = await client.post(f"/work-orders/{created.json()['id']}/complete", headers=bearer(f.owner), json={})
    assert nothing.status_code == 200
    assert (await client.get("/expenses", headers=bearer(f.owner))).json() == []  # no cost, no expense


async def test_cancelling_a_work_order_reopens_its_defect(client):
    f = await fleet(client)
    await inspect(client, f.driver, f.vehicle["id"], {"Body damage": "Dent"})
    wo = (await work_orders(client, f.owner))[0]
    cancelled = await client.put(f"/work-orders/{wo['id']}", headers=bearer(f.owner), json={"status": "cancelled"})
    assert cancelled.json()["status"] == "cancelled"
    assert await work_orders(client, f.owner, "?open_only=true") == []
    assert len(await work_orders(client, f.owner, "?status_filter=cancelled")) == 1


async def test_who_can_see_and_change_work_orders(client):
    f = await fleet(client)
    await inspect(client, f.driver, f.vehicle["id"], {"Body damage": "Dent"})
    wo = (await work_orders(client, f.owner))[0]
    assert (await client.get("/work-orders", headers=bearer(f.driver))).status_code == 403
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.get("/work-orders", headers=bearer(accountant))).status_code == 403
    workshop, _ = await staff_session(client, f.owner, "workshop", "w@example.com", with_2fa=False)
    assert len(await work_orders(client, workshop)) == 1
    assert (await client.put(f"/work-orders/{wo['id']}", headers=bearer(workshop), json={"status": "waiting_parts"})).status_code == 200
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert await work_orders(client, other) == []
    assert (await client.get(f"/work-orders/{wo['id']}", headers=bearer(other))).status_code == 404
    assert (await client.post(f"/work-orders/{wo['id']}/complete", headers=bearer(other), json={})).status_code == 404


async def test_a_supervisor_sees_work_orders_for_their_vehicles_only(client):
    from tests.helpers import PASSWORD, enable_2fa, login

    f = await fleet(client)
    second = await add_vehicle(client, f.owner, "KCB 222B")
    await client.post("/work-orders", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "title": "Mine to see"})
    await client.post("/work-orders", headers=bearer(f.owner), json={"vehicle_id": second["id"], "title": "Not mine"})
    invite = await client.post("/users", headers=bearer(f.owner), json={"name": "Sup", "email": "sup@example.com", "roles": ["supervisor"], "vehicle_scope": [f.vehicle["id"]]})
    await client.post("/auth/accept-invite", json={"token": invite.json()["invite_token"], "password": PASSWORD})
    sup = (await login(client, "sup@example.com")).json()
    await enable_2fa(client, sup)
    assert [w["title"] for w in await work_orders(client, sup)] == ["Mine to see"]
    assert (await client.post("/work-orders", headers=bearer(sup), json={"vehicle_id": f.vehicle["id"], "title": "Try to add"})).status_code == 403


# ---- service schedules ---------------------------------------------------------------------------------


async def add_schedule(client, f, **extra):
    body = {"name": "Oil and filters", "every_km": 10000, "last_done_km": 120000, "advance_km": 500, **extra}
    res = await client.post(f"/vehicles/{f.vehicle['id']}/services", headers=bearer(f.owner), json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def test_a_schedule_shows_where_it_stands_as_the_odometer_moves(client):
    f = await fleet(client)
    s = await add_schedule(client, f)
    assert s["due_status"] == "ok" and s["next_km"] == 130000 and s["km_left"] == 5000
    await set_odometer(client, f, 129700)
    listed = (await client.get(f"/vehicles/{f.vehicle['id']}/services", headers=bearer(f.owner))).json()["schedules"][0]
    assert listed["due_status"] == "due_soon" and listed["km_left"] == 300
    await set_odometer(client, f, 130100)
    fleetwide = (await client.get("/service-schedules?due_only=true", headers=bearer(f.owner))).json()
    assert [(x["registration"], x["due_status"]) for x in fleetwide] == [("KCA 123A", "overdue")]


async def test_a_schedule_needs_an_interval_and_is_managed_by_the_office(client):
    f = await fleet(client)
    none = await client.post(f"/vehicles/{f.vehicle['id']}/services", headers=bearer(f.owner), json={"name": "Nothing"})
    assert none.status_code == 422 and none.json()["detail"]["code"] == "interval_required"
    last = nairobi_today() - timedelta(days=80)
    s = await add_schedule(client, f, every_km=None, every_months=3, last_done_on=last.isoformat())
    assert s["due_status"] == "due_soon" and s["days_left"] == (add_months(last, 3) - nairobi_today()).days
    assert (await client.post(f"/vehicles/{f.vehicle['id']}/services", headers=bearer(f.driver), json={"name": "xx", "every_km": 1000})).status_code == 403
    changed = await client.put(f"/service-schedules/{s['id']}", headers=bearer(f.owner), json={"name": "Grease", "every_months": 6, "last_done_on": nairobi_today().isoformat()})
    assert changed.json()["name"] == "Grease" and changed.json()["due_status"] == "ok"
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.put(f"/service-schedules/{s['id']}", headers=bearer(other), json={"name": "xx", "every_km": 1})).status_code == 404
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/services", headers=bearer(other))).status_code == 404


async def test_a_due_service_is_reminded_once_and_raises_a_work_order_that_resets_it_when_done(client):
    f = await fleet(client)
    sched = await add_schedule(client, f)
    from sqlalchemy import update

    from app.db import get_sessionmaker
    from app.models import User

    async with get_sessionmaker()() as db:
        await db.execute(update(User).where(User.email == "owner@example.com").values(phone="+254700111222"))
        await db.commit()
    outbox = get_sms_sender().outbox
    today = nairobi_today()

    assert await send_service_reminders(today) == 0  # 5,000 km to go: nothing yet
    await set_odometer(client, f, 129700)
    assert await send_service_reminders(today) == 1
    assert "Oil and filters" in outbox[-1][1] and "KCA 123A" in outbox[-1][1] and "300 km" in outbox[-1][1]
    assert await send_service_reminders(today) == 0  # not again
    await set_odometer(client, f, 130200)
    assert await send_service_reminders(today) == 0  # overdue is the same due service: already announced

    orders = await work_orders(client, f.owner, "?open_only=true")
    assert len(orders) == 1 and orders[0]["source"] == "service" and orders[0]["schedule_id"] == sched["id"]
    assert orders[0]["priority"] == "high"

    done = await client.post(f"/work-orders/{orders[0]['id']}/complete", headers=bearer(f.owner), json={"odometer_km": 130200, "labour_cents": 450000})
    assert done.status_code == 200
    services = (await client.get(f"/vehicles/{f.vehicle['id']}/services", headers=bearer(f.owner))).json()
    assert services["schedules"][0]["due_status"] == "ok" and services["schedules"][0]["next_km"] == 140200
    assert [(h["odometer_km"], h["cost_cents"]) for h in services["history"]] == [(130200, 450000)]
    expense = next(e for e in (await client.get("/expenses", headers=bearer(f.owner))).json() if e["category"] == "service")
    assert expense["amount_cents"] == 450000

    await set_odometer(client, f, 139800)  # the next service comes due: a fresh reminder
    assert await send_service_reminders(today) == 1
    assert len(await work_orders(client, f.owner, "?open_only=true")) == 1


async def test_reminders_never_cross_businesses(client):
    f = await fleet(client)
    await add_schedule(client, f)
    await set_odometer(client, f, 129900)
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    await send_service_reminders(nairobi_today())
    assert await work_orders(client, other) == []
    assert len(await work_orders(client, f.owner)) == 1


@pytest.mark.parametrize("bad", [{"every_km": 0}, {"every_months": -1}, {"advance_km": -5}, {"name": "x"}])
async def test_bad_schedule_values_are_rejected(client, bad):
    f = await fleet(client)
    res = await client.post(f"/vehicles/{f.vehicle['id']}/services", headers=bearer(f.owner), json={"name": "Oil", "every_km": 10000, **bad})
    assert res.status_code == 422
