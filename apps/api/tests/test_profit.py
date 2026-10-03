from app.models import BillingMethod, ExpenseCategory
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import (
    lease_setup,
    make_lease,
    moment,
    month_start,
    seed_client,
    seed_crew,
    seed_expense,
    seed_fuel,
    seed_job,
    seed_staff,
    seed_trip,
)

MONTH = lambda offset=0: month_start(offset).isoformat()


async def report(client, who, offset=0, to=None, trips=False):
    res = await client.get(f"/profit?from_month={MONTH(offset)}&to_month={MONTH(to if to is not None else offset)}&include_trips={str(trips).lower()}", headers=bearer(who))
    assert res.status_code == 200, res.text
    return res.json()


async def fleet_of_two(client):
    owner, _ = await owner_session(client)
    depot = (await client.post("/depots", headers=bearer(owner), json={"name": "Mombasa Yard"})).json()
    a = await add_vehicle(client, owner, "KCA 111A", depot_id=depot["id"])
    b = await add_vehicle(client, owner, "KCB 222B")
    return owner, a, b


async def test_profit_by_vehicle_client_driver_trip_depot_and_business(client):
    owner, a, b = await fleet_of_two(client)
    driver = await seed_staff(client, owner, "Driver", "0712345678")
    bamburi, mombasa = await seed_client("Bamburi Cement"), await seed_client("Mombasa Cement")
    job1, job2 = await seed_job(bamburi), await seed_job(mombasa)
    t1 = await seed_trip(a["id"], revenue_cents=10_000_000, client_id=bamburi, job_id=job1, driver_membership_id=driver, km=400)
    t2 = await seed_trip(a["id"], revenue_cents=6_000_000, client_id=mombasa, job_id=job2, km=200)
    t3 = await seed_trip(b["id"], revenue_cents=4_000_000, client_id=bamburi, job_id=job1, km=100)
    await seed_fuel(a["id"], 2_000_000, trip_id=t1)
    await seed_expense(a["id"], 500_000, ExpenseCategory.TOLL, trip_id=t1)
    await seed_expense(a["id"], 700_000, ExpenseCategory.REPAIR)  # the lorry's, not a trip's
    await seed_expense(b["id"], 300_000, ExpenseCategory.TOLL, trip_id=t3)
    await seed_expense(None, 1_000_000, ExpenseCategory.OVERHEAD)  # the office
    data = await report(client, owner, trips=True)
    rows = {v["registration"]: v for v in data["vehicles"]}
    assert rows["KCA 111A"]["revenue"] == 16_000_000 and rows["KCA 111A"]["operating"] == 3_200_000 and rows["KCA 111A"]["gross"] == 12_800_000 and rows["KCA 111A"]["net"] == 12_800_000
    assert rows["KCB 222B"]["gross"] == 3_700_000 and rows["KCA 111A"]["km"] == 600 and rows["KCA 111A"]["cost_per_km"] == round(3_200_000 / 600) and rows["KCA 111A"]["revenue_per_km"] == round(16_000_000 / 600)
    assert rows["KCA 111A"]["loaded_km"] == 600 and rows["KCA 111A"]["empty_km"] == 0
    clients = {c["name"]: c for c in data["clients"]}
    assert clients["Bamburi Cement"]["revenue_cents"] == 14_000_000 and clients["Bamburi Cement"]["direct_cost_cents"] == 2_800_000 and clients["Bamburi Cement"]["contribution_cents"] == 11_200_000 and clients["Bamburi Cement"]["trips"] == 2
    assert clients["Mombasa Cement"]["contribution_cents"] == 6_000_000
    drivers = {d["name"]: d for d in data["drivers"]}
    assert drivers["driver user"]["contribution_cents"] == 7_500_000
    trip = next(t for t in data["trips"] if t["trip_id"] == str(t1))
    assert trip["revenue_cents"] == 10_000_000 and trip["direct_cost_cents"] == 2_500_000 and trip["contribution_cents"] == 7_500_000 and trip["client_name"] == "Bamburi Cement" and trip["registration"] == "KCA 111A"
    depots = {d["name"]: d for d in data["depots"]}
    assert depots["Mombasa Yard"]["net"] == 12_800_000 and depots["No depot"]["net"] == 3_700_000
    biz = data["business"]
    assert biz["revenue"] == 20_000_000 and biz["net"] == 16_500_000 and biz["overheads"] == 1_000_000 and biz["net_after_overheads"] == 15_500_000 and biz["trips"] == 3
    assert biz["not_on_a_trip"] == 700_000  # the lorry's repair: in the business figures, in no client or driver row
    assert t2 and not (await report(client, owner))["trips"]  # trips only when asked for


