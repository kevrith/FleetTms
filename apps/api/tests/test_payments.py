import uuid

from app import daraja
from app.daraja import fake_daraja
from tests.helpers import bearer, owner_session, staff_session
from tests.money import (
    SHORTCODE,
    business_id,
    c2b,
    configure,
    invoice,
    owner_with_client,
    pay_in,
    seed_invoice,
)


async def setup(client, total=1_000_000, **kw):
    owner, c = await owner_with_client(client)
    await configure(client, owner)
    inv = await seed_invoice(c["id"], total_cents=total, **kw)
    return owner, c, inv, await business_id()


# ---- the Safaricom callback ------------------------------------------------------------------------------------------


async def test_a_payment_naming_the_invoice_marks_it_paid(client):
    owner, _c, inv, bid = await setup(client)
    res = await pay_in(client, bid, c2b(amount="10000.00", bill_ref="INV-0001"))
    assert res.status_code == 200 and res.json() == {"ResultCode": 0, "ResultDesc": "Accepted"}
    got = await invoice(client, owner, inv["id"])
    assert got["status"] == "paid" and got["balance_cents"] == 0
    [p] = got["payments"]
    assert p["method"] == "mpesa" and p["reference"] == "QGH7XYZ123" and p["amount_cents"] == 1_000_000
    listed = (await client.get("/payments/mpesa", headers=bearer(owner))).json()
    assert listed[0]["status"] == "matched" and listed[0]["payer_name"] == "John Kamau" and listed[0]["allocated_cents"] == 1_000_000
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert "invoice.payment" in actions and "mpesa.payment_received" in actions


async def test_the_same_payment_sent_twice_counts_once(client):
    owner, _c, inv, bid = await setup(client)
    for _ in range(3):
        assert (await pay_in(client, bid, c2b(amount="4000.00"))).status_code == 200
    got = await invoice(client, owner, inv["id"])
    assert got["paid_cents"] == 400_000 and len(got["payments"]) == 1 and got["status"] == "partially_paid"
    assert len((await client.get("/payments/mpesa", headers=bearer(owner))).json()) == 1


async def test_the_account_number_may_be_typed_loosely(client):
    owner, _c, inv, bid = await setup(client, total=500_000)
    await pay_in(client, bid, c2b(trans_id="AAA1111111", amount="1000.00", bill_ref="inv 0001"))
    await pay_in(client, bid, c2b(trans_id="AAA2222222", amount="1000.00", bill_ref=" Inv-1 "))
    assert (await invoice(client, owner, inv["id"]))["paid_cents"] == 200_000


async def test_paying_more_than_is_owed_settles_the_invoice_and_queues_the_rest(client):
    owner, _c, inv, bid = await setup(client, total=1_000_000)
    await pay_in(client, bid, c2b(amount="12500.00"))
    got = await invoice(client, owner, inv["id"])
    assert got["status"] == "paid" and got["paid_cents"] == 1_000_000
    [txn] = (await client.get("/payments/mpesa?status_filter=needs_attention", headers=bearer(owner))).json()
    assert txn["status"] == "partly_matched" and txn["left_cents"] == 250_000 and txn["reason"] == "overpaid"


async def test_a_payment_that_cannot_be_matched_waits_in_a_queue_with_the_reason(client):
    owner, _c, inv, bid = await setup(client)
    cases = [("AAA0000001", ""), ("AAA0000002", "Bamburi"), ("AAA0000003", "INV-0099")]
    for code, ref in cases:
        assert (await pay_in(client, bid, c2b(trans_id=code, amount="10000.00", bill_ref=ref))).status_code == 200
    queue = {t["trans_id"]: t for t in (await client.get("/payments/mpesa?status_filter=unmatched", headers=bearer(owner))).json()}
    assert {k: v["reason"] for k, v in queue.items()} == {"AAA0000001": "no_reference", "AAA0000002": "unknown_reference", "AAA0000003": "unknown_invoice"}
    assert (await invoice(client, owner, inv["id"]))["paid_cents"] == 0  # nothing was guessed onto the invoice


async def test_a_payment_for_a_voided_or_paid_invoice_is_not_applied(client):
    owner, c, inv, bid = await setup(client)
    gone = await seed_invoice(c["id"], void=True)
    await pay_in(client, bid, c2b(trans_id="AAA0000001", bill_ref=gone["number"]))
    await pay_in(client, bid, c2b(trans_id="AAA0000002", amount="10000.00", bill_ref=inv["number"]))
    await pay_in(client, bid, c2b(trans_id="AAA0000003", amount="500.00", bill_ref=inv["number"]))  # already paid by now
    by_code = {t["trans_id"]: t for t in (await client.get("/payments/mpesa", headers=bearer(owner))).json()}
    assert by_code["AAA0000001"]["reason"] == "void_invoice" and by_code["AAA0000001"]["status"] == "unmatched"
    assert by_code["AAA0000002"]["status"] == "matched"
    assert by_code["AAA0000003"]["reason"] == "already_paid" and by_code["AAA0000003"]["status"] == "unmatched"


