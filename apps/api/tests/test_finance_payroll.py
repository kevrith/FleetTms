import uuid
from datetime import UTC, datetime

from app.models import ExpenseCategory, FinePayer, Incident, IncidentType
from app.payroll_service import allocate_salary
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import in_db, moment, month_start, seed_crew, seed_expense, seed_staff

MONTH = lambda offset=0: month_start(offset).isoformat()


async def loan_setup(client, business="Kamau Haulage"):
    owner, _ = await owner_session(client, business, "owner@kamau.example")
    lender = (await client.post("/parties", headers=bearer(owner), json={"kind": "lender", "name": "Equity Asset Finance"})).json()
    vehicle = await add_vehicle(client, owner, "KDA 303C", ownership_type="asset_financed", party_id=lender["id"])
    return owner, vehicle, lender


def loan_body(vehicle, lender, **extra):
    return {"vehicle_id": vehicle["id"], "party_id": lender["id"], "principal_cents": 100_000_000, "annual_rate_pct": 12, "months": 12, "first_due": MONTH(1), "reference": "LN-2201", **extra}


# ---- asset finance ---------------------------------------------------------------------------------------------------


async def test_a_loan_gets_its_repayment_schedule(client):
    owner, vehicle, lender = await loan_setup(client)
    res = await client.post("/finance", headers=bearer(owner), json=loan_body(vehicle, lender))
    assert res.status_code == 201, res.text
    loan = res.json()
    assert loan["instalment_cents"] == 8_884_879 and len(loan["schedule"]) == 12 and loan["principal_balance_cents"] == 100_000_000
    assert loan["schedule"][0]["interest_cents"] == 1_000_000 and loan["schedule"][-1]["principal_cents"] + sum(r["principal_cents"] for r in loan["schedule"][:-1]) == 100_000_000
    assert loan["outstanding_cents"] == sum(r["amount_cents"] for r in loan["schedule"]) and loan["total_interest_cents"] == sum(r["interest_cents"] for r in loan["schedule"])
    manual = await client.post("/finance", headers=bearer(owner), json=loan_body(vehicle, lender, instalment_cents=9_000_000))
    assert manual.json()["instalment_cents"] == 9_000_000 and manual.json()["schedule"][0]["amount_cents"] == 9_000_000


async def test_a_loan_needs_a_financed_vehicle_and_its_lender(client):
    owner, vehicle, lender = await loan_setup(client)
    owned = await add_vehicle(client, owner, "KDA 404D")
    assert (await client.post("/finance", headers=bearer(owner), json=loan_body(owned, lender))).json()["detail"]["code"] == "wrong_ownership"
    assert (await client.post("/finance", headers=bearer(owner), json=loan_body(vehicle, lender, months=0))).status_code == 422
    assert (await client.post("/finance", headers=bearer(owner), json=loan_body(vehicle, lender, principal_cents=0))).status_code == 422


async def test_repayments_are_ticked_off_in_part_or_in_full_and_the_loan_closes(client):
    owner, vehicle, lender = await loan_setup(client)
    loan = (await client.post("/finance", headers=bearer(owner), json=loan_body(vehicle, lender, months=2, annual_rate_pct=0))).json()
    pay = lambda n, **kw: client.post(f"/finance/{loan['id']}/instalments/{n}/pay", headers=bearer(owner), json={"method": "mpesa", **kw})
    part = await pay(1, amount_cents=20_000_000, mpesa_code="fin1111111")
    assert part.status_code == 200 and part.json()["schedule"][0]["paid_cents"] == 20_000_000 and part.json()["schedule"][0]["mpesa_code"] == "FIN1111111"
    assert (await pay(1, amount_cents=40_000_000)).json()["detail"]["code"] == "overpayment"
    assert (await pay(1, mpesa_code="FIN2222222")).json()["detail"]["code"] == "duplicate_mpesa_code"  # one code per instalment
    assert (await pay(2, mpesa_code="FIN1111111")).json()["detail"]["code"] == "duplicate_mpesa_code"  # and codes are never reused
    assert (await pay(9)).status_code == 404
    rest = await pay(1)
    assert rest.json()["schedule"][0]["paid_cents"] == 50_000_000 and rest.json()["principal_balance_cents"] == 50_000_000 and rest.json()["status"] == "active"
    assert (await pay(1)).json()["detail"]["code"] == "paid"
    done = await pay(2)
    assert done.json()["status"] == "closed" and done.json()["outstanding_cents"] == 0 and done.json()["principal_balance_cents"] == 0
    assert "finance.repayment" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_a_repayment_past_due_is_overdue_and_a_loan_counts_against_the_lorrys_profit(client):
    owner, vehicle, lender = await loan_setup(client)
    loan = (await client.post("/finance", headers=bearer(owner), json=loan_body(vehicle, lender, first_due=MONTH(), months=3, annual_rate_pct=0))).json()
    assert loan["overdue_cents"] == 33_333_333 and loan["schedule"][0]["overdue"] is True
    dash = (await client.get("/dashboard", headers=bearer(owner))).json()
    assert "loan_overdue" in [a["kind"] for a in dash["alerts"]]
    report = (await client.get(f"/profit?from_month={MONTH()}&to_month={MONTH()}", headers=bearer(owner))).json()
    row = next(v for v in report["vehicles"] if v["vehicle_id"] == vehicle["id"])
    assert row["finance"] == 33_333_333 and row["net"] == -33_333_333  # a repayment is a cost of the lorry whether or not it earned


