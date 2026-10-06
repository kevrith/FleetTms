"""The Platform Admin console: analytics, renewals, running a customer's subscription, the invoice ledger, notes, admins, audit, inbox, status."""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app import platform_mpesa
from app.models import SubscriptionInvoice, User
from app.reminders import NAIROBI
from tests.billing_helpers import pay_invoice, subscription
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session
from tests.leasing import in_db
from tests.test_support_and_privacy import make_platform_admin


@pytest.fixture(autouse=True)
def _billing(billing):
    platform_mpesa.fake_prompts().sent.clear()


async def customer(client, name="Kamau Haulage", email="owner@example.com", plates=("KCA 123A",), phone=None):
    owner, _ = await owner_session(client, business=name, email=email, phone=phone)
    for plate in plates:
        await add_vehicle(client, owner, plate)
    bid = (await client.get("/auth/me", headers=bearer(owner))).json()["business"]["id"]
    return owner, bid


async def audit_actions(client, owner):
    return [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


def when(days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


# ---- analytics and attention -------------------------------------------------------------------------------------------------


async def test_analytics_show_revenue_growth_conversion_and_what_is_owed(client):
    paying, _ = await customer(client, "Alpha Haulage", "alpha@example.com")
    await pay_invoice(client, paying)
    await customer(client, "Bravo Transporters", "bravo@example.com", plates=("KCB 456B", "KCC 789C"))
    unpaid, _ = await customer(client, "Charlie Freight", "charlie@example.com")
    await client.post("/subscription/invoices", headers=bearer(unpaid))
    admin = await make_platform_admin(client)
    a = (await client.get("/platform/analytics?months=6", headers=bearer(admin))).json()
    k = a["kpis"]
    assert k["mrr_cents"] == 180_000 and k["arr_cents"] == 2_160_000 and k["paying"] == 1 and k["arpa_cents"] == 180_000 and k["businesses"] == 3 and k["vehicles"] == 4
    assert k["new_30d"] == 3 and k["churned_30d"] == 0 and k["collected_30d_cents"] == 180_000 and k["outstanding_cents"] == 180_000 and k["overdue_cents"] == 0
    assert a["states"] == {"active": 1, "trialing": 2}
    assert len(a["revenue"]) == 6 and a["revenue"][-1]["subscription_cents"] == 180_000 and a["revenue"][-1]["invoices"] == 1 and sum(r["subscription_cents"] for r in a["revenue"][:-1]) == 0
    assert a["signups"][-1]["count"] == 3 and a["payment_methods"] == {"mpesa": 180_000}
    assert [t["name"] for t in a["top_customers"]] == ["Alpha Haulage"] and a["vehicles_by_plan"] == {"standard": 4}
    assert (await client.get("/platform/analytics?months=1", headers=bearer(admin))).status_code == 422


async def test_trial_conversion_counts_customers_whose_trial_ended_and_who_paid(client):
    paid, paid_id = await customer(client, "Alpha Haulage", "alpha@example.com")
    await pay_invoice(client, paid)
    _, lapsed_id = await customer(client, "Bravo Transporters", "bravo@example.com")
    admin = await make_platform_admin(client)
    for bid in (paid_id, lapsed_id):  # both trials end yesterday
        r = await client.put(f"/platform/businesses/{bid}/subscription", headers=bearer(admin), json={"trial_ends_at": when(-1), "reason": "Test the numbers"})
        assert r.status_code == 200, r.text
    k = (await client.get("/platform/analytics", headers=bearer(admin))).json()["kpis"]
    assert k["past_trial"] == 2 and k["converted"] == 1 and k["trial_conversion_pct"] == 50


async def test_the_attention_list_orders_what_needs_a_person_and_links_to_it(client):
    owner, bid = await customer(client)
    invoice = (await client.post("/subscription/invoices", headers=bearer(owner))).json()
    admin = await make_platform_admin(client)
    assert (await client.get("/platform/attention", headers=bearer(admin))).json() == []
    await in_db(lambda db: db.execute(update(SubscriptionInvoice).where(SubscriptionInvoice.id == uuid.UUID(invoice["id"])).values(due_date=(datetime.now(UTC) - timedelta(days=5)).date())))
    await client.put(f"/platform/businesses/{bid}/subscription", headers=bearer(admin), json={"trial_ends_at": when(2), "reason": "Short trial"})
    items = {i["key"]: i for i in (await client.get("/platform/attention", headers=bearer(admin))).json()}
    assert items["invoices_overdue"]["count"] == 1 and items["invoices_overdue"]["link"] == "/platform/invoices?status=overdue" and items["invoices_overdue"]["severity"] == "amber"
    assert items["trials_ending"]["count"] == 1
    await client.post("/feedback", headers=bearer(owner), json={"kind": "problem", "message": "The map is slow", "app": "web"})
    assert {i["key"] for i in (await client.get("/platform/attention", headers=bearer(admin))).json()} >= {"invoices_overdue", "trials_ending", "feedback_new"}


# ---- renewals ----------------------------------------------------------------------------------------------------------------


async def test_renewals_list_overdue_first_then_the_soonest_with_money_at_risk_and_expected(client):
    _, a_id = await customer(client, "Alpha Haulage", "alpha@example.com", phone="0711000001")
    await customer(client, "Bravo Transporters", "bravo@example.com")
    _, c_id = await customer(client, "Charlie Freight", "charlie@example.com", plates=("KCB 456B", "KCC 789C"))
    _, d_id = await customer(client, "Delta Cargo", "delta@example.com")
    admin = await make_platform_admin(client)
    put = lambda bid, **body: client.put(f"/platform/businesses/{bid}/subscription", headers=bearer(admin), json={"reason": "Set up the test", **body})
    await put(a_id, paid_until=when(-3))  # grace
    await put(c_id, paid_until=when(5))  # renews soon
    await put(d_id, paid_until=when(90))  # far away
    res = (await client.get("/platform/renewals?window=30", headers=bearer(admin))).json()
    names = [r["name"] for r in res["rows"]]
    assert names[0] == "Alpha Haulage" and res["rows"][0]["category"] == "overdue" and res["rows"][0]["days_left"] <= -2
    assert names[1:] == ["Charlie Freight", "Bravo Transporters"]  # Charlie's period ends in 5 days, Bravo's trial in 14
    assert names.index("Charlie Freight") < names.index("Bravo Transporters") and "Delta Cargo" not in names
    assert res["totals"] == {"overdue": 1, "trial": 1, "renewing": 1, "expected_cents": 360_000, "at_risk_cents": 180_000}
    assert res["rows"][0]["owner"]["phone"] == "+254711000001"
    wide = (await client.get("/platform/renewals?window=120", headers=bearer(admin))).json()
    assert "Delta Cargo" in [r["name"] for r in wide["rows"]]
    assert [r["name"] for r in (await client.get("/platform/renewals?category=overdue", headers=bearer(admin))).json()["rows"]] == ["Alpha Haulage"]
    assert [r["name"] for r in (await client.get("/platform/renewals?category=trial&window=30", headers=bearer(admin))).json()["rows"]] == ["Bravo Transporters"]
    assert (await client.get("/platform/renewals?category=nonsense", headers=bearer(admin))).status_code == 422


async def test_a_free_account_is_not_in_the_renewals(client):
    _, bid = await customer(client)
    admin = await make_platform_admin(client)
    await client.post(f"/platform/businesses/{bid}/complimentary", headers=bearer(admin), json={"value": True, "reason": "Pilot"})
    assert (await client.get("/platform/renewals?window=365", headers=bearer(admin))).json()["rows"] == []


async def test_a_reminder_can_be_sent_now_but_only_when_one_is_due(client):
    from app.sms import get_sms_sender

    owner, bid = await customer(client, phone="0733555666")
    admin = await make_platform_admin(client)
    none = await client.post(f"/platform/businesses/{bid}/remind", headers=bearer(admin))
    assert none.status_code == 409 and none.json()["detail"]["code"] == "nothing_to_send"  # a new trial is not near its end
    await client.put(f"/platform/businesses/{bid}/subscription", headers=bearer(admin), json={"trial_ends_at": when(1.5), "reason": "Ending soon"})
    get_sms_sender().outbox.clear()
    sent = await client.post(f"/platform/businesses/{bid}/remind", headers=bearer(admin))
    assert sent.status_code == 200 and sent.json() == {"sent": 1, "notice": "trial_ending"}
    [(phone, text)] = [m for m in get_sms_sender().outbox if "free trial ends" in m[1]]
    assert phone == "+254733555666" and "Settings, Subscription" in text
    assert "platform.reminder_sent" in await audit_actions(client, owner)
    await client.post(f"/platform/businesses/{bid}/complimentary", headers=bearer(admin), json={"value": True, "reason": "Pilot"})
    assert (await client.post(f"/platform/businesses/{bid}/remind", headers=bearer(admin))).status_code == 409


# ---- running one customer's subscription -------------------------------------------------------------------------------------


async def test_the_subscription_detail_shows_everything_about_one_customer(client):
    owner, bid = await customer(client, plates=("KCA 123A", "KCB 456B"))
    paid = await pay_invoice(client, owner)
    admin = await make_platform_admin(client)
    d = (await client.get(f"/platform/businesses/{bid}/subscription", headers=bearer(admin))).json()
    assert d["access"]["state"] == "active" and d["subscription"]["paid_until"] and d["subscription"]["period"] == "monthly" and d["quote"]["monthly_cents"] == 360_000
    assert {v["registration"]: v["plan"] for v in d["vehicles"]} == {"KCA 123A": "standard", "KCB 456B": "standard"}
    assert [i["number"] for i in d["invoices"]] == [paid["number"]] and d["invoices"][0]["business"] == "Kamau Haulage"
    assert d["payments"][0]["method"] == "mpesa" and d["payments"][0]["status"] == "paid" and d["support_grant"] == {"active": False, "expires_at": None}
    assert d["sms"]["credits"] == 0 and d["annual_quote"]["period"] == "annual"
    assert (await client.get(f"/platform/businesses/{uuid.uuid4()}/subscription", headers=bearer(admin))).status_code == 404


async def test_a_customer_with_support_access_shows_the_grant(client):
    owner, bid = await customer(client)
    granted = await client.post("/support/grants", headers=bearer(owner), json={"reason": "Help with my invoices", "hours": 4})
    assert granted.status_code == 201, granted.text
    admin = await make_platform_admin(client)
    g = (await client.get(f"/platform/businesses/{bid}/subscription", headers=bearer(admin))).json()["support_grant"]
    assert g["active"] is True and g["expires_at"]


async def test_the_subscription_can_be_corrected_by_hand_and_every_change_is_in_the_owners_trail_with_old_and_new(client):
    owner, bid = await customer(client)
    admin = await make_platform_admin(client)
    url = f"/platform/businesses/{bid}/subscription"
    res = await client.put(url, headers=bearer(admin), json={"paid_until": when(40), "period": "annual", "payroll_enabled": True, "reason": "Paid by cheque, entered late"})
    assert res.status_code == 200, res.text
    s = res.json()["subscription"]
    assert s["period"] == "annual" and s["payroll_enabled"] is True and s["paid_until"]
    assert res.json()["access"]["state"] == "active"
    assert (await subscription(client, owner))["access"]["state"] == "active"
    entry = next(e for e in (await client.get("/audit", headers=bearer(owner))).json() if e["action"] == "platform.subscription_edited")
    assert entry["note"] == "Paid by cheque, entered late" and entry["before"]["period"] == "monthly" and entry["after"]["period"] == "annual" and entry["before"]["paid_until"] is None
    cleared = await client.put(url, headers=bearer(admin), json={"paid_until": None, "reason": "Cheque bounced"})
    assert cleared.json()["subscription"]["paid_until"] is None and cleared.json()["access"]["state"] == "trialing"
    price = await client.put(url, headers=bearer(admin), json={"custom_monthly_cents": 4_000_000, "reason": "Agreed with the owner"})
    assert price.json()["subscription"]["custom_monthly_cents"] == 4_000_000
    unset = await client.put(url, headers=bearer(admin), json={"custom_monthly_cents": None, "reason": "Deal ended"})
    assert unset.json()["subscription"]["custom_monthly_cents"] is None


async def test_a_correction_needs_a_reason_a_change_and_a_sensible_date(client):
    _, bid = await customer(client)
    admin = await make_platform_admin(client)
    url = f"/platform/businesses/{bid}/subscription"
    assert (await client.put(url, headers=bearer(admin), json={"period": "annual"})).status_code == 422  # no reason
    assert (await client.put(url, headers=bearer(admin), json={"period": "annual", "reason": "x"})).status_code == 422
    assert (await client.put(url, headers=bearer(admin), json={"reason": "Nothing sent"})).json()["detail"]["code"] == "nothing_to_change"
    assert (await client.put(url, headers=bearer(admin), json={"period": "monthly", "reason": "Already monthly"})).json()["detail"]["code"] == "no_change"
    assert (await client.put(url, headers=bearer(admin), json={"paid_until": when(366 * 6), "reason": "A typo in the year"})).json()["detail"]["code"] == "too_far"
    assert (await client.put(url, headers=bearer(admin), json={"trial_ends_at": None, "reason": "Clear the trial"})).json()["detail"]["code"] == "trial_needed"
    assert (await client.put(url, headers=bearer(admin), json={"custom_monthly_cents": 5, "reason": "Too cheap to be real"})).status_code == 422
    assert (await client.put(url, headers=bearer(admin), json={"period": "weekly", "reason": "Not a period"})).status_code == 422


async def test_the_renewal_can_be_advanced_from_the_paid_date_or_from_today_and_the_owner_can_see_it(client):
    owner, bid = await customer(client)
    paid = await pay_invoice(client, owner)
    assert paid["status"] == "paid"
    admin = await make_platform_admin(client)
    url = f"/platform/businesses/{bid}/subscription/advance"
    before = datetime.fromisoformat((await subscription(client, owner))["paid_until"])
    res = await client.post(url, headers=bearer(admin), json={"months": 2, "days": 3, "reason": "Two months for the outage"})
    assert res.status_code == 200, res.text
    after = datetime.fromisoformat(res.json()["subscription"]["paid_until"])
    assert 58 <= (after - before).days <= 66  # two calendar months and three days after the old end
    entry = next(e for e in (await client.get("/audit", headers=bearer(owner))).json() if e["action"] == "platform.subscription_advanced")
    assert entry["after"]["months"] == 2 and entry["after"]["days"] == 3 and entry["note"] == "Two months for the outage"
    await client.put(f"/platform/businesses/{bid}/subscription", headers=bearer(admin), json={"paid_until": when(-30), "reason": "Back-date to test"})
    lapsed = await client.post(url, headers=bearer(admin), json={"days": 10, "reason": "Ten days from today"})
    moved = datetime.fromisoformat(lapsed.json()["subscription"]["paid_until"])
    assert 9 <= (moved - datetime.now(UTC)).days <= 10 and lapsed.json()["access"]["state"] == "active"
    assert (await client.post(url, headers=bearer(admin), json={"reason": "Nothing to add"})).status_code == 422


async def test_advancing_a_customer_that_never_paid_starts_the_paid_period_from_today(client):
    _, bid = await customer(client)
    admin = await make_platform_admin(client)
    res = await client.post(f"/platform/businesses/{bid}/subscription/advance", headers=bearer(admin), json={"months": 1, "reason": "A free month, as promised"})
    assert res.json()["access"]["state"] == "active" and 27 <= (datetime.fromisoformat(res.json()["subscription"]["paid_until"]) - datetime.now(UTC)).days <= 31


async def test_the_platform_can_cancel_and_reactivate_a_subscription_for_the_customer(client):
    owner, bid = await customer(client)
    admin = await make_platform_admin(client)
    url = f"/platform/businesses/{bid}/subscription"
    cancelled = await client.post(f"{url}/cancel", headers=bearer(admin), json={"reason": "The owner phoned to cancel"})
    assert cancelled.status_code == 200 and cancelled.json()["subscription"]["cancelled_at"] and cancelled.json()["subscription"]["data_removed_on"]
    assert (await subscription(client, owner))["cancelled_at"]
    assert (await client.post(f"{url}/cancel", headers=bearer(admin), json={"reason": "Again"})).json()["detail"]["code"] == "already_cancelled"
    back = await client.post(f"{url}/reactivate", headers=bearer(admin), json={"reason": "They changed their mind"})
    assert back.json()["subscription"]["cancelled_at"] is None
    assert (await client.post(f"{url}/reactivate", headers=bearer(admin), json={"reason": "Again"})).json()["detail"]["code"] == "not_cancelled"
    actions = await audit_actions(client, owner)
    assert "platform.subscription_cancelled" in actions and "platform.subscription_reactivated" in actions


async def test_a_vehicles_plan_can_be_changed_and_the_price_follows(client):
    owner, bid = await customer(client, plates=("KCA 123A", "KCB 456B"))
    admin = await make_platform_admin(client)
    detail = (await client.get(f"/platform/businesses/{bid}/subscription", headers=bearer(admin))).json()
    vid = next(v["vehicle_id"] for v in detail["vehicles"] if v["registration"] == "KCB 456B")
    res = await client.put(f"/platform/businesses/{bid}/vehicles/{vid}/plan", headers=bearer(admin), json={"plan": "premium", "reason": "They asked for the fuel sensor"})
    assert res.status_code == 200, res.text
    assert res.json()["quote"]["monthly_cents"] == 180_000 + 280_000 and {v["plan"] for v in res.json()["vehicles"]} == {"standard", "premium"}
    assert (await client.put(f"/platform/businesses/{bid}/vehicles/{vid}/plan", headers=bearer(admin), json={"plan": "premium", "reason": "Again"})).json()["detail"]["code"] == "no_change"
    assert (await client.put(f"/platform/businesses/{bid}/vehicles/{uuid.uuid4()}/plan", headers=bearer(admin), json={"plan": "starter", "reason": "Unknown"})).status_code == 404
    assert (await client.put(f"/platform/businesses/{bid}/vehicles/{vid}/plan", headers=bearer(admin), json={"plan": "gold", "reason": "Not a plan"})).status_code == 422
    entry = next(e for e in (await client.get("/audit", headers=bearer(owner))).json() if e["action"] == "platform.vehicle_plan_changed")
    assert entry["before"]["plan"] == "standard" and entry["after"]["plan"] == "premium" and entry["after"]["registration"] == "KCB 456B"


async def test_the_platform_can_raise_void_and_reraise_an_invoice_and_agree_a_total(client):
    owner, bid = await customer(client)
    admin = await make_platform_admin(client)
    url = f"/platform/businesses/{bid}/invoices"
    first = await client.post(url, headers=bearer(admin), json={"reason": "Raised for them on the phone"})
    assert first.status_code == 201 and first.json()["total_cents"] == 180_000 and first.json()["status"] == "issued" and first.json()["business"] == "Kamau Haulage"
    assert (await subscription(client, owner))["open_invoice"]["id"] == first.json()["id"]
    assert (await client.post(url, headers=bearer(admin), json={"reason": "Again"})).json()["detail"]["code"] == "invoice_open"
    voided = await client.post(f"/platform/invoices/{first.json()['id']}/void", headers=bearer(admin), json={"reason": "Wrong plans on it"})
    assert voided.status_code == 200 and voided.json()["status"] == "void"
    assert (await client.post(f"/platform/invoices/{first.json()['id']}/void", headers=bearer(admin), json={"reason": "Twice"})).json()["detail"]["code"] == "not_voidable"
    deal = await client.post(url, headers=bearer(admin), json={"total_cents": 150_000, "reason": "Discount agreed with the owner"})
    assert deal.status_code == 201 and deal.json()["total_cents"] == 150_000
    mark = await client.post(f"/platform/invoices/{deal.json()['id']}/mark-paid", headers=bearer(admin), json={"method": "bank", "reference": "KCB778812"})
    assert mark.status_code == 200
    assert (await client.post(f"/platform/invoices/{deal.json()['id']}/void", headers=bearer(admin), json={"reason": "Too late"})).json()["detail"]["code"] == "not_voidable"
    actions = await audit_actions(client, owner)
    assert {"platform.invoice_raised", "platform.invoice_voided", "platform.invoice_marked_paid"} <= set(actions)
    assert (await client.post(f"/platform/invoices/{uuid.uuid4()}/void", headers=bearer(admin), json={"reason": "Unknown"})).status_code == 404


async def test_a_text_bundle_can_be_invoiced_and_a_customer_with_no_vehicles_or_a_huge_fleet_cannot_be_invoiced_by_mistake(client):
    _, bid = await customer(client)
    admin = await make_platform_admin(client)
    url = f"/platform/businesses/{bid}/invoices"
    bundle = await client.post(url, headers=bearer(admin), json={"kind": "sms_bundle", "messages": 500, "reason": "They asked for texts"})
    assert bundle.status_code == 201 and bundle.json()["kind"] == "sms_bundle" and bundle.json()["total_cents"] == 60_000
    assert (await client.post(url, headers=bearer(admin), json={"kind": "sms_bundle", "messages": 7, "reason": "Not a bundle"})).json()["detail"]["code"] == "bad_bundle"
    _, empty_id = await customer(client, "Empty Haulage", "empty@example.com", plates=())
    assert (await client.post(f"/platform/businesses/{empty_id}/invoices", headers=bearer(admin), json={"reason": "No vehicles yet"})).json()["detail"]["code"] == "no_vehicles"
    _, big_id = await customer(client, "Big Fleet", "big@example.com", plates=tuple(f"KDA {n:03d}A" for n in range(31)))
    assert (await client.post(f"/platform/businesses/{big_id}/invoices", headers=bearer(admin), json={"reason": "Fleet of 31"})).json()["detail"]["code"] == "custom_pricing"
    agreed = await client.post(f"/platform/businesses/{big_id}/invoices", headers=bearer(admin), json={"total_cents": 4_000_000, "reason": "Agreed price"})
    assert agreed.status_code == 201 and agreed.json()["total_cents"] == 4_000_000


async def test_a_businesss_name_and_kra_pin_can_be_corrected_with_the_old_value_kept(client):
    owner, bid = await customer(client)
    admin = await make_platform_admin(client)
    url = f"/platform/businesses/{bid}"
    res = await client.put(url, headers=bearer(admin), json={"name": "Kamau Haulage Ltd", "kra_pin": " p051234567k ", "reason": "Typo at sign-up"})
    assert res.status_code == 200 and res.json()["name"] == "Kamau Haulage Ltd"
    assert (await client.get(url, headers=bearer(admin))).json()["kra_pin"] == "P051234567K"
    entry = next(e for e in (await client.get("/audit", headers=bearer(owner))).json() if e["action"] == "platform.business_edited")
    assert entry["before"] == {"name": "Kamau Haulage", "kra_pin": None} and entry["after"] == {"name": "Kamau Haulage Ltd", "kra_pin": "P051234567K"}
    assert (await client.put(url, headers=bearer(admin), json={"name": "Kamau Haulage Ltd", "reason": "Same name"})).json()["detail"]["code"] == "no_change"
    assert (await client.put(url, headers=bearer(admin), json={"kra_pin": None, "reason": "Clear the PIN"})).status_code == 200
    assert (await client.put(url, headers=bearer(admin), json={"name": "X", "reason": "Too short"})).status_code == 422


# ---- the invoice ledger and exports ------------------------------------------------------------------------------------------


async def test_the_ledger_lists_every_invoice_with_filters_totals_and_paging(client):
    a, _ = await customer(client, "Alpha Haulage", "alpha@example.com")
    await pay_invoice(client, a)
    b, _ = await customer(client, "Bravo Transporters", "bravo@example.com")
    await client.post("/subscription/invoices", headers=bearer(b))
    c, c_id = await customer(client, "Charlie Freight", "charlie@example.com")
    await client.post("/subscription/sms-bundles", headers=bearer(c), json={"messages": 500})
    admin = await make_platform_admin(client)
    led = (await client.get("/platform/invoices", headers=bearer(admin))).json()
    assert led["total"] == 3 and led["pages"] == 1 and led["sums"] == {"paid": {"cents": 180_000, "count": 1}, "issued": {"cents": 240_000, "count": 2}}
    assert {r["business"] for r in led["rows"]} == {"Alpha Haulage", "Bravo Transporters", "Charlie Freight"}
    assert [r["business"] for r in (await client.get("/platform/invoices?status=paid", headers=bearer(admin))).json()["rows"]] == ["Alpha Haulage"]
    assert [r["business"] for r in (await client.get("/platform/invoices?kind=sms_bundle", headers=bearer(admin))).json()["rows"]] == ["Charlie Freight"]
    assert [r["business"] for r in (await client.get("/platform/invoices?q=bravo", headers=bearer(admin))).json()["rows"]] == ["Bravo Transporters"]
    assert [r["business"] for r in (await client.get("/platform/invoices?q=QWE1234567", headers=bearer(admin))).json()["rows"]] == ["Alpha Haulage"]  # by M-Pesa code
    assert [r["business"] for r in (await client.get(f"/platform/invoices?business_id={c_id}", headers=bearer(admin))).json()["rows"]] == ["Charlie Freight"]
    page = (await client.get("/platform/invoices?page=2&page_size=2", headers=bearer(admin))).json()
    assert page["total"] == 3 and page["pages"] == 2 and len(page["rows"]) == 1 and page["page"] == 2
    today = datetime.now(NAIROBI).date().isoformat()
    assert (await client.get(f"/platform/invoices?start={today}&end={today}", headers=bearer(admin))).json()["total"] == 3
    assert (await client.get("/platform/invoices?end=2020-01-01", headers=bearer(admin))).json()["total"] == 0
    assert (await client.get("/platform/invoices?page_size=500", headers=bearer(admin))).status_code == 422
    await in_db(lambda db: db.execute(update(SubscriptionInvoice).where(SubscriptionInvoice.number == "SUB-0001").values(due_date=(datetime.now(UTC) - timedelta(days=4)).date())), business="Bravo Transporters")
    over = (await client.get("/platform/invoices?status=overdue", headers=bearer(admin))).json()
    assert [r["business"] for r in over["rows"]] == ["Bravo Transporters"] and over["rows"][0]["overdue"] is True


async def test_the_exports_are_csv_and_a_name_that_looks_like_a_formula_is_written_as_text(client):
    owner, _ = await customer(client, '=HYPERLINK("http://evil.example","pay")', "evil@example.com")
    await pay_invoice(client, owner)
    admin = await make_platform_admin(client)
    inv = await client.get("/platform/invoices.csv", headers=bearer(admin))
    assert inv.status_code == 200 and inv.headers["content-type"].startswith("text/csv") and "fleettms-invoices.csv" in inv.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(inv.text)))
    assert rows[0][:4] == ["number", "customer", "kind", "status"] and rows[1][0] == "SUB-0001" and rows[1][1].startswith("'=HYPERLINK") and rows[1][4] == "1800.00" and rows[1][8] == "mpesa"
    cust = list(csv.reader(io.StringIO((await client.get("/platform/customers.csv", headers=bearer(admin))).text)))
    assert cust[0][0] == "name" and cust[1][0].startswith("'=HYPERLINK") and cust[1][1] == "active" and cust[1][5] == "1800.00"


