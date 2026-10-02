
from app.models import ExpenseCategory
from app.report_delivery import fake_sender
from tests.helpers import bearer
from tests.leasing import (
    lease_body,
    lease_setup,
    lessor_login,
    make_lease,
    moment,
    month_start,
    seed_client,
    seed_crew,
    seed_expense,
    seed_fuel,
    seed_staff,
    seed_trip,
)

MONTH = lambda offset=0: month_start(offset).isoformat()


async def profit_row(client, owner, vehicle, offset=0):
    res = await client.get(f"/profit?from_month={MONTH(offset)}&to_month={MONTH(offset)}", headers=bearer(owner))
    assert res.status_code == 200, res.text
    return next(v for v in res.json()["vehicles"] if v["vehicle_id"] == vehicle["id"]), res.json()


async def worked_example(client):
    """Masterplan 5.23: revenue 600,000; fuel 230,000; trip expenses 40,000; crew 55,000; maintenance 15,000; a 20,000 engine repair the
    operator paid for the lessor; lease of 30 percent of revenue."""
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party)
    driver = await seed_staff(client, owner, "Driver", "0712345678", salary_cents=3_500_000)
    turnboy = await seed_staff(client, owner, "Turnboy", "0722345678", role="turnboy", salary_cents=2_000_000)
    await seed_crew(vehicle["id"], driver, 3_500_000)
    await seed_crew(vehicle["id"], turnboy, 2_000_000, role="turnboy")
    client_id = await seed_client()
    for _ in range(3):
        await seed_trip(vehicle["id"], revenue_cents=20_000_000, client_id=client_id, at=moment(0, 1))
    await seed_fuel(vehicle["id"], 23_000_000, moment(0, 1))
    await seed_expense(vehicle["id"], 4_000_000, ExpenseCategory.TOLL, moment(0, 1))
    await seed_expense(vehicle["id"], 1_500_000, ExpenseCategory.SERVICE, moment(0, 1), note="Oil change")
    repair = await seed_expense(vehicle["id"], 2_000_000, ExpenseCategory.REPAIR, moment(0, 1), note="Engine repair")
    return owner, vehicle, party, lease, repair


# ---- agreements -------------------------------------------------------------------------------------------------------


async def test_a_lease_needs_the_right_vehicle_party_and_terms(client):
    owner, vehicle, party = await lease_setup(client)
    post = lambda **kw: client.post("/leases", headers=bearer(owner), json={**lease_body(vehicle, party), **kw})
    assert (await post(revenue_pct=0)).status_code == 422  # charges nothing
    assert (await post(fixed_cents=100)).status_code == 422  # a fixed amount needs its period
    assert (await post(fixed_period="month")).status_code == 422
    assert (await post(end_date=MONTH(-5))).status_code == 422
    assert (await post(responsibilities={"wheels": "lessor"})).status_code == 422
    owned = (await client.post("/vehicles", headers=bearer(owner), json={"registration": "KCB 111A", "make": "Isuzu", "model": "FVR", "tank_litres": 100, "odometer_km": 1})).json()
    assert (await post(vehicle_id=owned["id"])).json()["detail"]["code"] == "wrong_ownership"
    other_party = (await client.post("/parties", headers=bearer(owner), json={"kind": "lessor", "name": "Someone Else"})).json()
    assert (await post(party_id=other_party["id"])).json()["detail"]["code"] == "wrong_party"
    lease = await post()
    assert lease.status_code == 201 and lease.json()["responsibilities"]["major_repairs"] == "lessor" and lease.json()["responsibilities"]["fuel"] == "lessee"
    assert (await post()).json()["detail"]["code"] == "lease_exists"  # one running lease per lorry
    assert "lease.created" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_changing_terms_is_audited_and_an_ended_lease_cannot_change(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party)
    body = lease_body(vehicle, party, revenue_pct=35, responsibilities={"fuel": "lessor"})
    changed = await client.put(f"/leases/{lease['id']}", headers=bearer(owner), json=body)
    assert changed.status_code == 200 and changed.json()["revenue_pct"] == 35 and changed.json()["responsibilities"]["fuel"] == "lessor"
    audit = next(e for e in (await client.get("/audit", headers=bearer(owner))).json() if e["action"] == "lease.updated")
    assert audit["before"]["revenue_pct"] == "30.00" or audit["before"]["revenue_pct"] == 30 or "30" in str(audit["before"]["revenue_pct"])
    assert (await client.post(f"/leases/{lease['id']}/end", headers=bearer(owner), json={})).json()["status"] == "ended"
    assert (await client.put(f"/leases/{lease['id']}", headers=bearer(owner), json=body)).status_code == 409
    assert (await client.post(f"/leases/{lease['id']}/end", headers=bearer(owner), json={})).status_code == 409
    again = await client.post("/leases", headers=bearer(owner), json=lease_body(vehicle, party))  # a new lease can follow
    assert again.status_code == 201


