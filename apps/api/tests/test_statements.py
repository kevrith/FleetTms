import io
from datetime import UTC, datetime, timedelta

from openpyxl import Workbook

from app.reminders import NAIROBI
from tests.helpers import bearer, staff_session
from tests.money import SHORTCODE, business_id, c2b, configure, invoice, pay_in, seed_invoice
from tests.shots import ago, fleet
from tests.test_clients import add_client
from tests.test_fuel_floats_devices import fuel_body

HEADER = "Receipt No.,Completion Time,Details,Transaction Status,Paid In,Withdrawn,Balance"


def stamp(hours_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).astimezone(NAIROBI).strftime("%Y-%m-%d %H:%M:%S")


def csv_bytes(*rows: tuple, header: str = HEADER) -> bytes:
    """rows: (receipt, hours_ago, details, status, paid_in, withdrawn)"""
    lines = [header] + [f'{r},{stamp(h)},"{d}",{s},{pi},{wd},0.00' for r, h, d, s, pi, wd in rows]
    return ("\n".join(lines) + "\n").encode()


async def upload(client, who, content: bytes, name="statement.csv"):
    return await client.post("/payments/statements", headers=bearer(who), files={"file": (name, content, "text/csv")})


async def claim_fuel(client, f, code, amount=2220000, hours_ago=26):
    res = await client.post("/fuel", headers=bearer(f.driver), json=fuel_body(f, mpesa_code=code, amount_cents=amount, captured_at=ago(hours=hours_ago)))
    assert res.status_code == 201, res.text
    return res.json()


