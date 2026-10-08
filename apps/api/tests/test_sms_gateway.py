"""The Africa's Talking sender, against a mock gateway: what it sends, what it does when the gateway misbehaves, and what it never logs."""

import logging
from urllib.parse import parse_qs

import httpx
import pytest

from app import sms
from app.config import settings
from app.sms import AfricasTalkingSms, FakeSmsSender, MeteredSms

KEY = "test-key-" + "x" * 12  # not a real key
PHONE = "+254712345678"


def answer(status_code=101, status="Success"):
    body = {"SMSMessageData": {"Message": "Sent to 1/1", "Recipients": [{"statusCode": status_code, "number": PHONE, "status": status, "messageId": "ATXid_1", "cost": "KES 0.8000"}]}}
    return httpx.Response(201, json=body)


def sender(handler, **kw):
    return AfricasTalkingSms("fleettms", KEY, kw.pop("sender_id", ""), transport=httpx.MockTransport(handler), retry_wait=0, **kw)


async def test_a_message_goes_to_the_gateway_with_the_key_in_a_header_and_the_text_in_the_form():
    seen = []

    def handler(request):
        seen.append(request)
        return answer()

    await sender(handler, sender_id="FleetTms").send(PHONE, "Your FleetTms code is 123456.")
    [request] = seen
    assert str(request.url) == "https://api.africastalking.com/version1/messaging" and request.method == "POST"
    assert request.headers["apiKey"] == KEY and request.headers["accept"] == "application/json"
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    assert form == {"username": "fleettms", "to": PHONE, "message": "Your FleetTms code is 123456.", "from": "FleetTms"}


async def test_the_sandbox_has_its_own_address_and_no_sender_id_is_sent_unless_one_is_set():
    seen = []
    await sender(lambda r: seen.append(r) or answer(), sandbox=True).send(PHONE, "hello")
    assert str(seen[0].url) == "https://api.sandbox.africastalking.com/version1/messaging"
    assert "from" not in parse_qs(seen[0].content.decode())


@pytest.mark.parametrize(("code", "reason"), [(403, "invalid phone number"), (405, "insufficient balance"), (406, "recipient blocked"), (999, "Odd")])
async def test_a_refusal_for_one_number_is_logged_with_its_reason_and_does_not_raise(caplog, code, reason):
    with caplog.at_level(logging.WARNING, logger="app.sms"):
        await sender(lambda r: answer(code, "Odd")).send(PHONE, "Your FleetTms code is 654321.")
    assert any("was not sent" in r.message and reason in r.message for r in caplog.records)


async def test_a_network_failure_is_tried_three_times_then_logged_without_raising(caplog):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("no route")

    with caplog.at_level(logging.WARNING, logger="app.sms"):
        await sender(handler).send(PHONE, "Your FleetTms code is 654321.")
    assert len(calls) == 3
    assert any("ConnectError" in r.message for r in caplog.records)


async def test_a_server_error_is_retried_and_a_later_success_stops_the_retries():
    replies = iter([httpx.Response(503), httpx.Response(502), answer()])
    calls = []

    def handler(request):
        calls.append(1)
        return next(replies)

    await sender(handler).send(PHONE, "hello")
    assert len(calls) == 3


async def test_a_refused_key_is_not_asked_again(caplog):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, text="The supplied authentication is invalid")

    with caplog.at_level(logging.WARNING, logger="app.sms"):
        await sender(handler).send(PHONE, "hello")
    assert len(calls) == 1 and any("401" in r.message for r in caplog.records)


async def test_an_answer_that_cannot_be_read_or_names_no_recipient_is_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="app.sms"):
        await sender(lambda r: httpx.Response(201, text="<html>")).send(PHONE, "hello")
        await sender(lambda r: httpx.Response(201, json={"SMSMessageData": {"Recipients": []}})).send(PHONE, "hello")
    messages = [r.message for r in caplog.records]
    assert any("could not be read" in m for m in messages) and any("accepted no recipient" in m for m in messages)


async def test_the_log_never_holds_the_message_the_key_or_the_whole_number(caplog):
    secret_text = "Your FleetTms code is 482913."
    with caplog.at_level(logging.DEBUG, logger="app"):
        await sender(lambda r: answer(405, "InsufficientBalance")).send(PHONE, secret_text)
        await sender(lambda r: (_ for _ in ()).throw(httpx.ConnectError("boom"))).send(PHONE, secret_text)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert logged and "482913" not in logged and KEY not in logged and PHONE not in logged and "+2547****78" in logged


async def test_the_gateway_is_used_only_when_it_is_configured(monkeypatch):
    assert isinstance(sms.build_sender(), FakeSmsSender)
    monkeypatch.setattr(settings, "at_username", "fleettms")
    assert isinstance(sms.build_sender(), FakeSmsSender)  # a key is needed too
    monkeypatch.setattr(settings, "at_api_key", KEY)
    monkeypatch.setattr(settings, "at_sender_id", "FleetTms")
    monkeypatch.setattr(settings, "at_sandbox", True)
    built = sms.build_sender()
    assert isinstance(built, AfricasTalkingSms) and built.sender_id == "FleetTms" and built.url == AfricasTalkingSms.SANDBOX


async def test_the_production_check_accepts_the_real_gateway_and_still_refuses_the_stand_in(monkeypatch):
    from app import http_security

    monkeypatch.setattr(sms, "_sender", MeteredSms(AfricasTalkingSms("fleettms", KEY)))
    monkeypatch.setattr(settings, "environment", "production")
    good = {
        "jwt_secret": "s" * 40, "cors_origins": "https://app.example.com", "public_api_url": "https://api.example.com", "enforce_plans": True,
        "enforce_billing": True, "rate_limits_enabled": True, "document_reader": "", "ask_llm": "", "smtp_host": "smtp.example.com",
    }  # fmt: skip
    for name, value in good.items():
        monkeypatch.setattr(settings, name, value)
    http_security.check_production()  # the real gateway: starts
    monkeypatch.setattr(sms, "_sender", MeteredSms(FakeSmsSender()))
    with pytest.raises(RuntimeError, match="stand-in"):
        http_security.check_production()
