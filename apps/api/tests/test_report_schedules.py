from datetime import date

import pytest

from app.models import ReportFrequency
from app.report_delivery import fake_sender
from app.report_schedules import last_finished_period, send_scheduled_reports
from tests.helpers import bearer, driver_session, owner_session


@pytest.fixture(autouse=True)
def _empty_outboxes():
    for channel in ("email", "whatsapp"):
        fake_sender(channel).outbox.clear()
        fake_sender(channel).fail_with = None


async def schedule(client, owner, **body):
    body = {"frequency": "daily", "channel": "email", "recipient": "boss@example.com", **body}
    return await client.post("/report-schedules", headers=bearer(owner), json=body)


def test_each_frequency_covers_the_last_finished_period():
    wednesday = date(2026, 10, 7)
    assert last_finished_period(ReportFrequency.DAILY, wednesday) == (date(2026, 10, 6), date(2026, 10, 6))
    assert last_finished_period(ReportFrequency.WEEKLY, wednesday) == (date(2026, 9, 28), date(2026, 10, 4))
    assert last_finished_period(ReportFrequency.MONTHLY, wednesday) == (date(2026, 9, 1), date(2026, 9, 30))
    assert last_finished_period(ReportFrequency.MONTHLY, date(2026, 1, 1)) == (date(2025, 12, 1), date(2025, 12, 31))


async def test_a_daily_report_is_sent_once_as_a_pdf_by_email(client):
    owner, _ = await owner_session(client)
    assert (await schedule(client, owner)).status_code == 201
    assert await send_scheduled_reports(date(2026, 10, 7)) == 1
    [mail] = fake_sender("email").outbox
    assert mail["recipient"] == "boss@example.com" and mail["pdf"].startswith(b"%PDF")
    assert mail["filename"] == "fleettms-report-2026-10-06-to-2026-10-06.pdf"
    assert await send_scheduled_reports(date(2026, 10, 7)) == 0  # already sent for that day
    assert await send_scheduled_reports(date(2026, 10, 8)) == 1  # the next day's report
    assert len(fake_sender("email").outbox) == 2


async def test_a_whatsapp_report_goes_to_the_normalised_number(client):
    owner, _ = await owner_session(client)
    res = await schedule(client, owner, channel="whatsapp", recipient="0712345678", frequency="weekly")
    assert res.status_code == 201
    await send_scheduled_reports(date(2026, 10, 7))
    [msg] = fake_sender("whatsapp").outbox
    assert msg["recipient"] == res.json()["recipient"] and msg["recipient"].startswith("+254")
    assert msg["pdf"].startswith(b"%PDF")


async def test_a_failed_send_is_recorded_and_tried_again(client):
    owner, _ = await owner_session(client)
    created = (await schedule(client, owner)).json()
    fake_sender("email").fail_with = "Email was not accepted: SMTPException"
    assert await send_scheduled_reports(date(2026, 10, 7)) == 0
    row = (await client.get("/report-schedules", headers=bearer(owner))).json()[0]
    assert row["last_error"] and row["last_period_end"] is None
    fake_sender("email").fail_with = None
    assert await send_scheduled_reports(date(2026, 10, 7)) == 1
    row = (await client.get("/report-schedules", headers=bearer(owner))).json()[0]
    assert row["last_error"] is None and row["last_period_end"] == "2026-10-06" and row["id"] == created["id"]


async def test_paused_schedules_send_nothing_and_deleted_ones_are_gone(client):
    owner, _ = await owner_session(client)
    sid = (await schedule(client, owner)).json()["id"]
    assert (await client.patch(f"/report-schedules/{sid}", headers=bearer(owner), json={"is_active": False})).json()["is_active"] is False
    assert await send_scheduled_reports(date(2026, 10, 7)) == 0
    assert (await client.delete(f"/report-schedules/{sid}", headers=bearer(owner))).status_code == 204
    assert (await client.get("/report-schedules", headers=bearer(owner))).json() == []


