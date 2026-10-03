import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app import platform_mpesa
from app.config import settings
from app.sms import get_sms_sender
from tests.billing_helpers import (
    answer_prompt,
    callback_body,
    days,
    pay_invoice,
    set_dates,
    subscription,
)
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import in_db
from tests.shots import fleet
from tests.test_support_and_privacy import make_platform_admin


@pytest.fixture(autouse=True)
def _reset(billing):
    platform_mpesa.fake_prompts().sent.clear()
    platform_mpesa.fake_prompts().fail_with = None


# ---- a new business is on a trial -----------------------------------------------------------------------------------------


async def test_a_new_business_has_fourteen_days_of_standard_with_no_payment_details(client):
    owner, _ = await owner_session(client)
    v = await add_vehicle(client, owner, "KCA 123A")
    s = await subscription(client, owner)
    assert s["access"]["state"] == "trialing" and s["access"]["writable"] is True and s["access"]["days_left"] == 14
    assert s["fleet_plan"] == "standard" and s["vehicles"] == [{"vehicle_id": v["id"], "registration": "KCA 123A", "plan": "standard", "effective_plan": "standard"}]
    assert s["quote"]["monthly_cents"] == 180_000 and s["annual_quote"]["total_cents"] == 1_800_000 and s["annual_quote"]["saving_cents"] == 360_000
    assert s["open_invoice"] is None and s["paid_until"] is None


async def test_plans_and_prices_can_be_looked_up_without_signing_in(client):
    res = (await client.get("/plans")).json()
    assert [(p["plan"], p["price_cents"]) for p in res["plans"]] == [("starter", 100_000), ("standard", 180_000), ("premium", 280_000)]
    assert res["trial_days"] == 14 and res["grace_days"] == 7 and res["volume"] == {"from": 11, "to": 30, "pct": 10, "custom_from": 31} and res["features"]["immobiliser"]["plan"] == "premium"
    assert "immobiliser" not in next(p for p in res["plans"] if p["plan"] == "standard")["features"] and "immobiliser" in next(p for p in res["plans"] if p["plan"] == "premium")["features"]


