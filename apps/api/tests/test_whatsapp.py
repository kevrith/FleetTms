"""Automatic WhatsApp (the Business API): orders to suppliers and reminders to clients, with Meta's reports and the supplier's button answers."""

import hashlib
import hmac
import json
import secrets
import uuid

import httpx
import pytest
from sqlalchemy import select

from app import whatsapp
from app.config import settings
from app.db import get_sessionmaker
from app.models import WhatsAppMessage
from app.sms import get_sms_sender
from app.tenancy import current_business_id
from tests.helpers import bearer, driver_session, owner_session
from tests.money import business_id, owner_with_client
from tests.test_reminders import run_on
from tests.test_reminders import setup as reminder_setup
from tests.test_suppliers import order_body, supplier

SECRET = secrets.token_urlsafe(24)  # made fresh each run, never written down
VERIFY = secrets.token_urlsafe(24)
TOKEN = secrets.token_urlsafe(24)


@pytest.fixture(autouse=True)
def _whatsapp(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)
    monkeypatch.setattr(settings, "whatsapp_verify_token", VERIFY)
    whatsapp.fake_whatsapp().reset()
    get_sms_sender().outbox.clear()
    yield
    whatsapp.fake_whatsapp().reset()


def signed(payload: dict, secret: str = SECRET) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    return body, {"x-hub-signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(), "content-type": "application/json"}


def report(wa_id: str, status: str, **extra) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {"statuses": [{"id": wa_id, "status": status, "timestamp": "1790000000", **extra}]}}]}]}


def press(original: str, button: str, sender: str = "254712345678") -> dict:
    message = {"from": sender, "id": "wamid.IN1", "timestamp": "1790000100", "type": "button", "button": {"payload": button, "text": button}, "context": {"id": original}}
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {"messages": [message]}}]}]}


async def hook(client, payload: dict, **kw):
    body, headers = signed(payload, **kw)
    return await client.post("/hooks/whatsapp", content=body, headers=headers)


async def sent_order(client, **owner_extra):
    owner, _ = await owner_session(client, **owner_extra)
    sup = await supplier(client, owner)
    order = (await client.post("/orders", headers=bearer(owner), json=order_body(sup, notes="Deliver to the yard\nGate B", expected_on="2026-12-01"))).json()
    res = await client.post(f"/orders/{order['id']}/whatsapp", headers=bearer(owner))
    assert res.status_code == 200, res.text
    return owner, order, res.json()


async def messages() -> list[WhatsAppMessage]:
    async with get_sessionmaker()() as db:
        current_business_id.set(await business_id())
        try:
            return list((await db.execute(select(WhatsAppMessage).order_by(WhatsAppMessage.created_at))).scalars())
        finally:
            current_business_id.set(None)


# ---- parts orders ---------------------------------------------------------------------------------------------------------


async def test_an_order_goes_to_the_supplier_by_itself_as_one_clean_line_with_two_answer_buttons(client):
    owner, order, sent = await sent_order(client)
    assert sent["status"] == "sent" and sent["sent_at"] and sent["whatsapp"]["automatic"] is True and sent["whatsapp"]["status"] == "sent"
    [out] = whatsapp.fake_whatsapp().outbox
    assert out["to"] == "+254712345678" and out["buttons"] == ("confirm", "decline") and out["template"] == "fleettms_order"
    supplier_name, number, business, summary, closing = out["params"]
    assert (supplier_name, number, business) == ("Kiambu Spares", "PO-0001", "Kamau Haulage") and closing == "Please confirm if you can supply."
    assert "4 x Oil filter, 2 x Fan belt." in summary and "Total KES 11,800.00." in summary and "Needed by 01 Dec 2026." in summary and "Deliver to the yard Gate B" in summary
    assert all("\n" not in p and "  " not in p and p for p in out["params"])  # a template variable holds no line break and is never empty
    assert "order.sent" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    [row] = await messages()
    assert row.wa_message_id == "wamid.FAKE00001" and row.purpose == "order" and row.entity_id == uuid.UUID(order["id"])


