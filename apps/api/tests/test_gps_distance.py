"""A vehicle whose odometer cannot be trusted takes its trip distance from GPS, and its running kilometres follow."""

from datetime import datetime, timedelta

from tests.helpers import bearer
from tests.shots import fleet, inspect, make_trip, photo_id, start
from tests.test_dashboard import finish_trip
from tests.test_tracking import drive, running, send


async def use_gps(client, f):
    body = (await client.get(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner))).json()
    body.pop("id")
    body["distance_source"] = "gps"
    res = await client.put(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner), json=body)
    assert res.status_code == 200, res.text
    assert res.json()["distance_source"] == "gps"


async def vehicle_km(client, f) -> int:
    return (await client.get(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner))).json()["odometer_km"]


async def trip_of(client, f, trip) -> dict:
    return (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()


async def test_a_gps_vehicles_trip_distance_comes_from_its_fixes_not_its_stuck_dial(client):
    f = await fleet(client)
    await use_gps(client, f)
    trip = await running(client, f)  # started at 125100 on a dial that then never moves
    await send(client, f.driver, trip, drive(trip, n=11, step_deg=0.01, every=60))  # 11.1 km by GPS
    await finish_trip(client, f, trip, end=125100)
    done = await trip_of(client, f, trip)
    assert done["distance_km"] == 11 and done["distance_check"] == "gps_only"
    assert await vehicle_km(client, f) == 125000 + 11  # the dial's 125,100 is a record only; the running total grew by the GPS distance


async def test_a_gps_vehicle_accepts_readings_below_its_running_total(client):
    f = await fleet(client)
    await use_gps(client, f)
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    trip = await make_trip(client, f)
    res = await start(client, f.driver, trip["id"], value=40)  # a dial far below the vehicle's 125,000
    assert res.status_code == 200, res.text
    end = await client.post(f"/trips/{trip['id']}/end", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 12})
    assert end.status_code == 200, end.text  # even lower than the start: nothing is judged from the dial
    done = await trip_of(client, f, trip)
    assert done["distance_km"] is None and done["distance_check"] == "no_gps"
    assert await vehicle_km(client, f) == 125000


async def test_an_odometer_vehicle_still_refuses_a_backward_reading(client):
    f = await fleet(client)
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    trip = await make_trip(client, f)
    res = await start(client, f.driver, trip["id"], value=40)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "odometer_backward"


async def test_late_fixes_add_only_the_difference_to_the_running_total(client):
    f = await fleet(client)
    await use_gps(client, f)
    trip = await running(client, f)
    await finish_trip(client, f, trip, end=125100)  # no fixes yet: the phone was offline
    assert (await trip_of(client, f, trip))["distance_km"] is None and await vehicle_km(client, f) == 125000
    ended_at = datetime.fromisoformat((await trip_of(client, f, trip))["ended_at"])

    def fixes(n, every_ms):  # n fixes heading north, 2.2 m a step is too little, so use 0.002 degrees (222 m)
        return [{"recorded_at": (ended_at - timedelta(milliseconds=(n - i) * every_ms)).isoformat(), "lat": -1.0 + i * 0.002, "lng": 36.0, "accuracy_m": 5} for i in range(n)]

    assert (await send(client, f.driver, trip, fixes(11, 100))).json()["accepted"] == 11
    first = (await trip_of(client, f, trip))["distance_km"]
    assert first is not None and await vehicle_km(client, f) == 125000 + first
    # more fixes arrive for the same trip: its distance grows, and the total grows by the growth only
    more = [{"recorded_at": (ended_at - timedelta(milliseconds=(5 + i) * 7)).isoformat(), "lat": -0.9 + i * 0.01, "lng": 36.0, "accuracy_m": 5} for i in range(30)]
    await send(client, f.driver, trip, more)
    second = (await trip_of(client, f, trip))["distance_km"]
    assert second >= first and await vehicle_km(client, f) == 125000 + second
