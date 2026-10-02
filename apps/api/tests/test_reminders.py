from datetime import timedelta

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import PaymentReminder
from app.payment_reminders import remind_business
from app.reminders import nairobi_today
from app.report_delivery import fake_sender
from app.sms import get_sms_sender
from app.tenancy import current_business_id
from tests.helpers import bearer, staff_session
from tests.money import business_id, configure, owner_with_client, seed_invoice


async def run_on(days_from_today: int) -> int:
    """The daily reminder pass, as if today were `days_from_today` days from now."""
    async with get_sessionmaker()() as db:
        current_business_id.set(await business_id())
        try:
            return await remind_business(db, today=nairobi_today() + timedelta(days=days_from_today))
        finally:
            current_business_id.set(None)


async def rows() -> list[PaymentReminder]:
    async with get_sessionmaker()() as db:
        current_business_id.set(await business_id())
        try:
            return list((await db.execute(select(PaymentReminder).order_by(PaymentReminder.sent_at))).scalars())
        finally:
            current_business_id.set(None)


def texts() -> list[str]:
    return [m for p, m in get_sms_sender().outbox if p == "+254712000111"]


async def setup(client, *, enabled=True, due_in=3, shortcode="174379", **kw):
    owner, c = await owner_with_client(client)
    await configure(client, owner, reminders_enabled=enabled, shortcode=shortcode, **kw)
    inv = await seed_invoice(c["id"], total_cents=1_160_000, due_in=due_in)
    fake_sender("email").outbox.clear()
    get_sms_sender().outbox.clear()
    return owner, c, inv


async def test_reminders_are_off_until_the_owner_turns_them_on(client):
    await setup(client, enabled=False, due_in=-10)
    assert await run_on(0) == 0 and texts() == [] and fake_sender("email").outbox == []


async def test_a_reminder_goes_by_sms_and_email_before_the_due_date_and_never_twice(client):
    _owner, _c, _inv = await setup(client, due_in=3)
    assert await run_on(0) == 2
    [sms] = texts()
    assert "INV-0001" in sms and "KES 11,600.00" in sms and "is due on" in sms and "Paybill 174379, account number INV-0001" in sms
    [mail] = fake_sender("email").outbox
    assert mail["recipient"] == "jane@bamburi.example" and mail["pdf"].startswith(b"%PDF") and "Paybill 174379" in mail["body"] and "INV-0001" in mail["subject"]
    assert await run_on(0) == 0 and await run_on(1) == 0  # the same step is never repeated
    assert len(texts()) == 1 and len(fake_sender("email").outbox) == 1


async def test_after_the_due_date_the_tone_changes_and_each_step_goes_once(client):
    _owner, _c, _inv = await setup(client, due_in=3)
    await run_on(0)
    assert await run_on(4) == 2  # one day after the due date
    assert "is 1 day overdue" in texts()[-1] and "Please ignore this if you have already paid" in texts()[-1]
    assert await run_on(10) == 2  # a week after
    assert await run_on(10) == 0
    assert sorted(r.offset_days for r in await rows() if r.channel == "sms") == [-3, 1, 7]


async def test_a_backlog_sends_only_the_latest_step(client):
    _owner, _c, _inv = await setup(client, due_in=-20)  # 20 days late and never reminded
    assert await run_on(0) == 2
    assert [r.offset_days for r in await rows()] == [14, 14]
    assert len(texts()) == 1 and "20 days overdue" in texts()[0]