async def test_meta_reports_move_the_message_from_sent_to_delivered_to_read_and_never_backwards(client):
    owner, order, _ = await sent_order(client)
    shown = lambda: client.get(f"/orders/{order['id']}", headers=bearer(owner))
    assert (await hook(client, report("wamid.FAKE00001", "delivered"))).status_code == 200
    w = (await shown()).json()["whatsapp"]
    assert w["status"] == "delivered" and w["delivered_at"] and w["read_at"] is None
    await hook(client, report("wamid.FAKE00001", "read"))
    assert (await shown()).json()["whatsapp"]["status"] == "read"
    await hook(client, report("wamid.FAKE00001", "delivered"))  # arrives late: does not undo "read"
    await hook(client, report("wamid.FAKE00001", "sent"))
    w = (await shown()).json()["whatsapp"]
    assert w["status"] == "read" and w["read_at"] and w["delivered_at"]
    listed = (await client.get("/orders", headers=bearer(owner))).json()
    assert listed[0]["whatsapp"]["status"] == "read"


async def test_a_failed_delivery_shows_why_and_a_late_failure_does_not_undo_a_delivery(client):
    owner, order, _ = await sent_order(client)
    await hook(client, report("wamid.FAKE00001", "failed", errors=[{"code": 131026, "title": "Message undeliverable"}]))
    w = (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()["whatsapp"]
    assert w["status"] == "failed" and w["error"] == "Message undeliverable"
    await hook(client, report("wamid.FAKE00001", "delivered"))
    assert (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()["whatsapp"]["status"] == "delivered"
    await hook(client, report("wamid.FAKE00001", "failed", errors=[{"title": "Too late"}]))
    assert (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()["whatsapp"]["status"] == "delivered"


async def test_the_supplier_pressing_confirm_confirms_the_order_once_and_the_audit_trail_says_who(client):
    owner, order, _ = await sent_order(client)
    assert (await hook(client, press("wamid.FAKE00001", "confirm"))).status_code == 200
    got = (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()
    assert got["status"] == "confirmed" and got["confirmed_at"] and got["whatsapp"]["reply"] == "confirm" and got["whatsapp"]["replied_at"]
    entries = [e for e in (await client.get("/audit", headers=bearer(owner))).json() if e["action"] == "order.confirmed_on_whatsapp"]
    assert len(entries) == 1 and "Kiambu Spares pressed Confirm" in entries[0]["note"] and entries[0]["actor_user_id"] is None
    await hook(client, press("wamid.FAKE00001", "decline"))  # a second answer to the same message is ignored
    assert (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()["whatsapp"]["reply"] == "confirm"
    assert get_sms_sender().outbox == []


async def test_the_supplier_pressing_cannot_supply_leaves_the_order_and_texts_the_managers(client):
    owner, order, _ = await sent_order(client, phone="0733555666")
    await hook(client, press("wamid.FAKE00001", "decline"))
    got = (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()
    assert got["status"] == "sent" and got["whatsapp"]["reply"] == "decline"
    assert "order.declined_on_whatsapp" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    [(phone, text)] = [m for m in get_sms_sender().outbox if "cannot supply" in m[1]]
    assert phone == "+254733555666" and "Kiambu Spares cannot supply order PO-0001" in text


async def test_only_the_number_the_order_went_to_can_answer_it_and_only_with_one_of_the_two_buttons(client):
    owner, order, _ = await sent_order(client)
    await hook(client, press("wamid.FAKE00001", "confirm", sender="254799000111"))  # someone else
    await hook(client, press("wamid.FAKE00001", "pay-me-now"))  # not one of our buttons
    await hook(client, press("wamid.NOT-OURS", "confirm"))  # a message we never sent
    got = (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()
    assert got["status"] == "sent" and got["whatsapp"]["reply"] is None
    text_reply = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [{"from": "254712345678", "id": "x", "type": "text", "text": {"body": "yes"}, "context": {"id": "wamid.FAKE00001"}}]}}]}]}
    assert (await hook(client, text_reply)).status_code == 200
    assert (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()["whatsapp"]["reply"] is None


async def test_nothing_unsigned_or_wrongly_signed_is_believed_and_the_address_is_checked_with_the_verify_token(client, monkeypatch):
    owner, order, _ = await sent_order(client)
    payload = press("wamid.FAKE00001", "confirm")
    body = json.dumps(payload).encode()
    assert (await client.post("/hooks/whatsapp", content=body)).status_code == 403
    assert (await client.post("/hooks/whatsapp", content=body, headers={"x-hub-signature-256": "sha256=" + "0" * 64})).status_code == 403
    assert (await hook(client, payload, secret=secrets.token_urlsafe(24))).status_code == 403
    monkeypatch.setattr(settings, "whatsapp_app_secret", "")
    assert (await hook(client, payload, secret="")).status_code == 403  # no secret configured: nothing is accepted
    assert (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()["status"] == "sent"
    good = await client.get("/hooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"})
    assert good.status_code == 200 and good.text == "1158201444"
    assert (await client.get("/hooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"})).status_code == 403
    monkeypatch.setattr(settings, "whatsapp_verify_token", "")
    assert (await client.get("/hooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"})).status_code == 403