async def test_only_owner_and_accountant_manage_loans(client):
    owner, vehicle, lender = await loan_setup(client)
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.post("/finance", headers=bearer(manager), json=loan_body(vehicle, lender))).status_code == 403
    assert (await client.get("/finance", headers=bearer(manager))).status_code == 403
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.post("/finance", headers=bearer(accountant), json=loan_body(vehicle, lender))).status_code == 201
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/finance", headers=bearer(other))).json() == []


# ---- ownership costs --------------------------------------------------------------------------------------------------


def cost_body(vehicle, **extra):
    return {"vehicle_id": vehicle["id"], "kind": "insurance", "name": "Annual insurance", "amount_cents": 24_000_000, "period": "year", "start_date": MONTH(-6), **extra}


async def test_ownership_costs_are_spread_across_months_and_counted_once(client):
    owner, vehicle, _lender = await loan_setup(client)
    ins = await client.post("/ownership-costs", headers=bearer(owner), json=cost_body(vehicle))
    assert ins.status_code == 201 and ins.json()["monthly_cents"] == 2_000_000
    dep = await client.post("/ownership-costs", headers=bearer(owner), json=cost_body(vehicle, kind="depreciation", name="Depreciation", amount_cents=600_000_000, salvage_cents=120_000_000, life_months=60))
    assert dep.json()["monthly_cents"] == 8_000_000
    await seed_expense(vehicle["id"], 24_000_000, ExpenseCategory.INSURANCE, moment(0, 1))  # the premium paid in one go
    await seed_expense(vehicle["id"], 300_000, ExpenseCategory.GARAGE, moment(0, 1))
    row = next(v for v in (await client.get(f"/profit?from_month={MONTH()}", headers=bearer(owner))).json()["vehicles"] if v["vehicle_id"] == vehicle["id"])
    assert row["ownership"] == 10_000_000 and row["expenses"] == 300_000  # the premium is not counted twice
    assert row["net"] == -10_300_000
    listed = (await client.get(f"/ownership-costs?vehicle_id={vehicle['id']}", headers=bearer(owner))).json()
    assert len(listed) == 2
    assert (await client.delete(f"/ownership-costs/{ins.json()['id']}", headers=bearer(owner))).status_code == 204
    assert "ownership_cost.deleted" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_bad_ownership_costs_are_refused(client):
    owner, vehicle, _lender = await loan_setup(client)
    post = lambda **kw: client.post("/ownership-costs", headers=bearer(owner), json=cost_body(vehicle, **kw))
    assert (await post(kind="depreciation")).status_code == 422  # needs a life
    assert (await post(kind="depreciation", life_months=60, salvage_cents=24_000_000)).status_code == 422  # worth more than it cost
    assert (await post(end_date=MONTH(-9))).status_code == 422
    assert (await post(amount_cents=0)).status_code == 422
    assert (await post(vehicle_id=str(uuid.uuid4()))).status_code == 404


# ---- payroll ---------------------------------------------------------------------------------------------------------------


def test_a_salary_is_spread_by_days_and_always_adds_up():
    a, b = uuid.uuid4(), uuid.uuid4()
    parts = allocate_salary(3_000_000, {a: 15, b: 10}, 30)
    assert [p["cents"] for p in parts] == [1_500_000, 1_000_000, 500_000] and parts[-1]["vehicle_id"] is None  # 5 days with no lorry are the business's own cost
    assert sum(p["cents"] for p in allocate_salary(100, {a: 10, b: 10}, 30)) == 100
    assert allocate_salary(1000, {}, 30) == [{"vehicle_id": None, "cents": 1000}]
    assert [p["cents"] for p in allocate_salary(999, {a: 30}, 30)] == [999]


