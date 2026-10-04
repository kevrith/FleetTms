"""Product analytics: counts of which parts are used and a sign-up funnel, with no people and no content in either."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, update

from app import analytics
from app.config import settings
from app.db import get_sessionmaker
from app.models import Business, UsageCounter
from tests.billing_helpers import pay_invoice
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session
from tests.shots import begin_trip, fleet
from tests.test_support_and_privacy import make_platform_admin

TOMORROW = datetime.now(UTC).date() + timedelta(days=1)


@pytest.fixture(autouse=True)
def clean_usage():
    import redis

    def clear():
        r = redis.Redis.from_url(settings.redis_url)
        for key in r.scan_iter("usage:*"):
            r.delete(key)
        r.close()

    clear()
    yield
    clear()


async def counters():
    async with get_sessionmaker()() as db:
        return [(c.feature, c.business_key, c.requests) for c in (await db.execute(select(UsageCounter))).scalars()]


def test_only_the_first_word_of_an_address_is_ever_looked_at_and_plumbing_is_not_a_feature():
    assert analytics.feature_of("/vehicles") == "vehicles"
    assert analytics.feature_of("/vehicles/3f2b8c1e-0000-4000-8000-000000000000/inspections") == "vehicles"
    assert analytics.feature_of("/report-catalog/profit/export") == "report-catalog"
    assert analytics.feature_of("/map/vehicles") == "map"
    for plumbing in ("/auth/login", "/me/trips", "/health", "/ready", "/hooks/traccar/key", "/media/token", "/track/token", "/platform/overview", "/partners/portal", "/subscription", "/"):
        assert analytics.feature_of(plumbing) is None, plumbing
    assert analytics.feature_of("/3f2b8c1e-0000-4000-8000-000000000000") is None  # an id is never a feature
    assert analytics.feature_of("/" + "a" * 40) is None


def test_a_business_is_a_stable_pseudonym_that_does_not_contain_its_id_and_changes_with_the_secret(monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    assert analytics.business_key(a) == analytics.business_key(a) != analytics.business_key(b)
    assert len(analytics.business_key(a)) == 12 and str(a)[:8] not in analytics.business_key(a)
    before = analytics.business_key(a)
    monkeypatch.setattr(settings, "jwt_secret", "another-secret-of-sufficient-length-0123456789")
    assert analytics.business_key(a) != before


async def test_requests_are_counted_by_part_of_the_product_and_written_once_a_day(client):
    owner, _ = await owner_session(client)
    for _ in range(3):
        await client.get("/vehicles", headers=bearer(owner))
    for _ in range(2):
        await client.get("/depots", headers=bearer(owner))
    await client.get("/auth/me", headers=bearer(owner))  # plumbing: not counted
    assert await counters() == []  # today is still being counted, in memory
    assert await analytics.flush(today=TOMORROW) == 2
    got = {f: n for f, _, n in await counters()}
    assert got == {"vehicles": 3, "depots": 2}
    assert await analytics.flush(today=TOMORROW) == 0  # nothing left to move: no double counting
    assert {f: n for f, _, n in await counters()} == got


async def test_a_second_flush_adds_to_what_is_already_there(client):
    owner, _ = await owner_session(client)
    await client.get("/vehicles", headers=bearer(owner))
    await analytics.flush(today=TOMORROW)
    await client.get("/vehicles", headers=bearer(owner))
    await client.get("/vehicles", headers=bearer(owner))
    await analytics.flush(today=TOMORROW)
    assert [(f, n) for f, _, n in await counters()] == [("vehicles", 3)]


async def test_what_is_stored_holds_no_person_no_address_no_id_and_no_content(client):
    owner, _ = await owner_session(client, "Alpha Haulage", "alpha@example.com", phone="0711000111")
    business_id = (await client.get("/auth/me", headers=bearer(owner))).json()["business"]["id"]
    await add_vehicle(client, owner, "KCA 123A")
    await client.get("/vehicles", headers=bearer(owner), params={"q": "KCA"})
    await analytics.flush(today=TOMORROW)
    assert {c.name for c in UsageCounter.__table__.columns} == {"id", "day", "feature", "business_key", "requests"}
    stored = " ".join(f"{f} {k} {n}" for f, k, n in await counters())
    for personal in ("alpha@example.com", "0711000111", "+254711000111", "Alpha Haulage", business_id, "KCA"):
        assert personal not in stored
    assert all(len(k) == 12 for _, k, _ in await counters())


async def test_two_businesses_are_two_different_pseudonyms(client):
    a, _ = await owner_session(client, "Alpha Haulage", "a@example.com")
    b, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    await client.get("/vehicles", headers=bearer(a))
    await client.get("/vehicles", headers=bearer(b))
    await client.get("/vehicles", headers=bearer(b))
    await analytics.flush(today=TOMORROW)
    rows = await counters()
    assert len({k for _, k, _ in rows}) == 2 and sorted(n for _, _, n in rows) == [1, 2]


async def test_support_sessions_and_switched_off_analytics_count_nothing(monkeypatch):
    redis = Redis.from_url(settings.redis_url)
    someone = SimpleNamespace(business_id=uuid.uuid4(), support=False)
    await analytics.note(SimpleNamespace(business_id=someone.business_id, support=True), "/vehicles")
    await analytics.note(SimpleNamespace(business_id=None, support=False), "/vehicles")
    monkeypatch.setattr(settings, "analytics_enabled", False)
    await analytics.note(someone, "/vehicles")
    assert [k async for k in redis.scan_iter("usage:*")] == []
    monkeypatch.setattr(settings, "analytics_enabled", True)
    await analytics.note(someone, "/vehicles")
    assert len([k async for k in redis.scan_iter("usage:*")]) == 1
    await redis.aclose()


async def test_a_request_is_still_served_when_redis_cannot_be_reached(client, monkeypatch):
    owner, _ = await owner_session(client)
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    analytics._clients.clear()
    try:
        assert (await client.get("/vehicles", headers=bearer(owner))).status_code == 200
    finally:
        analytics._clients.clear()


async def test_the_platform_admin_sees_which_parts_are_used_and_by_how_many_businesses(client):
    a, _ = await owner_session(client, "Alpha Haulage", "a@example.com")
    b, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    for who in (a, b):
        await client.get("/vehicles", headers=bearer(who))
    await client.get("/depots", headers=bearer(a))
    await analytics.flush(today=TOMORROW)
    admin = await make_platform_admin(client)
    seen = (await client.get("/platform/analytics/usage?days=7", headers=bearer(admin))).json()
    assert seen["businesses_active"] == 2
    assert [(f["feature"], f["businesses"], f["requests"]) for f in seen["features"]] == [("vehicles", 2, 2), ("depots", 1, 1)]
    assert [d["businesses"] for d in seen["daily_active_businesses"]] == [2]
    assert (await client.get("/platform/analytics/usage", headers=bearer(a))).status_code == 403
    assert (await client.get("/platform/analytics/funnel")).status_code == 401


async def test_the_funnel_shows_how_far_new_businesses_get_and_where_they_are_stuck(client):
    await owner_session(client, "Alpha Haulage", "alpha@example.com")  # signed up and did nothing
    bravo, _ = await owner_session(client, "Bravo Transporters", "bravo@example.com")
    await add_vehicle(client, bravo, "KCB 222B")
    sample, _ = await owner_session(client, "Sample Co", "sample@example.com")
    assert (await client.post("/onboarding/sample-data", headers=bearer(sample))).status_code == 201  # sample data says nothing about a real start
    free, _ = await owner_session(client, "Free Co", "free@example.com")
    async with get_sessionmaker()() as db:
        await db.execute(update(Business).where(Business.name == "Free Co").values(complimentary=True))
        await db.commit()
    f = await fleet(client)  # Kamau Haulage: a vehicle, a driver and a turnboy
    await begin_trip(client, f)
    body = {"client_name": "Mwangi Cement", "billing_method": "per_tonne", "rate_cents": 300_000, "pickup": "Mombasa", "dropoff": "Nairobi", "distance_km": 480, "cargo_description": "Cement", "weight_tonnes": 30, "trips": 1}
    assert (await client.post("/onboarding/first-job", headers=bearer(f.owner), json=body)).status_code == 201
    await pay_invoice(client, f.owner)

    admin = await make_platform_admin(client)
    seen = (await client.get("/platform/analytics/funnel", headers=bearer(admin))).json()
    steps = {s["step"]: (s["businesses"], s["stuck"]) for s in seen["steps"]}
    assert steps == {
        "signed_up": (4, 0),  # Alpha, Bravo, Sample Co, Kamau; the free account is left out
        "added_a_vehicle": (2, 2),  # Bravo and Kamau; Alpha and Sample Co got no further
        "has_a_team": (1, 1),  # Kamau; Bravo stopped
        "made_a_job": (1, 0),
        "started_a_trip": (1, 0),
        "raised_an_invoice": (0, 1),  # Kamau has not invoiced a client yet
        "paying": (1, 0),  # Kamau paid; nobody who invoiced a client failed to pay, as nobody invoiced
    }
    assert free and seen["steps"][0]["share_pct"] == 100.0
    [cohort] = seen["cohorts"]
    assert cohort["signed_up"] == 4 and cohort["added_a_vehicle"] == 2 and cohort["has_a_team"] == 1