async def test_a_signed_delivery_that_is_junk_is_answered_200_so_meta_does_not_repeat_it(client):
    body = b"not json"
    headers = {"x-hub-signature-256": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()}
    assert (await client.post("/hooks/whatsapp", content=body, headers=headers)).status_code == 200
    assert (await hook(client, {"entry": "nonsense"})).status_code == 200
    assert (await hook(client, {"entry": [{"changes": [{"value": {"statuses": ["x"], "messages": [None]}}]}]})).status_code == 200
    assert (await hook(client, report("wamid.UNKNOWN", "read"))).status_code == 200


async def test_reports_for_one_business_never_touch_another_and_each_audit_entry_lands_in_its_own_business(client):
    first, order, _ = await sent_order(client)
    second, _ = await owner_session(client, business="Other Haulage", email="other@example.com")
    sup2 = await supplier(client, second, phone="0722000111")
    order2 = (await client.post("/orders", headers=bearer(second), json=order_body(sup2))).json()
    assert (await client.post(f"/orders/{order2['id']}/whatsapp", headers=bearer(second))).status_code == 200
    both = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [
        {"from": "254712345678", "id": "a", "type": "button", "button": {"payload": "confirm"}, "context": {"id": "wamid.FAKE00001"}},
        {"from": "254722000111", "id": "b", "type": "button", "button": {"payload": "confirm"}, "context": {"id": "wamid.FAKE00002"}},
    ]}}]}]}
    assert (await hook(client, both)).status_code == 200
    for who, o in ((first, order), (second, order2)):
        assert (await client.get(f"/orders/{o['id']}", headers=bearer(who))).json()["status"] == "confirmed"
        mine = [e for e in (await client.get("/audit", headers=bearer(who))).json() if e["action"] == "order.confirmed_on_whatsapp"]
        assert len(mine) == 1 and mine[0]["after"]["number"] == "PO-0001"


