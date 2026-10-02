"""Offline sync: a driver's queued morning arrives later, once, with the times the driver did things."""

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.db import get_sessionmaker
from app.models import Business, FuelEntry, Inspection, SyncReceipt
from app.tenancy import current_business_id
from tests.helpers import bearer, staff_session
from tests.shots import ago, checklist, fleet, make_trip, sync, upload


def new_id() -> str:
    return str(uuid.uuid4())


async def count(model) -> int:
    async with get_sessionmaker()() as db:
        current_business_id.set((await db.execute(select(Business.id))).scalars().first())
        n = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        current_business_id.set(None)
    return n


async def queue_photo(client, tokens, kind, minutes_ago):
    """A photo taken offline: the phone picks its id, and uploads it when the network returns."""
    cid = new_id()
    res = await upload(client, tokens, kind, client_id=cid, offline=True, captured_at=ago(minutes=minutes_ago))
    assert res.status_code == 201, res.text
    return cid


async def morning(client, f):
    """Everything a driver does before and during a trip, as one offline queue captured 2 to 3 hours ago."""
    trip = await make_trip(client, f)
    items = await checklist(client, f.driver)
    start_photo = await queue_photo(client, f.driver, "odometer", 150)
    cargo_photo = await queue_photo(client, f.driver, "cargo", 140)
    end_photo = await queue_photo(client, f.driver, "odometer", 20)
    actions = [
        {"client_id": new_id(), "type": "inspection.submit", "payload": {
            "vehicle_id": f.vehicle["id"], "captured_at": ago(minutes=170),
            "results": [{"item_id": i["id"], "ok": True} for i in items]}},
        {"client_id": new_id(), "type": "trip.start", "payload": {
            "trip_id": trip["id"], "captured_at": ago(minutes=150), "photo_client_id": start_photo, "value": 125100}},
        {"client_id": new_id(), "type": "trip.loading", "payload": {
            "trip_id": trip["id"], "captured_at": ago(minutes=140), "photo_client_id": cargo_photo, "loaded_weight_kg": 9800}},
        {"client_id": new_id(), "type": "fuel.add", "payload": {
            "vehicle_id": f.vehicle["id"], "trip_id": trip["id"], "captured_at": ago(minutes=100), "client_id": new_id(),
            "litres": "120.00", "price_per_litre_cents": 18500, "amount_cents": 2220000, "station": "Total Naivasha",
            "mpesa_code": "QGH7XYZ123"}},
        {"client_id": new_id(), "type": "trip.deliver", "payload": {"trip_id": trip["id"], "captured_at": ago(minutes=30)}},
        {"client_id": new_id(), "type": "trip.end", "payload": {
            "trip_id": trip["id"], "captured_at": ago(minutes=20), "photo_client_id": end_photo, "value": 125580}},
    ]  # fmt: skip
    return trip, actions


async def test_a_whole_offline_morning_syncs_with_the_times_the_driver_did_things(client):
    f = await fleet(client)
    trip, actions = await morning(client, f)
    res = await sync(client, f.driver, actions)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [r["status"] for r in body["results"]] == ["ok"] * 6, body["results"]

    done = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()
    assert done["status"] == "completed" and done["distance_km"] == 480
    started = datetime.fromisoformat(done["started_at"])
    ended = datetime.fromisoformat(done["ended_at"])
    assert abs((ended - started).total_seconds() - 130 * 60) < 2  # the driver's own times, not the moment of sync
    assert done["start_reading"]["photo"]["late"] is True  # captured long before it arrived
    assert (await client.get("/vehicles/" + f.vehicle["id"], headers=bearer(f.owner))).json()["odometer_km"] == 125580
    fuel = (await client.get("/fuel", headers=bearer(f.owner))).json()
    assert len(fuel) == 1 and fuel[0]["amount_cents"] == 2220000 and fuel[0]["trip_id"] == trip["id"]
    assert "server_time" in body


