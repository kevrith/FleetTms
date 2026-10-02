"""SMS code as the second sign-in step, for owner and staff accounts that prefer it to an authenticator app."""

import pytest
from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import User
from tests.helpers import PASSWORD, bearer, enable_2fa, last_otp, login, signup

PHONE = "0712345678"


async def sms_owner(client, email="owner@example.com", phone=PHONE):
    """Owner with a phone number who has switched on SMS two-step. Returns the setup-time tokens."""
    tokens = await signup(client, email=email, phone=phone)
    assert (await client.post("/auth/2fa/sms/setup", headers=bearer(tokens))).status_code == 200
    confirm = await client.post("/auth/2fa/sms/confirm", headers=bearer(tokens), json={"code": last_otp()})
    assert confirm.status_code == 204, confirm.text
    return tokens


async def test_sms_setup_unlocks_the_app_and_is_audited(client):
    tokens = await sms_owner(client)
    assert (await client.get("/users", headers=bearer(tokens))).status_code == 200
    me = (await client.get("/auth/me", headers=bearer(tokens))).json()
    assert me["two_factor_enabled"] is True and me["two_factor_method"] == "sms"
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(tokens))).json()]
    assert "auth.2fa_enabled" in actions


async def test_login_needs_a_texted_code_after_the_password(client):
    await sms_owner(client)
    first = await login(client, "owner@example.com")
    assert first.status_code == 401 and first.json()["detail"]["code"] == "sms_code_required"

    ok = await client.post(
        "/auth/login", json={"identifier": "owner@example.com", "password": PASSWORD, "sms_code": last_otp()}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["mfa_setup_required"] is False
    assert (await client.get("/users", headers=bearer(ok.json()))).status_code == 200


async def test_wrong_or_reused_code_is_rejected_and_wrong_password_sends_no_sms(client):
    await sms_owner(client)
    # Wrong password: no SMS may be sent, so the endpoint cannot be used to spam a phone.
    from app.sms import get_sms_sender

    sent_before = len(get_sms_sender().outbox)
    bad = await login(client, "owner@example.com", password="x" * 12)
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "invalid_credentials"
    assert len(get_sms_sender().outbox) == sent_before

    await login(client, "owner@example.com")  # sends a code
    code = last_otp()
    wrong = await client.post(
        "/auth/login", json={"identifier": "owner@example.com", "password": PASSWORD, "sms_code": "000000" if code != "000000" else "111111"}
    )
    assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "invalid_credentials"
    good = await client.post("/auth/login", json={"identifier": "owner@example.com", "password": PASSWORD, "sms_code": code})
    assert good.status_code == 200
    reused = await client.post("/auth/login", json={"identifier": "owner@example.com", "password": PASSWORD, "sms_code": code})
    assert reused.status_code == 401  # a code works once


async def test_repeated_wrong_codes_lock_the_account(client):
    await sms_owner(client)
    await login(client, "owner@example.com")
    for _ in range(5):
        res = await client.post(
            "/auth/login", json={"identifier": "owner@example.com", "password": PASSWORD, "sms_code": "000000"}
        )
    res = await login(client, "owner@example.com")
    assert res.status_code == 429


async def test_setup_code_and_login_code_cannot_be_swapped(client):
    """A code texted for one purpose must not work for another (driver login, SMS setup, second step)."""
    from tests.helpers import driver_session, owner_session

    owner, _ = await owner_session(client, email="boss@example.com")
    await driver_session(client, owner, "0722345678")  # drivers sign in with an SMS login code
    login_code = last_otp()
    other = await signup(client, "Other Co", "o@example.com", phone=PHONE)
    await client.post("/auth/2fa/sms/setup", headers=bearer(other))
    setup_code = last_otp()

    # A driver-login code cannot confirm someone else's SMS setup.
    assert (await client.post("/auth/2fa/sms/confirm", headers=bearer(other), json={"code": login_code})).status_code == 401
    # The setup code cannot be used as the driver login code for the owner's phone either.
    assert (await client.post("/auth/otp/verify", json={"phone": PHONE, "code": setup_code})).status_code == 401
    assert (await client.post("/auth/2fa/sms/confirm", headers=bearer(other), json={"code": setup_code})).status_code == 204


async def test_sms_needs_a_phone_and_excludes_the_authenticator_app(client):
    no_phone = await signup(client, email="nophone@example.com")
    res = await client.post("/auth/2fa/sms/setup", headers=bearer(no_phone))
    assert res.status_code == 422 and res.json()["detail"]["code"] == "phone_required"

    with_totp = await signup(client, "Alpha", "a@example.com", phone="0733345678")
    await enable_2fa(client, with_totp)
    assert (await client.post("/auth/2fa/sms/setup", headers=bearer(with_totp))).status_code == 409

    sms = await sms_owner(client, "sms@example.com", "0744345678")
    assert (await client.post("/auth/2fa/setup", headers=bearer(sms))).status_code == 409


async def test_unconfirmed_sms_setup_does_not_turn_two_step_on(client):
    tokens = await signup(client, phone=PHONE)
    await client.post("/auth/2fa/sms/setup", headers=bearer(tokens))
    assert (await client.get("/users", headers=bearer(tokens))).status_code == 403  # still owes setup
    wrong = await client.post("/auth/2fa/sms/confirm", headers=bearer(tokens), json={"code": "000000"})
    assert wrong.status_code == 401
    async with get_sessionmaker()() as db:
        assert (await db.execute(select(User.sms_2fa_enabled))).scalar_one() is False


@pytest.mark.parametrize("path", ["/auth/2fa/sms/setup"])
async def test_sms_setup_needs_a_session(client, path):
    assert (await client.post(path)).status_code == 401
