"""Rate limits on what the internet can reach, the response headers, request size, and the production settings check."""

import secrets

import pytest

from app import http_security, ratelimit
from app.config import Settings, settings
from app.sms import FakeSmsSender
from tests.helpers import PASSWORD, bearer, owner_session

pytestmark = pytest.mark.usefixtures("rate_limits")


async def login_as(client, who, **headers):
    return await client.post("/auth/login", json={"identifier": who, "password": secrets.token_urlsafe(12)}, headers=headers)


async def test_one_address_cannot_try_sign_in_more_than_twenty_times_a_minute(client):
    codes = [(await login_as(client, f"nobody{i}@example.com")).status_code for i in range(22)]
    assert codes[:20] == [401] * 20
    assert codes[20:] == [429, 429]
    refused = await login_as(client, "nobody99@example.com")
    assert refused.json()["detail"]["code"] == "rate_limited"
    assert 1 <= int(refused.headers["retry-after"]) <= 60


async def test_a_made_up_forwarded_address_does_not_get_around_the_limit(client):
    for i in range(20):
        await login_as(client, f"nobody{i}@example.com")
    cheat = await login_as(client, "nobody50@example.com", **{"X-Forwarded-For": "203.0.113.9"})
    assert cheat.status_code == 429  # the header is not believed unless a trusted proxy sets it


async def test_behind_a_trusted_proxy_each_real_address_has_its_own_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    for i in range(20):
        await login_as(client, f"nobody{i}@example.com", **{"X-Forwarded-For": "203.0.113.1"})
    assert (await login_as(client, "nobody30@example.com", **{"X-Forwarded-For": "203.0.113.1"})).status_code == 429
    assert (await login_as(client, "nobody31@example.com", **{"X-Forwarded-For": "203.0.113.2"})).status_code == 401


async def test_a_phone_number_gets_at_most_five_codes_an_hour_whoever_owns_it(client):
    phone = "0711000111"  # not registered to anyone
    codes = []
    for _ in range(7):
        res = await client.post("/auth/otp/request", json={"phone": phone})
        codes.append(res.status_code)
    assert codes == [200] * 5 + [429, 429]  # the same for a number nobody has, so it also reveals nothing


async def test_signing_up_is_limited_to_five_businesses_an_hour_from_one_address(client):
    body = {"business_name": "Kamau Haulage", "name": "Owner One", "phone": None, "password": PASSWORD, "accept_terms": True, "accept_privacy": True, "accept_dpa": True}
    codes = [(await client.post("/auth/signup", json={**body, "email": f"o{i}@example.com"})).status_code for i in range(7)]
    assert codes[:5] == [201] * 5
    assert codes[5:] == [429, 429]


async def test_wrong_hook_keys_shut_an_address_out_but_good_posts_are_never_counted(client, monkeypatch):
    key = secrets.token_urlsafe(24)
    monkeypatch.setattr(settings, "traccar_forward_key", key)
    for _ in range(50):  # a busy tracker server posting with the right key is not limited
        res = await client.post(f"/hooks/traccar/{key}", json={})
        assert res.status_code != 429
    wrong = [(await client.post(f"/hooks/traccar/{secrets.token_urlsafe(24)}", json={})).status_code for _ in range(22)]
    assert wrong[:20] == [403] * 20
    assert wrong[20:] == [429, 429]
    assert (await client.post(f"/hooks/traccar/{key}", json={})).status_code == 429  # a guesser stays out for ten minutes


async def test_tracking_links_and_media_links_cannot_be_guessed_at_speed(client):
    codes = [(await client.get(f"/track/{secrets.token_urlsafe(16)}")).status_code for _ in range(122)]
    assert codes[:120] == [404] * 120 or set(codes[:120]) <= {404, 410}
    assert codes[120:] == [429, 429]


async def test_when_redis_is_down_requests_still_go_through(client, monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    ratelimit._clients.clear()
    try:
        for i in range(25):
            assert (await login_as(client, f"nobody{i}@example.com")).status_code == 401
    finally:
        ratelimit._clients.clear()


async def test_ordinary_use_is_not_limited(client):
    owner, _ = await owner_session(client)
    for _ in range(60):
        assert (await client.get("/auth/me", headers=bearer(owner))).status_code == 200


async def test_every_answer_carries_the_security_headers_and_is_not_cached(client):
    res = await client.get("/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["cache-control"] == "no-store"
    assert "geolocation=()" in res.headers["permissions-policy"]
    assert "strict-transport-security" not in res.headers  # only on a real https deployment


async def test_production_adds_strict_transport_security(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    assert "max-age=" in (await client.get("/health")).headers["strict-transport-security"]


async def test_a_request_that_says_it_is_huge_is_refused_before_it_is_read(client):
    res = await client.post("/auth/login", content=b"{}", headers={"Content-Length": str(http_security.MAX_REQUEST_BYTES + 1), "Content-Type": "application/json"})
    assert res.status_code == 413
    assert res.json()["detail"]["code"] == "too_large"


GOOD = {
    "environment": "production", "jwt_secret": secrets.token_urlsafe(40), "cors_origins": "https://app.example.com", "public_api_url": "https://api.example.com",
    "enforce_plans": True, "enforce_billing": True, "rate_limits_enabled": True, "document_reader": "", "ask_llm": "",
}  # fmt: skip


def problems(**changes):
    sms = changes.pop("sms", False)
    return http_security.production_problems(Settings.model_construct(**{**GOOD, **changes}), sms_is_stand_in=sms)


def test_a_properly_set_up_production_deployment_has_no_problems():
    assert problems() == []


@pytest.mark.parametrize(
    ("change", "mentions"),
    [
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"cors_origins": "http://localhost:5180"}, "CORS_ORIGINS"),
        ({"cors_origins": "http://app.example.com"}, "CORS_ORIGINS"),
        ({"public_api_url": "http://api.example.com"}, "PUBLIC_API_URL"),
        ({"public_api_url": ""}, "PUBLIC_API_URL"),
        ({"enforce_billing": False}, "ENFORCE_PLANS"),
        ({"enforce_plans": False}, "ENFORCE_PLANS"),
        ({"rate_limits_enabled": False}, "RATE_LIMITS_ENABLED"),
        ({"ask_llm": "fake"}, "ASK_LLM"),
        ({"document_reader": "fake"}, "DOCUMENT_READER"),
        ({"sms": True}, "Text messages"),
    ],
)
def test_each_development_setting_is_caught_for_production(change, mentions):
    found = problems(**change)
    assert any(mentions in p for p in found), found


def test_the_api_refuses_to_start_in_production_with_development_settings(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "jwt_secret", "short")
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        http_security.check_production()


def test_the_in_memory_sms_sender_counts_as_a_stand_in():
    from app.sms import MeteredSms

    assert isinstance(MeteredSms(FakeSmsSender()).inner, FakeSmsSender)