async def lines(client, who, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return {ln["receipt"]: ln for ln in (await client.get(f"/payments/statements/lines?{qs}", headers=bearer(who))).json()}


async def test_a_statement_matches_fuel_expenses_and_floats_by_their_mpesa_code(client):
    f = await fleet(client)
    await claim_fuel(client, f, "FUEL111111")
    spend = await client.post("/expenses", headers=bearer(f.driver), json={"category": "toll", "amount_cents": 50000, "mpesa_code": "TOLL222222"})
    assert spend.status_code == 201, spend.text
    sent = await client.post("/floats", headers=bearer(f.owner), json={"driver_membership_id": f.ids["+254712345678"], "amount_cents": 300000, "mpesa_code": "FLOT333333", "sent_at": ago(hours=30)})
    assert sent.status_code == 201, sent.text
    res = await upload(
        client, f.owner,
        csv_bytes(("FUEL111111", 25, "Pay Bill to Total Naivasha", "Completed", "", "22200.00"), ("TOLL222222", 3, "Pay to toll", "Completed", "", "500.00"), ("FLOT333333", 30, "Send to driver", "Completed", "", "3000.00"), ("ZZZ9999999", 4, "Unknown payee", "Completed", "", "1200.00")),
    )  # fmt: skip
    assert res.status_code == 201, res.text
    summary = res.json()["summary"]
    assert summary["matched"] == 3 and summary["unmatched"] == 1 and summary["amount_differs"] == 0
    got = await lines(client, f.owner)
    assert got["FUEL111111"]["match_label"] == "Fuel" and got["TOLL222222"]["match_label"] == "Expense" and got["FLOT333333"]["match_label"] == "Float"
    assert got["ZZZ9999999"]["state"] == "unmatched" and "nothing in FleetTms claims" in got["ZZZ9999999"]["note"]
    attention = await lines(client, f.owner, state="attention")
    assert list(attention) == ["ZZZ9999999"]


async def test_a_claim_for_more_than_the_statement_shows_is_flagged(client):
    f = await fleet(client)
    await claim_fuel(client, f, "FUEL111111", amount=2220000)
    res = await upload(client, f.owner, csv_bytes(("FUEL111111", 25, "Total", "Completed", "", "15000.00"), ("OTHER00001", 2, "x", "Completed", "100.00", "")))
    assert res.json()["summary"]["amount_differs"] == 1
    line = (await lines(client, f.owner))["FUEL111111"]
    assert line["state"] == "amount_differs" and "KES 15,000.00" in line["note"] and "KES 22,200.00" in line["note"]
    assert "statement_amount_differs" in (await client.get("/fuel", headers=bearer(f.owner))).json()[0]["flags"]
    dash = (await client.get("/dashboard", headers=bearer(f.owner))).json()
    assert "statement_mismatch" in [a["kind"] for a in dash["alerts"]]


async def test_a_claim_in_the_statement_period_with_no_matching_line_is_flagged_as_not_on_the_statement(client):
    f = await fleet(client)
    await claim_fuel(client, f, "FAKE000001", hours_ago=26)
    res = await upload(client, f.owner, csv_bytes(("REAL000001", 70, "a", "Completed", "", "100.00"), ("REAL000002", 1, "b", "Completed", "", "100.00")))
    missing = res.json()["summary"]["not_on_statement"]
    assert [m["mpesa_code"] for m in missing] == ["FAKE000001"] and missing[0]["kind"] == "fuel"
    assert "not_on_statement" in (await client.get("/fuel", headers=bearer(f.owner))).json()[0]["flags"]
    # a claim outside the statement's dates is not judged
    await claim_fuel(client, f, "LATE000001", hours_ago=0.2)
    again = await upload(client, f.owner, csv_bytes(("REAL000003", 70, "a", "Completed", "", "100.00"), ("REAL000004", 1, "b", "Completed", "", "100.00")))
    assert [m["mpesa_code"] for m in again.json()["summary"]["not_on_statement"]] == ["FAKE000001"]


async def test_uploading_a_statement_again_adds_nothing_twice_and_picks_up_new_claims(client):
    f = await fleet(client)
    content = csv_bytes(("FUEL111111", 25, "Total", "Completed", "", "22200.00"), ("OTHER00001", 2, "x", "Completed", "", "100.00"))
    first = await upload(client, f.owner, content)
    assert first.json()["new_rows"] == 2 and first.json()["summary"]["matched"] == 0 and first.json()["summary"]["unmatched"] == 2
    await claim_fuel(client, f, "FUEL111111")
    second = await upload(client, f.owner, content)
    assert second.json()["new_rows"] == 0 and second.json()["summary"]["already_known"] == 2 and second.json()["summary"]["matched"] == 1
    assert len(await lines(client, f.owner)) == 2
    assert len((await client.get("/payments/statements", headers=bearer(f.owner))).json()) == 2


async def test_money_that_came_in_recovers_a_payment_whose_notice_was_missed(client):
    f = await fleet(client)
    c = await add_client(client, f.owner, billing_method="per_trip", rate_cents=1_000_000)
    inv = await seed_invoice(c["id"], total_cents=1_000_000)
    paid = await upload(client, f.owner, csv_bytes(("PAID000001", 2, "Funds received from 2547XXXXX123 - JOHN KAMAU", "Completed", "10000.00", "")), )
    assert paid.json()["summary"]["payments_recovered"] == 1
    # the statement has no account number column, so a person matches it
    [txn] = (await client.get("/payments/mpesa?status_filter=unmatched", headers=bearer(f.owner))).json()
    assert txn["trans_id"] == "PAID000001" and txn["source"] == "statement"
    assert (await client.post(f"/payments/mpesa/{txn['id']}/match", headers=bearer(f.owner), json={"invoice_id": inv["id"]})).status_code == 200
    assert (await invoice(client, f.owner, inv["id"]))["status"] == "paid"
    again = await upload(client, f.owner, csv_bytes(("PAID000001", 2, "Funds received from 2547XXXXX123 - JOHN KAMAU", "Completed", "10000.00", "")))
    assert again.json()["summary"]["payments_recovered"] == 0 and (await lines(client, f.owner))["PAID000001"]["state"] == "matched"


async def test_a_paid_in_line_with_an_account_number_column_is_matched_to_its_invoice(client):
    f = await fleet(client)
    c = await add_client(client, f.owner, billing_method="per_trip", rate_cents=1_000_000)
    inv = await seed_invoice(c["id"], total_cents=500_000)
    header = HEADER + ",A/C No."
    content = (header + f"\nPAID000002,{stamp(2)},Funds received,Completed,5000.00,,0.00,INV-0001\n").encode()
    assert (await upload(client, f.owner, content)).json()["summary"]["matched"] == 1
    assert (await invoice(client, f.owner, inv["id"]))["status"] == "paid"


async def test_a_payment_already_received_from_safaricom_is_matched_not_added_again(client):
    f = await fleet(client)
    await configure(client, f.owner)
    c = await add_client(client, f.owner, billing_method="per_trip", rate_cents=1_000_000)
    inv = await seed_invoice(c["id"], total_cents=1_000_000)
    await pay_in(client, await business_id(), c2b(trans_id="PAID000003", amount="10000.00", bill_ref="INV-0001", BusinessShortCode=SHORTCODE))
    res = await upload(client, f.owner, csv_bytes(("PAID000003", 2, "Funds received", "Completed", "10000.00", "")))
    assert res.json()["summary"]["matched"] == 1 and res.json()["summary"]["payments_recovered"] == 0
    assert len((await invoice(client, f.owner, inv["id"]))["payments"]) == 1


async def test_failed_transactions_and_totals_are_skipped_and_an_excel_file_works(client):
    f = await fleet(client)
    wb = Workbook()
    ws = wb.active
    ws.append(["Statement for Kamau Haulage"])
    ws.append([])
    ws.append(["Receipt No.", "Completion Time", "Details", "Transaction Status", "Paid In", "Withdrawn", "Balance"])
    ws.append(["GOOD000001", datetime.now(NAIROBI).replace(tzinfo=None) - timedelta(hours=3), "Pay to Total", "Completed", None, "1,200.00", 0])
    ws.append(["FAIL000001", datetime.now(NAIROBI).replace(tzinfo=None) - timedelta(hours=3), "Pay", "Failed", None, 300, 0])
    ws.append(["TOTAL", None, "Total", None, None, 1500, None])
    buf = io.BytesIO()
    wb.save(buf)
    res = await upload(client, f.owner, buf.getvalue(), "statement.xlsx")
    assert res.status_code == 201, res.text
    assert res.json()["rows"] == 1 and res.json()["summary"]["skipped"] == 2
    assert list(await lines(client, f.owner)) == ["GOOD000001"]


async def test_a_file_that_is_not_a_statement_is_refused_in_plain_words(client):
    f = await fleet(client)
    for content in (b"name,age\nann,3\n", b"", HEADER.encode() + b"\n", b"\x00\x01\x02binary"):
        res = await upload(client, f.owner, content)
        assert res.status_code == 422 and res.json()["detail"]["code"] == "bad_statement", content
    bad_xlsx = await upload(client, f.owner, b"PK\x03\x04not really", "statement.xlsx")
    assert bad_xlsx.status_code == 422


async def test_a_line_can_be_ignored_with_a_reason_but_not_a_matched_one(client):
    f = await fleet(client)
    await claim_fuel(client, f, "FUEL111111")
    await upload(client, f.owner, csv_bytes(("FUEL111111", 25, "Total", "Completed", "", "22200.00"), ("PERS000001", 2, "Personal", "Completed", "", "900.00")))
    got = await lines(client, f.owner)
    assert (await client.post(f"/payments/statements/lines/{got['FUEL111111']['id']}/ignore", headers=bearer(f.owner), json={"note": "no"})).status_code == 422  # note too short
    assert (await client.post(f"/payments/statements/lines/{got['FUEL111111']['id']}/ignore", headers=bearer(f.owner), json={"note": "Not a problem"})).status_code == 409
    ok = await client.post(f"/payments/statements/lines/{got['PERS000001']['id']}/ignore", headers=bearer(f.owner), json={"note": "Owner's own transfer"})
    assert ok.json()["state"] == "ignored" and "PERS000001" not in await lines(client, f.owner, state="attention")


async def test_statements_are_for_owner_and_accountant_only_and_stay_inside_the_business(client):
    f = await fleet(client)
    await upload(client, f.owner, csv_bytes(("AAAA000001", 2, "x", "Completed", "", "100.00")))
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await upload(client, manager, csv_bytes(("AAAA000002", 2, "x", "Completed", "", "100.00")))).status_code == 403
    assert (await client.get("/payments/statements/lines", headers=bearer(f.driver))).status_code == 403
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert len(await lines(client, accountant)) == 1
    from tests.helpers import owner_session

    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert await lines(client, other) == {}
    assert (await upload(client, other, csv_bytes(("AAAA000001", 2, "x", "Completed", "", "100.00")))).json()["new_rows"] == 1  # the same code in another business is separate