async def test_unbilled_trips_are_counted_and_a_contract_fee_is_shared_across_its_trips(client):
    owner, a, b = await fleet_of_two(client)
    quarry = await seed_client("Quarry Ltd")
    contract = await seed_job(quarry, BillingMethod.MONTHLY_CONTRACT, 30_000_000)
    for _ in range(3):
        await seed_trip(a["id"], revenue_cents=0, client_id=quarry, job_id=contract, invoice=False)
    await seed_trip(b["id"], revenue_cents=0, invoice=False)  # delivered but never invoiced
    data = await report(client, owner)
    rows = {v["registration"]: v for v in data["vehicles"]}
    assert rows["KCA 111A"]["revenue"] == 30_000_000 and rows["KCA 111A"]["estimated"] == 3  # the month's fee until the contract invoice exists
    assert rows["KCB 222B"]["revenue"] == 0 and rows["KCB 222B"]["unbilled"] == 1 and data["business"]["unbilled"] == 1


async def test_empty_running_is_told_apart_from_loaded_running(client):
    owner, a, _b = await fleet_of_two(client)
    quarry = await seed_client("Quarry Ltd")
    job = await seed_job(quarry)
    await seed_trip(a["id"], revenue_cents=1_000_000, client_id=quarry, job_id=job, km=300)
    await seed_trip(a["id"], revenue_cents=0, invoice=False, loaded=False, km=120)  # driving back with nothing
    row = next(v for v in (await report(client, owner))["vehicles"] if v["registration"] == "KCA 111A")
    assert (row["loaded_km"], row["empty_km"], row["km"]) == (300, 120, 420)


async def test_a_lease_that_is_not_paying_off_is_flagged_after_three_months_in_a_row(client):
    owner, vehicle, party = await lease_setup(client)
    await make_lease(client, owner, vehicle, party, revenue_pct=0, fixed_cents=10_000_000, fixed_period="month", start_date=MONTH(-5))
    client_id = await seed_client()
    for offset in (-2, -1):
        await seed_trip(vehicle["id"], revenue_cents=12_000_000, client_id=client_id, at=moment(offset, 5))
    await seed_trip(vehicle["id"], revenue_cents=12_000_000, client_id=client_id, at=moment(0, 1))
    # revenue 120,000 against a 100,000 lease and no other costs: the operator keeps 20,000, the owner 100,000, three months running
    row = next(v for v in (await report(client, owner))["vehicles"] if v["vehicle_id"] == vehicle["id"])
    assert row["lease_not_paying"] is True and row["net"] == 2_000_000
    dash = (await client.get("/dashboard", headers=bearer(owner))).json()
    assert "lease_not_paying" in [a["kind"] for a in dash["alerts"]]
    await seed_trip(vehicle["id"], revenue_cents=60_000_000, client_id=client_id, at=moment(0, 2))  # a good month breaks the run
    assert next(v for v in (await report(client, owner))["vehicles"] if v["vehicle_id"] == vehicle["id"])["lease_not_paying"] is False


