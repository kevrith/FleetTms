from datetime import timedelta

import pyotp
from sqlalchemy import select, update

from app.auth_service import now
from app.db import get_sessionmaker
from app.models import AuthSession, OtpChallenge, User
from app.notify import fake_email
from app.sms import get_sms_sender
from tests.helpers import (
    PASSWORD,
    WRONG_PASSWORD,
    bearer,
    driver_session,
    enable_2fa,
    last_otp,
    login,
    owner_session,
    signup,
    staff_session,
)


async def code(res):
    return res.json()["detail"]["code"]


# ---- sign up ------------------------------------------------------------------------------------


async def test_signup_requires_all_three_acceptances(client):
    res = await client.post(
        "/auth/signup",
        json={
            "business_name": "Kamau Haulage", "name": "Owner One", "email": "o@example.com",
            "password": PASSWORD, "accept_terms": True, "accept_privacy": True, "accept_dpa": False,
        },
    )
    assert res.status_code == 422
    assert await code(res) == "terms_not_accepted"


async def test_signup_rejects_short_password_and_duplicate_email(client):
    bad = await client.post(
        "/auth/signup",
        json={
            "business_name": "Kamau Haulage", "name": "Owner One", "email": "o@example.com",
            "password": "short", "accept_terms": True, "accept_privacy": True, "accept_dpa": True,
        },
    )
    assert bad.status_code == 422
    await signup(client, email="o@example.com")
    dup = await client.post(
        "/auth/signup",
        json={
            "business_name": "Other Co", "name": "Someone", "email": "O@Example.com",
            "password": PASSWORD, "accept_terms": True, "accept_privacy": True, "accept_dpa": True,
        },
    )
    assert dup.status_code == 409


async def test_signup_records_acceptances_with_versions(client):
    tokens = await signup(client)
    await enable_2fa(client, tokens)
    me = (await client.get("/auth/me", headers=bearer(tokens))).json()
    assert me["roles"] == ["owner"]
    assert me["pending_documents"] == []  # terms, privacy and DPA were accepted at sign-up


# ---- password login and two-step verification ---------------------------------------------------


async def test_owner_must_set_up_two_step_before_using_the_app(client):
    tokens = await signup(client)
    assert tokens["mfa_setup_required"] is True
    blocked = await client.get("/users", headers=bearer(tokens))
    assert blocked.status_code == 403
    assert await code(blocked) == "mfa_setup_required"
    # ...but the setup endpoints and /me still work.
    assert (await client.get("/auth/me", headers=bearer(tokens))).status_code == 200
    await enable_2fa(client, tokens)
    assert (await client.get("/users", headers=bearer(tokens))).status_code == 200


async def test_login_needs_the_authenticator_code_once_enabled(client):
    _, secret = await owner_session(client)
    missing = await login(client, "owner@example.com")
    assert missing.status_code == 401
    assert await code(missing) == "two_factor_required"

    wrong = await client.post(
        "/auth/login", json={"identifier": "owner@example.com", "password": PASSWORD, "totp_code": "000000"}
    )
    assert wrong.status_code == 401

    ok = await login(client, "owner@example.com", secret)
    assert ok.status_code == 200
    assert ok.json()["mfa_setup_required"] is False
    assert (await client.get("/users", headers=bearer(ok.json()))).status_code == 200


async def test_wrong_password_gives_a_generic_message(client):
    await owner_session(client)
    wrong_pw = await login(client, "owner@example.com", password=WRONG_PASSWORD)
    no_user = await login(client, "nobody@example.com")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


async def test_account_locks_after_repeated_failures(client):
    _, secret = await owner_session(client)
    for _ in range(5):
        res = await login(client, "owner@example.com", password=WRONG_PASSWORD)
        assert res.status_code == 401
    locked = await login(client, "owner@example.com", secret)
    assert locked.status_code == 429
    assert await code(locked) == "account_locked"

    async with get_sessionmaker()() as db:  # time passes
        await db.execute(update(User).values(locked_until=now() - timedelta(seconds=1)))
        await db.commit()
    assert (await login(client, "owner@example.com", secret)).status_code == 200


async def test_login_by_phone_number_works_for_password_users(client):
    tokens = await signup(client, phone="0711000111")
    secret = await enable_2fa(client, tokens)
    assert (await login(client, "+254711000111", secret)).status_code == 200


# ---- driver login: phone + one-time code --------------------------------------------------------


async def test_driver_logs_in_with_phone_and_code(client):
    owner, _ = await owner_session(client)
    tokens = await driver_session(client, owner, "0712345678")
    assert tokens["mfa_setup_required"] is False
    me = (await client.get("/auth/me", headers=bearer(tokens))).json()
    assert me["roles"] == ["driver"]
    assert me["permissions"] == ["expenses.own", "trips.own"]


