import secrets
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app import fuel_prices, routing
from app.config import settings
from app.models import FuelPrice
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import in_db
from tests.shots import fleet
from tests.test_clients import add_client, add_route
from tests.test_tracking import running

THIS_MONTH = fuel_prices.this_month()


@pytest.fixture(autouse=True)
def _feeds():
    fuel_prices.fake_feed().result = None
    fuel_prices.fake_feed().fail_with = None
    yield
    settings.google_maps_api_key = ""
    settings.epra_prices_url = ""


async def put_price(client, who, month=THIS_MONTH, region="Nairobi", diesel=19145, petrol=20520):
    return await client.put("/fuel-prices", headers=bearer(who), json={"month": month.isoformat(), "region": region, "diesel_cents": diesel, "petrol_cents": petrol})


# ---- EPRA pump prices feeding quotes -------------------------------------------------------------------------------------


async def test_a_typed_in_pump_price_is_what_a_quote_starts_from(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    r = await add_route(client, f.owner, c["id"])
    before = await client.post("/quotes", headers=bearer(f.owner), json={"client_id": c["id"], "route_id": r["id"], "weight_tonnes": "30"})
    assert before.status_code == 422 and before.json()["detail"]["code"] == "fuel_price_required"  # no fuel recorded and no price yet
    assert (await put_price(client, f.owner)).status_code == 200
    quote = await client.post("/quotes", headers=bearer(f.owner), json={"client_id": c["id"], "route_id": r["id"], "weight_tonnes": "30"})
    assert quote.status_code == 201, quote.text
    assert quote.json()["fuel_price_cents"] == 19145
    typed = await client.post("/quotes", headers=bearer(f.owner), json={"client_id": c["id"], "route_id": r["id"], "weight_tonnes": "30", "fuel_price_cents": 18000})
    assert typed.json()["fuel_price_cents"] == 18000  # a price typed into the quote still wins


async def test_the_newest_price_for_the_businesss_town_is_used_and_future_months_wait(client):
    f = await fleet(client)
    last = date(THIS_MONTH.year - 1, 12, 1) if THIS_MONTH.month == 1 else date(THIS_MONTH.year, THIS_MONTH.month - 1, 1)
    next_ = date(THIS_MONTH.year + 1, 1, 1) if THIS_MONTH.month == 12 else date(THIS_MONTH.year, THIS_MONTH.month + 1, 1)
    await put_price(client, f.owner, month=last, diesel=18000, petrol=19000)
    await put_price(client, f.owner, month=next_, diesel=22000, petrol=23000)
    await put_price(client, f.owner, region="Mombasa", diesel=19000, petrol=20000)
    got = (await client.get("/fuel-prices", headers=bearer(f.owner))).json()
    assert got["region"] == "Nairobi" and got["current"]["cents"] == 18000 and got["current"]["month"] == last.isoformat()  # next month's price has not started
    assert got["current_petrol"]["cents"] == 19000 and len(got["prices"]) == 3
    changed = await client.put("/fuel-prices/region", headers=bearer(f.owner), json={"region": "Mombasa"})
    assert changed.status_code == 200 and changed.json()["current"]["cents"] == 19000 and changed.json()["region"] == "Mombasa"
    await put_price(client, f.owner, diesel=19400, petrol=20400)
    await put_price(client, f.owner, diesel=19500, petrol=20500)  # saving the same month and town again replaces it
    again = (await client.get("/fuel-prices", headers=bearer(f.owner))).json()
    assert len(again["prices"]) == 4 and next(p for p in again["prices"] if p["region"] == "Nairobi" and p["month"] == THIS_MONTH.isoformat())["diesel_cents"] == 19500


async def test_price_changes_are_checked_audited_and_limited_to_those_who_manage_clients(client):
    f = await fleet(client)
    assert (await client.put("/fuel-prices", headers=bearer(f.owner), json={"month": THIS_MONTH.isoformat(), "region": "Atlantis", "diesel_cents": 1, "petrol_cents": 1})).json()["detail"]["code"] == "unknown_region"
    assert (await client.put("/fuel-prices", headers=bearer(f.owner), json={"month": THIS_MONTH.isoformat(), "region": "Nairobi", "diesel_cents": 0, "petrol_cents": 1})).status_code == 422
    assert (await client.put("/fuel-prices/region", headers=bearer(f.owner), json={"region": "Atlantis"})).status_code == 422
    assert (await put_price(client, f.driver)).status_code == 403
    supervisor, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    assert (await put_price(client, supervisor)).status_code == 403
    assert (await client.get("/fuel-prices", headers=bearer(supervisor))).status_code == 200  # they can see it
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await put_price(client, accountant)).status_code == 200
    assert "fuel_price.saved" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/fuel-prices", headers=bearer(other))).json()["prices"] == []


