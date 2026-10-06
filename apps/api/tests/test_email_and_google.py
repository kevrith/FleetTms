"""Confirming an email address before the app is usable, and signing in or up with Google."""

from datetime import timedelta

import pyotp
import pytest
from sqlalchemy import select, update

from app import google_auth, notify
from app.auth_service import now
from app.config import settings
from app.db import get_sessionmaker
from app.models import Business, User
from app.notify import fake_email
from tests.helpers import PASSWORD, bearer, enable_2fa, login, signup


@pytest.fixture
def mail_on(monkeypatch):
    """Real email is set up, so confirming the address is enforced; the messages land in the in-memory outbox."""
    monkeypatch.setattr(settings, "smtp_host", "mail.test")
    monkeypatch.setattr(notify, "get_email_sender", lambda: fake_email())
    fake_email().outbox.clear()
    yield fake_email()
    fake_email().outbox.clear()


@pytest.fixture
def google_on(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id.apps.example")


def link_token(outbox) -> str:
    body = outbox.outbox[-1][2]
    return body.split("/verify-email?token=")[1].split()[0]


async def user_row(email: str) -> User:
    async with get_sessionmaker()() as db:
        return (await db.execute(select(User).where(User.email == email))).scalar_one()


# ---- confirming the email -------------------------------------------------------------------------------------------


async def test_a_new_account_cannot_use_the_app_until_the_email_link_is_opened(client, mail_on):
    tokens = await signup(client, email="new@example.com")
    to, subject, _ = mail_on.outbox[-1]
    assert to == "new@example.com" and "Confirm your email" in subject

    me = (await client.get("/auth/me", headers=bearer(tokens))).json()
    assert me["email_verified"] is False and me["email_verification_pending"] is True
    blocked = await client.get("/vehicles", headers=bearer(tokens))
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "email_not_verified"

    assert (await client.post("/auth/email/verify", json={"token": link_token(mail_on)})).status_code == 204
    me = (await client.get("/auth/me", headers=bearer(tokens))).json()
    assert me["email_verified"] is True and me["email_verification_pending"] is False
    after = await client.get("/vehicles", headers=bearer(tokens))
    assert after.json()["detail"]["code"] == "mfa_setup_required"  # the next step, two-step set-up, is now reachable
    await enable_2fa(client, tokens)
    assert (await client.get("/vehicles", headers=bearer(tokens))).status_code == 200


async def test_the_link_works_once_and_a_wrong_or_expired_one_is_refused(client, mail_on):
    await signup(client, email="new@example.com")
    token = link_token(mail_on)
    wrong = await client.post("/auth/email/verify", json={"token": "x" * 43})
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "invalid_link"
    async with get_sessionmaker()() as db:
        await db.execute(update(User).where(User.email == "new@example.com").values(email_verify_expires_at=now() - timedelta(minutes=1)))
        await db.commit()
    assert (await client.post("/auth/email/verify", json={"token": token})).status_code == 400  # expired
    # Ask for a new link, then use it twice.
    tokens = (await login(client, "new@example.com")).json()
    assert (await client.post("/auth/email/resend", headers=bearer(tokens))).status_code == 204
    fresh = link_token(mail_on)
    assert fresh != token
    assert (await client.post("/auth/email/verify", json={"token": fresh})).status_code == 204
    assert (await client.post("/auth/email/verify", json={"token": fresh})).status_code == 400  # used up


async def test_asking_for_another_link_is_limited(client, mail_on, rate_limits):
    tokens = await signup(client, email="new@example.com")
    codes = [(await client.post("/auth/email/resend", headers=bearer(tokens))).status_code for _ in range(4)]
    assert codes == [204, 204, 204, 429]


async def test_nothing_is_enforced_where_no_mail_can_be_sent(client):
    tokens = await signup(client, email="new@example.com")  # no SMTP in the tests: the link could never arrive
    me = (await client.get("/auth/me", headers=bearer(tokens))).json()
    assert me["email_verification_pending"] is False
    assert (await client.get("/vehicles", headers=bearer(tokens))).json()["detail"]["code"] == "mfa_setup_required"


async def test_accepting_an_invitation_counts_as_confirming_the_address(client, mail_on):
    owner = await signup(client, email="owner@example.com")
    await client.post("/auth/email/verify", json={"token": link_token(mail_on)})
    await enable_2fa(client, owner)
    res = await client.post("/users", headers=bearer(owner), json={"name": "Acc", "email": "acc@example.com", "roles": ["accountant"]})
    token = res.json()["invite_token"]
    assert (await user_row("acc@example.com")).email_verified_at is None
    assert (await client.post("/auth/accept-invite", json={"token": token, "password": PASSWORD})).status_code == 204
    assert (await user_row("acc@example.com")).email_verified_at is not None


# ---- Google ---------------------------------------------------------------------------------------------------------


def google_says(monkeypatch, *, email="owner@example.com", sub="google-sub-1", name="Owner One"):
    async def fake(credential):
        if credential.startswith("bad"):
            raise google_auth.GoogleTokenError("That Google sign-in could not be checked.")
        return {"sub": sub, "email": email, "name": name, "email_verified": True}

    monkeypatch.setattr(google_auth, "verify_id_token", fake)


GOOGLE_TOKEN = "a-google-token-long-enough"
SIGNUP = {"business_name": "Kamau Haulage", "accept_terms": True, "accept_privacy": True, "accept_dpa": True}


async def test_google_is_off_until_a_client_id_is_set(client, monkeypatch):
    assert (await client.get("/auth/providers")).json() == {"google_client_id": None}
    res = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN})
    assert res.status_code == 404 and res.json()["detail"]["code"] == "google_not_configured"
    monkeypatch.setattr(settings, "google_client_id", "client-id.apps.example")
    assert (await client.get("/auth/providers")).json() == {"google_client_id": "client-id.apps.example"}