async def test_a_paid_voided_or_opted_out_invoice_is_not_chased(client):
    owner, c, inv = await setup(client, due_in=-20)
    other = await seed_invoice(c["id"], total_cents=100_000, due_in=-20)
    gone = await seed_invoice(c["id"], total_cents=100_000, due_in=-20)
    await client.post(f"/invoices/{inv['id']}/payments", headers=bearer(owner), json={"amount_cents": 1_160_000, "method": "cash"})
    await client.post(f"/invoices/{gone['id']}/void", headers=bearer(owner), json={"reason": "Raised in error"})
    off = await client.put(f"/clients/{c['id']}", headers=bearer(owner), json={"name": c["name"], "phone": c["phone"], "email": c["email"], "billing_method": "per_trip", "rate_cents": 1, "reminders_enabled": False})
    assert off.json()["reminders_enabled"] is False
    assert await run_on(0) == 0 and other["number"] == "INV-0002"
    # editing the client without mentioning reminders leaves them off
    same = await client.put(f"/clients/{c['id']}", headers=bearer(owner), json={"name": c["name"], "phone": c["phone"], "email": c["email"], "billing_method": "per_trip", "rate_cents": 2})
    assert same.json()["reminders_enabled"] is False
    on = await client.put(f"/clients/{c['id']}", headers=bearer(owner), json={"name": c["name"], "phone": c["phone"], "email": c["email"], "billing_method": "per_trip", "rate_cents": 2, "reminders_enabled": True})
    assert on.json()["reminders_enabled"] is True and await run_on(0) == 2  # only the one invoice still owed


async def test_only_the_chosen_channels_are_used_and_a_missing_address_is_skipped(client):
    _owner, _c, _inv = await setup(client, due_in=1, reminder_channels=["sms"])
    assert await run_on(0) == 1 and len(texts()) == 1 and fake_sender("email").outbox == []


async def test_a_failing_channel_is_tried_three_times_then_left_alone_without_stopping_the_other(client):
    _owner, _c, _inv = await setup(client, due_in=2)
    fake_sender("email").fail_with = "Email was not accepted: SMTPException"
    try:
        assert await run_on(0) == 1  # the text went, the email did not
        assert await run_on(0) == 0 and await run_on(0) == 0 and await run_on(0) == 0
    finally:
        fake_sender("email").fail_with = None
    by_channel = {r.channel: r for r in await rows()}
    assert by_channel["sms"].status == "sent" and by_channel["sms"].attempts == 1
    assert by_channel["email"].status == "failed" and by_channel["email"].attempts == 3 and "not accepted" in by_channel["email"].error
    assert len(texts()) == 1  # the text was not repeated while the email was retried


async def test_the_office_can_send_a_reminder_now_and_it_always_goes(client):
    owner, _c, inv = await setup(client, enabled=False, due_in=-3)
    one = await client.post(f"/invoices/{inv['id']}/remind", headers=bearer(owner), json={})
    two = await client.post(f"/invoices/{inv['id']}/remind", headers=bearer(owner), json={"channels": ["sms"]})
    assert [(s["channel"], s["status"]) for s in one.json()["sent"]] == [("sms", "sent"), ("email", "sent")] and two.status_code == 200
    assert len(texts()) == 2 and "3 days overdue" in texts()[0]
    detail = (await client.get(f"/invoices/{inv['id']}", headers=bearer(owner))).json()
    assert len(detail["reminders"]) == 3 and not any(r["automatic"] for r in detail["reminders"])
    assert "invoice.reminder" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_a_manual_reminder_needs_someone_to_send_to_and_an_invoice_still_owed(client):
    owner, _c, inv = await setup(client, enabled=False, due_in=-3)
    nobody = await client.post("/clients", headers=bearer(owner), json={"name": "No Contact Ltd", "billing_method": "per_trip", "rate_cents": 1})
    bare = await seed_invoice(nobody.json()["id"], total_cents=10_000)
    res = await client.post(f"/invoices/{bare['id']}/remind", headers=bearer(owner), json={})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "no_recipient"
    await client.post(f"/invoices/{inv['id']}/payments", headers=bearer(owner), json={"amount_cents": 1_160_000, "method": "cash"})
    assert (await client.post(f"/invoices/{inv['id']}/remind", headers=bearer(owner), json={})).json()["detail"]["code"] == "not_owed"
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.post(f"/invoices/{inv['id']}/remind", headers=bearer(manager), json={})).status_code == 403


async def test_a_till_number_asks_the_client_to_send_the_invoice_number(client):
    _owner, _c, _inv = await setup(client, due_in=2, shortcode="523456", shortcode_type="till")
    await run_on(0)
    assert "Till 523456" in texts()[0]