# ---- the worked example (acceptance) ------------------------------------------------------------------------------------


async def test_the_masterplan_worked_example_gives_260000_160000_and_100000(client):
    owner, vehicle, _party, lease, _ = await worked_example(client)
    row, report = await profit_row(client, owner, vehicle)
    assert row["revenue"] == 60_000_000 and row["fuel"] == 23_000_000 and row["expenses"] == 5_500_000 and row["crew"] == 5_500_000
    assert row["operating"] == 34_000_000 and row["gross"] == 26_000_000  # gross profit KES 260,000
    assert row["lease_charges"] == 18_000_000 and row["lease_offsets"] == 2_000_000 and row["lease_payable"] == 16_000_000  # lease payable KES 160,000
    assert row["net"] == 10_000_000  # net profit KES 100,000
    assert row["lessor_paid"] == 2_000_000 and row["trips"] == 3
    assert report["business"]["net"] == 10_000_000
    # working the month out for real books the same numbers in the lease ledger
    run = await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH()})
    assert run.status_code == 200, run.text
    assert run.json()["charge"]["amount_cents"] == 18_000_000 and run.json()["charge"]["basis"]["revenue_share_cents"] == 18_000_000
    [offset] = run.json()["offsets"]
    assert offset["amount_cents"] == -2_000_000 and offset["source_kind"] == "expense" and "Engine repair" in offset["description"]
    detail = (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()
    assert detail["balance_cents"] == 16_000_000
    row2, _ = await profit_row(client, owner, vehicle)
    assert row2["net"] == 10_000_000  # the same once the ledger holds the month


async def test_running_a_month_again_does_not_double_the_offsets_and_picks_up_new_costs(client):
    owner, vehicle, _party, lease, _ = await worked_example(client)
    run = lambda: client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH()})
    await run()
    again = await run()
    assert again.json()["offsets"] == []
    await seed_expense(vehicle["id"], 500_000, ExpenseCategory.REPAIR, moment(0, 1), note="Gearbox seal")
    third = await run()
    assert [o["amount_cents"] for o in third.json()["offsets"]] == [-500_000]
    detail = (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()
    assert detail["balance_cents"] == 18_000_000 - 2_500_000
    assert len([e for e in detail["entries"] if e["kind"] == "charge"]) == 1


async def test_the_operators_own_costs_are_not_offset_and_the_matrix_can_be_changed(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party, responsibilities={"routine_service": "lessor", "major_repairs": "lessee"})
    await seed_expense(vehicle["id"], 1_000_000, ExpenseCategory.SERVICE, moment(0, 1))
    await seed_expense(vehicle["id"], 3_000_000, ExpenseCategory.REPAIR, moment(0, 1))
    await seed_expense(vehicle["id"], 200_000, ExpenseCategory.TOLL, moment(0, 1))
    run = (await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH()})).json()
    assert [o["amount_cents"] for o in run["offsets"]] == [-1_000_000]  # only the service: this lease makes the repair the operator's
    row, _ = await profit_row(client, owner, vehicle)
    assert row["expenses"] == 3_200_000 and row["lessor_paid"] == 1_000_000


async def test_an_expense_that_is_not_counted_yet_is_not_offset(client):
    from app.models import ExpenseStatus

    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party)
    await seed_expense(vehicle["id"], 2_000_000, ExpenseCategory.REPAIR, moment(0, 1), status=ExpenseStatus.AWAITING_APPROVAL)
    run = (await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH()})).json()
    assert run["offsets"] == []


# ---- payment models (acceptance) ----------------------------------------------------------------------------------------


async def test_a_minimum_guarantee_charges_the_guarantee_in_a_slow_month_and_the_share_in_a_busy_one(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party, min_guarantee_cents=12_000_000)
    client_id = await seed_client()
    await seed_trip(vehicle["id"], revenue_cents=30_000_000, client_id=client_id, at=moment(-2, 5))  # slow: 30% is 90,000
    for _ in range(2):
        await seed_trip(vehicle["id"], revenue_cents=30_000_000, client_id=client_id, at=moment(-1, 5))  # busy: 30% of 600,000 is 180,000
    slow = (await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-2)})).json()["charge"]
    busy = (await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-1)})).json()["charge"]
    assert slow["amount_cents"] == 12_000_000 and slow["basis"]["guarantee_applied"] is True and slow["basis"]["revenue_share_cents"] == 9_000_000
    assert busy["amount_cents"] == 18_000_000 and busy["basis"]["guarantee_applied"] is False


