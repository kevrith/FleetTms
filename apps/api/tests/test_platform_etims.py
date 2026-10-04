"""FleetTms's own tax invoices to KRA for what businesses pay it: queued when paid, sent from the platform's device, retried, reviewed."""

import pytest
from sqlalchemy import select, update

from app import platform_etims
from app.config import settings
from app.db import get_sessionmaker
from app.etims import EtimsRejected, EtimsTransient, fake_etims
from app.models import PlatformEtimsSubmission
from app.platform_etims import run_submissions
from tests.billing_helpers import pay_invoice, subscription
from tests.fleet import add_vehicle
from tests.helpers import bearer, driver_session, owner_session
from tests.money import configure
from tests.pdf_text import pdf_text
from tests.test_support_and_privacy import make_platform_admin

PLATFORM_PIN = "P000111222Z"
BUYER_PIN = "P051234567K"


@pytest.fixture(autouse=True)
def _platform_device(billing, monkeypatch):
    monkeypatch.setattr(settings, "platform_kra_pin", PLATFORM_PIN)
    monkeypatch.setattr(settings, "platform_etims_device_serial", "PLAT0012345")
    monkeypatch.setattr(settings, "platform_vat_pct", 16)
    fake_etims().reset()
    yield
    fake_etims().reset()


async def rows():
    async with get_sessionmaker()() as db:
        return list((await db.execute(select(PlatformEtimsSubmission).order_by(PlatformEtimsSubmission.invoice_no))).scalars())


async def paying_owner(client, *, pin=BUYER_PIN):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    if pin:
        await configure(client, owner, kra_pin=pin)
    return owner


def test_the_vat_is_taken_out_of_the_vat_inclusive_price_and_always_adds_back_to_the_total():
    assert platform_etims.amounts(180_000) == (155_172, 24_828)
    assert platform_etims.amounts(116_000) == (100_000, 16_000)
    assert platform_etims.amounts(180_000, vat_pct=0) == (180_000, 0)
    for total in (1, 99, 100_000, 180_000, 1_620_001, 600_000):
        net, vat = platform_etims.amounts(total)
        assert net + vat == total and abs(vat - total * 16 / 116) <= 0.5


async def test_a_paid_subscription_is_sent_to_kra_from_the_platforms_device_with_the_buyers_pin_and_the_vat_split(client):
    owner = await paying_owner(client)
    invoice = await pay_invoice(client, owner)
    assert invoice["tax_invoice"] == {"status": "sending", "receipt_no": None, "filed_at": None}  # queued, not yet sent
    assert fake_etims().sent == []
    assert await run_submissions() == 1
    (sent,) = fake_etims().sent
    assert sent["tin"] == PLATFORM_PIN and sent["bhfId"] == "00" and sent["invcNo"] == 1 and sent["custTin"] == BUYER_PIN and sent["rcptTyCd"] == "S"
    assert sent["totTaxblAmt"] == 1551.72 and sent["totTaxAmt"] == 248.28 and sent["totAmt"] == 1800.0
    assert sent["taxRtB"] == 16 and sent["taxblAmtB"] == 1551.72 and sent["itemList"][0]["taxTyCd"] == "B"
    assert "FleetTms fleet software subscription" in sent["itemList"][0]["itemNm"] and "(1 vehicles)" in sent["itemList"][0]["itemNm"]
    (row,) = await rows()
    assert row.status == "submitted" and row.receipt_no == "1001" and row.attempts == 1
    shown = (await subscription(client, owner))["invoices"][0]["tax_invoice"]
    assert shown["status"] == "filed" and shown["receipt_no"] == "1001"
    assert "platform_etims.submitted" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]  # the owner can see it was filed
    assert await run_submissions() == 0 and len(fake_etims().sent) == 1  # nothing is sent twice


async def test_a_text_bundle_is_also_a_sale_and_invoice_numbers_run_on_after_each_other(client):
    first = await paying_owner(client)
    await pay_invoice(client, first)
    bundle = (await client.post("/subscription/sms-bundles", headers=bearer(first), json={"messages": 500})).json()
    assert (await client.post(f"/subscription/invoices/{bundle['id']}/pay", headers=bearer(first), json={"phone": "0712345678"})).status_code == 200
    from tests.billing_helpers import answer_prompt

    assert (await answer_prompt(client, receipt="QWE7654321")).status_code == 200
    assert [r.invoice_no for r in await rows()] == [1, 2]
    assert await run_submissions() == 2
    texts = fake_etims().sent[1]
    assert texts["invcNo"] == 2 and texts["totAmt"] == 600.0 and texts["itemList"][0]["itemNm"] == "FleetTms text messages: bundle of 500"