async def payroll_setup(client):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KCA 123A")
    driver = await seed_staff(client, owner, "Driver", "0712345678", salary_cents=3_000_000)
    turnboy = await seed_staff(client, owner, "Turnboy", "0722345678", role="turnboy", salary_cents=1_800_000)
    await seed_crew(vehicle["id"], driver, 3_000_000)
    await seed_crew(vehicle["id"], turnboy, 1_800_000, role="turnboy")
    return owner, vehicle, driver, turnboy


async def seed_fine(vehicle_id, membership_id, cents):
    async def make(db):
        i = Incident(type=IncidentType.TRAFFIC_FINE, vehicle_id=uuid.UUID(vehicle_id), driver_membership_id=uuid.UUID(membership_id), occurred_at=datetime.now(UTC), fine_amount_cents=cents, fine_payer=FinePayer.DRIVER, deduct_from_payroll=True, reference="TKT-1")
        db.add(i)
        await db.flush()
        return i.id

    return await in_db(make)


async def test_a_payroll_run_takes_back_advances_and_fines_and_spreads_the_cost_over_the_lorry(client):
    owner, vehicle, driver, _turnboy = await payroll_setup(client)
    adv = await client.post("/payroll/advances", headers=bearer(owner), json={"membership_id": driver, "amount_cents": 1_000_000, "note": "School fees", "mpesa_code": "adv1111111"})
    assert adv.status_code == 201 and adv.json()["remaining_cents"] == 1_000_000
    fine = await seed_fine(vehicle["id"], driver, 500_000)
    run = await client.post("/payroll/runs", headers=bearer(owner), json={"month": MONTH()})
    assert run.status_code == 201, run.text
    lines = {ln["name"]: ln for ln in run.json()["lines"]}
    d, t = lines["driver user"], lines["turnboy user"]
    assert (d["gross_cents"], d["advances_cents"], d["fines_cents"], d["net_cents"]) == (3_000_000, 1_000_000, 500_000, 1_500_000)
    assert (t["gross_cents"], t["net_cents"]) == (1_800_000, 1_800_000) and d["allocation"] == [{"registration": "KCA 123A", "cents": 3_000_000}]
    assert run.json()["gross_cents"] == 4_800_000 and run.json()["net_cents"] == 3_300_000 and run.json()["status"] == "draft"
    approved = await client.post(f"/payroll/runs/{run.json()['id']}/approve", headers=bearer(owner))
    assert approved.json()["status"] == "approved"
    advances = (await client.get("/payroll/advances", headers=bearer(owner))).json()
    assert advances[0]["remaining_cents"] == 0
    assert (await client.get("/payroll/advances?owing_only=true", headers=bearer(owner))).json() == []

    async def deducted(db):
        from sqlalchemy import select

        return (await db.execute(select(Incident.payroll_deducted_cents).where(Incident.id == fine))).scalar_one()

    assert await in_db(deducted) == 500_000
    row = next(v for v in (await client.get(f"/profit?from_month={MONTH()}", headers=bearer(owner))).json()["vehicles"] if v["vehicle_id"] == vehicle["id"])
    assert row["crew"] == 4_800_000  # the whole salary bill counts as the lorry's cost, whatever was taken off the pay
    paid = await client.post(f"/payroll/runs/{run.json()['id']}/paid", headers=bearer(owner), json={})
    assert paid.json()["status"] == "paid"
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert {"payroll.advance_given", "payroll.run_created", "payroll.run_approved", "payroll.run_paid"} <= set(actions)


async def test_deductions_never_take_more_than_the_salary_and_the_rest_waits(client):
    owner, vehicle, driver, _turnboy = await payroll_setup(client)
    await client.post("/payroll/advances", headers=bearer(owner), json={"membership_id": driver, "amount_cents": 5_000_000})
    await seed_fine(vehicle["id"], driver, 500_000)
    run = (await client.post("/payroll/runs", headers=bearer(owner), json={"month": MONTH(-1)})).json()
    d = next(ln for ln in run["lines"] if ln["name"] == "driver user")
    assert (d["advances_cents"], d["fines_cents"], d["net_cents"]) == (3_000_000, 0, 0)
    await client.post(f"/payroll/runs/{run['id']}/approve", headers=bearer(owner))
    assert (await client.get("/payroll/advances?owing_only=true", headers=bearer(owner))).json()[0]["remaining_cents"] == 2_000_000
    nxt = (await client.post("/payroll/runs", headers=bearer(owner), json={"month": MONTH()})).json()
    d2 = next(ln for ln in nxt["lines"] if ln["name"] == "driver user")
    assert (d2["advances_cents"], d2["fines_cents"], d2["net_cents"]) == (2_000_000, 500_000, 500_000)