async def test_the_same_batch_sent_twice_creates_nothing_new(client):
    f = await fleet(client)
    _, actions = await morning(client, f)
    first = await sync(client, f.driver, actions)
    inspections, fuel, receipts = await count(Inspection), await count(FuelEntry), await count(SyncReceipt)
    again = await sync(client, f.driver, actions)
    assert [r["status"] for r in first.json()["results"]] == ["ok"] * 6
    assert [r["status"] for r in again.json()["results"]] == ["duplicate"] * 6
    assert (await count(Inspection), await count(FuelEntry), await count(SyncReceipt)) == (inspections, fuel, receipts)
    trips = (await client.get("/trips", headers=bearer(f.owner))).json()
    assert len(trips) == 1 and trips[0]["distance_km"] == 480


async def test_a_batch_split_in_two_and_resent_is_still_applied_once(client):
    f = await fleet(client)
    trip, actions = await morning(client, f)
    first_half = await sync(client, f.driver, actions[:3])  # the connection dropped after the first three
    assert [r["status"] for r in first_half.json()["results"]] == ["ok"] * 3
    resent = await sync(client, f.driver, actions)  # the phone cannot tell, so it sends everything again
    assert [r["status"] for r in resent.json()["results"]] == ["duplicate"] * 3 + ["ok"] * 3
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["status"] == "completed"


async def test_one_rejected_action_does_not_stop_the_rest(client):
    f = await fleet(client)
    trip = await make_trip(client, f)
    start_photo = await queue_photo(client, f.driver, "odometer", 60)
    actions = [
        {"client_id": new_id(), "type": "trip.start", "payload": {  # no inspection was queued first
            "trip_id": trip["id"], "captured_at": ago(minutes=60), "photo_client_id": start_photo, "value": 125100}},
        {"client_id": new_id(), "type": "fuel.add", "payload": {
            "vehicle_id": f.vehicle["id"], "captured_at": ago(minutes=50), "client_id": new_id(),
            "litres": "50", "price_per_litre_cents": 18500, "amount_cents": 925000}},
    ]  # fmt: skip
    results = (await sync(client, f.driver, actions)).json()["results"]
    assert results[0]["status"] == "rejected" and results[0]["code"] == "inspection_required"
    assert results[0]["retryable"] is False
    assert results[1]["status"] == "ok"
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["status"] == "scheduled"


async def test_an_action_whose_photo_has_not_arrived_is_retryable(client):
    f = await fleet(client)
    _, actions = await morning(client, f)
    missing = new_id()
    start = actions[1]
    real_photo = start["payload"]["photo_client_id"]
    start["payload"]["photo_client_id"] = missing
    results = (await sync(client, f.driver, actions[:2])).json()["results"]
    assert results[1]["code"] == "photo_invalid" and results[1]["retryable"] is True

    # The photo arrives under the id the phone promised; the same queued action now goes through.
    res = await upload(client, f.driver, "odometer", client_id=missing, offline=True, captured_at=ago(minutes=150))
    assert res.status_code == 201
    start["payload"]["photo_client_id"] = missing
    retried = (await sync(client, f.driver, [start])).json()["results"]
    assert retried[0]["status"] == "ok"
    del real_photo


async def test_uploading_the_same_queued_photo_twice_keeps_one(client):
    f = await fleet(client)
    cid = new_id()
    data_first = await upload(client, f.driver, "odometer", client_id=cid, offline=True, captured_at=ago(minutes=90))
    again = await upload(client, f.driver, "odometer", client_id=cid, offline=True, captured_at=ago(minutes=90))
    assert data_first.status_code == 201 and again.status_code == 201
    assert again.json()["id"] == data_first.json()["id"]  # a retry after a lost reply, not a second photo


async def test_old_photos_are_only_accepted_from_a_phone_that_says_it_was_offline(client):
    f = await fleet(client)
    online = await upload(client, f.driver, "odometer", captured_at=ago(hours=3))
    assert online.json()["detail"]["code"] == "photo_not_fresh"
    assert (await upload(client, f.driver, "odometer", captured_at=ago(hours=3), offline=True)).status_code == 201
    ancient = await upload(client, f.driver, "odometer", captured_at=ago(days=9), offline=True)
    assert ancient.json()["detail"]["code"] == "photo_not_fresh"


