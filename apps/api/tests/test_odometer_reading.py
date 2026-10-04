"""Reading the odometer from its photo: what is stored beside what was typed, what is flagged, and everything that must not stop a trip."""

import asyncio

import pytest

from app.config import settings
from app.document_reader import fake_reader
from tests.billing_helpers import pay_invoice
from tests.fraud_scenarios import open_alerts
from tests.helpers import bearer
from tests.shots import fleet, inspect, make_trip, photo_id, start


@pytest.fixture(autouse=True)
def reader():
    """The fake reading service, which returns what a test gives it, and nothing is read unless a test says what the photo shows."""
    settings.document_reader = "fake"
    fake = fake_reader()
    fake.result, fake.fail_with, fake.calls = None, None, []
    yield fake
    settings.document_reader = ""


def sees(reader, value, confidence=0.9, **extra):
    reader.result = {"reading": value, "unit": "km", "confidence": confidence, **extra}


async def scheduled(client):
    f = await fleet(client)
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    return f, await make_trip(client, f)


async def start_reading(client, f, trip, value=125100, **extra):
    res = await start(client, f.driver, trip["id"], value, **extra)
    assert res.status_code == 200, res.text
    return res.json()["start_reading"]


# ---- what the photo says, beside what was typed -----------------------------------------------------------------------


async def test_a_typed_number_that_matches_the_photo_is_stored_with_what_was_read_and_raises_nothing(client, reader):
    f, trip = await scheduled(client)
    sees(reader, 125100)
    reading = await start_reading(client, f, trip, 125100)
    assert reading["auto_read_value"] == 125100 and reading["value"] == 125100 and "mismatch" not in reading["flags"]
    assert [kind for kind, *_ in reader.calls] == ["odometer"]
    assert "odometer_photo_mismatch" not in {a["kind"] for a in await open_alerts(client, f.owner)}


async def test_a_typed_number_that_is_not_the_one_in_the_photo_is_flagged_and_the_owner_is_told(client, reader):
    f, trip = await scheduled(client)
    sees(reader, 125100)
    reading = await start_reading(client, f, trip, 125400)
    assert reading["auto_read_value"] == 125100 and "mismatch" in reading["flags"]
    [alert] = [a for a in await open_alerts(client, f.owner) if a["kind"] == "odometer_photo_mismatch"]
    assert alert["severity"] == "amber" and alert["evidence"] == {"typed_km": 125400, "photo_km": 125100, "phase": "start"}
    assert "125,100" in alert["title"] and "125,400" in alert["title"] and alert["trip_id"] == trip["id"]


async def test_the_end_reading_is_checked_the_same_way(client, reader):
    f, trip = await scheduled(client)
    sees(reader, 125100)
    await start_reading(client, f, trip, 125100)
    sees(reader, 125600)
    end = await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125680})
    assert end.status_code == 200, end.text
    reading = end.json()["end_reading"]
    assert reading["auto_read_value"] == 125600 and "mismatch" in reading["flags"] and end.json()["distance_km"] == 580  # the driver's number still counts; the owner is told
    alerts = [a for a in await open_alerts(client, f.owner) if a["kind"] == "odometer_photo_mismatch"]
    assert [a["evidence"]["phase"] for a in alerts] == ["end"]


async def test_the_server_reading_beats_what_the_phone_says_it_read(client, reader):
    f, trip = await scheduled(client)
    sees(reader, 125100)
    reading = await start_reading(client, f, trip, 125400, auto_read_value=125400)  # the phone claims to have read what was typed
    assert reading["auto_read_value"] == 125100 and "mismatch" in reading["flags"]


async def test_when_the_server_cannot_read_the_photo_the_phones_own_reading_is_kept_as_before(client, reader):
    f, trip = await scheduled(client)
    reader.result = {"reading": None, "unit": "km", "confidence": 0.0}
    reading = await start_reading(client, f, trip, 125400, auto_read_value=125100)
    assert reading["auto_read_value"] == 125100 and "mismatch" in reading["flags"]  # the old behaviour: a flag, from the phone's reading
    assert "odometer_photo_mismatch" not in {a["kind"] for a in await open_alerts(client, f.owner)}  # but no alert on a phone's say-so