async def test_the_price_follows_each_vehicles_plan_and_a_big_fleet_gets_ten_percent_off(client):
    owner, _ = await owner_session(client)
    ids = [(await add_vehicle(client, owner, f"KCA {100 + i}A"))["id"] for i in range(11)]
    s = await subscription(client, owner)
    assert s["quote"]["discount_pct"] == 10 and s["quote"]["total_cents"] == 11 * 180_000 - 198_000
    changed = await client.put("/subscription/plans", headers=bearer(owner), json={"vehicles": [{"vehicle_id": ids[0], "plan": "premium"}, {"vehicle_id": ids[1], "plan": "starter"}]})
    assert changed.status_code == 200
    q = changed.json()["quote"]
    assert {line["plan"]: line["vehicles"] for line in q["lines"]} == {"starter": 1, "standard": 9, "premium": 1} and q["list_cents"] == 100_000 + 9 * 180_000 + 280_000
    assert (await client.put("/subscription/plans", headers=bearer(owner), json={"vehicles": [{"vehicle_id": ids[0], "plan": "gold"}]})).json()["detail"]["code"] == "bad_plan"
    assert (await client.put("/subscription/plans", headers=bearer(owner), json={"vehicles": [{"vehicle_id": str(uuid.uuid4()), "plan": "starter"}]})).status_code == 404
    assert "subscription.plans_changed" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_the_owner_chooses_annual_billing_and_payroll(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    s = (await client.put("/subscription/settings", headers=bearer(owner), json={"period": "annual", "payroll_enabled": True})).json()
    assert s["period"] == "annual" and s["payroll_enabled"] is True and s["payroll_employees"] == 1
    assert s["quote"]["monthly_cents"] == 180_000 + 10_000 and s["quote"]["total_cents"] == 1_900_000  # ten months for twelve, with the one employee on payroll


# ---- trial, M-Pesa payment, active (acceptance) ----------------------------------------------------------------------------------


async def test_a_trial_becomes_an_active_plan_when_the_mpesa_payment_goes_through(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    invoice = (await client.post("/subscription/invoices", headers=bearer(owner))).json()
    assert invoice["status"] == "issued" and invoice["total_cents"] == 180_000 and invoice["number"] == "SUB-0001" and invoice["kind"] == "subscription"
    assert (await client.post("/subscription/invoices", headers=bearer(owner))).json()["id"] == invoice["id"]  # one open invoice at a time
    asked = await client.post(f"/subscription/invoices/{invoice['id']}/pay", headers=bearer(owner), json={"phone": "0712 345 678"})
    assert asked.status_code == 200 and asked.json()["status"] == "pending"
    sent = platform_mpesa.fake_prompts().sent
    assert len(sent) == 1 and sent[0]["phone"] == "+254712345678" and sent[0]["amount_kes"] == 1800 and sent[0]["reference"] == "SUB-0001" and "/hooks/subscription-pay/" in sent[0]["callback_url"] and "mpesa" not in sent[0]["callback_url"].lower()
    assert (await subscription(client, owner))["access"]["state"] == "trialing"  # not paid until Safaricom says so
    assert (await answer_prompt(client)).json() == {"ResultCode": 0, "ResultDesc": "Accepted"}
    s = await subscription(client, owner)
    assert s["access"]["state"] == "active" and s["paid_until"] and s["open_invoice"] is None
    paid = s["invoices"][0]
    assert paid["status"] == "paid" and paid["payment_method"] == "mpesa" and paid["mpesa_code"] == "QWE1234567" and paid["paid_at"]
    assert (await answer_prompt(client)).status_code == 200  # a repeated callback changes nothing
    assert len([i for i in (await subscription(client, owner))["invoices"] if i["status"] == "paid"]) == 1
    assert "subscription.paid" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_the_next_invoice_starts_where_the_paid_time_ends(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    first = await pay_invoice(client, owner)
    ends = datetime.fromisoformat(first["period_end"])
    second = (await client.post("/subscription/invoices", headers=bearer(owner))).json()
    assert datetime.fromisoformat(second["period_start"]) == ends and second["number"] == "SUB-0002"
    await client.post(f"/subscription/invoices/{second['id']}/pay", headers=bearer(owner), json={"phone": "0712345678"})
    await answer_prompt(client, receipt="ABC9876543")
    s = await subscription(client, owner)
    assert datetime.fromisoformat(s["paid_until"]) > ends + timedelta(days=27)


async def test_an_annual_invoice_covers_twelve_months_for_ten(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    await client.put("/subscription/settings", headers=bearer(owner), json={"period": "annual"})
    paid = await pay_invoice(client, owner)
    assert paid["total_cents"] == 1_800_000 and paid["billing_period"] == "annual"
    s = await subscription(client, owner)
    assert 360 <= (datetime.fromisoformat(s["paid_until"]) - datetime.now(UTC)).days <= 366


async def test_a_declined_short_or_forged_payment_does_not_pay_the_invoice(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    invoice = (await client.post("/subscription/invoices", headers=bearer(owner))).json()
    pay = lambda: client.post(f"/subscription/invoices/{invoice['id']}/pay", headers=bearer(owner), json={"phone": "0712345678"})
    await pay()
    await answer_prompt(client, ok=False)  # the owner cancelled the prompt
    state = (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()
    assert state["status"] == "issued" and state["last_payment"]["status"] == "failed"
    async def age(db):
        from app.models import SubscriptionPayment

        await db.execute(update(SubscriptionPayment).values(created_at=datetime.now(UTC) - timedelta(minutes=5)))

    await in_db(age)
    await pay()
    await answer_prompt(client, amount=1)  # paid KES 1 against KES 1,800
    assert (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()["status"] == "issued"
    await in_db(age)
    await pay()
    forged = await answer_prompt(client, key="not-the-key")
    assert forged.status_code == 403
    unknown = await client.post(f"/hooks/subscription-pay/{platform_mpesa.callback_key()}", json=callback_body("ws_CO_unknown", amount=1800))
    assert unknown.status_code == 200
    junk = await client.post(f"/hooks/subscription-pay/{platform_mpesa.callback_key()}", json={"hello": "world"})
    assert junk.status_code == 200 and (await subscription(client, owner))["access"]["state"] == "trialing"


async def test_asking_for_payment_checks_the_phone_and_reports_a_refusal(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    invoice = (await client.post("/subscription/invoices", headers=bearer(owner))).json()
    url = f"/subscription/invoices/{invoice['id']}/pay"
    assert (await client.post(url, headers=bearer(owner), json={"phone": "999999999"})).json()["detail"]["code"] == "invalid_phone"
    platform_mpesa.fake_prompts().fail_with = "Safaricom did not accept the request: ConnectError"
    refused = await client.post(url, headers=bearer(owner), json={"phone": "0712345678"})
    assert refused.status_code == 502 and refused.json()["detail"]["code"] == "prompt_failed"
    platform_mpesa.fake_prompts().fail_with = None
    assert (await client.post(url, headers=bearer(owner), json={"phone": "0712345678"})).status_code == 200
    assert (await client.post(url, headers=bearer(owner), json={"phone": "0712345678"})).json()["detail"]["code"] == "prompt_sent"
    await answer_prompt(client)
    assert (await client.post(url, headers=bearer(owner), json={"phone": "0712345678"})).json()["detail"]["code"] == "not_payable"


async def test_an_invoice_needs_a_vehicle_and_a_very_large_fleet_is_priced_by_agreement(client):
    owner, _ = await owner_session(client)
    assert (await client.post("/subscription/invoices", headers=bearer(owner))).json()["detail"]["code"] == "no_vehicles"
    for i in range(31):
        await add_vehicle(client, owner, f"KCA {200 + i}A")
    big = await client.post("/subscription/invoices", headers=bearer(owner))
    assert big.status_code == 422 and big.json()["detail"]["code"] == "custom_pricing"
    admin = await make_platform_admin(client)
    bid = (await client.get("/auth/me", headers=bearer(owner))).json()["business"]["id"]
    assert (await client.post(f"/platform/businesses/{bid}/custom-price", headers=bearer(admin), json={"monthly_cents": 4_000_000})).status_code == 200
    invoice = await client.post("/subscription/invoices", headers=bearer(owner))
    assert invoice.status_code == 201 and invoice.json()["total_cents"] == 4_000_000


# ---- failed payment, grace, read-only, nothing lost (acceptance) --------------------------------------------------------------------


async def test_a_missed_payment_is_a_week_of_warning_then_read_only_with_nothing_lost_and_paying_fixes_it(client):
    f = await fleet(client)
    await pay_invoice(client, f.owner)
    await set_dates(paid_until=days(-3))  # the period ended three days ago
    s = await subscription(client, f.owner)
    assert s["access"]["state"] == "grace" and s["access"]["writable"] is True and s["access"]["days_left"] == 4
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "Grace Yard"})).status_code == 201  # still works, with a warning
    await set_dates(paid_until=days(-9))
    assert (await subscription(client, f.owner))["access"]["state"] == "read_only"
    blocked = await client.post("/depots", headers=bearer(f.owner), json={"name": "Blocked Yard"})
    assert blocked.status_code == 402 and blocked.json()["detail"]["code"] == "subscription_read_only" and "Nothing has been lost" in blocked.json()["detail"]["message"]
    assert (await client.post("/expenses", headers=bearer(f.driver), json={"category": "toll", "amount_cents": 50000, "vehicle_id": f.vehicle["id"]})).status_code == 402
    assert [d["name"] for d in (await client.get("/depots", headers=bearer(f.owner))).json()] == ["Grace Yard"]  # reading works, and what was there is still there
    assert (await client.get("/vehicles", headers=bearer(f.owner))).json()[0]["registration"] == "KCA 123A"
    paid = await pay_invoice(client, f.owner)  # paying still works
    assert paid["status"] == "paid"
    assert (await subscription(client, f.owner))["access"]["state"] == "active"
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "Back Yard"})).status_code == 201
    assert len((await client.get("/depots", headers=bearer(f.owner))).json()) == 2


async def test_a_trial_that_ends_unpaid_also_gets_a_week_then_read_only_and_support_can_extend_it(client):
    f = await fleet(client)
    await set_dates(trial_ends=days(-9))
    assert (await subscription(client, f.owner))["access"]["state"] == "read_only"
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "X"})).status_code == 402
    admin = await make_platform_admin(client)
    bid = (await client.get("/auth/me", headers=bearer(f.owner))).json()["business"]["id"]
    ext = await client.post(f"/platform/businesses/{bid}/extend-trial", headers=bearer(admin), json={"days": 14, "reason": "Waiting for their bank"})
    assert ext.status_code == 200 and ext.json()["state"] == "trialing"
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "X"})).status_code == 201
    assert "platform.trial_extended" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]  # the owner can see what support did