async def test_send_now_sends_a_test_without_using_up_the_scheduled_send(client):
    owner, _ = await owner_session(client)
    sid = (await schedule(client, owner)).json()["id"]
    assert (await client.post(f"/report-schedules/{sid}/send-now", headers=bearer(owner))).json() == {"sent": True}
    assert len(fake_sender("email").outbox) == 1
    fake_sender("email").fail_with = "Email was not accepted: OSError"
    assert (await client.post(f"/report-schedules/{sid}/send-now", headers=bearer(owner))).status_code == 502


@pytest.mark.parametrize("body", [{"recipient": "not-an-email"}, {"channel": "whatsapp", "recipient": "12"}, {"frequency": "hourly"}])
async def test_bad_recipients_are_rejected(client, body):
    owner, _ = await owner_session(client)
    assert (await schedule(client, owner, **body)).status_code == 422


async def test_duplicates_are_refused_and_businesses_are_separate(client):
    owner, _ = await owner_session(client)
    assert (await schedule(client, owner)).status_code == 201
    assert (await schedule(client, owner)).status_code == 409
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/report-schedules", headers=bearer(other))).json() == []
    assert await send_scheduled_reports(date(2026, 10, 7)) == 1


async def test_a_driver_cannot_manage_scheduled_reports(client):
    owner, _ = await owner_session(client)
    driver = await driver_session(client, owner, "0712345678")
    assert (await client.get("/report-schedules", headers=bearer(driver))).status_code == 403
    assert (await schedule(client, driver)).status_code == 403


async def test_the_whatsapp_sender_uploads_the_pdf_then_sends_it_as_a_document(monkeypatch):
    import httpx

    from app import report_delivery
    from app.config import settings

    monkeypatch.setattr(settings, "whatsapp_token", "token-from-test")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "12345")
    monkeypatch.setattr(settings, "whatsapp_report_template", "")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "media-1"})

    real = httpx.AsyncClient
    monkeypatch.setattr(report_delivery.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    sender = report_delivery.get_report_sender("whatsapp")
    assert isinstance(sender, report_delivery.WhatsAppSender)
    await sender.send("+254712345678", "Weekly", "r.pdf", b"%PDF-test")
    assert [r.url.path for r in calls] == ["/v21.0/12345/media", "/v21.0/12345/messages"]
    assert calls[0].headers["authorization"] == "Bearer token-from-test"
    import json

    body = json.loads(calls[1].content)
    assert body["to"] == "254712345678" and body["type"] == "document" and body["document"]["id"] == "media-1"

    monkeypatch.setattr(settings, "whatsapp_report_template", "weekly_report")
    calls.clear()
    await sender.send("+254712345678", "Weekly", "r.pdf", b"%PDF-test")
    assert json.loads(calls[1].content)["template"]["name"] == "weekly_report"


async def test_a_whatsapp_rejection_becomes_a_delivery_error(monkeypatch):
    import httpx

    from app import report_delivery
    from app.config import settings

    monkeypatch.setattr(settings, "whatsapp_token", "t")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "1")
    real = httpx.AsyncClient
    monkeypatch.setattr(report_delivery.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})), **kw))
    with pytest.raises(report_delivery.DeliveryError):
        await report_delivery.WhatsAppSender().send("+254712345678", "s", "r.pdf", b"x")


async def test_the_email_sender_attaches_the_pdf(monkeypatch):
    import smtplib

    from app import report_delivery
    from app.config import settings

    sent = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent.append("tls")

        def login(self, user, password):
            sent.append(("login", user))

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    for key, value in {"smtp_host": "smtp.test", "smtp_user": "u", "smtp_password": "p", "smtp_from": "reports@test"}.items():
        monkeypatch.setattr(settings, key, value)
    sender = report_delivery.get_report_sender("email")
    assert isinstance(sender, report_delivery.SmtpSender)
    await sender.send("boss@example.com", "Daily", "r.pdf", b"%PDF-test")
    message = sent[-1]
    assert sent[:3] == [("connect", "smtp.test", 587), "tls", ("login", "u")]
    assert message["To"] == "boss@example.com" and message["From"] == "reports@test"
    [attachment] = list(message.iter_attachments())
    assert attachment.get_content_type() == "application/pdf" and attachment.get_filename() == "r.pdf"