# ---- everything that must not stop a trip -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        {"reading": 125100, "unit": "km", "confidence": 0.3},  # not sure
        {"reading": None, "unit": "km", "confidence": 0.9},  # cannot make it out
        {"reading": 78000, "unit": "mi", "confidence": 0.9},  # miles cannot be compared without guessing
        {"reading": 125100.5, "unit": "km", "confidence": 0.9},  # not a whole number
        {"reading": -5, "unit": "km", "confidence": 0.9},
        {"reading": 99_999_999, "unit": "km", "confidence": 0.9},
        {"reading": "125100", "unit": "km", "confidence": 0.9},  # not a number
        {"confidence": 0.9},
    ],
)
async def test_a_reading_that_cannot_be_believed_is_ignored_and_the_trip_starts(client, reader, result):
    f, trip = await scheduled(client)
    reader.result = result
    reading = await start_reading(client, f, trip, 125400)
    assert reading["auto_read_value"] is None and "mismatch" not in reading["flags"]
    assert "odometer_photo_mismatch" not in {a["kind"] for a in await open_alerts(client, f.owner)}


async def test_a_failing_or_slow_reading_service_never_holds_a_trip_up(client, reader, monkeypatch):
    f, trip = await scheduled(client)
    reader.fail_with = "The service is down."
    assert (await start_reading(client, f, trip, 125400))["auto_read_value"] is None

    async def slow(kind, image, content_type):
        await asyncio.sleep(2)
        return {"reading": 125100, "unit": "km", "confidence": 0.9}

    reader.fail_with = None
    monkeypatch.setattr(reader, "read", slow)
    monkeypatch.setattr(settings, "odometer_read_timeout_seconds", 0.05)
    end = await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125500})
    assert end.status_code == 200 and end.json()["end_reading"]["auto_read_value"] is None


async def test_with_reading_switched_off_or_not_set_up_nothing_is_read(client, reader, monkeypatch):
    f, trip = await scheduled(client)
    sees(reader, 125100)
    monkeypatch.setattr(settings, "odometer_reading", False)
    assert (await start_reading(client, f, trip, 125400))["auto_read_value"] is None and reader.calls == []


async def test_without_a_reading_service_configured_trips_work_as_they_always_did(client):
    settings.document_reader = ""  # no key, nothing switched on
    f, trip = await scheduled(client)
    assert (await start_reading(client, f, trip, 125100))["auto_read_value"] is None


async def test_the_check_is_part_of_every_plan_not_only_the_full_set(client, reader, billing):
    f, trip = await scheduled(client)
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "starter"}]})
    await pay_invoice(client, f.owner)
    sees(reader, 125100)
    await start_reading(client, f, trip, 125400)
    assert "odometer_photo_mismatch" in {a["kind"] for a in await open_alerts(client, f.owner)}


# ---- the suggestion while typing ------------------------------------------------------------------------------------------


async def test_the_phone_can_ask_what_the_photo_says_to_fill_the_number_in_for_the_driver_to_check(client, reader):
    f, trip = await scheduled(client)
    sees(reader, 125100)
    pid = await photo_id(client, f.driver, "odometer")
    res = await client.post("/odometer/suggest", headers=bearer(f.driver), json={"photo_id": pid})
    assert res.status_code == 200 and res.json() == {"value": 125100, "readable": True}
    reader.result = {"reading": None, "confidence": 0.0}
    again = await client.post("/odometer/suggest", headers=bearer(f.driver), json={"photo_id": pid})
    assert again.json() == {"value": None, "readable": False}
    started = await start(client, f.driver, trip["id"], 125100, photo_id=pid)  # asking did not use up the photo
    assert started.status_code == 200


async def test_a_suggestion_is_only_for_your_own_unused_odometer_photo(client, reader):
    f, trip = await scheduled(client)
    sees(reader, 125100)
    mine = await photo_id(client, f.driver, "odometer")
    receipt = await photo_id(client, f.driver, "receipt")
    assert (await client.post("/odometer/suggest", headers=bearer(f.turnboy), json={"photo_id": mine})).status_code == 404  # someone else's photo
    assert (await client.post("/odometer/suggest", headers=bearer(f.driver), json={"photo_id": receipt})).status_code == 404  # not an odometer
    assert (await client.post("/odometer/suggest", headers=bearer(f.driver), json={"photo_id": "00000000-0000-4000-8000-000000000000"})).status_code == 404
    assert (await start(client, f.driver, trip["id"], 125100, photo_id=mine)).status_code == 200
    assert (await client.post("/odometer/suggest", headers=bearer(f.driver), json={"photo_id": mine})).status_code == 404  # already used
    assert (await client.post("/odometer/suggest", json={"photo_id": mine})).status_code == 401


async def test_suggestions_are_limited_each_day(client, reader, rate_limits, monkeypatch):
    f, _ = await scheduled(client)
    sees(reader, 125100)
    monkeypatch.setattr(settings, "odometer_suggestions_per_day", 2)
    pid = await photo_id(client, f.driver, "odometer")
    codes = [(await client.post("/odometer/suggest", headers=bearer(f.driver), json={"photo_id": pid})).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