async def test_nothing_is_queued_for_an_invoice_that_is_not_paid_or_when_the_platform_has_no_device(client, monkeypatch):
    owner = await paying_owner(client)
    invoice = (await client.post("/subscription/invoices", headers=bearer(owner))).json()
    assert invoice["tax_invoice"] is None and await rows() == []  # raised, not paid: no sale
    monkeypatch.setattr(settings, "platform_etims_device_serial", "")
    assert platform_etims.enabled() is False
    await pay_invoice(client, owner)
    assert await rows() == [] and await run_submissions() == 0 and fake_etims().sent == []
    assert (await subscription(client, owner))["access"]["state"] == "active"  # the payment itself is untouched


async def test_a_business_without_a_pin_is_still_invoiced_and_the_pdf_shows_the_kra_receipt_once_filed(client):
    owner = await paying_owner(client, pin=None)
    paid = await pay_invoice(client, owner)
    await run_submissions()
    assert fake_etims().sent[0]["custTin"] is None
    res = await client.get(f"/subscription/invoices/{paid['id']}/pdf", headers=bearer(owner))
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf" and res.headers["content-disposition"] == f'attachment; filename="{paid["number"]}.pdf"'
    text = pdf_text(res.content)
    assert "Tax invoice SUB-0001" in text and f"Seller KRA PIN {PLATFORM_PIN}" in text and "VAT 16%" in text and "KES 248.28" in text and "KES 1,800.00" in text
    assert "KRA eTIMS receipt no. 1001" in text


async def test_an_unpaid_invoice_pdf_is_not_a_tax_invoice_and_a_paid_one_not_yet_filed_says_so(client):
    owner = await paying_owner(client)
    invoice = (await client.post("/subscription/invoices", headers=bearer(owner))).json()
    unpaid = pdf_text((await client.get(f"/subscription/invoices/{invoice['id']}/pdf", headers=bearer(owner))).content)
    assert "Invoice SUB-0001" in unpaid and "Tax invoice" not in unpaid and "Balance due" in unpaid
    await pay_invoice(client, owner)
    waiting = pdf_text((await client.get(f"/subscription/invoices/{invoice['id']}/pdf", headers=bearer(owner))).content)
    assert "Tax invoice SUB-0001" in waiting and "being sent to KRA" in waiting and "eTIMS receipt" not in waiting
    assert (await client.get("/subscription/invoices/00000000-0000-0000-0000-000000000000/pdf", headers=bearer(owner))).status_code == 404


async def test_only_the_owner_of_the_business_can_see_its_invoice_pdf(client):
    owner = await paying_owner(client)
    paid = await pay_invoice(client, owner)
    other, _ = await owner_session(client, business="Other Haulage", email="other@example.com")
    assert (await client.get(f"/subscription/invoices/{paid['id']}/pdf", headers=bearer(other))).status_code == 404
    driver = await driver_session(client, owner, "0712000111")
    assert (await client.get(f"/subscription/invoices/{paid['id']}/pdf", headers=bearer(driver))).status_code == 403


