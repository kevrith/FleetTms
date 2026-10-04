"""Paying a subscription by card on the provider's hosted page: the webhook and the check on return both settle it, once, and only for the right amount."""

import hashlib
import hmac
import json
import secrets

import httpx
import pytest

from app import card_payments, platform_mpesa
from app.card_payments import Charge
from app.config import settings
from tests.billing_helpers import answer_prompt, days, set_dates, subscription
from tests.fleet import add_vehicle
from tests.helpers import bearer, driver_session, owner_session
from tests.shots import fleet

SECRET = secrets.token_urlsafe(24)  # made fresh each run, never written down
REAL_CLIENT = httpx.AsyncClient  # kept before any test swaps in a stand-in


@pytest.fixture(autouse=True)
def _cards(billing, monkeypatch):
    monkeypatch.setattr(settings, "paystack_secret_key", "")  # the stand-in, unless a test switches the real one on
    card_payments.fake_cards().reset()
    platform_mpesa.fake_prompts().sent.clear()
    yield
    card_payments.fake_cards().reset()


def signed(payload: dict, secret: str = SECRET) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    return body, {"x-paystack-signature": hmac.new(secret.encode(), body, hashlib.sha512).hexdigest(), "content-type": "application/json"}


def success_event(reference: str, amount: int = 180_000, currency: str = "KES", event: str = "charge.success", status: str = "success") -> dict:
    return {"event": event, "data": {"reference": reference, "amount": amount, "currency": currency, "status": status}}


async def webhook(client, payload: dict, monkeypatch, **kw):
    """The provider's report. The key is set only while it is delivered: with a key the real provider would be used, not the stand-in."""
    monkeypatch.setattr(settings, "paystack_secret_key", SECRET)
    body, headers = signed(payload, **kw)
    try:
        return await client.post("/hooks/paystack", content=body, headers=headers)
    finally:
        monkeypatch.setattr(settings, "paystack_secret_key", "")


async def open_invoice(client):
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    return owner, (await client.post("/subscription/invoices", headers=bearer(owner))).json()


async def start_card(client, owner, invoice):
    res = await client.post(f"/subscription/invoices/{invoice['id']}/pay-card", headers=bearer(owner))
    assert res.status_code == 200, res.text
    return res.json(), card_payments.fake_cards().started[-1]["reference"]