# ---- notes -------------------------------------------------------------------------------------------------------------------


async def test_notes_about_a_customer_can_be_added_pinned_edited_and_deleted_and_the_owner_never_sees_them(client):
    owner, bid = await customer(client)
    admin = await make_platform_admin(client)
    url = f"/platform/businesses/{bid}/notes"
    first = await client.post(url, headers=bearer(admin), json={"body": "Owner promised payment on Friday"})
    second = await client.post(url, headers=bearer(admin), json={"body": "Wants a fuel sensor quote", "pinned": True})
    assert first.status_code == 201 and first.json()["author"] == "Kastra Support"
    listed = (await client.get(url, headers=bearer(admin))).json()
    assert [n["body"] for n in listed] == ["Wants a fuel sensor quote", "Owner promised payment on Friday"]  # pinned first
    edited = await client.put(f"/platform/notes/{first.json()['id']}", headers=bearer(admin), json={"body": "Paid on Friday, as promised", "pinned": True})
    assert edited.json()["body"] == "Paid on Friday, as promised" and edited.json()["pinned"] is True
    assert (await client.delete(f"/platform/notes/{second.json()['id']}", headers=bearer(admin))).status_code == 204
    assert [n["body"] for n in (await client.get(url, headers=bearer(admin))).json()] == ["Paid on Friday, as promised"]
    assert (await client.put(f"/platform/notes/{uuid.uuid4()}", headers=bearer(admin), json={"body": "x"})).status_code == 404
    assert (await client.delete(f"/platform/notes/{uuid.uuid4()}", headers=bearer(admin))).status_code == 404
    assert (await client.post(url, headers=bearer(admin), json={"body": ""})).status_code == 422
    assert (await client.get(f"/platform/businesses/{uuid.uuid4()}/notes", headers=bearer(admin))).status_code == 404
    assert (await client.get(url, headers=bearer(owner))).status_code == 403
    trail = str((await client.get("/audit", headers=bearer(owner))).json())
    assert "promised" not in trail and "note." not in trail  # internal: not in the owner's trail
    log = (await client.get("/platform/audit?source=platform", headers=bearer(admin))).json()["rows"]
    assert {"note.added", "note.edited", "note.deleted"} <= {r["action"] for r in log}