async def test_kra_being_unreachable_is_retried_later_and_a_refusal_waits_for_the_platform_admin(client):
    owner = await paying_owner(client)
    await pay_invoice(client, owner)
    fake_etims().script = [EtimsTransient("Could not reach KRA: ConnectError")]
    assert await run_submissions() == 0
    (row,) = await rows()
    assert row.status == "pending" and row.attempts == 1 and "Could not reach KRA" in row.last_error and row.next_attempt_at > row.last_attempt_at
    assert await run_submissions() == 0  # not due yet
    async with get_sessionmaker()() as db:
        await db.execute(update(PlatformEtimsSubmission).values(next_attempt_at=row.last_attempt_at))
        await db.commit()
    fake_etims().script = [EtimsRejected("961", "Invalid buyer PIN")]
    assert await run_submissions() == 0
    (row,) = await rows()
    assert row.status == "needs_review" and row.next_attempt_at is None and "Invalid buyer PIN" in row.last_error
    shown = (await subscription(client, owner))["invoices"][0]["tax_invoice"]
    assert shown == {"status": "sending", "receipt_no": None, "filed_at": None}  # the customer never sees KRA's error text

    admin = await make_platform_admin(client)
    overview = (await client.get("/platform/etims", headers=bearer(admin))).json()
    assert overview["enabled"] is True and overview["needs_review"] == 1 and "Invalid buyer PIN" in overview["invoices"][0]["last_error"]
    assert overview["invoices"][0]["status"] == "needs_review" and overview["invoices"][0]["business_has_pin"] is True
    retried = await client.post(f"/platform/etims/{overview['invoices'][0]['id']}/retry", headers=bearer(admin))
    assert retried.status_code == 200 and retried.json()["status"] == "submitted" and retried.json()["receipt_no"] == "1001"
    assert (await client.post(f"/platform/etims/{overview['invoices'][0]['id']}/retry", headers=bearer(admin))).status_code == 409
    assert "platform_etims.retried" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_the_platform_admin_can_mark_an_invoice_as_handled_by_hand(client):
    owner = await paying_owner(client)
    await pay_invoice(client, owner)
    fake_etims().script = [EtimsRejected("961", "Invalid buyer PIN")]
    await run_submissions()
    admin = await make_platform_admin(client)
    (item,) = (await client.get("/platform/etims", headers=bearer(admin))).json()["invoices"]
    assert (await client.post(f"/platform/etims/{item['id']}/resolve", headers=bearer(admin), json={"note": "x"})).status_code == 422
    done = await client.post(f"/platform/etims/{item['id']}/resolve", headers=bearer(admin), json={"note": "Entered on the KRA portal", "receipt_no": "KRA-778"})
    assert done.status_code == 200 and done.json()["status"] == "resolved" and done.json()["receipt_no"] == "KRA-778"
    assert (await client.post(f"/platform/etims/{item['id']}/resolve", headers=bearer(admin), json={"note": "again please"})).status_code == 409
    assert await run_submissions() == 0
    assert "platform_etims.resolved_by_hand" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_backfill_queues_what_was_paid_before_the_device_was_set_up_and_connect_registers_the_device(client, monkeypatch):
    owner = await paying_owner(client)
    monkeypatch.setattr(settings, "platform_etims_device_serial", "")
    await pay_invoice(client, owner)
    assert await rows() == []
    admin = await make_platform_admin(client)
    assert (await client.post("/platform/etims/backfill", headers=bearer(admin))).json()["detail"]["code"] == "etims_setup"
    assert (await client.post("/platform/etims/connect", headers=bearer(admin))).status_code == 422
    monkeypatch.setattr(settings, "platform_etims_device_serial", "PLAT0012345")
    assert (await client.post("/platform/etims/connect", headers=bearer(admin))).json() == {"connected": True}
    assert fake_etims().connected[0].tin == PLATFORM_PIN and fake_etims().items[0]["taxTyCd"] == "B"
    assert (await client.post("/platform/etims/backfill", headers=bearer(admin))).json() == {"queued": 1}
    assert (await client.post("/platform/etims/backfill", headers=bearer(admin))).json() == {"queued": 0}  # safe to run again
    assert await run_submissions() == 1


async def test_a_platform_that_is_not_vat_registered_sends_no_vat(client, monkeypatch):
    monkeypatch.setattr(settings, "platform_vat_pct", 0)
    owner = await paying_owner(client)
    await pay_invoice(client, owner)
    await run_submissions()
    (sent,) = fake_etims().sent
    assert sent["totTaxAmt"] == 0 and sent["totTaxblAmt"] == 1800.0 and sent["itemList"][0]["taxTyCd"] == "D"


async def test_only_platform_admins_see_the_platform_invoices_to_kra(client):
    owner = await paying_owner(client)
    for method, path in (("GET", "/platform/etims"), ("POST", "/platform/etims/connect"), ("POST", "/platform/etims/backfill")):
        res = await client.request(method, path, headers=bearer(owner))
        assert res.status_code == 403, path