async def test_creating_a_business_with_google_needs_no_password_and_no_confirmation_email(client, google_on, mail_on, monkeypatch):
    google_says(monkeypatch)
    no_terms = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN, "business_name": "Kamau Haulage"})
    assert no_terms.status_code == 422 and no_terms.json()["detail"]["code"] == "terms_not_accepted"
    res = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN, **SIGNUP})
    assert res.status_code == 200, res.text
    tokens = res.json()
    user = await user_row("owner@example.com")
    assert user.email_verified_at is not None and user.password_hash is None and user.google_sub == "google-sub-1"
    assert mail_on.outbox == []  # Google has already checked the address
    assert (await client.get("/auth/me", headers=bearer(tokens))).json()["roles"] == ["owner"]
    assert (await client.get("/vehicles", headers=bearer(tokens))).json()["detail"]["code"] == "mfa_setup_required"  # the owner policy still applies
    async with get_sessionmaker()() as db:
        assert (await db.execute(select(Business.name))).scalar_one() == "Kamau Haulage"


async def test_signing_in_with_google_needs_an_existing_account(client, google_on, monkeypatch):
    google_says(monkeypatch)
    res = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN})
    assert res.status_code == 404 and res.json()["detail"]["code"] == "no_account"
    await client.post("/auth/google", json={"credential": GOOGLE_TOKEN, **SIGNUP})
    again = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN})
    assert again.status_code == 200 and again.json()["business_id"]
    async with get_sessionmaker()() as db:
        assert len((await db.execute(select(Business))).scalars().all()) == 1  # signing in does not make a second business


async def test_a_token_google_would_not_vouch_for_is_refused(client, google_on, monkeypatch):
    google_says(monkeypatch)
    res = await client.post("/auth/google", json={"credential": "bad-" + GOOGLE_TOKEN})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "invalid_google_token"


async def test_google_joins_the_account_with_the_same_email_and_keeps_its_two_step_check(client, google_on, mail_on, monkeypatch):
    tokens = await signup(client, email="owner@example.com")
    await client.post("/auth/email/verify", json={"token": link_token(mail_on)})  # a confirmed account keeps its password
    secret = await enable_2fa(client, tokens)
    await client.post("/users", headers=bearer(tokens), json={"name": "Acc", "email": "acc@example.com", "roles": ["accountant"]})  # other people exist
    google_says(monkeypatch)
    first = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN})
    assert first.status_code == 401 and first.json()["detail"]["code"] == "two_factor_required"
    wrong = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN, "totp_code": "000000"})
    assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "invalid_credentials"
    ok = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN, "totp_code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json()["mfa_setup_required"] is False
    assert (await user_row("owner@example.com")).google_sub == "google-sub-1"
    assert (await login(client, "owner@example.com", secret)).status_code == 200  # the password still works for a confirmed account


async def test_google_cannot_be_used_to_guess_the_two_step_code(client, google_on, monkeypatch):
    tokens = await signup(client, email="owner@example.com")
    secret = await enable_2fa(client, tokens)
    google_says(monkeypatch)
    for _ in range(settings.max_failed_logins):
        await client.post("/auth/google", json={"credential": GOOGLE_TOKEN, "totp_code": "000000"})
    locked = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN, "totp_code": pyotp.TOTP(secret).now()})
    assert locked.status_code == 429 and locked.json()["detail"]["code"] == "account_locked"


async def test_an_account_opened_on_someone_elses_address_is_taken_back_by_the_real_owner(client, google_on, mail_on, monkeypatch):
    await signup(client, email="victim@example.com")  # a stranger registers the address and never confirms it
    google_says(monkeypatch, email="victim@example.com", sub="victims-google")
    res = await client.post("/auth/google", json={"credential": GOOGLE_TOKEN})
    assert res.status_code == 200
    user = await user_row("victim@example.com")
    assert user.email_verified_at is not None and user.password_hash is None  # the stranger's password no longer works
    assert (await login(client, "victim@example.com")).status_code == 401


async def test_another_google_account_cannot_take_over_a_linked_address(client, google_on, monkeypatch):
    google_says(monkeypatch, sub="first")
    await client.post("/auth/google", json={"credential": GOOGLE_TOKEN, **SIGNUP})
    google_says(monkeypatch, sub="second")
    assert (await client.post("/auth/google", json={"credential": GOOGLE_TOKEN})).status_code == 401
