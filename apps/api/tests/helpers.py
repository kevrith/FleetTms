import re
import secrets

import pyotp

from app.sms import get_sms_sender

# Generated fresh for every test run, so no password is ever written into the repo.
PASSWORD = secrets.token_urlsafe(16)
WRONG_PASSWORD = secrets.token_urlsafe(16)


def bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def signup(client, business="Kamau Haulage", email="owner@example.com", phone=None, name="Owner One"):
    res = await client.post(
        "/auth/signup",
        json={
            "business_name": business,
            "name": name,
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "accept_terms": True,
            "accept_privacy": True,
            "accept_dpa": True,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def enable_2fa(client, tokens: dict) -> str:
    """Complete two-step setup for the signed-in session; returns the TOTP secret."""
    setup = await client.post("/auth/2fa/setup", headers=bearer(tokens))
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    confirm = await client.post(
        "/auth/2fa/confirm", headers=bearer(tokens), json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirm.status_code == 204, confirm.text
    return secret


async def login(client, identifier, secret=None, business_id=None, password=PASSWORD):
    body = {"identifier": identifier, "password": password, "business_id": business_id}
    if secret:
        body["totp_code"] = pyotp.TOTP(secret).now()
    return await client.post("/auth/login", json=body)


async def owner_session(client, business="Kamau Haulage", email="owner@example.com"):
    """Sign up a business and return (tokens, totp_secret) for a fully verified owner session."""
    tokens = await signup(client, business=business, email=email)
    secret = await enable_2fa(client, tokens)
    return tokens, secret


def last_otp(phone_prefix="+254") -> str:
    for phone, message in reversed(get_sms_sender().outbox):
        if phone.startswith(phone_prefix):
            return re.search(r"\b(\d{6})\b", message).group(1)
    raise AssertionError("no SMS sent")


async def invite(client, owner_tokens, **body):
    res = await client.post("/users", headers=bearer(owner_tokens), json=body)
    return res


async def staff_session(client, owner_tokens, role, email, with_2fa=True):
    """Invite a password-based staff member, accept the invite and sign in. Returns (tokens, secret)."""
    res = await invite(client, owner_tokens, name=f"{role} user", email=email, roles=[role])
    assert res.status_code == 201, res.text
    token = res.json()["invite_token"]
    accepted = await client.post("/auth/accept-invite", json={"token": token, "password": PASSWORD})
    assert accepted.status_code == 204, accepted.text
    login_res = await login(client, email)
    assert login_res.status_code == 200, login_res.text
    tokens = login_res.json()
    secret = await enable_2fa(client, tokens) if with_2fa else None
    return tokens, secret


async def driver_session(client, owner_tokens, phone, role="driver"):
    res = await invite(client, owner_tokens, name=f"{role} user", phone=phone, roles=[role])
    assert res.status_code == 201, res.text
    req = await client.post("/auth/otp/request", json={"phone": phone})
    assert req.status_code == 200
    verify = await client.post("/auth/otp/verify", json={"phone": phone, "code": last_otp()})
    assert verify.status_code == 200, verify.text
    return verify.json()