# ---- who runs the console ----------------------------------------------------------------------------------------------------


async def test_admins_can_be_added_by_email_listed_and_removed_but_not_yourself(client):
    owner, _ = await customer(client)
    admin = await make_platform_admin(client)
    admins = (await client.get("/platform/admins", headers=bearer(admin))).json()
    assert [(a["email"], a["you"]) for a in admins] == [("support@example.com", True)]
    assert (await client.post("/platform/admins", headers=bearer(admin), json={"email": "nobody@example.com"})).status_code == 404
    assert (await client.post("/platform/admins", headers=bearer(admin), json={"email": "SUPPORT@example.com"})).json()["detail"]["code"] == "already_admin"
    assert (await client.get("/platform/overview", headers=bearer(owner))).status_code == 403
    added = await client.post("/platform/admins", headers=bearer(admin), json={"email": "Owner@Example.com"})
    assert added.status_code == 201 and added.json()["email"] == "owner@example.com"
    assert (await client.get("/platform/overview", headers=bearer(owner))).status_code == 200  # the new admin can use the console at once
    assert len((await client.get("/platform/admins", headers=bearer(admin))).json()) == 2
    me = (await client.get("/platform/admins", headers=bearer(admin))).json()
    own_id = next(a["id"] for a in me if a["you"])
    assert (await client.delete(f"/platform/admins/{own_id}", headers=bearer(admin))).json()["detail"]["code"] == "self"
    other_id = next(a["id"] for a in me if not a["you"])
    assert (await client.delete(f"/platform/admins/{other_id}", headers=bearer(admin))).status_code == 204
    assert (await client.get("/platform/overview", headers=bearer(owner))).status_code == 403
    assert (await client.delete(f"/platform/admins/{other_id}", headers=bearer(admin))).status_code == 404
    log = {r["action"] for r in (await client.get("/platform/audit?source=platform", headers=bearer(admin))).json()["rows"]}
    assert {"admin.granted", "admin.revoked"} <= log