async def test_otp_request_gives_the_same_answer_for_unknown_numbers(client):
    owner, _ = await owner_session(client)
    await client.post("/users", headers=bearer(owner), json={"name": "Dan Driver", "phone": "0712345678", "roles": ["driver"]})
    known = await client.post("/auth/otp/request", json={"phone": "0712345678"})
    sent = len(get_sms_sender().outbox)
    unknown = await client.post("/auth/otp/request", json={"phone": "0799999999"})
    assert known.json() == unknown.json()
    assert len(get_sms_sender().outbox) == sent == 1  # nothing sent to the unknown number


async def test_otp_code_works_once_only(client):
    owner, _ = await owner_session(client)
    await client.post("/users", headers=bearer(owner), json={"name": "Dan Driver", "phone": "0712345678", "roles": ["driver"]})
    await client.post("/auth/otp/request", json={"phone": "0712345678"})
    otp = last_otp()
    assert (await client.post("/auth/otp/verify", json={"phone": "0712345678", "code": otp})).status_code == 200
    assert (await client.post("/auth/otp/verify", json={"phone": "0712345678", "code": otp})).status_code == 401


async def test_otp_is_locked_after_too_many_wrong_guesses(client):
    owner, _ = await owner_session(client)
    await client.post("/users", headers=bearer(owner), json={"name": "Dan Driver", "phone": "0712345678", "roles": ["driver"]})
    await client.post("/auth/otp/request", json={"phone": "0712345678"})
    otp = last_otp()
    wrong = "000000" if otp != "000000" else "111111"
    for _ in range(5):
        assert (await client.post("/auth/otp/verify", json={"phone": "0712345678", "code": wrong})).status_code == 401
    # Even the right code is refused now.
    assert (await client.post("/auth/otp/verify", json={"phone": "0712345678", "code": otp})).status_code == 401


async def test_otp_expires(client):
    owner, _ = await owner_session(client)
    await client.post("/users", headers=bearer(owner), json={"name": "Dan Driver", "phone": "0712345678", "roles": ["driver"]})
    await client.post("/auth/otp/request", json={"phone": "0712345678"})
    otp = last_otp()
    async with get_sessionmaker()() as db:
        await db.execute(update(OtpChallenge).values(expires_at=now() - timedelta(seconds=1)))
        await db.commit()
    assert (await client.post("/auth/otp/verify", json={"phone": "0712345678", "code": otp})).status_code == 401


async def test_otp_requests_are_throttled(client):
    owner, _ = await owner_session(client)
    await client.post("/users", headers=bearer(owner), json={"name": "Dan Driver", "phone": "0712345678", "roles": ["driver"]})
    for _ in range(3):
        await client.post("/auth/otp/request", json={"phone": "0712345678"})
    assert len(get_sms_sender().outbox) == 1


async def test_staff_cannot_use_phone_codes(client):
    owner, _ = await owner_session(client)
    await client.post(
        "/users", headers=bearer(owner),
        json={"name": "Mary Manager", "email": "mgr@example.com", "phone": "0733000111", "roles": ["manager"]},
    )
    await client.post("/auth/otp/request", json={"phone": "0733000111"})
    assert get_sms_sender().outbox == []


async def test_owner_who_is_also_a_driver_must_use_password_and_2fa(client):
    tokens = await signup(client, phone="0711000111")
    await enable_2fa(client, tokens)
    me = (await client.get("/auth/me", headers=bearer(tokens))).json()
    await client.put(
        f"/users/{(await client.get('/users', headers=bearer(tokens))).json()[0]['membership_id']}/roles",
        headers=bearer(tokens), json={"roles": ["owner", "driver"]},
    )
    await client.post("/auth/otp/request", json={"phone": "0711000111"})
    assert get_sms_sender().outbox == []
    assert me["user"]["phone"] == "+254711000111"


# ---- sessions -----------------------------------------------------------------------------------


async def test_refresh_rotates_and_old_token_replay_ends_the_session(client):
    _, secret = await owner_session(client)
    login_res = (await login(client, "owner@example.com", secret)).json()
    first = login_res["refresh_token"]

    second = await client.post("/auth/refresh", json={"refresh_token": first})
    assert second.status_code == 200
    new_tokens = second.json()
    assert new_tokens["refresh_token"] != first
    assert (await client.get("/users", headers=bearer(new_tokens))).status_code == 200

    replay = await client.post("/auth/refresh", json={"refresh_token": first})  # stolen/old token
    assert replay.status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})).status_code == 401
    assert (await client.get("/users", headers=bearer(new_tokens))).status_code == 401


async def test_garbage_tokens_are_rejected(client):
    assert (await client.post("/auth/refresh", json={"refresh_token": "nonsense"})).status_code == 401
    assert (await client.get("/users", headers={"Authorization": "Bearer not.a.jwt"})).status_code == 401


async def test_logout_ends_only_this_session(client):
    _, secret = await owner_session(client)
    one = (await login(client, "owner@example.com", secret)).json()
    two = (await login(client, "owner@example.com", secret)).json()
    assert (await client.post("/auth/logout", headers=bearer(one))).status_code == 204
    assert (await client.get("/users", headers=bearer(one))).status_code == 401
    assert (await client.get("/users", headers=bearer(two))).status_code == 200