async def test_prices_can_be_fetched_from_a_feed_and_a_broken_feed_is_reported(client):
    f = await fleet(client)
    nope = await client.post("/fuel-prices/fetch", headers=bearer(f.owner))
    assert nope.status_code == 502 and nope.json()["detail"]["code"] == "feed_failed"
    fuel_prices.fake_feed().result = (THIS_MONTH, [{"region": "Nairobi", "diesel_cents": 19200, "petrol_cents": 20600}, {"region": "Kisumu", "diesel_cents": 19300, "petrol_cents": 20700}, {"region": "Atlantis", "diesel_cents": 1, "petrol_cents": 1}])
    ok = await client.post("/fuel-prices/fetch", headers=bearer(f.owner))
    assert ok.status_code == 200 and ok.json()["saved"] == 2 and ok.json()["current"]["source"] == "epra" and ok.json()["current"]["cents"] == 19200  # the town EPRA does not list for us is skipped
    fuel_prices.fake_feed().fail_with = "The price feed could not be read: ConnectError"
    assert (await client.post("/fuel-prices/fetch", headers=bearer(f.owner))).json()["detail"]["message"].startswith("The price feed could not be read")


async def test_the_daily_job_only_fetches_when_the_month_has_no_prices_yet(client):
    await fleet(client)
    fuel_prices.fake_feed().result = (THIS_MONTH, [{"region": "Nairobi", "diesel_cents": 19200, "petrol_cents": 20600}])

    async def run(db):
        return await fuel_prices.fetch_prices(db, only_if_missing=True)

    assert await in_db(run) == 1
    fuel_prices.fake_feed().result = (THIS_MONTH, [{"region": "Nairobi", "diesel_cents": 99999, "petrol_cents": 99999}])
    assert await in_db(run) == 0  # this month already has prices, so the feed is not read again

    async def read(db):
        return (await db.execute(select(FuelPrice.diesel_cents))).scalars().all()

    assert await in_db(read) == [19200]