# ---- the audit trail ---------------------------------------------------------------------------------------------------------


async def test_the_platform_audit_lists_what_was_done_to_customers_and_by_the_platform_with_filters_and_paging(client):
    _, bid = await customer(client)
    other, other_id = await customer(client, "Other Haulage", "other@example.com")
    admin = await make_platform_admin(client)
    await client.post(f"/platform/businesses/{bid}/suspend", headers=bearer(admin), json={"reason": "Chargeback dispute"})
    await client.post(f"/platform/businesses/{bid}/unsuspend", headers=bearer(admin))
    await client.put(f"/platform/businesses/{other_id}/subscription", headers=bearer(admin), json={"period": "annual", "reason": "They prefer annual"})
    await client.post(f"/platform/businesses/{bid}/notes", headers=bearer(admin), json={"body": "Spoke to the owner"})
    log = (await client.get("/platform/audit", headers=bearer(admin))).json()
    actions = [r["action"] for r in log["rows"]]
    assert {"platform.suspended", "platform.unsuspended", "platform.subscription_edited", "note.added"} <= set(actions)
    assert actions.index("note.added") < actions.index("platform.suspended")  # newest first
    suspended = next(r for r in log["rows"] if r["action"] == "platform.suspended")
    assert suspended["business"] == "Kamau Haulage" and suspended["actor"] == "Kastra Support" and suspended["after"] == {"reason": "Chargeback dispute"} and suspended["source"] == "customer"
    only = (await client.get(f"/platform/audit?business_id={other_id}", headers=bearer(admin))).json()["rows"]
    assert [r["action"] for r in only] == ["platform.subscription_edited"] and only[0]["before"]["period"] == "monthly"
    assert {r["source"] for r in (await client.get("/platform/audit?source=platform", headers=bearer(admin))).json()["rows"]} == {"platform"}
    assert {r["action"] for r in (await client.get("/platform/audit?action=platform.susp", headers=bearer(admin))).json()["rows"]} == {"platform.suspended"}
    paged = (await client.get("/platform/audit?page=1&page_size=2", headers=bearer(admin))).json()
    assert len(paged["rows"]) == 2 and paged["total"] >= 4 and paged["pages"] >= 2
    assert "Spoke to the owner" not in str(log)  # a note's words are not in the log, only that it was written
    business_trail = [e["action"] for e in (await client.get("/audit", headers=bearer(other))).json()]
    assert "platform.suspended" not in business_trail  # another business never sees it