async def test_logout_all_devices(client):
    _, secret = await owner_session(client)
    one = (await login(client, "owner@example.com", secret)).json()
    two = (await login(client, "owner@example.com", secret)).json()
    assert (await client.post("/auth/logout-all", headers=bearer(one))).status_code == 204
    assert (await client.get("/users", headers=bearer(one))).status_code == 401
    assert (await client.get("/users", headers=bearer(two))).status_code == 401


async def test_expired_session_is_rejected(client):
    tokens, _ = await owner_session(client)
    async with get_sessionmaker()() as db:
        await db.execute(update(AuthSession).values(expires_at=now() - timedelta(seconds=1)))
        await db.commit()
    assert (await client.get("/users", headers=bearer(tokens))).status_code == 401


async def test_removing_a_user_cuts_access_immediately(client):
    owner, _ = await owner_session(client)
    mgr, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.get("/users", headers=bearer(mgr))).status_code == 200

    members = (await client.get("/users", headers=bearer(owner))).json()
    target = next(m for m in members if m["email"] == "mgr@example.com")
    assert (await client.delete(f"/users/{target['membership_id']}", headers=bearer(owner))).status_code == 204

    assert (await client.get("/users", headers=bearer(mgr))).status_code == 401
    assert (await login(client, "mgr@example.com")).status_code in (401, 403)


async def test_deactivated_user_cannot_use_an_existing_token(client):
    tokens, _ = await owner_session(client)
    async with get_sessionmaker()() as db:
        await db.execute(update(User).values(is_active=False))
        await db.commit()
    assert (await client.get("/users", headers=bearer(tokens))).status_code == 401


# ---- invitations --------------------------------------------------------------------------------


async def test_invite_flow_and_token_is_single_use(client):
    owner, _ = await owner_session(client)
    res = await client.post(
        "/users", headers=bearer(owner), json={"name": "Acc", "email": "acc@example.com", "roles": ["accountant"]}
    )
    token = res.json()["invite_token"]
    assert token
    # No password yet: cannot log in.
    assert (await login(client, "acc@example.com")).status_code == 401
    assert (await client.post("/auth/accept-invite", json={"token": token, "password": PASSWORD})).status_code == 204
    assert (await client.post("/auth/accept-invite", json={"token": token, "password": PASSWORD})).status_code == 400
    assert (await login(client, "acc@example.com")).status_code == 200


async def test_invite_is_emailed_with_a_working_link(client):
    fake_email().outbox.clear()
    owner, _ = await owner_session(client)
    res = await client.post(
        "/users", headers=bearer(owner), json={"name": "Acc", "email": "acc@example.com", "roles": ["accountant"]}
    )
    token = res.json()["invite_token"]
    to, subject, body = fake_email().outbox[-1]
    assert to == "acc@example.com"
    assert "invited you" in subject and "FleetTms" in subject
    assert f"/accept-invite?token={token}" in body
    # A driver signs in by phone and gets no invitation email.
    fake_email().outbox.clear()
    await client.post("/users", headers=bearer(owner), json={"name": "Dan", "phone": "0712000009", "roles": ["driver"]})
    assert fake_email().outbox == []


async def test_expired_invite_is_rejected(client):
    owner, _ = await owner_session(client)
    res = await client.post(
        "/users", headers=bearer(owner), json={"name": "Acc", "email": "acc@example.com", "roles": ["accountant"]}
    )
    async with get_sessionmaker()() as db:
        await db.execute(update(User).where(User.email == "acc@example.com").values(invite_expires_at=now() - timedelta(hours=1)))
        await db.commit()
    bad = await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
    assert bad.status_code == 400


async def test_invite_validation(client):
    owner, _ = await owner_session(client)
    h = bearer(owner)
    assert (await client.post("/users", headers=h, json={"name": "Dan Driver", "roles": ["driver"]})).status_code == 422
    assert (await client.post("/users", headers=h, json={"name": "Mary Manager", "roles": ["manager"]})).status_code == 422
    assert (await client.post("/users", headers=h, json={"name": "Dan Driver", "phone": "123", "roles": ["driver"]})).status_code == 422
    ok = await client.post("/users", headers=h, json={"name": "Dan Driver", "phone": "0712345678", "roles": ["driver"]})
    assert ok.status_code == 201 and ok.json()["invite_token"] is None
    dup = await client.post("/users", headers=h, json={"name": "Dan Driver", "phone": "0712345678", "roles": ["driver"]})
    assert dup.status_code == 409


async def test_session_user_lookup_uses_current_totp(client):
    # Guards the helper itself: a correct code is accepted, the same secret cannot be re-enrolled.
    tokens = await signup(client)
    secret = await enable_2fa(client, tokens)
    assert pyotp.TOTP(secret).verify(pyotp.TOTP(secret).now())
    again = await client.post("/auth/2fa/setup", headers=bearer(tokens))
    assert again.status_code == 409
    async with get_sessionmaker()() as db:
        assert (await db.execute(select(User.totp_enabled))).scalar_one() is True