async def test_a_read_only_account_can_still_pay_raise_an_sos_and_look_at_everything(client):
    f = await fleet(client)
    await set_dates(trial_ends=days(-30))
    blocked = await client.post("/fuel", headers=bearer(f.driver), json={"vehicle_id": f.vehicle["id"], "litres": "10", "price_per_litre_cents": 18000, "amount_cents": 180000})
    assert blocked.status_code == 402
    sos = await client.post("/sos", headers=bearer(f.driver), json={"lat": -1.29, "lng": 36.82, "accuracy_m": 10})
    assert sos.status_code != 402  # an emergency is never blocked
    assert (await client.post("/subscription/invoices", headers=bearer(f.owner))).status_code == 201
    assert (await client.get("/dashboard", headers=bearer(f.owner))).status_code == 200


# ---- plans decide features ----------------------------------------------------------------------------------------------------


async def test_a_trial_has_standard_features_but_not_premium_and_premium_cannot_be_had_free_by_switching(client):
    f = await fleet(client)
    assert (await client.get("/geofences", headers=bearer(f.owner))).status_code == 200  # Standard
    gated = await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))
    assert gated.status_code == 402 and gated.json()["detail"]["code"] == "plan_required" and "Premium plan" in gated.json()["detail"]["message"]
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "premium"}]})
    s = await subscription(client, f.owner)
    assert s["vehicles"][0]["plan"] == "premium" and s["vehicles"][0]["effective_plan"] == "standard" and s["fleet_plan"] == "standard"  # set to Premium, but a trial is Standard
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))).status_code == 402
    await pay_invoice(client, f.owner)
    assert (await subscription(client, f.owner))["fleet_plan"] == "premium"
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))).status_code == 200