async def test_fixed_per_trip_per_km_and_profit_share_models(client):
    owner, vehicle, party = await lease_setup(client)
    client_id = await seed_client()
    for _ in range(4):
        await seed_trip(vehicle["id"], revenue_cents=5_000_000, client_id=client_id, at=moment(-1, 5), km=500)
    cases = [
        ({"revenue_pct": 0, "fixed_cents": 12_000_000, "fixed_period": "month"}, 12_000_000),
        ({"revenue_pct": 0, "per_trip_cents": 1_000_000}, 4_000_000),
        ({"revenue_pct": 0, "per_km_cents": 2_000}, 4_000_000),
        ({"revenue_pct": 0, "profit_pct": 50}, 10_000_000),  # half of the 20,000,000 earned, nothing else was spent
        ({"revenue_pct": 5, "fixed_cents": 1_000_000, "fixed_period": "month"}, 2_000_000),
    ]
    for terms, expected in cases:
        lease = await make_lease(client, owner, vehicle, party, **terms)
        got = (await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-1)})).json()["charge"]["amount_cents"]
        assert got == expected, terms
        await client.post(f"/leases/{lease['id']}/end", headers=bearer(owner), json={})


async def test_a_month_before_the_agreement_or_in_the_future_cannot_be_run(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party, start_date=MONTH(-1))
    run = lambda m: client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": m})
    assert (await run(MONTH(-3))).json()["detail"]["code"] == "outside_agreement"
    assert (await run(MONTH(1))).json()["detail"]["code"] == "future_month"


# ---- the ledger: payments, overdue, adjustments ---------------------------------------------------------------------------


async def test_payments_reduce_the_balance_and_mpesa_codes_are_not_reused(client):
    owner, vehicle, _party, lease, _ = await worked_example(client)
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH()})
    pay = lambda **kw: client.post(f"/leases/{lease['id']}/payments", headers=bearer(owner), json={"amount_cents": 10_000_000, "method": "mpesa", "mpesa_code": "lsa1111111", **kw})
    first = await pay()
    assert first.status_code == 201 and first.json()["amount_cents"] == -10_000_000 and first.json()["mpesa_code"] == "LSA1111111"
    assert (await pay()).json()["detail"]["code"] == "duplicate_mpesa_code"
    assert (await pay(mpesa_code="bad")).status_code == 422
    detail = (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()
    assert detail["balance_cents"] == 6_000_000
    bank = await client.post(f"/leases/{lease['id']}/payments", headers=bearer(owner), json={"amount_cents": 6_000_000, "method": "bank", "reference": "RTGS 8841"})
    assert bank.status_code == 201
    assert (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()["balance_cents"] == 0
    # the same code cannot be used as a fuel claim either
    f = await client.post("/fuel", headers=bearer(owner), json={"vehicle_id": vehicle["id"], "litres": "10", "price_per_litre_cents": 100, "amount_cents": 1000, "mpesa_code": "LSA1111111"})
    assert f.status_code == 409


async def test_a_charge_past_its_due_date_is_overdue_and_shows_on_the_dashboard(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party, revenue_pct=0, fixed_cents=10_000_000, fixed_period="month", payment_due_days=7)
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-2)})  # due a month and more ago
    detail = (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()
    assert detail["balance_cents"] == 10_000_000 and detail["overdue_cents"] == 10_000_000
    dash = (await client.get("/dashboard", headers=bearer(owner))).json()
    [alert] = [a for a in dash["alerts"] if a["kind"] == "lease_overdue"]
    assert alert["severity"] == "red" and "100,000.00" in alert["title"]
    await client.post(f"/leases/{lease['id']}/payments", headers=bearer(owner), json={"amount_cents": 10_000_000, "method": "cash"})
    after = (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()
    assert after["overdue_cents"] == 0 and after["balance_cents"] == 0
    assert "lease_overdue" not in [a["kind"] for a in (await client.get("/dashboard", headers=bearer(owner))).json()["alerts"]]


async def test_an_adjustment_corrects_the_account_with_a_reason(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party, revenue_pct=0, fixed_cents=10_000_000, fixed_period="month")
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-1)})
    adj = lambda **kw: client.post(f"/leases/{lease['id']}/adjustments", headers=bearer(owner), json={"amount_cents": -500_000, "reason": "Disputed charge waived", **kw})
    assert (await adj()).status_code == 201
    assert (await adj(amount_cents=0)).status_code == 422
    assert (await adj(reason="x")).status_code == 422
    assert (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()["balance_cents"] == 9_500_000
    assert "lease.adjustment" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


# ---- statements and the lessor portal (acceptance) ---------------------------------------------------------------------


async def test_a_lease_statement_shows_the_charge_offsets_payments_and_balance_and_can_be_sent(client):
    owner, _vehicle, _party, lease, _ = await worked_example(client)
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH()})
    await client.post(f"/leases/{lease['id']}/payments", headers=bearer(owner), json={"amount_cents": 4_000_000, "method": "cash"})
    st = (await client.get(f"/leases/{lease['id']}/statement?month={MONTH()}", headers=bearer(owner))).json()
    assert st["vehicle"] == "KDB 404D" and st["party"] == "Wanjiku Transporters" and st["opening_balance_cents"] == 0
    assert [(ln["kind"], ln["amount_cents"]) for ln in st["lines"]] == [("charge", 18_000_000), ("offset", -2_000_000), ("payment", -4_000_000)]
    assert st["closing_balance_cents"] == 12_000_000 and st["usage"] == {"revenue_cents": 60_000_000} and st["trip_count"] == 3  # revenue is shown because the lease is a revenue share
    pdf = await client.get(f"/leases/{lease['id']}/statement.pdf?month={MONTH()}", headers=bearer(owner))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    fake_sender("whatsapp").outbox.clear()
    sent = await client.post(f"/leases/{lease['id']}/statement/send", headers=bearer(owner), json={"month": MONTH(), "channel": "whatsapp"})
    assert sent.status_code == 200 and fake_sender("whatsapp").outbox[0]["recipient"] == "+254711000111"
    mail = await client.post(f"/leases/{lease['id']}/statement/send", headers=bearer(owner), json={"month": MONTH(), "channel": "email"})
    assert mail.json()["to"] == "lessor@example.com"
    nobody = (await client.post("/parties", headers=bearer(owner), json={"kind": "lessor", "name": "No Contacts"})).json()
    assert nobody["id"]