async def test_a_wrong_key_or_shortcode_is_refused_and_one_business_cannot_post_to_another(client):
    _owner, _c, _inv, bid = await setup(client)
    assert (await pay_in(client, bid, c2b(), key="0" * 40)).status_code == 403
    assert (await pay_in(client, bid, c2b(BusinessShortCode="999999"))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    other_id = await business_id("Bravo")
    assert (await pay_in(client, bid, c2b(), key=daraja.callback_key(other_id))).status_code == 403  # Bravo's key on our address
    assert (await client.get("/payments/mpesa", headers=bearer(other))).json() == []
    assert (await pay_in(client, bid, {"nonsense": True})).status_code == 422
    assert (await pay_in(client, bid, c2b(amount="0"))).status_code == 422
    assert (await pay_in(client, bid, c2b(), kind="validation")).json()["ResultCode"] == 0


async def test_a_payment_the_office_already_entered_by_hand_is_not_counted_twice(client):
    owner, _c, inv, bid = await setup(client)
    by_hand = await client.post(f"/invoices/{inv['id']}/payments", headers=bearer(owner), json={"amount_cents": 400_000, "method": "mpesa", "reference": "qgh7xyz123"})
    assert by_hand.status_code == 201 and by_hand.json()["payments"][0]["reference"] == "QGH7XYZ123"
    await pay_in(client, bid, c2b(amount="4000.00"))
    got = await invoice(client, owner, inv["id"])
    assert got["paid_cents"] == 400_000 and len(got["payments"]) == 1
    assert (await client.get("/payments/mpesa", headers=bearer(owner))).json()[0]["status"] == "matched"


async def test_the_same_mpesa_code_cannot_be_entered_by_hand_twice_or_once_it_has_arrived(client):
    owner, _c, inv, bid = await setup(client, total=2_000_000)
    hand = lambda code: client.post(f"/invoices/{inv['id']}/payments", headers=bearer(owner), json={"amount_cents": 100_000, "method": "mpesa", "reference": code})
    assert (await hand("AAA1111111")).status_code == 201
    assert (await hand("AAA1111111")).json()["detail"]["code"] == "already_recorded"
    await pay_in(client, bid, c2b(trans_id="BBB2222222", bill_ref=""))
    assert (await hand("BBB2222222")).json()["detail"]["code"] == "in_payments_queue"


# ---- the office's queue -----------------------------------------------------------------------------------------------


async def test_the_office_matches_a_waiting_payment_to_an_invoice_and_can_split_it(client):
    owner, c, inv, bid = await setup(client, total=600_000)
    second = await seed_invoice(c["id"], total_cents=400_000)
    await pay_in(client, bid, c2b(amount="10000.00", bill_ref="Bamburi cement"))
    [txn] = (await client.get("/payments/mpesa", headers=bearer(owner))).json()
    detail = (await client.get(f"/payments/mpesa/{txn['id']}", headers=bearer(owner))).json()
    assert detail["suggestions"] == []  # no single invoice owes exactly KES 10,000
    first = await client.post(f"/payments/mpesa/{txn['id']}/match", headers=bearer(owner), json={"invoice_id": inv["id"]})
    assert first.status_code == 200 and first.json()["status"] == "partly_matched" and first.json()["left_cents"] == 400_000
    done = await client.post(f"/payments/mpesa/{txn['id']}/match", headers=bearer(owner), json={"invoice_id": second["id"]})
    assert done.json()["status"] == "matched" and done.json()["left_cents"] == 0
    assert (await invoice(client, owner, inv["id"]))["status"] == "paid" and (await invoice(client, owner, second["id"]))["status"] == "paid"
    assert (await client.post(f"/payments/mpesa/{txn['id']}/match", headers=bearer(owner), json={"invoice_id": inv["id"]})).status_code == 422


async def test_a_waiting_payment_suggests_the_invoice_that_owes_exactly_that_much(client):
    owner, c, inv, bid = await setup(client, total=750_000)
    await seed_invoice(c["id"], total_cents=300_000)
    await pay_in(client, bid, c2b(amount="7500.00", bill_ref=""))
    [txn] = (await client.get("/payments/mpesa", headers=bearer(owner))).json()
    detail = (await client.get(f"/payments/mpesa/{txn['id']}", headers=bearer(owner))).json()
    assert [s["number"] for s in detail["suggestions"]] == [inv["number"]]


async def test_matching_refuses_to_overpay_an_invoice_or_use_a_dismissed_payment(client):
    owner, _c, inv, bid = await setup(client, total=100_000)
    await pay_in(client, bid, c2b(amount="5000.00", bill_ref=""))
    [txn] = (await client.get("/payments/mpesa", headers=bearer(owner))).json()
    res = await client.post(f"/payments/mpesa/{txn['id']}/match", headers=bearer(owner), json={"invoice_id": inv["id"], "amount_cents": 200_000})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "overpayment"
    assert (await client.post(f"/payments/mpesa/{txn['id']}/match", headers=bearer(owner), json={"invoice_id": str(uuid.uuid4())})).status_code == 404
    dismissed = await client.post(f"/payments/mpesa/{txn['id']}/dismiss", headers=bearer(owner), json={"reason": "Refunded to the client"})
    assert dismissed.json()["status"] == "dismissed"
    assert (await client.post(f"/payments/mpesa/{txn['id']}/match", headers=bearer(owner), json={"invoice_id": inv["id"]})).json()["detail"]["code"] == "dismissed"
    assert "mpesa.payment_dismissed" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_a_fully_matched_payment_cannot_be_dismissed(client):
    owner, _c, _inv, bid = await setup(client)
    await pay_in(client, bid, c2b(amount="10000.00"))
    [txn] = (await client.get("/payments/mpesa", headers=bearer(owner))).json()
    assert (await client.post(f"/payments/mpesa/{txn['id']}/dismiss", headers=bearer(owner), json={"reason": "mistake"})).status_code == 409


async def test_only_owner_and_accountant_see_payments_and_one_business_never_sees_anothers(client):
    owner, _c, _inv, bid = await setup(client)
    await pay_in(client, bid, c2b(amount="10000.00"))
    [txn] = (await client.get("/payments/mpesa", headers=bearer(owner))).json()
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.get("/payments/mpesa", headers=bearer(accountant))).status_code == 200
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.get("/payments/mpesa", headers=bearer(manager))).status_code == 403
    assert (await client.post(f"/payments/mpesa/{txn['id']}/dismiss", headers=bearer(manager), json={"reason": "no"})).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get(f"/payments/mpesa/{txn['id']}", headers=bearer(other))).status_code == 404