async def test_the_audit_only_shows_platform_and_subscription_actions_never_a_businesss_own_work(client):
    owner, _ = await customer(client)
    admin = await make_platform_admin(client)
    await client.post("/depots", headers=bearer(owner), json={"name": "North Yard"})
    prefixes = {r["action"].split(".")[0] for r in (await client.get("/platform/audit", headers=bearer(admin))).json()["rows"]}
    assert prefixes <= {"platform", "subscription", "platform_etims", "support", "note", "admin", "feedback"}
    assert "depot" not in prefixes and "vehicle" not in prefixes


# ---- the feedback inbox ------------------------------------------------------------------------------------------------------


async def test_feedback_arrives_in_the_inbox_and_can_be_marked_read_or_resolved_with_a_note(client):
    owner, _ = await customer(client)
    sent = await client.post("/feedback", headers=bearer(owner), json={"kind": "problem", "message": "The invoice total looks wrong", "page": "/invoices", "app": "web"})
    assert sent.status_code == 201
    admin = await make_platform_admin(client)
    [item] = (await client.get("/platform/feedback", headers=bearer(admin))).json()
    assert item["status"] == "new" and item["business"] == "Kamau Haulage" and item["message"] == "The invoice total looks wrong"
    url = f"/platform/feedback/{item['id']}"
    read = await client.put(url, headers=bearer(admin), json={"status": "read"})
    assert read.status_code == 200 and read.json()["status"] == "read" and read.json()["handled_at"]
    done = await client.put(url, headers=bearer(admin), json={"status": "resolved", "note": "Fixed in the next release"})
    assert done.json()["status"] == "resolved" and done.json()["note"] == "Fixed in the next release"
    [again] = (await client.get("/platform/feedback", headers=bearer(admin))).json()
    assert again["status"] == "resolved" and again["handled_note"] == "Fixed in the next release"
    reopened = await client.put(url, headers=bearer(admin), json={"status": "new"})
    assert reopened.json()["handled_at"] is None
    assert (await client.put(url, headers=bearer(admin), json={"status": "closed"})).status_code == 422
    assert (await client.put(f"/platform/feedback/{uuid.uuid4()}", headers=bearer(admin), json={"status": "read"})).status_code == 404
    assert (await client.put(url, headers=bearer(owner), json={"status": "read"})).status_code == 403


