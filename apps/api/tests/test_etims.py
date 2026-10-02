from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.db import get_sessionmaker
from app.etims import EtimsRejected, EtimsTransient, fake_etims
from app.etims_rules import (
    RETRY_MINUTES,
    EtimsRuleError,
    build_sale,
    retry_delay_minutes,
    split_vat,
    tax_code,
)
from app.etims_service import run_submissions
from app.models import EtimsSubmission
from app.tenancy import current_business_id
from tests.helpers import bearer, owner_session, staff_session
from tests.money import business_id, configure, owner_with_client, seed_invoice

PIN = "P051234567K"


@pytest.fixture(autouse=True)
def _fresh_kra():
    fake_etims().reset()
    yield
    fake_etims().reset()


async def setup(client, *, enabled=True, **client_extra):
    owner, c = await owner_with_client(client, **client_extra)
    await configure(client, owner, etims_enabled=enabled, etims_device_serial="DEV0012345" if enabled else None, kra_pin=PIN)
    return owner, c


async def queue(client, owner):
    return (await client.get("/etims/submissions", headers=bearer(owner))).json()


async def in_db(fn):
    async with get_sessionmaker()() as db:
        current_business_id.set(await business_id())
        try:
            result = await fn(db)
            await db.commit()
            return result
        finally:
            current_business_id.set(None)


async def send_due():
    return await run_submissions()


async def make_due():
    """Pretends the wait is over, so a retry can be tried now."""
    await in_db(lambda db: db.execute(update(EtimsSubmission).where(EtimsSubmission.status == "pending").values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))))


# ---- the rules --------------------------------------------------------------------------------------------------------


def test_tax_codes_follow_the_vat_rate_and_the_businesss_choice_for_none():
    assert tax_code(16, "A") == "B" and tax_code(8, "A") == "E"
    assert tax_code(0, "A") == "A" and tax_code(0, "C") == "C" and tax_code(0, "D") == "D"
    with pytest.raises(EtimsRuleError, match="12 percent"):
        tax_code(12, "A")


def test_the_retry_schedule_grows_and_ends():
    assert [retry_delay_minutes(n) for n in range(1, len(RETRY_MINUTES) + 1)] == list(RETRY_MINUTES)
    assert retry_delay_minutes(0) is None and retry_delay_minutes(len(RETRY_MINUTES) + 1) is None
    assert list(RETRY_MINUTES) == sorted(RETRY_MINUTES)


def test_vat_is_shared_across_lines_and_adds_up_exactly():
    shares = split_vat([1005, 1005, 1005], 16, 482)  # 16 percent of 3015 is 482.4
    assert sum(shares) == 482 and all(abs(s - 161) <= 1 for s in shares)
    assert split_vat([], 16, 0) == []


def _sale(**kw):
    base = {
        "tin": PIN, "branch_id": "00", "invoice_no": 7, "original_no": None, "business_name": "Kamau Haulage", "client_name": "Bamburi Cement", "client_pin": "P051234567K", "client_phone": "+254712000111",
        "lines": [{"description": "Transport Mombasa to Nairobi", "amount_cents": 1_000_000}, {"description": "Trip 1 (covered by the monthly fee)", "amount_cents": 0}],
        "vat_pct": 16, "vat_cents": 160_000, "zero_code": "A", "item_code": "KE3NTXU0000001", "item_class_code": "78101800", "pkg_unit": "NT", "qty_unit": "U",
        "issued_at": datetime(2026, 10, 2, 9, 30, tzinfo=UTC), "credit_note": False,
    }  # fmt: skip
    return build_sale(**{**base, **kw})