async def test_next_months_statement_carries_the_balance_forward(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party, revenue_pct=0, fixed_cents=10_000_000, fixed_period="month")
    for offset in (-2, -1):
        await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(offset)})
    st = (await client.get(f"/leases/{lease['id']}/statement?month={MONTH(-1)}", headers=bearer(owner))).json()
    assert st["opening_balance_cents"] == 10_000_000 and st["closing_balance_cents"] == 20_000_000


async def test_a_lessor_logs_in_and_sees_only_their_own_lorrys_statement(client):
    owner, _vehicle, party, lease, _ = await worked_example(client)
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH()})
    # a second lessor with their own lorry
    party2 = (await client.post("/parties", headers=bearer(owner), json={"kind": "lessor", "name": "Other Owner"})).json()
    from tests.fleet import add_vehicle

    vehicle2 = await add_vehicle(client, owner, "KDC 505E", ownership_type="leased_in", party_id=party2["id"])
    lease2 = await make_lease(client, owner, vehicle2, party2)
    lessor = await lessor_login(client, owner, party)
    mine = (await client.get("/portal/leases", headers=bearer(lessor))).json()
    assert [m["registration"] for m in mine] == ["KDB 404D"] and mine[0]["balance_cents"] == 18_000_000 - 2_000_000
    detail = await client.get(f"/portal/leases/{lease['id']}", headers=bearer(lessor))
    assert detail.status_code == 200 and "service_history" in detail.json() and "inspections" in detail.json()
    assert all(e["basis"] is None for e in detail.json()["entries"])
    assert (await client.get(f"/portal/leases/{lease2['id']}", headers=bearer(lessor))).status_code == 404  # another lessor's lorry does not exist for them
    assert (await client.get(f"/portal/leases/{lease2['id']}/statement?month={MONTH()}", headers=bearer(lessor))).status_code == 404
    assert (await client.get(f"/portal/leases/{lease2['id']}/statement.pdf?month={MONTH()}", headers=bearer(lessor))).status_code == 404
    st = (await client.get(f"/portal/leases/{lease['id']}/statement?month={MONTH()}", headers=bearer(lessor))).json()
    assert st["closing_balance_cents"] == 16_000_000 and st["trips"] == [] and st["usage"] == {"revenue_cents": 60_000_000}
    assert all("source" not in (ln["basis"] or {}) for ln in st["lines"])
    pdf = await client.get(f"/portal/leases/{lease['id']}/statement.pdf?month={MONTH()}", headers=bearer(lessor))
    assert pdf.content.startswith(b"%PDF")
    # and nothing else in the business
    for path in ("/leases", "/profit", "/finance", "/vehicles", "/invoices", "/dashboard", "/staff", "/payroll/runs", "/clients"):
        assert (await client.get(path, headers=bearer(lessor))).status_code == 403, path


