from tests.helpers import bearer, owner_session, staff_session
from tests.money import business_id, c2b, configure, owner_with_client, pay_in, seed_invoice
from tests.shots import ago, fleet
from tests.test_clients import add_client
from tests.test_fuel_floats_devices import fuel_body


async def ledger(client):
    """Two clients owing across every age."""
    owner, a = await owner_with_client(client)
    b = await add_client(client, owner, name="Mombasa Cement", phone="0722000222", email="mc@example.com")
    invoices = {
        "current": await seed_invoice(a["id"], total_cents=100_000, due_in=10),
        "1_30": await seed_invoice(a["id"], total_cents=200_000, due_in=-10),
        "31_60": await seed_invoice(a["id"], total_cents=400_000, due_in=-40),
        "61_90": await seed_invoice(b["id"], total_cents=800_000, due_in=-70),
        "over_90": await seed_invoice(b["id"], total_cents=1_600_000, due_in=-120),
    }
    return owner, a, b, invoices


async def test_debtors_are_aged_from_the_due_date_per_client_and_in_total(client):
    owner, _a, _b, _ = await ledger(client)
    res = (await client.get("/debtors", headers=bearer(owner))).json()
    assert res["buckets"] == {"current": 100_000, "1_30": 200_000, "31_60": 400_000, "61_90": 800_000, "over_90": 1_600_000}
    assert res["balance_cents"] == 3_100_000 and res["overdue_cents"] == 3_000_000
    first, second = res["clients"]
    assert first["name"] == "Mombasa Cement" and first["overdue_cents"] == 2_400_000 and first["oldest_days_late"] == 120  # worst payer first
    assert second["name"] == "Bamburi Cement" and second["balance_cents"] == 700_000 and second["buckets"]["current"] == 100_000 and second["invoices"] == 3


async def test_paid_and_voided_invoices_leave_the_debtors_and_part_payments_reduce_them(client):
    owner, _a, _b, inv = await ledger(client)
    pay = lambda i, cents: client.post(f"/invoices/{inv[i]['id']}/payments", headers=bearer(owner), json={"amount_cents": cents, "method": "cash"})
    assert (await pay("over_90", 1_600_000)).status_code == 201  # paid in full
    assert (await pay("31_60", 150_000)).status_code == 201  # part
    assert (await client.post(f"/invoices/{inv['61_90']['id']}/void", headers=bearer(owner), json={"reason": "Raised in error"})).status_code == 200
    res = (await client.get("/debtors", headers=bearer(owner))).json()
    assert res["buckets"] == {"current": 100_000, "1_30": 200_000, "31_60": 250_000, "61_90": 0, "over_90": 0}
    assert [c["name"] for c in res["clients"]] == ["Bamburi Cement"]  # Mombasa Cement owes nothing now
    assert res["clients"][0]["last_payment_on"]


async def test_one_clients_statement_lists_open_invoices_payments_and_reminders(client):
    owner, a, _b, inv = await ledger(client)
    await client.post(f"/invoices/{inv['1_30']['id']}/payments", headers=bearer(owner), json={"amount_cents": 50_000, "method": "cheque", "reference": "000123"})
    res = (await client.get(f"/debtors/{a['id']}", headers=bearer(owner))).json()
    assert res["client"]["name"] == "Bamburi Cement" and res["balance_cents"] == 650_000
    assert [(i["number"], i["bucket"], i["days_late"]) for i in res["invoices"]] == [("INV-0003", "31_60", 40), ("INV-0002", "1_30", 10), ("INV-0001", "current", 0)]
    assert [(p["invoice_number"], p["method"], p["amount_cents"], p["reference"]) for p in res["payments"]] == [("INV-0002", "cheque", 50_000, "000123")]
    sent = await client.post(f"/invoices/{inv['1_30']['id']}/remind", headers=bearer(owner), json={"channels": ["sms"]})
    assert sent.status_code == 200
    again = (await client.get(f"/debtors/{a['id']}", headers=bearer(owner))).json()
    assert [(r["invoice_number"], r["channel"], r["automatic"]) for r in again["reminders"]] == [("INV-0002", "sms", False)]
    assert (await client.get("/debtors/00000000-0000-0000-0000-000000000000", headers=bearer(owner))).status_code == 404