# ---- system status -----------------------------------------------------------------------------------------------------------


async def test_the_system_page_reports_readiness_the_queue_the_integrations_and_what_is_stuck(client):
    from tests.test_monitoring import worker_alive

    await worker_alive()
    admin = await make_platform_admin(client)
    s = (await client.get("/platform/system", headers=bearer(admin))).json()
    assert s["ready"] is True and s["failing"] == [] and {"database", "redis", "storage", "worker"} <= set(s["checks"])
    assert s["queue"]["worker_heartbeat_seconds"] is not None and s["queue"]["worker_heartbeat_seconds"] < 120
    assert set(s["integrations"]) == {"sms", "etims_platform", "storage", "cards", "whatsapp", "mpesa"} and s["integrations"]["storage"] == "local"
    assert s["stuck"] == {"etims_review": 0, "etims_waiting": 0, "whatsapp_failed_24h": 0, "reminders_failed_24h": 0, "card_payments_pending": 0}
    assert s["version"] and s["environment"] and s["checked_at"]


async def test_only_a_super_admin_changes_who_the_admins_are(client):
    owner, _ = await customer(client)
    admin = await make_platform_admin(client)
    assert (await client.get("/auth/me", headers=bearer(admin))).json()["is_platform_super"] is True
    assert (await client.post("/platform/admins", headers=bearer(admin), json={"email": "owner@example.com"})).status_code == 201
    listed = (await client.get("/platform/admins", headers=bearer(admin))).json()
    assert {a["email"]: a["super"] for a in listed} == {"support@example.com": True, "owner@example.com": False}

    # The new admin runs the console but cannot change who the admins are, and cannot remove the person who added them.
    assert (await client.get("/auth/me", headers=bearer(owner))).json()["is_platform_super"] is False
    assert (await client.get("/platform/overview", headers=bearer(owner))).status_code == 200
    assert (await client.get("/platform/admins", headers=bearer(owner))).status_code == 200
    super_id = next(a["id"] for a in listed if a["super"])
    removed = await client.delete(f"/platform/admins/{super_id}", headers=bearer(owner))
    assert removed.status_code == 403 and removed.json()["detail"]["code"] == "super_admin_required"
    added = await client.post("/platform/admins", headers=bearer(owner), json={"email": "support@example.com"})
    assert added.status_code == 403 and added.json()["detail"]["code"] == "super_admin_required"

    # Not even another super admin can remove a super admin through the console.
    await in_db(lambda db: db.execute(update(User).where(User.email == "owner@example.com").values(is_platform_super=True)))
    again = await client.delete(f"/platform/admins/{super_id}", headers=bearer(owner))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "super_admin"
    assert (await client.get("/platform/overview", headers=bearer(admin))).status_code == 200