async def test_starter_has_phone_tracking_and_the_basics_but_not_trackers_tyres_or_extra_roles(client):
    f = await fleet(client)
    await pay_invoice(client, f.owner)
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "starter"}]})
    for path in ("/geofences", "/tyres", "/parts", "/map/vehicles", "/scorecards", "/etims/summary", "/behaviour/events", "/fraud/alerts"):
        res = await client.get(path, headers=bearer(f.owner))
        if path in ("/fraud/alerts",):
            assert res.status_code == 200, path
        else:
            assert res.status_code == 402 and res.json()["detail"]["code"] == "plan_required", path
    assert (await client.get("/vehicles", headers=bearer(f.owner))).status_code == 200 and (await client.get("/trips", headers=bearer(f.owner))).status_code == 200
    tracker = await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": "356938035643809"})
    assert tracker.status_code == 402 and "GPS tracker integration" in tracker.json()["detail"]["message"]
    role = await client.post("/users", headers=bearer(f.owner), json={"name": "Mgr", "email": "m@example.com", "roles": ["manager"]})
    assert role.status_code == 402 and role.json()["detail"]["code"] == "plan_required"
    assert (await client.post("/users", headers=bearer(f.owner), json={"name": "Drv", "phone": "0755555555", "roles": ["driver"]})).status_code == 201


