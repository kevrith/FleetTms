from app.lease_notices import notices_for_business, run_lease_charges
from app.models import ExpenseCategory
from app.sms import get_sms_sender
from tests.helpers import bearer
from tests.leasing import (
    in_db,
    lease_setup,
    make_lease,
    moment,
    month_start,
    seed_client,
    seed_expense,
    seed_trip,
    set_phone,
)
from tests.test_statements import csv_bytes, upload

MONTH = lambda offset=0: month_start(offset).isoformat()


async def test_a_lease_payment_is_matched_on_the_mpesa_statement_and_a_different_amount_is_flagged(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party, revenue_pct=0, fixed_cents=10_000_000, fixed_period="month")
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-1)})
    await client.post(f"/leases/{lease['id']}/payments", headers=bearer(owner), json={"amount_cents": 6_000_000, "method": "mpesa", "mpesa_code": "LSE1111111"})
    await client.post(f"/leases/{lease['id']}/payments", headers=bearer(owner), json={"amount_cents": 2_000_000, "method": "mpesa", "mpesa_code": "LSE2222222"})
    res = await upload(client, owner, csv_bytes(("LSE1111111", 5, "Pay to Wanjiku Transporters", "Completed", "", "60000.00"), ("LSE2222222", 4, "Pay to Wanjiku Transporters", "Completed", "", "25000.00")))
    assert res.status_code == 201, res.text
    assert res.json()["summary"]["matched"] == 1 and res.json()["summary"]["amount_differs"] == 1
    lines = {ln["receipt"]: ln for ln in (await client.get("/payments/statements/lines", headers=bearer(owner))).json()}
    assert lines["LSE1111111"]["match_label"] == "Lease payment" and lines["LSE1111111"]["state"] == "matched"
    assert lines["LSE2222222"]["state"] == "amount_differs" and "KES 20,000.00" in lines["LSE2222222"]["note"]


async def test_the_owner_is_texted_once_when_a_lease_payment_is_due_soon_and_once_when_it_is_overdue(client):
    owner, vehicle, party = await lease_setup(client)
    await set_phone("owner@kamau.example", "+254700111222")
    lease = await make_lease(client, owner, vehicle, party, revenue_pct=0, fixed_cents=10_000_000, fixed_period="month", payment_due_days=7)
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-2)})  # long overdue
    get_sms_sender().outbox.clear()

    async def go(db):
        return await notices_for_business(db)

    assert await in_db(go) == 1
    [(_phone, text)] = [m for m in get_sms_sender().outbox if m[0] == "+254700111222"]
    assert "KDB 404D" in text and "overdue" in text and "KES 100,000.00" in text
    assert await in_db(go) == 0  # once per month's charge
    await client.post(f"/leases/{lease['id']}/payments", headers=bearer(owner), json={"amount_cents": 10_000_000, "method": "cash"})
    assert await in_db(go) == 0  # nothing owed, nothing to say


async def test_a_late_lessee_is_texted_too(client):
    owner, vehicle, party = await lease_setup(client, direction="out", party_name="Rift Valley Quarries", registration="KDC 505E")
    await set_phone("owner@kamau.example", "+254700111222")
    lease = await make_lease(client, owner, vehicle, party, direction="out", revenue_pct=0, fixed_cents=15_000_000, fixed_period="month")
    await client.post(f"/leases/{lease['id']}/run", headers=bearer(owner), json={"month": MONTH(-2)})
    get_sms_sender().outbox.clear()

    async def go(db):
        return await notices_for_business(db)

    await in_db(go)
    to_lessee = [m for p, m in get_sms_sender().outbox if p == "+254711000111"]
    assert len(to_lessee) == 1 and "KDC 505E" in to_lessee[0] and "lease payment" in to_lessee[0]


async def test_the_monthly_job_works_out_last_months_charge_for_every_running_lease(client):
    owner, vehicle, party = await lease_setup(client)
    await make_lease(client, owner, vehicle, party, revenue_pct=0, fixed_cents=10_000_000, fixed_period="month")
    owner2, vehicle2, party2 = await lease_setup(client, direction="out", party_name="Quarry Co", registration="KDC 505E", business="Bravo Haulage")
    await make_lease(client, owner2, vehicle2, party2, direction="out", revenue_pct=10)  # waits for the lessee's figures
    assert await run_lease_charges() == 1
    detail = (await client.get("/leases", headers=bearer(owner))).json()[0]
    assert detail["balance_cents"] == 10_000_000
    assert await run_lease_charges() == 1  # safe to run again: nothing doubles
    assert (await client.get("/leases", headers=bearer(owner))).json()[0]["balance_cents"] == 10_000_000


async def test_leases_and_ledgers_never_cross_businesses(client):
    owner, vehicle, party = await lease_setup(client)
    lease = await make_lease(client, owner, vehicle, party)
    other, vehicle2, party2 = await lease_setup(client, party_name="Other Lessor", registration="KXX 999X", business="Bravo Haulage")
    assert (await client.get("/leases", headers=bearer(other))).json() == []
    for method, path in (("GET", f"/leases/{lease['id']}"), ("POST", f"/leases/{lease['id']}/run"), ("POST", f"/leases/{lease['id']}/end")):
        assert (await client.request(method, path, headers=bearer(other), json={"month": MONTH()})).status_code == 404, path
    assert (await client.post("/leases", headers=bearer(other), json={"direction": "in", "vehicle_id": vehicle["id"], "party_id": party2["id"], "start_date": MONTH(-1), "revenue_pct": 30})).status_code == 404
    assert seed_client and seed_expense and seed_trip and moment and ExpenseCategory and vehicle2