# ---- only platform admins -----------------------------------------------------------------------------------------------------


async def test_none_of_the_console_routes_is_open_to_a_business_owner(client):
    owner, bid = await customer(client)
    fake = uuid.uuid4()
    routes = [
        ("GET", "/platform/analytics"), ("GET", "/platform/attention"), ("GET", "/platform/renewals"), ("GET", f"/platform/businesses/{bid}/subscription"),
        ("PUT", f"/platform/businesses/{bid}/subscription"), ("POST", f"/platform/businesses/{bid}/subscription/advance"), ("POST", f"/platform/businesses/{bid}/subscription/cancel"),
        ("POST", f"/platform/businesses/{bid}/subscription/reactivate"), ("PUT", f"/platform/businesses/{bid}/vehicles/{fake}/plan"), ("POST", f"/platform/businesses/{bid}/invoices"),
        ("POST", f"/platform/invoices/{fake}/void"), ("POST", f"/platform/businesses/{bid}/remind"), ("PUT", f"/platform/businesses/{bid}"), ("GET", "/platform/invoices"),
        ("GET", "/platform/invoices.csv"), ("GET", "/platform/customers.csv"), ("GET", f"/platform/businesses/{bid}/notes"), ("POST", f"/platform/businesses/{bid}/notes"),
        ("PUT", f"/platform/notes/{fake}"), ("DELETE", f"/platform/notes/{fake}"), ("GET", "/platform/admins"), ("POST", "/platform/admins"), ("DELETE", f"/platform/admins/{fake}"),
        ("GET", "/platform/audit"), ("PUT", f"/platform/feedback/{fake}"), ("GET", "/platform/system"),
    ]
    for method, path in routes:
        res = await client.request(method, path, headers=bearer(owner), json={} if method in ("POST", "PUT") else None)
        assert res.status_code == 403, (method, path, res.status_code)
    assert (await client.get("/platform/analytics")).status_code == 401
