"""A round trip's loaded and empty kilometres, and a lorry that does not come home after delivering."""

from datetime import datetime, timedelta

from tests.helpers import bearer
from tests.shots import fleet, photo_id
from tests.test_tracking import drive, running, send

DEPOT = {"name": "Mombasa yard", "kind": "depot", "shape": {"type": "circle", "lat": -1.29, "lng": 36.82, "radius_m": 300}, "alert_on": []}


async def deliver_at(client, f, trip, minutes):
    when = (datetime.fromisoformat(trip["started_at"]) + timedelta(minutes=minutes)).isoformat()
    res = await client.post(f"/trips/{trip['id']}/deliver", headers=bearer(f.driver), json={"captured_at": when})
    assert res.status_code == 200, res.text


async def end(client, f, trip, value, **extra):
    pid = await photo_id(client, f.driver, "odometer", **{k: extra.pop(k) for k in ("lat", "lng") if k in extra})
    return await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": pid, "value": value, **extra})


async def read(client, f, trip):
    return (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()


async def test_the_trip_reports_the_loaded_and_empty_kilometres_of_the_round(client):
    f = await fleet(client)
    trip = await running(client, f)
    await send(client, f.driver, trip, drive(trip, n=21, step_deg=0.01, every=60))  # 22 km out and back in 20 minutes
    await deliver_at(client, f, trip, 10)
    assert (await end(client, f, trip, 125122)).status_code == 200
    done = await read(client, f, trip)
    assert done["distance_km"] == 22 and done["loaded_km"] == 11 and done["empty_km"] == 11


async def test_no_gps_means_no_split_rather_than_a_wrong_one(client):
    f = await fleet(client)
    trip = await running(client, f)
    await deliver_at(client, f, trip, 10)
    assert (await end(client, f, trip, 125122)).status_code == 200
    done = await read(client, f, trip)
    assert done["distance_km"] == 22 and done["loaded_km"] is None and done["empty_km"] is None


async def test_a_trip_never_delivered_has_no_return_leg(client):
    f = await fleet(client)
    trip = await running(client, f)
    await send(client, f.driver, trip, drive(trip, n=21, step_deg=0.01, every=60))
    assert (await end(client, f, trip, 125122)).status_code == 200
    done = await read(client, f, trip)
    assert done["loaded_km"] is None and done["empty_km"] is None


async def test_ending_away_from_the_depot_after_delivering_is_noted_with_the_reason(client):
    f = await fleet(client)
    assert (await client.post("/geofences", headers=bearer(f.owner), json=DEPOT)).status_code == 201
    trip = await running(client, f)
    assert [d["name"] for d in (await read(client, f, trip))["depots"]] == ["Mombasa yard"]  # the phone can tell the driver they are back
    await deliver_at(client, f, trip, 10)
    res = await end(client, f, trip, 125122, lat=-4.04, lng=39.66, away_reason="Slept at the client's gate")
    assert res.status_code == 200, res.text  # a note, never a block
    done = await read(client, f, trip)
    assert done["status"] == "completed" and "away_from_depot" in done["end_reading"]["flags"]
    assert done["ended_away_reason"] == "Slept at the client's gate" and done["depots"] == []


async def test_ending_with_no_depot_mapped_is_not_noted(client):
    f = await fleet(client)
    trip = await running(client, f)
    await deliver_at(client, f, trip, 10)
    assert (await end(client, f, trip, 125122, lat=-4.04, lng=39.66)).status_code == 200  # no depot mapped: nothing to be away from
    assert "away_from_depot" not in (await read(client, f, trip))["end_reading"]["flags"]


async def test_ending_at_the_depot_is_not_noted_and_a_reason_given_there_is_dropped(client):
    f = await fleet(client)
    assert (await client.post("/geofences", headers=bearer(f.owner), json=DEPOT)).status_code == 201
    trip = await running(client, f)
    await deliver_at(client, f, trip, 10)
    done = await end(client, f, trip, 125122, away_reason="not needed")  # the photo is taken at -1.29, 36.82: the depot
    assert done.status_code == 200
    seen = await read(client, f, trip)
    assert "away_from_depot" not in seen["end_reading"]["flags"] and seen["ended_away_reason"] is None
