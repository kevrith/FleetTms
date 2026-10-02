"""Quick sign-in on a trusted phone: SMS code first, then a PIN."""

import secrets

import pytest

from tests.helpers import bearer, driver_session, last_otp, owner_session, staff_session

PHONE = "0712345678"
DEVICE = "pixel-" + secrets.token_hex(6)
PIN = "482915"


async def enable(client, tokens, pin=PIN, device=DEVICE):
    return await client.post(
        "/auth/quick-login/enable", headers=bearer(tokens), json={"device_id": device, "pin": pin, "device_label": "Pixel 6"}
    )


async def quick(client, secret, pin=PIN, device=DEVICE, phone=PHONE):
    return await client.post(
        "/auth/quick-login", json={"phone": phone, "device_id": device, "device_secret": secret, "pin": pin}
    )


async def driver_with_quick_login(client):
    owner, _ = await owner_session(client)
    driver = await driver_session(client, owner, PHONE)
    res = await enable(client, driver)
    assert res.status_code == 200, res.text
    return owner, driver, res.json()["device_secret"]


async def test_pin_sign_in_works_after_the_first_sms_sign_in(client):
    _, _, secret = await driver_with_quick_login(client)
    res = await quick(client, secret)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mfa_setup_required"] is False
    me = (await client.get("/auth/me", headers=bearer(body))).json()
    assert me["roles"] == ["driver"] and me["user"]["phone"] == "+254712345678"
    assert (await client.get("/me/trips", headers=bearer(body))).status_code == 200


async def test_it_cannot_be_turned_on_without_a_signed_in_session(client):
    assert (await client.post("/auth/quick-login/enable", json={"device_id": DEVICE, "pin": PIN})).status_code == 401


async def test_wrong_pin_is_refused_and_five_wrong_pins_switch_it_off(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "otp_resend_seconds", 0)  # let the test ask for a second code straight away
    _, driver, secret = await driver_with_quick_login(client)
    for i in range(4):
        res = await quick(client, secret, pin="135792")
        assert res.status_code == 401 and res.json()["detail"]["code"] == "wrong_pin", i
    locked = await quick(client, secret, pin="135792")
    assert locked.status_code == 423 and locked.json()["detail"]["code"] == "quick_login_locked"
    # Even the right PIN no longer works: the SMS code is needed again.
    assert (await quick(client, secret)).status_code == 401
    assert (await client.get(f"/auth/quick-login/status?device_id={DEVICE}", headers=bearer(driver))).json() == {"enabled": False}
    # And the person can still sign in the ordinary way, then turn it back on.
    await client.post("/auth/otp/request", json={"phone": PHONE})
    again = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": last_otp()})
    assert again.status_code == 200
    fresh = await enable(client, again.json())
    assert (await quick(client, fresh.json()["device_secret"])).status_code == 200


async def test_a_right_pin_resets_the_wrong_pin_count(client):
    _, _, secret = await driver_with_quick_login(client)
    for _ in range(3):
        await quick(client, secret, pin="135792")
    assert (await quick(client, secret)).status_code == 200
    for _ in range(4):
        assert (await quick(client, secret, pin="135792")).status_code == 401  # a fresh run of four, not the old three plus four
    assert (await quick(client, secret)).status_code == 200


async def test_the_phones_secret_is_required_and_pins_are_not_tried_without_it(client):
    _, _, secret = await driver_with_quick_login(client)
    for _ in range(8):
        res = await quick(client, "x" * 30)
        assert res.status_code == 401 and res.json()["detail"]["code"] == "invalid_credentials"
    assert (await quick(client, secret)).status_code == 200  # guessing from elsewhere cannot lock the real phone out
    assert (await quick(client, secret, device="another-phone-1")).status_code == 401  # secret belongs to one phone


async def test_it_is_for_drivers_and_turnboys_only(client):
    owner, _ = await owner_session(client)
    assert (await enable(client, owner)).status_code == 403
    manager, _ = await staff_session(client, owner, "manager", "m@example.com")
    assert (await enable(client, manager)).status_code == 403
    turnboy = await driver_session(client, owner, "0722345678", role="turnboy")
    assert (await enable(client, turnboy)).status_code == 200


@pytest.mark.parametrize("pin", ["12345", "1234567", "abcdef", "000000", "111111", "123456", "654321", "12 345"])
async def test_weak_or_malformed_pins_are_refused(client, pin):
    owner, _ = await owner_session(client)
    driver = await driver_session(client, owner, PHONE)
    res = await enable(client, driver, pin=pin)
    assert res.status_code == 422 and res.json()["detail"]["code"] in {"invalid_pin", "weak_pin"}


async def test_turning_it_off_and_signing_out_everywhere_both_end_it(client):
    _, driver, secret = await driver_with_quick_login(client)
    off = await client.post("/auth/quick-login/disable", headers=bearer(driver), json={"device_id": DEVICE})
    assert off.status_code == 204
    assert (await quick(client, secret)).status_code == 401

    fresh = (await enable(client, driver)).json()["device_secret"]
    assert (await quick(client, fresh)).status_code == 200
    assert (await client.post("/auth/logout-all", headers=bearer(driver))).status_code == 204
    assert (await quick(client, fresh)).status_code == 401  # a lost phone's quick sign-in goes with "sign out everywhere"


async def test_changing_the_pin_replaces_the_old_secret_and_pin(client):
    _, driver, old_secret = await driver_with_quick_login(client)
    new = (await enable(client, driver, pin="908273")).json()["device_secret"]
    assert (await quick(client, old_secret)).status_code == 401
    assert (await quick(client, new, pin=PIN)).status_code == 401
    assert (await quick(client, new, pin="908273")).status_code == 200


async def test_removing_someone_from_the_company_stops_their_quick_sign_in(client):
    owner, _, secret = await driver_with_quick_login(client)
    staff = (await client.get("/staff", headers=bearer(owner))).json()
    member = next(s for s in staff if s["phone"] == "+254712345678")
    assert (await client.delete(f"/users/{member['membership_id']}", headers=bearer(owner))).status_code == 204
    res = await quick(client, secret)
    assert res.status_code in {401, 403}
    assert "access_token" not in res.json()


async def test_quick_sign_in_is_audited(client):
    owner, _, secret = await driver_with_quick_login(client)
    await quick(client, secret)
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert "auth.quick_login_enabled" in actions
    assert any(e["note"] == "Quick sign-in" for e in (await client.get("/audit", headers=bearer(owner))).json())