async def test_the_dashboard_answers_how_much_the_leased_lorry_made_after_paying_its_owner(client):
    owner, vehicle, party = await lease_setup(client)
    await make_lease(client, owner, vehicle, party, revenue_pct=30)
    client_id = await seed_client()
    for _ in range(2):
        await seed_trip(vehicle["id"], revenue_cents=30_000_000, client_id=client_id, at=moment(-1, 5))
    await seed_fuel(vehicle["id"], 10_000_000, moment(-1, 5))
    dash = (await client.get("/dashboard", headers=bearer(owner))).json()
    last = dash["profit_last_month"]
    [row] = [v for v in last["vehicles"] if v["vehicle_id"] == vehicle["id"]]
    assert row["revenue_cents"] == 60_000_000 and row["gross_profit_cents"] == 50_000_000 and row["lease_payable_cents"] == 18_000_000 and row["net_profit_cents"] == 32_000_000
    assert last["business"]["net"] == 32_000_000
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.get("/dashboard", headers=bearer(manager))).json()["profit_last_month"] is None


async def test_profit_covers_a_range_of_months_and_checks_the_range(client):
    owner, a, _b = await fleet_of_two(client)
    client_id = await seed_client()
    await seed_trip(a["id"], revenue_cents=5_000_000, client_id=client_id, at=moment(-2, 5))
    await seed_trip(a["id"], revenue_cents=7_000_000, client_id=client_id, at=moment(-1, 5))
    data = await report(client, owner, offset=-2, to=0)
    assert len(data["months"]) == 3 and data["business"]["revenue"] == 12_000_000
    assert (await report(client, owner, offset=-1))["business"]["revenue"] == 7_000_000
    assert (await client.get(f"/profit?from_month={MONTH(1)}&to_month={MONTH(0)}", headers=bearer(owner))).json()["detail"]["code"] == "bad_range"
    assert (await client.get(f"/profit?from_month={MONTH(-30)}&to_month={MONTH(0)}", headers=bearer(owner))).json()["detail"]["code"] == "range_too_long"


async def test_profit_matches_a_hand_calculated_spreadsheet(client):
    """A lorry with crew, loan, insurance and a lease, worked out by hand:
    revenue 450,000; fuel 120,000; tolls 18,000; crew 40,000 -> gross 272,000. Lease: fixed 90,000 -> net 182,000.
    Insurance 36,000 a year is 3,000 a month -> 179,000."""
    owner, vehicle, party = await lease_setup(client)
    await make_lease(client, owner, vehicle, party, revenue_pct=0, fixed_cents=9_000_000, fixed_period="month")
    driver = await seed_staff(client, owner, "Driver", "0712345678", salary_cents=4_000_000)
    await seed_crew(vehicle["id"], driver, 4_000_000)
    client_id = await seed_client()
    for revenue in (15_000_000, 20_000_000, 10_000_000):
        await seed_trip(vehicle["id"], revenue_cents=revenue, client_id=client_id, at=moment(0, 1))
    await seed_fuel(vehicle["id"], 12_000_000, moment(0, 1))
    await seed_expense(vehicle["id"], 1_800_000, ExpenseCategory.TOLL, moment(0, 1))
    await client.post("/ownership-costs", headers=bearer(owner), json={"vehicle_id": vehicle["id"], "kind": "insurance", "name": "Insurance", "amount_cents": 3_600_000, "period": "year", "start_date": MONTH(-3)})
    row = next(v for v in (await report(client, owner))["vehicles"] if v["vehicle_id"] == vehicle["id"])
    assert (row["revenue"], row["operating"], row["gross"]) == (45_000_000, 17_800_000, 27_200_000)
    assert (row["lease_payable"], row["ownership"], row["net"]) == (9_000_000, 300_000, 17_900_000)


async def test_profit_is_for_owner_and_accountant_and_never_crosses_businesses(client):
    owner, a, _b = await fleet_of_two(client)
    await seed_trip(a["id"], revenue_cents=5_000_000, client_id=await seed_client())
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.get("/profit", headers=bearer(accountant))).status_code == 200
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.get("/profit", headers=bearer(manager))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/profit", headers=bearer(other))).json()["vehicles"] == []
    assert seed_crew and seed_expense and seed_fuel