async def test_a_vehicles_own_plan_decides_its_tracker_and_fuel_sensor(client):
    f = await fleet(client)
    other = await add_vehicle(client, f.owner, "KCB 222B")
    await pay_invoice(client, f.owner)
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": other["id"], "plan": "starter"}, {"vehicle_id": f.vehicle["id"], "plan": "standard"}]})
    assert (await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": other["id"], "imei": "111111111111111"})).status_code == 402
    ok = await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": "222222222222222"})
    assert ok.status_code == 201
    sensor = await client.post("/trackers", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "imei": "333333333333333", "has_fuel_sensor": True})
    assert sensor.status_code == 402 and "Fuel sensors" in sensor.json()["detail"]["message"]


async def test_a_free_account_has_every_feature_and_is_never_read_only(client):
    f = await fleet(client)
    admin = await make_platform_admin(client)
    bid = (await client.get("/auth/me", headers=bearer(f.owner))).json()["business"]["id"]
    assert (await client.post(f"/platform/businesses/{bid}/complimentary", headers=bearer(admin), json={"value": True, "reason": "The pilot fleet"})).json()["state"] == "complimentary"
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "starter"}]})
    await set_dates(trial_ends=days(-400))
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))).status_code == 200
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "Always"})).status_code == 201


async def test_switching_billing_off_gives_everyone_everything_as_in_development(client):
    settings.enforce_plans = settings.enforce_billing = False
    f = await fleet(client)
    await set_dates(trial_ends=days(-100))
    assert (await client.get(f"/vehicles/{f.vehicle['id']}/immobiliser", headers=bearer(f.owner))).status_code == 200
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "Dev"})).status_code == 201


# ---- who may see and change it ------------------------------------------------------------------------------------------------