async def test_the_feed_that_epra_style_json_comes_through_is_parsed(monkeypatch):
    body = {"month": "2026-10-17", "prices": [{"region": "Nairobi", "diesel": 191.45, "petrol": 205.2}]}
    real = httpx.AsyncClient
    monkeypatch.setattr("app.fuel_prices.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)), **kw))
    monkeypatch.setattr(settings, "epra_prices_url", "http://feed.test/prices.json")
    month, rows = await fuel_prices.HttpFeed().fetch()
    assert month == date(2026, 10, 1) and rows == [{"region": "Nairobi", "diesel_cents": 19145, "petrol_cents": 20520}]
    monkeypatch.setattr("app.fuel_prices.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"month": "soon"})), **kw))
    with pytest.raises(fuel_prices.FeedError, match="could not be read"):
        await fuel_prices.HttpFeed().fetch()


# ---- route suggestions ---------------------------------------------------------------------------------------------------


async def test_a_route_between_known_towns_is_estimated_without_any_key(client):
    f = await fleet(client)
    res = await client.post("/routes/suggest", headers=bearer(f.owner), json={"origin": "Mombasa", "destination": "Nairobi"})
    assert res.status_code == 200
    got = res.json()
    assert got["provider"] == "estimate" and 420 < got["distance_km"] < 560 and 7 < got["expected_hours"] < 11  # the real road is about 485 km
    assert (await client.post("/routes/suggest", headers=bearer(f.owner), json={"origin": " nairobi, Kenya", "destination": "KISUMU"})).json()["distance_km"] > 250
    unknown = await client.post("/routes/suggest", headers=bearer(f.owner), json={"origin": "Mombasa", "destination": "Timbuktu"})
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "no_route" and "GOOGLE_MAPS_API_KEY" in unknown.json()["detail"]["message"]
    assert (await client.post("/routes/suggest", headers=bearer(f.driver), json={"origin": "Mombasa", "destination": "Nairobi"})).status_code == 403
    assert (await client.post("/routes/suggest", headers=bearer(f.owner), json={"origin": "M", "destination": "Nairobi"})).status_code == 422


async def test_with_a_google_key_the_routes_api_is_asked_and_the_time_is_stretched_for_a_lorry(client, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"], seen["body"] = dict(request.headers), request.content.decode()
        return httpx.Response(200, json={"routes": [{"distanceMeters": 484_300, "duration": "22140s", "description": "A109"}]})

    real = httpx.AsyncClient
    monkeypatch.setattr("app.routing.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    key = secrets.token_hex(8)
    monkeypatch.setattr(settings, "google_maps_api_key", key)
    f = await fleet(client)
    got = (await client.post("/routes/suggest", headers=bearer(f.owner), json={"origin": "Mombasa", "destination": "Nakuru"})).json()
    assert got == {"distance_km": 484, "expected_hours": 8.0, "summary": "A109", "provider": "google"}  # 22140 s is 6.15 h by car, times 1.3
    assert seen["headers"]["x-goog-api-key"] == key and "routes.distanceMeters" in seen["headers"]["x-goog-fieldmask"] and '"regionCode":"KE"' in seen["body"].replace(" ", "")
    monkeypatch.setattr("app.routing.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})), **kw))
    nope = await client.post("/routes/suggest", headers=bearer(f.owner), json={"origin": "Mombasa", "destination": "Nowhere"})
    assert nope.status_code == 422 and "could not find a route" in nope.json()["detail"]["message"]
    assert routing.get_routes().__class__.__name__ == "GoogleRoutes"


# ---- the private beta: getting started and feedback ------------------------------------------------------------------------


async def test_the_getting_started_checklist_ticks_itself_off_from_what_exists(client):
    f = await fleet(client)
    first = (await client.get("/onboarding", headers=bearer(f.owner))).json()
    done = {i["key"]: i["done"] for i in first["items"]}
    assert done["vehicles"] and done["team"] and not done["clients"] and not done["routes"] and not done["trip"] and not done["gps"] and not done["alerts"] and not done["limits"]
    assert first["done"] == 2 and first["total"] == 9 and first["dismissed"] is False and all(i["link"].startswith("/") for i in first["items"])
    c = await add_client(client, f.owner)
    await add_route(client, f.owner, c["id"])
    await client.put("/fraud/settings", headers=bearer(f.owner), json={"thresholds": {"fuel_variance_pct": 12}})
    await client.put("/spend-limits", headers=bearer(f.owner), json=[{"category": None, "role": None, "limit_cents": 100000}])
    assert (await client.post("/onboarding/first-job", headers=bearer(f.owner), json={"client_name": "Bamburi Cement", "pickup": "Mombasa", "dropoff": "Nairobi", "distance_km": 480, "rate_cents": 12_000_000})).status_code == 201
    trip = await running(client, f)
    await client.post(f"/trips/{trip['id']}/locations", headers=bearer(f.driver), json={"points": [{"recorded_at": trip["started_at"], "lat": -1.29, "lng": 36.82, "accuracy_m": 5}]})
    done = {i["key"]: i["done"] for i in (await client.get("/onboarding", headers=bearer(f.owner))).json()["items"]}
    assert all(done.values())


async def test_the_checklist_can_be_hidden_and_brought_back_by_the_owner_only(client):
    f = await fleet(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.get("/onboarding", headers=bearer(manager))).status_code == 403
    assert (await client.post("/onboarding/dismiss", headers=bearer(manager))).status_code == 403
    assert (await client.post("/onboarding/dismiss", headers=bearer(f.owner))).status_code == 204
    assert (await client.get("/onboarding", headers=bearer(f.owner))).json()["dismissed"] is True
    assert (await client.post("/onboarding/restore", headers=bearer(f.owner))).status_code == 204
    assert (await client.get("/onboarding", headers=bearer(f.owner))).json()["dismissed"] is False
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    theirs = {i["key"]: i["done"] for i in (await client.get("/onboarding", headers=bearer(other))).json()["items"]}
    assert not theirs["vehicles"] and not theirs["clients"] and not theirs["trip"]  # another business has its own list


async def test_anyone_signed_in_can_send_feedback_and_the_owner_and_the_platform_see_it(client):
    from tests.test_support_and_privacy import make_platform_admin

    f = await fleet(client)
    sent = await client.post("/feedback", headers=bearer(f.driver), json={"kind": "problem", "message": "The odometer photo screen froze twice", "page": "/trips/start", "app": "mobile"})
    assert sent.status_code == 201
    await client.post("/feedback", headers=bearer(f.owner), json={"message": "Please add a weekly fuel report"})
    assert (await client.post("/feedback", headers=bearer(f.owner), json={"message": "x"})).status_code == 422
    assert (await client.post("/feedback", json={"message": "no sign in"})).status_code == 401
    mine = (await client.get("/feedback", headers=bearer(f.owner))).json()
    assert [m["message"] for m in mine] == ["Please add a weekly fuel report", "The odometer photo screen froze twice"] and mine[1]["from"] == "driver user" and mine[1]["app"] == "mobile" and mine[1]["page"] == "/trips/start"
    assert (await client.get("/feedback", headers=bearer(f.driver))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/feedback", headers=bearer(other))).json() == []
    await client.post("/feedback", headers=bearer(other), json={"kind": "praise", "message": "The map is very clear"})
    admin = await make_platform_admin(client)
    everything = (await client.get("/platform/feedback", headers=bearer(admin))).json()
    assert len(everything) == 3 and {m["business"] for m in everything} == {"Kamau Haulage", "Bravo"}
    assert (await client.get("/platform/feedback", headers=bearer(f.owner))).status_code == 403

