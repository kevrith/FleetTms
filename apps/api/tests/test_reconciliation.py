from datetime import timedelta

from app.reminders import nairobi_today
from tests.fleet import add_vehicle
from tests.helpers import PASSWORD, bearer, driver_session, enable_2fa, login, staff_session
from tests.shots import ago, fleet, my_balance, send_float, sync


async def spend(client, tokens, cents, category="toll", **extra):
    res = await client.post("/expenses", headers=bearer(tokens), json={"category": category, "amount_cents": cents, "mpesa_code": None, **extra})
    assert res.status_code == 201, res.text
    return res.json()


async def sheet(client, tokens, day=None):
    res = await client.get(f"/me/reconciliation{'?day=' + day.isoformat() if day else ''}", headers=bearer(tokens))
    assert res.status_code == 200, res.text
    return res.json()


async def submit(client, tokens, day=None):
    return await client.post("/me/reconciliation/submit", headers=bearer(tokens), json={"day": day.isoformat()} if day else {})


async def supervisor(client, f, scope, email="sup@example.com"):
    invite = await client.post("/users", headers=bearer(f.owner), json={"name": "Sup", "email": email, "roles": ["supervisor"], "vehicle_scope": scope})
    await client.post("/auth/accept-invite", json={"token": invite.json()["invite_token"], "password": PASSWORD})
    tokens = (await login(client, email)).json()
    await enable_2fa(client, tokens)
    return tokens