# ---- settings ---------------------------------------------------------------------------------------------------------


async def test_the_owner_sets_the_paybill_and_registers_the_callback_with_safaricom(client):
    owner, _c = await owner_with_client(client)
    fake_daraja().registered.clear()
    s = await configure(client, owner, shortcode_type="paybill", kra_pin="P051234567K")
    assert s["shortcode"] == SHORTCODE and s["urls_registered_at"] is None and s["kra_pin"] == "P051234567K"
    assert s["confirmation_url"].endswith("/confirmation") and "mpesa" not in s["confirmation_url"].lower()  # Safaricom refuses addresses with that word
    reg = await client.post("/payments/settings/register-urls", headers=bearer(owner))
    assert reg.status_code == 200
    [sent] = fake_daraja().registered
    assert sent["shortcode"] == SHORTCODE and sent["confirmation_url"] == s["confirmation_url"] and sent["validation_url"] == s["validation_url"]
    assert (await client.get("/payments/settings", headers=bearer(owner))).json()["urls_registered_at"]
    changed = await configure(client, owner, shortcode="400200")
    assert changed["urls_registered_at"] is None  # a new number has to be registered again


async def test_registering_needs_a_number_and_reports_a_safaricom_failure_plainly(client):
    owner, _c = await owner_with_client(client)
    assert (await client.post("/payments/settings/register-urls", headers=bearer(owner))).json()["detail"]["code"] == "no_shortcode"
    await configure(client, owner)
    fake_daraja().fail_with = "Safaricom did not accept the request: HTTPStatusError"
    try:
        res = await client.post("/payments/settings/register-urls", headers=bearer(owner))
        assert res.status_code == 502 and "Safaricom" in res.json()["detail"]["message"]
    finally:
        fake_daraja().fail_with = None


async def test_bad_settings_are_refused_and_only_the_owner_can_change_them(client):
    owner, _c = await owner_with_client(client)
    put = lambda who, **kw: client.put("/payments/settings", headers=bearer(who), json=kw)
    assert (await put(owner, shortcode="abc")).status_code == 422
    assert (await put(owner, kra_pin="12345")).json()["detail"]["code"] == "invalid_kra_pin"
    assert (await put(owner, reminders_enabled=True, reminder_channels=[])).json()["detail"]["code"] == "no_channel"
    assert (await put(owner, reminder_offsets=[500])).json()["detail"]["code"] == "bad_offsets"
    assert (await put(owner, etims_enabled=True)).json()["detail"]["code"] == "kra_pin_required"
    assert (await put(owner, etims_enabled=True, kra_pin="P051234567K")).json()["detail"]["code"] == "device_serial_required"
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await put(accountant, shortcode="174379")).status_code == 403
    read = await client.get("/payments/settings", headers=bearer(accountant))
    assert read.status_code == 200 and "confirmation_url" not in read.json()  # the secret address is for the owner only
    assert (await put(owner, shortcode="174379")).status_code == 200
    assert "payment_settings.changed" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_a_payment_can_be_simulated_in_development_and_follows_the_same_path(client):
    owner, _c, inv, _bid = await setup(client)
    res = await client.post("/payments/simulate", headers=bearer(owner), json={"amount_cents": 1_000_000, "bill_ref": inv["number"]})
    assert res.status_code == 201 and res.json()["status"] == "matched" and res.json()["source"] == "simulated"
    assert (await invoice(client, owner, inv["id"]))["status"] == "paid"
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.post("/payments/simulate", headers=bearer(accountant), json={"amount_cents": 100, "bill_ref": "x"})).status_code == 403