def test_the_sale_body_totals_tax_and_leaves_out_lines_with_nothing_to_pay():
    body = _sale()
    assert body["invcNo"] == 7 and body["orgInvcNo"] == 0 and body["rcptTyCd"] == "S" and body["totItemCnt"] == 1
    assert (body["totTaxblAmt"], body["totTaxAmt"], body["totAmt"]) == (10000.0, 1600.0, 11600.0)
    assert (body["taxblAmtB"], body["taxAmtB"], body["taxRtB"], body["taxblAmtA"], body["taxAmtA"]) == (10000.0, 1600.0, 16, 0, 0)
    [item] = body["itemList"]
    assert item["taxTyCd"] == "B" and item["totAmt"] == 11600.0 and item["itemCd"] == "KE3NTXU0000001" and item["qty"] == 1
    assert body["cfmDt"] == "20261002123000" and body["salesDt"] == "20261002"  # Nairobi time, three hours ahead


def test_a_credit_note_names_the_invoice_it_cancels_and_a_free_invoice_is_refused():
    note = _sale(invoice_no=9, original_no=7, credit_note=True)
    assert note["rcptTyCd"] == "R" and note["orgInvcNo"] == 7 and note["rfdRsnCd"] and note["rfdDt"]
    with pytest.raises(EtimsRuleError, match="nothing to charge"):
        _sale(lines=[{"description": "covered", "amount_cents": 0}])
    with pytest.raises(EtimsRuleError, match="12 percent"):
        _sale(vat_pct=12)


# ---- the flow -----------------------------------------------------------------------------------------------------------


async def test_nothing_is_queued_until_the_owner_turns_etims_on(client):
    owner, c = await setup(client, enabled=False)
    await seed_invoice(c["id"])
    assert await queue(client, owner) == []
    assert (await client.get("/etims/summary", headers=bearer(owner))).json()["enabled"] is False


async def test_an_invoice_is_queued_when_issued_and_sent_to_kra_by_the_worker(client):
    owner, c = await setup(client)
    inv = await seed_invoice(c["id"], total_cents=1_160_000, vat_pct=16)
    [row] = await queue(client, owner)
    assert row["status"] == "pending" and row["invoice_number"] == inv["number"] and row["invoice_no"] == 1 and row["attempts"] == 0
    assert await send_due() == 1
    [done] = await queue(client, owner)
    assert done["status"] == "submitted" and done["receipt_no"] == "1001" and done["attempts"] == 1 and done["last_error"] is None
    [sent] = fake_etims().sent
    assert sent["tin"] == PIN and sent["bhfId"] == "00" and sent["invcNo"] == 1 and sent["custTin"] == "P051234567K" and sent["totAmt"] == 11600.0
    assert sent["itemList"][0]["taxTyCd"] == "B"
    assert await send_due() == 0  # not sent again
    listed = (await client.get("/invoices", headers=bearer(owner))).json()
    assert listed[0]["etims"] == {"status": "submitted", "receipt_no": "1001", "last_error": None, "credit_note_status": None}
    assert (await client.get(f"/invoices/{inv['id']}/pdf", headers=bearer(owner))).content.startswith(b"%PDF")  # carries the receipt and its QR code
    assert "etims.submitted" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_a_delivery_issues_an_invoice_that_is_queued_for_kra(client):
    from tests.test_pod_billing import deliver, job_for, running
    from tests.test_pod_billing import setup as pod_setup

    f, c, r = await pod_setup(client)
    await configure(client, f.owner, etims_enabled=True, etims_device_serial="DEV0012345", kra_pin=PIN)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    assert (await deliver(client, f, trip_id)).status_code == 200
    [row] = await queue(client, f.owner)
    assert row["status"] == "pending" and row["invoice_number"] == "INV-0001"


async def test_when_kra_cannot_be_reached_it_waits_and_tries_again_with_growing_gaps(client):
    owner, c = await setup(client)
    await seed_invoice(c["id"])
    fake_etims().script = [EtimsTransient("Could not reach KRA: ConnectTimeout")]
    assert await send_due() == 0
    [row] = await queue(client, owner)
    assert row["status"] == "pending" and row["attempts"] == 1 and "ConnectTimeout" in row["last_error"]
    wait = datetime.fromisoformat(row["next_attempt_at"]) - datetime.fromisoformat(row["last_attempt_at"])
    assert timedelta(minutes=4, seconds=50) < wait < timedelta(minutes=5, seconds=10)
    assert await send_due() == 0 and fake_etims().sent == []  # not due yet, so not tried
    await make_due()
    assert await send_due() == 1
    [row] = await queue(client, owner)
    assert row["status"] == "submitted" and row["attempts"] == 2 and row["last_error"] is None