async def test_a_draft_run_can_be_recalculated_but_an_approved_one_is_locked(client):
    owner, _vehicle, _driver, turnboy = await payroll_setup(client)
    run = (await client.post("/payroll/runs", headers=bearer(owner), json={"month": MONTH()})).json()
    await client.post("/payroll/advances", headers=bearer(owner), json={"membership_id": turnboy, "amount_cents": 400_000})
    again = await client.post(f"/payroll/runs/{run['id']}/recalculate", headers=bearer(owner))
    assert next(ln for ln in again.json()["lines"] if ln["name"] == "turnboy user")["advances_cents"] == 400_000
    assert (await client.post(f"/payroll/runs/{run['id']}/paid", headers=bearer(owner), json={})).json()["detail"]["code"] == "not_approved"
    await client.post(f"/payroll/runs/{run['id']}/approve", headers=bearer(owner))
    assert (await client.post(f"/payroll/runs/{run['id']}/approve", headers=bearer(owner))).status_code == 409
    assert (await client.post(f"/payroll/runs/{run['id']}/recalculate", headers=bearer(owner))).status_code == 409
    assert (await client.post("/payroll/runs", headers=bearer(owner), json={"month": MONTH()})).json()["detail"]["code"] == "run_exists"
    assert (await client.post("/payroll/runs", headers=bearer(owner), json={"month": MONTH(2)})).json()["detail"]["code"] == "future_month"


async def test_without_salaries_there_is_no_run_and_estimates_feed_the_profit_until_a_run_is_approved(client):
    owner, _ = await owner_session(client)
    assert (await client.post("/payroll/runs", headers=bearer(owner), json={"month": MONTH()})).json()["detail"]["code"] == "no_salaries"
    owner2, vehicle, _driver, _turnboy = await payroll_setup_named(client)
    row = next(v for v in (await client.get(f"/profit?from_month={MONTH()}", headers=bearer(owner2))).json()["vehicles"] if v["vehicle_id"] == vehicle["id"])
    assert row["crew"] == 4_800_000  # the salaries on file, before any run


async def payroll_setup_named(client):
    owner, _ = await owner_session(client, "Bravo Haulage", "bravo@example.com")
    vehicle = await add_vehicle(client, owner, "KCB 555B")
    driver = await seed_staff(client, owner, "Driver", "0733345678", salary_cents=3_000_000, business="Bravo Haulage")
    turnboy = await seed_staff(client, owner, "Turnboy", "0744345678", role="turnboy", salary_cents=1_800_000, business="Bravo Haulage")
    await seed_crew(vehicle["id"], driver, 3_000_000, business="Bravo Haulage")
    await seed_crew(vehicle["id"], turnboy, 1_800_000, role="turnboy", business="Bravo Haulage")
    return owner, vehicle, driver, turnboy


async def test_payroll_is_for_owner_and_accountant_only_and_advance_codes_are_unique(client):
    owner, _vehicle, driver, turnboy = await payroll_setup(client)
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.get("/payroll/runs", headers=bearer(accountant))).status_code == 200
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    for method, path, body in (("GET", "/payroll/runs", None), ("POST", "/payroll/runs", {"month": MONTH()}), ("GET", "/payroll/advances", None), ("POST", "/payroll/advances", {"membership_id": driver, "amount_cents": 100})):
        assert (await client.request(method, path, headers=bearer(manager), json=body)).status_code == 403, path
    first = await client.post("/payroll/advances", headers=bearer(owner), json={"membership_id": driver, "amount_cents": 100_000, "mpesa_code": "ADV9999999"})
    assert first.status_code == 201
    assert (await client.post("/payroll/advances", headers=bearer(owner), json={"membership_id": turnboy, "amount_cents": 100_000, "mpesa_code": "ADV9999999"})).status_code == 409
    assert (await client.post("/payroll/advances", headers=bearer(owner), json={"membership_id": str(uuid.uuid4()), "amount_cents": 100})).status_code == 404
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/payroll/advances", headers=bearer(other))).json() == []