async def test_only_the_owner_manages_the_subscription_but_everyone_sees_a_warning(client):
    f = await fleet(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    for method, path, body in (("GET", "/subscription", None), ("PUT", "/subscription/settings", {"period": "annual"}), ("POST", "/subscription/invoices", None), ("PUT", "/subscription/plans", {"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "starter"}]})):
        assert (await client.request(method, path, headers=bearer(manager), json=body)).status_code == 403, path
        assert (await client.request(method, path, headers=bearer(f.driver), json=body)).status_code == 403, path
    await set_dates(trial_ends=days(2))
    banner = (await client.get("/subscription/banner", headers=bearer(f.driver))).json()
    assert banner["state"] == "trialing" and banner["days_left"] == 2 and "total_cents" not in banner
    assert (await client.get("/subscription/banner", headers=bearer(manager))).json()["state"] == "trialing"  # every member sees it
    assert (await client.get("/subscription", headers=bearer(f.owner))).status_code == 200
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await subscription(client, other))["vehicles"] == []  # another business has its own


# ---- the platform console ------------------------------------------------------------------------------------------------------


async def test_the_platform_admin_sees_customers_by_state_and_the_revenue_of_those_paying(client):
    a, _ = await owner_session(client, "Alpha Haulage", "a@example.com")
    b, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    await add_vehicle(client, a, "KCA 111A")
    await add_vehicle(client, b, "KCB 222B")
    await add_vehicle(client, b, "KCB 333B")
    await client.put("/subscription/plans", headers=bearer(b), json={"vehicles": [{"vehicle_id": (await client.get("/vehicles", headers=bearer(b))).json()[0]["id"], "plan": "premium"}]})
    await pay_invoice(client, b)
    admin = await make_platform_admin(client)
    o = (await client.get("/platform/overview", headers=bearer(admin))).json()
    assert o["businesses"] == 2 and o["by_state"] == {"trialing": 1, "active": 1} and o["vehicles"] == 3 and o["vehicles_by_plan"] == {"standard": 2, "premium": 1}
    assert o["mrr_cents"] == 180_000 + 280_000 and o["open_invoices"] == 0
    rows = (await client.get("/platform/customers", headers=bearer(admin))).json()
    assert [r["name"] for r in rows] == ["Bravo Transporters", "Alpha Haulage"] and rows[0]["state"] == "active" and rows[0]["plans"] == {"standard": 1, "premium": 1} and rows[1]["state"] == "trialing"
    assert [r["name"] for r in (await client.get("/platform/customers", params={"state": "trialing"}, headers=bearer(admin))).json()] == ["Alpha Haulage"]
    assert [r["name"] for r in (await client.get("/platform/customers", params={"q": "brav"}, headers=bearer(admin))).json()] == ["Bravo Transporters"]
    detail = (await client.get(f"/platform/businesses/{rows[0]['id']}", headers=bearer(admin))).json()
    assert detail["owner"]["email"] == "b@example.com" and detail["invoices"][0]["status"] == "paid" and "trips" not in detail  # customer facts only, never the business's own data
    assert (await client.get(f"/platform/businesses/{uuid.uuid4()}", headers=bearer(admin))).status_code == 404
    health = (await client.get("/platform/health", headers=bearer(admin))).json()
    assert health["database"] is True and "redis" in health and health["version"]


async def test_the_platform_admin_can_suspend_unsuspend_and_mark_a_bank_transfer_paid(client):
    f = await fleet(client)
    admin = await make_platform_admin(client)
    bid = (await client.get("/auth/me", headers=bearer(f.owner))).json()["business"]["id"]
    assert (await client.post(f"/platform/businesses/{bid}/suspend", headers=bearer(admin), json={"reason": "Chargeback dispute"})).json()["state"] == "suspended"
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "X"})).status_code == 402
    assert (await client.post(f"/platform/businesses/{bid}/unsuspend", headers=bearer(admin))).json()["state"] == "trialing"
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "X"})).status_code == 201
    invoice = (await client.post("/subscription/invoices", headers=bearer(f.owner))).json()
    paid = await client.post(f"/platform/invoices/{invoice['id']}/mark-paid", headers=bearer(admin), json={"method": "bank", "reference": "KCB778812"})
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    assert (await client.post(f"/platform/invoices/{invoice['id']}/mark-paid", headers=bearer(admin), json={"method": "bank", "reference": "KCB778812"})).status_code == 409
    s = await subscription(client, f.owner)
    assert s["access"]["state"] == "active" and s["invoices"][0]["payment_method"] == "bank" and s["invoices"][0]["mpesa_code"] == "KCB778812"
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert {"platform.suspended", "platform.unsuspended", "platform.invoice_marked_paid"} <= set(actions)


async def test_the_platform_console_is_for_platform_admins_only(client):
    f = await fleet(client)
    for path in ("/platform/overview", "/platform/customers", "/platform/health"):
        assert (await client.get(path, headers=bearer(f.owner))).status_code == 403, path
        assert (await client.get(path)).status_code == 401
    bid = (await client.get("/auth/me", headers=bearer(f.owner))).json()["business"]["id"]
    assert (await client.post(f"/platform/businesses/{bid}/suspend", headers=bearer(f.owner), json={"reason": "I am the owner"})).status_code == 403
    admin = await make_platform_admin(client)
    assert (await client.post(f"/platform/businesses/{bid}/extend-trial", headers=bearer(admin), json={"days": 0, "reason": "x"})).status_code == 422
    assert (await client.post(f"/platform/businesses/{bid}/suspend", headers=bearer(admin), json={"reason": "x"})).status_code == 422


# ---- text message bundles -----------------------------------------------------------------------------------------------------