async def test_the_days_sheet_is_opening_plus_floats_minus_expenses(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await spend(client, f.driver, 50000)
    await spend(client, f.driver, 70000, "parking")
    s = await sheet(client, f.driver)
    assert (s["opening_cents"], s["floats_cents"], s["expenses_cents"], s["closing_cents"]) == (0, 300000, 120000, 180000)
    assert s["status"] == "open" and len(s["expenses"]) == 2
    assert await my_balance(client, f.driver) == 180000


async def test_supervisor_approves_the_evening_reconciliation_and_the_balance_carries_forward(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await spend(client, f.driver, 120000)
    sub = await submit(client, f.driver)
    assert sub.status_code == 200 and sub.json()["status"] == "submitted" and sub.json()["closing_cents"] == 180000
    sup = await supervisor(client, f, [f.vehicle["id"]])
    waiting = (await client.get("/reconciliations?status_filter=submitted", headers=bearer(sup))).json()
    assert [(r["driver_name"], r["closing_cents"]) for r in waiting] == [("driver user", 180000)]
    approved = await client.post(f"/reconciliations/{sub.json()['id']}/approve", headers=bearer(sup), json={"balance_action": "carry_forward", "note": "All receipts seen"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert await my_balance(client, f.driver) == 180000  # still the driver's float
    tomorrow = nairobi_today() + timedelta(days=1)
    assert (await sheet(client, f.driver, tomorrow))["opening_cents"] == 180000  # tomorrow starts where today ended
    assert (await sheet(client, f.driver))["status"] == "approved"
    again = await client.post(f"/reconciliations/{sub.json()['id']}/approve", headers=bearer(sup), json={})
    assert again.status_code == 409
    assert (await submit(client, f.driver)).json()["detail"]["code"] == "already_approved"
    assert "reconciliation.approved" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_returning_the_balance_takes_it_to_zero(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await spend(client, f.driver, 120000)
    sub = (await submit(client, f.driver)).json()
    approved = await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(f.owner), json={"balance_action": "returned"})
    assert approved.status_code == 200 and approved.json()["balance_action"] == "returned"
    assert await my_balance(client, f.driver) == 0
    floats = (await client.get("/floats", headers=bearer(f.owner))).json()
    assert sorted(x["amount_cents"] for x in floats) == [-180000, 300000]  # the return is on the record


async def test_an_overspent_day_has_nothing_to_return_but_can_carry_the_deficit(client):
    f = await fleet(client)
    await send_float(client, f, 50000)
    await spend(client, f.driver, 80000)
    sub = (await submit(client, f.driver)).json()
    assert sub["closing_cents"] == -30000
    bad = await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(f.owner), json={"balance_action": "returned"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "nothing_to_return"
    ok = await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(f.owner), json={"balance_action": "carry_forward"})
    assert ok.status_code == 200


async def test_a_day_with_an_expense_waiting_on_the_owner_cannot_be_approved_yet(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await client.put("/spend-limits", headers=bearer(f.owner), json=[{"limit_cents": 50000}])
    big = await spend(client, f.driver, 90000)
    assert big["status"] == "awaiting_approval"
    sub = (await submit(client, f.driver)).json()
    assert sub["expenses_cents"] == 0  # the unapproved one is not in the figures
    blocked = await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(f.owner), json={})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "pending_expenses"
    await client.post(f"/expenses/{big['id']}/decision", headers=bearer(f.owner), json={"approve": True})
    done = await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(f.owner), json={})
    assert done.status_code == 200 and done.json()["expenses_cents"] == 90000 and done.json()["closing_cents"] == 210000  # figures refreshed


async def test_a_rejected_day_goes_back_and_can_be_resubmitted(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await spend(client, f.driver, 120000)
    sub = (await submit(client, f.driver)).json()
    sent_back = await client.post(f"/reconciliations/{sub['id']}/reject", headers=bearer(f.owner), json={"note": "Missing the parking receipt"})
    assert sent_back.json()["status"] == "rejected"
    assert (await sheet(client, f.driver))["note"] == "Missing the parking receipt"
    await spend(client, f.driver, 30000, "parking")
    again = (await submit(client, f.driver)).json()
    assert again["status"] == "submitted" and again["expenses_cents"] == 150000 and again["id"] == sub["id"]
    assert (await client.post(f"/reconciliations/{sub['id']}/reject", headers=bearer(f.owner), json={"note": "no"})).status_code == 422


async def test_yesterdays_spending_sets_todays_opening_balance(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await spend(client, f.driver, 40000, captured_at=ago(hours=30))
    yesterday = nairobi_today() - timedelta(days=1)
    today = await sheet(client, f.driver)
    assert today["expenses_cents"] == 0 and today["floats_cents"] == 300000
    old = await sheet(client, f.driver, yesterday)
    assert old["expenses_cents"] == 40000 and old["closing_cents"] == -40000


async def test_only_senior_staff_decide_and_supervisors_only_for_their_own_vehicles(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await spend(client, f.driver, 120000)
    sub = (await submit(client, f.driver)).json()
    assert (await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(f.driver), json={})).status_code == 403
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(accountant), json={})).status_code == 403
    assert (await client.get("/reconciliations", headers=bearer(accountant))).status_code == 200  # money access: can look

    other_vehicle = await add_vehicle(client, f.owner, "KCB 222B")
    outsider = await supervisor(client, f, [other_vehicle["id"]], "out@example.com")
    assert (await client.get("/reconciliations", headers=bearer(outsider))).json() == []
    assert (await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(outsider), json={})).status_code == 404
    manager, _ = await staff_session(client, f.owner, "manager", "m@example.com")
    assert (await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(manager), json={})).status_code == 200


async def test_reconciliation_rules_and_isolation(client):
    f = await fleet(client)
    tomorrow = nairobi_today() + timedelta(days=1)
    assert (await submit(client, f.driver, tomorrow)).json()["detail"]["code"] == "future_day"
    sub = (await submit(client, f.driver)).json()
    from tests.helpers import owner_session

    bravo, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/reconciliations", headers=bearer(bravo))).json() == []
    assert (await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(bravo), json={})).status_code == 404


async def test_reconciliation_can_be_submitted_offline(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    await spend(client, f.driver, 120000)
    action = {"client_id": "8d0c1c2e-6f0a-4a43-9d57-2f4a1c1f5555", "type": "reconciliation.submit", "payload": {"captured_at": ago(minutes=30)}}
    assert (await sync(client, f.driver, [action])).json()["results"][0]["status"] == "ok"
    assert (await sync(client, f.driver, [action])).json()["results"][0]["status"] == "duplicate"
    assert (await sheet(client, f.driver))["status"] == "submitted"
    stranger = await driver_session(client, f.owner, "0733345678")
    assert (await sheet(client, stranger))["status"] == "open"


async def test_an_unknown_balance_action_is_refused(client):
    f = await fleet(client)
    await send_float(client, f, 300000)
    sub = (await submit(client, f.driver)).json()
    res = await client.post(f"/reconciliations/{sub['id']}/approve", headers=bearer(f.owner), json={"balance_action": "keep it"})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "bad_action"