async def test_debtors_are_for_owner_and_accountant_and_never_cross_businesses(client):
    owner, a, _b, _ = await ledger(client)
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert len((await client.get("/debtors", headers=bearer(accountant))).json()["clients"]) == 2
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.get("/debtors", headers=bearer(manager))).status_code == 403
    assert (await client.get(f"/debtors/{a['id']}", headers=bearer(manager))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/debtors", headers=bearer(other))).json()["clients"] == []
    assert (await client.get(f"/debtors/{a['id']}", headers=bearer(other))).status_code == 404


# ---- the dashboard ----------------------------------------------------------------------------------------------------


async def test_the_dashboard_shows_money_owed_and_late_debt_to_those_who_may_see_it(client):
    owner, _a, _b, _ = await ledger(client)
    dash = (await client.get("/dashboard", headers=bearer(owner))).json()
    assert dash["numbers"]["money_owed_cents"] == 3_100_000
    assert dash["numbers"]["income_today_cents"] == 3_100_000  # everything was invoiced today
    late = next(x for x in dash["alerts"] if x["kind"] == "debt_late")
    assert late["severity"] == "red" and "24,000.00" in late["title"]  # 8,000 + 16,000 is more than 60 days late
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    seen = (await client.get("/dashboard", headers=bearer(manager))).json()
    assert seen["numbers"]["money_owed_cents"] is None and seen["profit_vs_cash"] is None and "debt_late" not in [x["kind"] for x in seen["alerts"]]


async def test_profit_against_cash_this_month(client):
    f = await fleet(client)
    await configure(client, f.owner)
    c = await add_client(client, f.owner, billing_method="per_trip", rate_cents=1_000_000)
    inv = await seed_invoice(c["id"], total_cents=1_160_000, vat_pct=16)  # 10,000 plus 1,600 VAT
    await seed_invoice(c["id"], total_cents=500_000, due_in=-5)
    assert (await client.post(f"/invoices/{inv['id']}/payments", headers=bearer(f.owner), json={"amount_cents": 400_000, "method": "cash"})).status_code == 201
    assert (await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code=None, captured_at=ago(minutes=30)))).status_code == 201  # 22,200
    assert (await client.post("/expenses", headers=bearer(f.driver), json={"category": "toll", "amount_cents": 50_000})).status_code == 201
    m = (await client.get("/dashboard", headers=bearer(f.owner))).json()["profit_vs_cash"]
    assert m["billed_cents"] == 1_000_000 + 500_000  # VAT is not income
    assert m["costs_cents"] == 2_220_000 + 50_000
    assert m["profit_cents"] == 1_500_000 - 2_270_000
    assert m["received_cents"] == 400_000 and m["cash_cents"] == 400_000 - 2_270_000
    assert m["owed_cents"] == 1_160_000 - 400_000 + 500_000


async def test_a_paid_invoice_stops_counting_as_owed_and_a_mpesa_payment_waiting_is_flagged(client):
    owner, c = await owner_with_client(client)
    await configure(client, owner)
    inv = await seed_invoice(c["id"], total_cents=100_000)
    await pay_in(client, await business_id(), c2b(amount="1000.00", bill_ref=inv["number"]))
    await pay_in(client, await business_id(), c2b(trans_id="AAA0000009", amount="50.00", bill_ref=""))
    dash = (await client.get("/dashboard", headers=bearer(owner))).json()
    assert dash["numbers"]["money_owed_cents"] == 0
    waiting = next(x for x in dash["alerts"] if x["kind"] == "mpesa_unmatched")
    assert waiting["severity"] == "amber" and "1 M-Pesa payment" in waiting["title"] and waiting["link"] == "/clients/payments"