async def test_the_owner_is_sent_to_the_providers_page_and_the_invoice_waits_until_the_provider_says_it_was_paid(client):
    owner, invoice = await open_invoice(client)
    started, reference = await start_card(client, owner, invoice)
    assert started["status"] == "pending" and started["checkout_url"] == f"https://checkout.example.test/pay/{reference}"
    [sent] = card_payments.fake_cards().started
    assert sent["email"] == "owner@example.com" and sent["amount_cents"] == 180_000 and sent["description"] == "FleetTms SUB-0001"
    assert sent["callback_url"].endswith(f"/settings/subscription?card={invoice['id']}") and len(reference) <= 64
    s = await subscription(client, owner)
    assert s["card_available"] is True and s["access"]["state"] == "trialing" and s["open_invoice"]["status"] == "issued"
    assert "subscription.card_payment_started" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_a_signed_success_report_pays_the_invoice_once_and_starts_the_period(client, monkeypatch):
    owner, invoice = await open_invoice(client)
    _, reference = await start_card(client, owner, invoice)
    assert (await webhook(client, success_event(reference), monkeypatch)).status_code == 200
    s = await subscription(client, owner)
    paid = s["invoices"][0]
    assert s["access"]["state"] == "active" and s["paid_until"] and s["open_invoice"] is None
    assert paid["status"] == "paid" and paid["payment_method"] == "card" and paid["mpesa_code"] == reference[-12:].upper()
    first_end = s["paid_until"]
    assert (await webhook(client, success_event(reference), monkeypatch)).status_code == 200  # the provider repeats itself
    assert (await subscription(client, owner))["paid_until"] == first_end
    got = (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()
    assert got["last_payment"] == {"status": "paid", "note": "Paid"}
    assert "subscription.paid" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_coming_back_from_the_card_page_settles_it_at_once_and_the_webhook_that_follows_changes_nothing(client, monkeypatch):
    owner, invoice = await open_invoice(client)
    _, reference = await start_card(client, owner, invoice)
    pending = await client.post(f"/subscription/invoices/{invoice['id']}/card-check", headers=bearer(owner))
    assert pending.status_code == 200 and pending.json()["status"] == "issued" and pending.json()["last_payment"]["status"] == "pending"
    card_payments.fake_cards().results[reference] = Charge(reference, "success", 180_000, "KES")
    done = await client.post(f"/subscription/invoices/{invoice['id']}/card-check", headers=bearer(owner))
    assert done.json()["status"] == "paid" and done.json()["payment_method"] == "card"
    end = (await subscription(client, owner))["paid_until"]
    assert (await webhook(client, success_event(reference), monkeypatch)).status_code == 200
    assert (await subscription(client, owner))["paid_until"] == end
    assert len([e for e in (await client.get("/audit", headers=bearer(owner))).json() if e["action"] == "subscription.paid"]) == 1


async def test_a_declined_or_abandoned_card_leaves_the_invoice_open_to_try_again(client):
    owner, invoice = await open_invoice(client)
    _, first = await start_card(client, owner, invoice)
    card_payments.fake_cards().results[first] = Charge(first, "failed")
    res = await client.post(f"/subscription/invoices/{invoice['id']}/card-check", headers=bearer(owner))
    assert res.json()["status"] == "issued" and res.json()["last_payment"] == {"status": "failed", "note": "The card payment was not completed."}
    _, second = await start_card(client, owner, invoice)
    assert second != first
    card_payments.fake_cards().results[second] = Charge(second, "success", 180_000, "KES")
    assert (await client.post(f"/subscription/invoices/{invoice['id']}/card-check", headers=bearer(owner))).json()["status"] == "paid"


async def test_a_card_payment_for_less_than_the_invoice_or_in_another_currency_is_not_credited(client, monkeypatch):
    owner, invoice = await open_invoice(client)
    _, reference = await start_card(client, owner, invoice)
    assert (await webhook(client, success_event(reference, amount=179_999), monkeypatch)).status_code == 200
    got = (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()
    assert got["status"] == "issued" and got["last_payment"] == {"status": "failed", "note": "The amount paid was less than the invoice."}
    _, again = await start_card(client, owner, invoice)
    await webhook(client, success_event(again, currency="USD"), monkeypatch)
    assert (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()["status"] == "issued"
    _, third = await start_card(client, owner, invoice)
    await webhook(client, success_event(third, amount=250_000), monkeypatch)  # more is fine
    assert (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()["status"] == "paid"


async def test_nothing_unsigned_wrongly_signed_or_about_someone_elses_reference_is_believed(client, monkeypatch):
    owner, invoice = await open_invoice(client)
    _, reference = await start_card(client, owner, invoice)
    monkeypatch.setattr(settings, "paystack_secret_key", SECRET)
    body = json.dumps(success_event(reference)).encode()
    assert (await client.post("/hooks/paystack", content=body)).status_code == 403
    assert (await client.post("/hooks/paystack", content=body, headers={"x-paystack-signature": "0" * 128})).status_code == 403
    assert (await webhook(client, success_event(reference), monkeypatch, secret=secrets.token_urlsafe(24))).status_code == 403
    monkeypatch.setattr(settings, "paystack_secret_key", "")
    body, headers = signed(success_event(reference), secret="")
    assert (await client.post("/hooks/paystack", content=body, headers=headers)).status_code == 403  # no secret set: nothing is accepted
    assert (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()["status"] == "issued"
    assert (await webhook(client, success_event("ft-not-ours"), monkeypatch)).status_code == 200  # signed but unknown: nothing changes
    assert (await webhook(client, success_event(reference, event="charge.failed", status="failed"), monkeypatch)).status_code == 200  # not a success report
    assert (await webhook(client, {"event": "transfer.success", "data": "x"}, monkeypatch)).status_code == 200
    junk = b"not json"
    headers = {"x-paystack-signature": hmac.new(SECRET.encode(), junk, hashlib.sha512).hexdigest()}
    monkeypatch.setattr(settings, "paystack_secret_key", SECRET)
    assert (await client.post("/hooks/paystack", content=junk, headers=headers)).status_code == 200
    monkeypatch.setattr(settings, "paystack_secret_key", "")
    assert (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()["status"] == "issued"


async def test_a_card_payment_that_arrives_after_the_invoice_was_paid_another_way_is_not_applied_twice_and_is_flagged_for_refund(client, monkeypatch):
    owner, invoice = await open_invoice(client)
    _, reference = await start_card(client, owner, invoice)
    await client.post(f"/subscription/invoices/{invoice['id']}/pay", headers=bearer(owner), json={"phone": "0712345678"})
    assert (await answer_prompt(client)).status_code == 200
    s = await subscription(client, owner)
    end = s["paid_until"]
    assert s["invoices"][0]["payment_method"] == "mpesa"
    assert (await webhook(client, success_event(reference), monkeypatch)).status_code == 200
    s = await subscription(client, owner)
    assert s["paid_until"] == end and s["invoices"][0]["payment_method"] == "mpesa"  # the period was not extended a second time
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert "subscription.duplicate_card_payment" in actions and actions.count("subscription.paid") == 1


async def test_an_invoice_must_be_open_belong_to_the_business_and_be_paid_by_its_owner(client, monkeypatch):
    owner, invoice = await open_invoice(client)
    other, _ = await owner_session(client, business="Other Haulage", email="other@example.com")
    assert (await client.post(f"/subscription/invoices/{invoice['id']}/pay-card", headers=bearer(other))).status_code == 404
    assert (await client.post(f"/subscription/invoices/{invoice['id']}/card-check", headers=bearer(other))).status_code == 404
    driver = await driver_session(client, owner, "0712000111")
    assert (await client.post(f"/subscription/invoices/{invoice['id']}/pay-card", headers=bearer(driver))).status_code == 403
    _, reference = await start_card(client, owner, invoice)
    await webhook(client, success_event(reference), monkeypatch)
    paid_again = await client.post(f"/subscription/invoices/{invoice['id']}/pay-card", headers=bearer(owner))
    assert paid_again.status_code == 409 and paid_again.json()["detail"]["code"] == "not_payable"


async def test_the_card_button_is_off_in_production_until_the_provider_is_set_up_and_a_provider_outage_is_reported(client, monkeypatch):
    owner, invoice = await open_invoice(client)
    monkeypatch.setattr(settings, "environment", "production")
    assert (await subscription(client, owner))["card_available"] is False
    off = await client.post(f"/subscription/invoices/{invoice['id']}/pay-card", headers=bearer(owner))
    assert off.status_code == 409 and off.json()["detail"]["code"] == "card_not_set_up"
    monkeypatch.setattr(settings, "environment", "development")
    card_payments.fake_cards().fail_with = "The card payment service could not be reached: ConnectError"
    down = await client.post(f"/subscription/invoices/{invoice['id']}/pay-card", headers=bearer(owner))
    assert down.status_code == 502 and down.json()["detail"]["code"] == "card_failed" and "ConnectError" in down.json()["detail"]["message"]
    got = (await client.get(f"/subscription/invoices/{invoice['id']}", headers=bearer(owner))).json()
    assert got["last_payment"] is None  # nothing was recorded for a payment that never started


async def test_a_read_only_account_can_pay_by_card_and_is_switched_back_on(client, monkeypatch):
    f = await fleet(client)
    invoice = (await client.post("/subscription/invoices", headers=bearer(f.owner))).json()
    await set_dates(trial_ends=days(-30))
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "X"})).status_code == 402
    _, reference = await start_card(client, f.owner, invoice)
    await webhook(client, success_event(reference, amount=invoice["total_cents"]), monkeypatch)
    assert (await subscription(client, f.owner))["access"]["state"] == "active"
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "Back"})).status_code == 201