async def test_sending_needs_a_number_a_draft_or_sent_order_and_automatic_sending_to_be_on(client, monkeypatch):
    owner, _ = await owner_session(client)
    nophone = await supplier(client, owner, name="No Phone Ltd", phone=None)
    sup = await supplier(client, owner)
    o1 = (await client.post("/orders", headers=bearer(owner), json=order_body(nophone))).json()
    assert (await client.post(f"/orders/{o1['id']}/whatsapp", headers=bearer(owner))).json()["detail"]["code"] == "no_phone"
    o2 = (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()
    await client.post(f"/orders/{o2['id']}/status", headers=bearer(owner), json={"status": "cancelled"})
    assert (await client.post(f"/orders/{o2['id']}/whatsapp", headers=bearer(owner))).status_code == 409
    o3 = (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()
    monkeypatch.setattr(settings, "environment", "production")
    off = await client.post(f"/orders/{o3['id']}/whatsapp", headers=bearer(owner))
    assert off.status_code == 409 and off.json()["detail"]["code"] == "whatsapp_not_set_up"
    assert (await client.get(f"/orders/{o3['id']}", headers=bearer(owner))).json()["whatsapp"]["automatic"] is False
    assert whatsapp.fake_whatsapp().outbox == []
    monkeypatch.setattr(settings, "environment", "development")
    assert (await client.post(f"/orders/{o3['id']}/whatsapp", headers=bearer(owner))).status_code == 200


async def test_meta_refusing_the_message_leaves_the_order_a_draft_with_the_reason_and_it_can_be_sent_again(client):
    owner, _ = await owner_session(client)
    sup = await supplier(client, owner)
    order = (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()
    whatsapp.fake_whatsapp().fail_with = "WhatsApp did not accept the message (HTTP 400). Template not approved."
    res = await client.post(f"/orders/{order['id']}/whatsapp", headers=bearer(owner))
    assert res.status_code == 502 and res.json()["detail"]["code"] == "whatsapp_failed" and "Template not approved" in res.json()["detail"]["message"]
    got = (await client.get(f"/orders/{order['id']}", headers=bearer(owner))).json()
    assert got["status"] == "draft" and got["sent_at"] is None and got["whatsapp"]["status"] == "failed" and "Template not approved" in got["whatsapp"]["error"]
    whatsapp.fake_whatsapp().fail_with = None
    again = await client.post(f"/orders/{order['id']}/whatsapp", headers=bearer(owner))
    assert again.status_code == 200 and again.json()["status"] == "sent" and again.json()["whatsapp"]["status"] == "sent"


async def test_the_link_way_still_works_and_shows_the_state_of_the_automatic_message(client):
    owner, order, _ = await sent_order(client)
    again = await client.post(f"/orders/{order['id']}/send", headers=bearer(owner))
    assert again.status_code == 200 and again.json()["whatsapp_url"].startswith("https://wa.me/254712345678?text=") and again.json()["whatsapp"]["status"] == "sent"


async def test_only_people_who_manage_the_workshop_can_send_orders_on_whatsapp(client):
    owner, order, _ = await sent_order(client)
    driver = await driver_session(client, owner, "0712000111")
    assert (await client.post(f"/orders/{order['id']}/whatsapp", headers=bearer(driver))).status_code == 403


# ---- payment reminders ----------------------------------------------------------------------------------------------------


async def test_a_payment_reminder_can_go_on_whatsapp_with_the_amount_and_when_and_never_twice(client):
    _owner, c, _inv = await reminder_setup(client, due_in=3, reminder_channels=["whatsapp"])
    assert await run_on(0) == 1
    [out] = whatsapp.fake_whatsapp().outbox
    assert out["template"] == "fleettms_reminder" and out["to"] == "+254712000111" and out["buttons"] == ()
    name, business, number, amount, when, pay = out["params"]
    assert (name, business, number, amount) == (c["name"], "Kamau Haulage", "INV-0001", "KES 11,600.00")
    assert when.startswith("is due on") and "Paybill 174379" in pay and "\n" not in pay
    assert get_sms_sender().outbox == []  # only the channel the owner chose
    assert await run_on(0) == 0 and len(whatsapp.fake_whatsapp().outbox) == 1
    [row] = await messages()
    assert row.purpose == "reminder" and row.status == "sent"


async def test_a_whatsapp_reminder_that_fails_is_recorded_and_tried_again_up_to_three_times(client):
    await reminder_setup(client, due_in=-5, reminder_channels=["whatsapp"])
    whatsapp.fake_whatsapp().fail_with = "WhatsApp could not be reached: ConnectError"
    assert await run_on(0) == 0
    assert await run_on(0) == 0 and await run_on(0) == 0 and await run_on(0) == 0
    assert len(await messages()) == 3  # three tries, then it is given up on
    whatsapp.fake_whatsapp().fail_with = None
    assert await run_on(0) == 0 and whatsapp.fake_whatsapp().outbox == []


async def test_whatsapp_is_one_of_the_reminder_channels_the_owner_can_choose(client):
    owner, _ = await owner_with_client(client)
    res = await client.put("/payments/settings", headers=bearer(owner), json={"shortcode": "174379", "reminders_enabled": True, "reminder_channels": ["sms", "whatsapp"]})
    assert res.status_code == 200 and res.json()["reminder_channels"] == ["sms", "whatsapp"]
    bad = await client.put("/payments/settings", headers=bearer(owner), json={"shortcode": "174379", "reminder_channels": ["telegram"]})
    assert bad.status_code == 422


# ---- the real Cloud API call ----------------------------------------------------------------------------------------------


async def test_the_real_sender_posts_the_template_with_its_variables_and_buttons_and_reads_back_the_message_id(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_token", TOKEN)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "1234567890")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.REAL1"}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert whatsapp.is_live() and isinstance(whatsapp.get_whatsapp(), whatsapp.CloudApi)
    message_id = await whatsapp.get_whatsapp().send_template("+254712345678", "fleettms_parts_order", ["Kiambu", "PO-0001"], buttons=("confirm", "decline"))
    assert message_id == "wamid.REAL1"
    [request] = seen
    assert str(request.url) == "https://graph.facebook.com/v21.0/1234567890/messages" and request.headers["authorization"] == f"Bearer {TOKEN}"
    sent = json.loads(request.content)
    assert sent["to"] == "254712345678" and sent["type"] == "template" and sent["template"]["name"] == "fleettms_parts_order" and sent["template"]["language"] == {"code": "en"}
    body, yes, no = sent["template"]["components"]
    assert body["parameters"] == [{"type": "text", "text": "Kiambu"}, {"type": "text", "text": "PO-0001"}]
    assert (yes["sub_type"], yes["index"], yes["parameters"][0]["payload"]) == ("quick_reply", "0", "confirm") and no["index"] == "1" and no["parameters"][0]["payload"] == "decline"


async def test_the_real_sender_turns_meta_refusals_and_outages_into_a_readable_error(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_token", TOKEN)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "1234567890")
    real = httpx.AsyncClient
    for answer, expect in (
        (httpx.Response(400, json={"error": {"message": "Template name does not exist"}}), "Template name does not exist"),
        (httpx.Response(200, json={"unexpected": True}), "unreadable"),
    ):
        monkeypatch.setattr(whatsapp.httpx, "AsyncClient", lambda a=answer, **kw: real(transport=httpx.MockTransport(lambda r: a), **kw))
        with pytest.raises(whatsapp.WhatsAppError, match=expect):
            await whatsapp.get_whatsapp().send_template("+254712345678", "t", ["x"])

    def down(request):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(down), **kw))
    with pytest.raises(whatsapp.WhatsAppError, match="could not be reached"):
        await whatsapp.get_whatsapp().send_template("+254712345678", "t", ["x"])


def test_template_variables_are_made_safe_and_a_live_setup_needs_its_own_template_names(monkeypatch):
    assert whatsapp.clean_param("a\nb\t c    d") == "a b c d" and whatsapp.clean_param("  ") == "-" and len(whatsapp.clean_param("x" * 5000)) == 1000
    assert whatsapp.template_for("order") == "fleettms_order"  # the stand-in needs no approved template
    monkeypatch.setattr(settings, "whatsapp_token", TOKEN)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "1")
    assert whatsapp.template_for("order") == "" and whatsapp.template_for("reminder") == ""
    monkeypatch.setattr(settings, "whatsapp_order_template", "parts_order_v1")
    assert whatsapp.template_for("order") == "parts_order_v1"


def test_production_will_not_start_with_a_whatsapp_token_but_without_what_replies_and_reports_need():
    from app import http_security
    from app.config import Settings
    from tests.test_rate_limits import GOOD

    assert not any("WHATSAPP" in p for p in http_security.production_problems(Settings.model_construct(**GOOD), sms_is_stand_in=False))
    live = {**GOOD, "whatsapp_token": TOKEN, "whatsapp_phone_number_id": "1"}
    assert any("WHATSAPP_APP_SECRET" in p for p in http_security.production_problems(Settings.model_construct(**live), sms_is_stand_in=False))
    full = {**live, "whatsapp_app_secret": SECRET, "whatsapp_verify_token": VERIFY}
    assert not any("WHATSAPP" in p for p in http_security.production_problems(Settings.model_construct(**full), sms_is_stand_in=False))