async def test_after_the_last_try_it_goes_to_the_review_queue_and_the_owner_can_send_it_again(client):
    owner, c = await setup(client)
    await seed_invoice(c["id"])
    fake_etims().script = [EtimsTransient("KRA had a problem (HTTP 503).")] * (len(RETRY_MINUTES) + 1)
    for _ in range(len(RETRY_MINUTES)):
        await send_due()
        await make_due()
    assert (await queue(client, owner))[0]["status"] == "pending"
    await send_due()
    [row] = await queue(client, owner)
    assert row["status"] == "needs_review" and row["next_attempt_at"] is None and row["last_error"].startswith("Gave up after 9 tries")
    assert await send_due() == 0
    dash = (await client.get("/dashboard", headers=bearer(owner))).json()
    assert "etims_stuck" in [a["kind"] for a in dash["alerts"]]
    attention = (await client.get("/etims/submissions?status_filter=attention", headers=bearer(owner))).json()
    assert len(attention) == 1
    again = await client.post(f"/etims/submissions/{row['id']}/retry", headers=bearer(owner))
    assert again.status_code == 200 and again.json()["status"] == "submitted" and again.json()["attempts"] == 1


async def test_a_refusal_from_kra_needs_a_person_at_once_and_retrying_after_the_fix_works(client):
    owner, c = await setup(client)
    await seed_invoice(c["id"])
    fake_etims().script = [EtimsRejected("961", "Customer PIN is invalid")]
    await send_due()
    [row] = await queue(client, owner)
    assert row["status"] == "needs_review" and row["attempts"] == 1 and "Customer PIN is invalid" in row["last_error"] and "961" in row["last_error"]
    fixed = await client.post(f"/etims/submissions/{row['id']}/retry", headers=bearer(owner))
    assert fixed.json()["status"] == "submitted" and fixed.json()["receipt_no"] == "1001"
    assert (await client.post(f"/etims/submissions/{row['id']}/retry", headers=bearer(owner))).status_code == 409  # already done


async def test_a_vat_rate_with_no_etims_code_is_explained_not_retried(client):
    owner, c = await setup(client)
    await seed_invoice(c["id"], total_cents=1_120_000, vat_pct=12)
    await send_due()
    [row] = await queue(client, owner)
    assert row["status"] == "needs_review" and "no tax code for VAT of 12 percent" in row["last_error"] and fake_etims().sent == []


async def test_a_voided_invoice_kra_already_has_is_cancelled_with_a_credit_note(client):
    owner, c = await setup(client)
    inv = await seed_invoice(c["id"], total_cents=1_160_000, vat_pct=16)
    await send_due()
    assert (await client.post(f"/invoices/{inv['id']}/void", headers=bearer(owner), json={"reason": "Raised in error"})).status_code == 200
    rows = {r["kind"]: r for r in await queue(client, owner)}
    assert rows["credit_note"]["status"] == "pending" and rows["credit_note"]["invoice_no"] == 2
    assert await send_due() == 1
    note = fake_etims().sent[-1]
    assert note["rcptTyCd"] == "R" and note["orgInvcNo"] == 1 and note["invcNo"] == 2 and note["totAmt"] == 11600.0
    assert (await client.get(f"/invoices/{inv['id']}", headers=bearer(owner))).json()["etims"]["credit_note_status"] == "submitted"


async def test_a_voided_invoice_kra_never_received_just_stops_being_sent(client):
    owner, c = await setup(client)
    inv = await seed_invoice(c["id"])
    await client.post(f"/invoices/{inv['id']}/void", headers=bearer(owner), json={"reason": "Raised in error"})
    [row] = await queue(client, owner)
    assert row["status"] == "resolved" and "voided before it was sent" in row["resolved_note"]
    assert await send_due() == 0 and fake_etims().sent == []