async def test_a_paid_card_invoice_is_queued_for_the_platforms_kra_invoice_like_any_other(client, monkeypatch):
    from app.models import PlatformEtimsSubmission  # noqa: F401
    from tests.test_platform_etims import rows

    monkeypatch.setattr(settings, "platform_kra_pin", "P000111222Z")
    monkeypatch.setattr(settings, "platform_etims_device_serial", "PLAT0012345")
    owner, invoice = await open_invoice(client)
    _, reference = await start_card(client, owner, invoice)
    await webhook(client, success_event(reference), monkeypatch)
    assert [r.status for r in await rows()] == ["pending"]


# ---- the real provider ------------------------------------------------------------------------------------------------------


def paystack(monkeypatch, handler):
    monkeypatch.setattr(settings, "paystack_secret_key", SECRET)
    monkeypatch.setattr(card_payments.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    assert card_payments.is_live() and isinstance(card_payments.get_cards(), card_payments.Paystack)


async def test_the_real_provider_is_asked_for_a_card_only_page_in_shillings_and_the_page_address_comes_back(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": True, "data": {"authorization_url": "https://checkout.paystack.com/abc", "reference": "ft1"}})

    paystack(monkeypatch, handler)
    url = await card_payments.get_cards().start(email="owner@example.com", amount_cents=180_000, reference="ft1", callback_url="https://app.example.com/settings/subscription?card=1", description="FleetTms SUB-0001")
    assert url == "https://checkout.paystack.com/abc"
    [request] = seen
    assert str(request.url) == "https://api.paystack.co/transaction/initialize" and request.headers["authorization"] == f"Bearer {SECRET}"
    sent = json.loads(request.content)
    assert sent["amount"] == 180_000 and sent["currency"] == "KES" and sent["channels"] == ["card"] and sent["reference"] == "ft1" and sent["email"] == "owner@example.com"


async def test_the_real_provider_check_reads_the_status_amount_and_currency(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://api.paystack.co/transaction/verify/ft1"
        return httpx.Response(200, json={"status": True, "data": {"status": "success", "reference": "ft1", "amount": 180000, "currency": "KES"}})

    paystack(monkeypatch, handler)
    assert await card_payments.get_cards().check("ft1") == Charge("ft1", "success", 180_000, "KES")
    for state, expected in (("abandoned", "failed"), ("failed", "failed"), ("ongoing", "pending"), ("pending", "pending")):
        assert card_payments.charge_from({"status": state, "reference": "r"}).status == expected


async def test_the_real_provider_refusals_and_outages_become_readable_errors(monkeypatch):
    paystack(monkeypatch, lambda r: httpx.Response(400, json={"status": False, "message": "Invalid key"}))
    with pytest.raises(card_payments.CardError, match="Invalid key"):
        await card_payments.get_cards().start(email="a@b.co", amount_cents=100, reference="r", callback_url="https://x", description="d")
    paystack(monkeypatch, lambda r: httpx.Response(200, json={"status": True, "data": {}}))
    with pytest.raises(card_payments.CardError, match="no payment page"):
        await card_payments.get_cards().start(email="a@b.co", amount_cents=100, reference="r", callback_url="https://x", description="d")
    paystack(monkeypatch, lambda r: httpx.Response(200, content=b"<html>"))
    with pytest.raises(card_payments.CardError, match="unreadable"):
        await card_payments.get_cards().check("r")

    def down(request):
        raise httpx.ConnectError("no route")

    paystack(monkeypatch, down)
    with pytest.raises(card_payments.CardError, match="could not be reached"):
        await card_payments.get_cards().check("r")


def test_the_webhook_signature_is_the_sha512_of_the_body_under_the_secret_key(monkeypatch):
    monkeypatch.setattr(settings, "paystack_secret_key", SECRET)
    body = b'{"event":"charge.success"}'
    good = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    assert card_payments.signature_ok(body, good) and card_payments.signature_ok(body, good.upper())
    assert not card_payments.signature_ok(body, good[:-1] + "0") and not card_payments.signature_ok(body, None) and not card_payments.signature_ok(b"{}", good)
    monkeypatch.setattr(settings, "paystack_secret_key", "")
    assert not card_payments.signature_ok(body, hmac.new(b"", body, hashlib.sha512).hexdigest())  # no secret: nothing is accepted