async def test_a_text_bundle_is_bought_paid_for_and_used_up_without_ever_holding_a_message_back(client):
    f = await fleet(client)
    bundle = (await client.post("/subscription/sms-bundles", headers=bearer(f.owner), json={"messages": 500})).json()
    assert bundle["kind"] == "sms_bundle" and bundle["total_cents"] == 60_000 and bundle["sms_messages"] == 500
    assert (await client.post("/subscription/sms-bundles", headers=bearer(f.owner), json={"messages": 7})).json()["detail"]["code"] == "bad_bundle"
    await client.post(f"/subscription/invoices/{bundle['id']}/pay", headers=bearer(f.owner), json={"phone": "0712345678"})
    await answer_prompt(client)
    assert (await subscription(client, f.owner))["sms"] == {"credits": 500, "sent_total": 0, "sent_this_month": 0, "low": False}
    assert (await subscription(client, f.owner))["access"]["state"] == "trialing"  # a bundle is not a subscription period

    async def send(db):
        await get_sms_sender().send("+254712345678", "FleetTms: a short alert")
        await get_sms_sender().send("+254712345678", "x" * 161)  # two segments
        await get_sms_sender().send("+254712345678", "Your FleetTms code is 123456. It expires in 5 minutes.")  # the platform's cost, not counted

    await in_db(send)
    sms = (await subscription(client, f.owner))["sms"]
    assert sms["credits"] == 497 and sms["sent_total"] == 3 and sms["sent_this_month"] == 3
    assert len(get_sms_sender().outbox) >= 3


async def test_running_out_of_credits_never_stops_a_message(client):
    f = await fleet(client)

    async def send(db):
        for _ in range(60):
            await get_sms_sender().send("+254712345678", "FleetTms: alert")

    await in_db(send)
    sms = (await subscription(client, f.owner))["sms"]
    assert sms["credits"] == -60 and sms["sent_total"] == 60 and sms["low"] is True
    assert len([m for p, m in get_sms_sender().outbox if m == "FleetTms: alert"]) == 60



# ---- reminders ------------------------------------------------------------------------------------------------------------------


async def notices(at=None):
    from app import subscriptions

    async def go(db):
        return await subscriptions.send_notices(db, at)

    return await in_db(go)


async def test_the_owner_is_texted_once_when_a_trial_is_ending_then_in_grace_then_read_only(client):
    f = await fleet(client)
    from tests.leasing import set_phone

    await set_phone("owner@example.com", "+254700111222")
    get_sms_sender().outbox.clear()
    assert await notices() == 0  # fourteen days left: nothing to say yet
    await set_dates(trial_ends=days(2.5))
    assert await notices() == 1 and await notices() == 0  # once
    first = [m for p, m in get_sms_sender().outbox if p == "+254700111222"]
    assert len(first) == 1 and "free trial ends in 3 days" in first[0]
    await set_dates(trial_ends=days(-1))
    assert await notices() == 1
    assert "has run out" in [m for p, m in get_sms_sender().outbox if p == "+254700111222"][-1] and "6 more days" in [m for p, m in get_sms_sender().outbox if p == "+254700111222"][-1]
    await set_dates(trial_ends=days(-10))
    assert await notices() == 1
    assert "now read-only" in [m for p, m in get_sms_sender().outbox if p == "+254700111222"][-1] and "Nothing has been lost" in get_sms_sender().outbox[-1][1]
    assert await notices() == 0
    assert (await subscription(client, f.owner))["sms"]["sent_total"] == 0  # the platform's reminders are not charged to the business's bundle


async def test_a_paid_up_account_is_reminded_before_it_runs_out_and_paying_starts_the_cycle_again(client):
    f = await fleet(client)
    from tests.leasing import set_phone

    await set_phone("owner@example.com", "+254700111222")
    await pay_invoice(client, f.owner)
    get_sms_sender().outbox.clear()
    assert await notices() == 0
    await set_dates(paid_until=days(2))
    assert await notices() == 1 and "runs out in 2 days" in get_sms_sender().outbox[-1][1]
    await pay_invoice(client, f.owner)
    assert await notices() == 0
    await set_dates(paid_until=days(1))
    assert await notices() == 1  # a new period gets its own reminder


async def test_free_accounts_get_no_reminders(client):
    f = await fleet(client)
    admin = await make_platform_admin(client)
    bid = (await client.get("/auth/me", headers=bearer(f.owner))).json()["business"]["id"]
    await client.post(f"/platform/businesses/{bid}/complimentary", headers=bearer(admin), json={"value": True, "reason": "The pilot fleet"})
    await set_dates(trial_ends=days(-30))
    assert await notices() == 0