async def test_times_are_checked_for_sense(client):
    f = await fleet(client)
    trip, actions = await morning(client, f)
    await sync(client, f.driver, actions[:2])
    loading = actions[2]
    loading["payload"]["captured_at"] = ago(minutes=200)  # before the trip started
    assert (await sync(client, f.driver, [loading])).json()["results"][0]["code"] == "time_travel"
    future = {"client_id": new_id(), "type": "trip.deliver", "payload": {"trip_id": trip["id"], "captured_at": datetime.fromisoformat(ago(minutes=-90)).isoformat()}}
    assert (await sync(client, f.driver, [future])).json()["results"][0]["code"] == "bad_capture_time"
    ancient = {"client_id": new_id(), "type": "trip.deliver", "payload": {"trip_id": trip["id"], "captured_at": ago(days=9)}}
    assert (await sync(client, f.driver, [ancient])).json()["results"][0]["code"] == "bad_capture_time"


async def test_a_photo_must_belong_to_the_moment_it_backs(client):
    f = await fleet(client)
    _, actions = await morning(client, f)
    await sync(client, f.driver, actions[:1])
    start = actions[1]
    start["payload"]["captured_at"] = ago(minutes=30)  # the photo was taken 2.5 hours before this "reading"
    res = (await sync(client, f.driver, [start])).json()["results"][0]
    assert res["code"] == "photo_time_mismatch" and res["status"] == "rejected"


async def test_an_inspection_counts_for_the_day_it_was_done(client):
    f = await fleet(client)
    trip = await make_trip(client, f)
    items = await checklist(client, f.driver)
    old_inspection = {"client_id": new_id(), "type": "inspection.submit", "payload": {
        "vehicle_id": f.vehicle["id"], "captured_at": ago(hours=30), "results": [{"item_id": i["id"], "ok": True} for i in items]}}  # fmt: skip
    photo = await queue_photo(client, f.driver, "odometer", 5)
    start = {"client_id": new_id(), "type": "trip.start", "payload": {
        "trip_id": trip["id"], "captured_at": ago(minutes=5), "photo_client_id": photo, "value": 125100}}  # fmt: skip
    results = (await sync(client, f.driver, [old_inspection, start])).json()["results"]
    assert results[0]["status"] == "ok"
    assert results[1]["code"] == "inspection_required"  # yesterday's inspection does not clear today's trip


async def test_bad_actions_are_rejected_not_fatal(client):
    f = await fleet(client)
    actions = [
        {"client_id": new_id(), "type": "make.coffee", "payload": {}},
        {"client_id": new_id(), "type": "fuel.add", "payload": {"vehicle_id": f.vehicle["id"]}},
        {"client_id": new_id(), "type": "trip.deliver", "payload": {}},
    ]
    results = (await sync(client, f.driver, actions)).json()["results"]
    assert [r["code"] for r in results] == ["unknown_action", "invalid_action", "invalid_action"]
    too_many = [{"client_id": new_id(), "type": "trip.deliver", "payload": {}} for _ in range(51)]
    assert (await sync(client, f.driver, too_many)).status_code == 422


async def test_sync_is_isolated_and_permissioned(client):
    f = await fleet(client)
    _, actions = await morning(client, f)
    other = await fleet_for_other_business(client)
    stranger = (await sync(client, other, actions[1:2])).json()["results"][0]
    assert stranger["status"] == "rejected" and stranger["code"] == "not_found"  # not their business's trip
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await sync(client, accountant, [])).status_code == 403
    assert (await client.post("/sync", json={"actions": []})).status_code == 401


async def fleet_for_other_business(client):
    from tests.helpers import driver_session, owner_session

    owner, _ = await owner_session(client, "Bravo", "b@example.com")
    return await driver_session(client, owner, "0799345678")


async def test_one_person_cannot_replay_anothers_action_id(client):
    f = await fleet(client)
    _, actions = await morning(client, f)
    await sync(client, f.driver, actions[:1])
    stolen = (await sync(client, f.turnboy, actions[:1])).json()["results"][0]
    assert stolen["code"] == "client_id_in_use"