async def test_an_invoice_dealt_with_on_the_kra_portal_is_marked_by_hand(client):
    owner, c = await setup(client)
    await seed_invoice(c["id"])
    fake_etims().script = [EtimsRejected("999", "Something odd")]
    await send_due()
    [row] = await queue(client, owner)
    short = await client.post(f"/etims/submissions/{row['id']}/resolve", headers=bearer(owner), json={"note": "x"})
    assert short.status_code == 422
    done = await client.post(f"/etims/submissions/{row['id']}/resolve", headers=bearer(owner), json={"note": "Entered on the KRA portal", "receipt_no": "KRA-445"})
    assert done.json()["status"] == "resolved" and done.json()["receipt_no"] == "KRA-445" and done.json()["resolved_note"] == "Entered on the KRA portal"
    assert (await client.post(f"/etims/submissions/{row['id']}/resolve", headers=bearer(owner), json={"note": "again again"})).status_code == 409
    assert "etims.resolved_by_hand" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_connecting_checks_the_device_and_registers_the_service(client):
    owner, _c = await setup(client)
    res = await client.post("/etims/connect", headers=bearer(owner))
    assert res.status_code == 200 and res.json()["connected_at"]
    [device] = fake_etims().connected
    assert device.tin == PIN and device.serial == "DEV0012345" and device.branch_id == "00"
    [item] = fake_etims().items
    assert item["itemCd"] == "KE3NTXU0000001" and item["itemTyCd"] == "3"
    assert (await client.get("/etims/summary", headers=bearer(owner))).json()["connected_at"]
    fake_etims().script = [EtimsRejected("901", "Device not registered")]
    refused = await client.post("/etims/connect", headers=bearer(owner))
    assert refused.status_code == 422 and "Device not registered" in refused.json()["detail"]["message"]
    fake_etims().script = [EtimsTransient("Could not reach KRA: ConnectError")]
    assert (await client.post("/etims/connect", headers=bearer(owner))).status_code == 502
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.post("/etims/connect", headers=bearer(accountant))).status_code == 403


async def test_changing_the_device_means_connecting_again(client):
    owner, _c = await setup(client)
    await client.post("/etims/connect", headers=bearer(owner))
    await configure(client, owner, etims_enabled=True, etims_device_serial="DEV9999999", kra_pin=PIN)
    assert (await client.get("/etims/summary", headers=bearer(owner))).json()["connected_at"] is None


async def test_the_queue_is_for_owner_and_accountant_and_one_business_cannot_touch_anothers(client):
    owner, c = await setup(client)
    await seed_invoice(c["id"])
    [row] = await queue(client, owner)
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert len(await queue(client, accountant)) == 1
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.get("/etims/submissions", headers=bearer(manager))).status_code == 403
    assert (await client.post(f"/etims/submissions/{row['id']}/retry", headers=bearer(manager))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert await queue(client, other) == []
    assert (await client.post(f"/etims/submissions/{row['id']}/retry", headers=bearer(other))).status_code == 404


async def test_the_worker_sends_for_every_business_with_the_right_tin(client):
    _owner, c = await setup(client)
    await seed_invoice(c["id"])
    other, _oc = await owner_session(client, "Bravo", "b@example.com")
    from tests.test_clients import add_client

    bc = await add_client(client, other, billing_method="per_trip", rate_cents=1)
    await client.put("/payments/settings", headers=bearer(other), json={"etims_enabled": True, "etims_device_serial": "DEVBRAVO01", "kra_pin": "A000111222B"})
    await seed_invoice(bc["id"], business="Bravo")
    assert await send_due() == 2
    assert sorted(b["tin"] for b in fake_etims().sent) == sorted([PIN, "A000111222B"])
    assert {b["invcNo"] for b in fake_etims().sent} == {1}  # each business has its own sequence


async def test_etims_numbers_run_in_order_per_business(client):
    owner, c = await setup(client)
    for _ in range(3):
        await seed_invoice(c["id"])
    rows = await queue(client, owner)
    assert sorted(r["invoice_no"] for r in rows) == [1, 2, 3]
    await in_db(lambda db: db.execute(select(EtimsSubmission)))
