"""The super admin's testing inbox for one-time codes while no real SMS gateway is set up."""

import pytest
from sqlalchemy import update

from app import sms
from app.config import settings
from app.db import get_sessionmaker
from app.models import User
from app.sms import AfricasTalkingSms, FakeSmsSender, MeteredSms
from tests.helpers import bearer, invite, last_otp, owner_session
from tests.test_support_and_privacy import make_platform_admin


@pytest.fixture(autouse=True)
def _empty_inbox():
    """The inbox lives in the sender's memory, which outlives a test: start each one with nothing in it."""
    sms.get_sms_sender().inbox.clear()


async def ask_for_a_code(client, owner, phone="0712345678"):
    assert (await invite(client, owner, name="Dan Driver", phone=phone, roles=["driver"])).status_code == 201
    assert (await client.post("/auth/otp/request", json={"phone": phone})).status_code == 200


async def test_a_super_admin_reads_the_code_that_was_sent_and_the_look_is_logged(client):
    owner, _ = await owner_session(client)
    admin = await make_platform_admin(client)
    await ask_for_a_code(client, owner)
    res = await client.get("/platform/sms-inbox", headers=bearer(admin))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["active"] is True and len(body["messages"]) == 1
    assert body["messages"][0]["to"] == "+254712345678" and last_otp() in body["messages"][0]["message"]
    audit = (await client.get("/platform/audit", headers=bearer(admin))).json()
    assert "sms_inbox.viewed" in str(audit)


async def test_an_empty_inbox_is_not_logged_and_only_a_super_admin_can_open_it(client):
    owner, _ = await owner_session(client)
    admin = await make_platform_admin(client)
    assert (await client.get("/platform/sms-inbox", headers=bearer(admin))).json()["messages"] == []
    assert "sms_inbox.viewed" not in str((await client.get("/platform/audit", headers=bearer(admin))).json())
    assert (await client.get("/platform/sms-inbox", headers=bearer(owner))).status_code == 403
    async with get_sessionmaker()() as db:
        await db.execute(update(User).where(User.email == "support@example.com").values(is_platform_super=False))
        await db.commit()
    assert (await client.get("/platform/sms-inbox", headers=bearer(admin))).status_code == 403  # a platform admin who is not a super admin


async def test_only_sign_in_codes_are_kept_never_a_businesss_own_messages(client):
    admin = await make_platform_admin(client)
    sender = sms.get_sms_sender()
    await sender.send("+254712345678", "Alert: KCA 123A left its area")
    await sender.send("+254712345678", "Your FleetTms code is 123456. It expires in 10 minutes.")
    messages = (await client.get("/platform/sms-inbox", headers=bearer(admin))).json()["messages"]
    assert len(messages) == 1 and messages[0]["message"].startswith("Your FleetTms code")


async def test_the_inbox_is_empty_once_a_real_gateway_sends_or_in_production(client, monkeypatch):
    admin = await make_platform_admin(client)
    await sms.get_sms_sender().send("+254712345678", "Your FleetTms code is 123456. It expires in 10 minutes.")
    monkeypatch.setattr(settings, "environment", "production")
    assert (await client.get("/platform/sms-inbox", headers=bearer(admin))).json() == {"active": False, "minutes": 30, "messages": []}
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(sms, "_sender", MeteredSms(AfricasTalkingSms("fleettms", "test-key")))
    assert (await client.get("/platform/sms-inbox", headers=bearer(admin))).json()["active"] is False
    monkeypatch.setattr(sms, "_sender", MeteredSms(FakeSmsSender()))
    assert (await client.get("/platform/sms-inbox", headers=bearer(admin))).json()["active"] is True