async def test_the_lessor_sees_trips_only_when_the_agreement_allows_it(client):
    owner, vehicle, party, lease, _ = await worked_example(client)
    await client.put(f"/leases/{lease['id']}", headers=bearer(owner), json=lease_body(vehicle, party, share_trips=True))
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH()})
    lessor = await lessor_login(client, owner, party)
    st = (await client.get(f"/portal/leases/{lease['id']}/statement?month={MONTH()}", headers=bearer(lessor))).json()
    assert len(st["trips"]) == 3 and st["trips"][0]["route"] == "Mombasa to Nairobi"


async def test_a_lessor_login_must_name_a_lessor_and_cannot_have_other_roles(client):
    owner, _vehicle, party = await lease_setup(client)
    invite = lambda **kw: client.post("/users", headers=bearer(owner), json={"name": "Lessor Person", "email": "l@example.com", "roles": ["lessor"], **kw})
    assert (await invite()).json()["detail"]["code"] == "party_required"
    lessee = (await client.post("/parties", headers=bearer(owner), json={"kind": "lessee", "name": "A Lessee"})).json()
    assert (await invite(party_id=lessee["id"])).json()["detail"]["code"] == "party_required"
    mixed = await client.post("/users", headers=bearer(owner), json={"name": "Lessor Person", "email": "l@example.com", "roles": ["lessor", "manager"], "party_id": party["id"]})
    assert mixed.json()["detail"]["code"] == "lessor_only"
    stray = await client.post("/users", headers=bearer(owner), json={"name": "Manager Person", "email": "m@example.com", "roles": ["manager"], "party_id": party["id"]})
    assert stray.json()["detail"]["code"] == "party_not_allowed"
    ok = await invite(party_id=party["id"])
    assert ok.status_code == 201 and ok.json()["party_id"] == party["id"]
    assert (await client.put(f"/users/{ok.json()['membership_id']}/roles", headers=bearer(owner), json={"roles": ["manager"]})).json()["detail"]["code"] == "lessor_login"


# ---- leased out -----------------------------------------------------------------------------------------------------------


async def test_a_leased_out_lorry_earns_lease_income_and_the_lessee_owes_a_balance(client):
    owner, vehicle, party = await lease_setup(client, direction="out", party_name="Rift Valley Quarries", registration="KDC 505E")
    lease = await make_lease(client, owner, vehicle, party, direction="out", revenue_pct=0, fixed_cents=15_000_000, fixed_period="month")
    await seed_expense(vehicle["id"], 1_000_000, ExpenseCategory.INSURANCE, moment(-1, 5))
    run = await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-1)})
    assert run.json()["charge"]["amount_cents"] == 15_000_000 and run.json()["offsets"] == []
    row, _ = await profit_row(client, owner, vehicle, offset=-1)
    assert row["revenue"] == 15_000_000 and row["lease_income"] == 15_000_000 and row["operating"] == 1_000_000 and row["net"] == 14_000_000  # income less what we still paid
    detail = (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()
    assert detail["direction"] == "out" and detail["balance_cents"] == 15_000_000
    paid = await client.post(f"/leases/{lease['id']}/payments", headers=bearer(owner), json={"amount_cents": 15_000_000, "method": "mpesa", "mpesa_code": "LES2222222"})
    assert paid.json()["description"].startswith("Received from")
    assert (await client.get(f"/leases/{lease['id']}", headers=bearer(owner))).json()["balance_cents"] == 0


async def test_a_leased_out_lease_that_charges_by_use_needs_the_lessees_figures(client):
    owner, vehicle, party = await lease_setup(client, direction="out", party_name="Rift Valley Quarries", registration="KDC 505E")
    lease = await make_lease(client, owner, vehicle, party, direction="out", revenue_pct=10)
    run = lambda **kw: client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-1), **kw})
    assert (await run()).json()["detail"]["code"] == "report_needed"
    got = await run(reported={"revenue_cents": 50_000_000})
    assert got.json()["charge"]["amount_cents"] == 5_000_000 and got.json()["charge"]["basis"]["source"] == "reported"
    swept = await client.post("/leases/run-month", headers=bearer(owner), json={"month": MONTH(-1)})
    assert swept.json()["done"] == 0 and len(swept.json()["waiting_for_lessee_figures"]) == 1
