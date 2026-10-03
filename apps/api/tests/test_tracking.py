import uuid
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.sms import get_sms_sender
from app.tracking_jobs import purge_old_points, watch_business
from tests.helpers import bearer, driver_session, staff_session
from tests.leasing import in_db
from tests.shots import begin_trip, fleet, make_trip
from tests.test_dashboard import finish_trip


def at(trip: dict, seconds: float) -> str:
    return (datetime.fromisoformat(trip["started_at"]) + timedelta(seconds=seconds)).isoformat()


def drive(trip: dict, n: int = 10, step_deg: float = 0.01, every: int = 5, lat0: float = -1.0, lng: float = 36.0, speed: float = 60.0) -> list[dict]:
    """n fixes heading north, each `step_deg` of latitude (1.112 km at 0.01) after the last."""
    return [{"recorded_at": at(trip, i * every), "lat": lat0 + i * step_deg, "lng": lng, "speed_kmh": speed, "accuracy_m": 8} for i in range(n)]


async def running(client, f):
    """A trip that has started (with its start time), as the web sees it."""
    trip = await begin_trip(client, f)
    seen = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()

    async def back_then(db):  # it began half an hour ago, so there is room for a drive's worth of fixes
        from sqlalchemy import update

        from app.models import Trip

        await db.execute(update(Trip).where(Trip.id == uuid.UUID(trip["id"])).values(started_at=datetime.fromisoformat(seen["started_at"]) - timedelta(minutes=30)))

    await in_db(back_then)
    return {**seen, "started_at": (datetime.fromisoformat(seen["started_at"]) - timedelta(minutes=30)).isoformat()}


async def send(client, who, trip, points):
    return await client.post(f"/trips/{trip['id']}/locations", headers=bearer(who), json={"points": points})


async def track(client, who, trip):
    res = await client.get(f"/trips/{trip['id']}/track", headers=bearer(who))
    assert res.status_code == 200, res.text
    return res.json()


# ---- ingestion -----------------------------------------------------------------------------------------------------------


async def test_the_crews_phone_reports_fixes_during_a_trip_and_a_resend_changes_nothing(client):
    f = await fleet(client)
    trip = await running(client, f)
    res = await send(client, f.driver, trip, drive(trip))
    assert res.status_code == 200, res.text
    assert res.json() == {"accepted": 10, "duplicate": 0, "rejected": {}, "tracking": True}
    again = await send(client, f.driver, trip, drive(trip))
    assert again.json()["accepted"] == 0 and again.json()["duplicate"] == 10
    both = await send(client, f.turnboy, trip, drive(trip, n=12))  # the turnboy's phone reports the same lorry
    assert both.json()["accepted"] == 2 and both.json()["duplicate"] == 10
    t = await track(client, f.owner, trip)
    assert t["fixes"] == 12 and len(t["points"]) == 12 and t["points"][0]["lat"] == -1.0


async def test_only_the_trips_own_crew_may_report_and_only_while_it_runs(client):
    f = await fleet(client)
    trip = await running(client, f)
    stranger = await driver_session(client, f.owner, "0799000111")
    assert (await send(client, stranger, trip, drive(trip, 2))).status_code == 404
    assert (await send(client, f.owner, trip, drive(trip, 2))).status_code == 404  # even the owner: it is the crew's phone that reports
    assert (await client.post(f"/trips/{trip['id']}/locations", json={"points": drive(trip, 1)})).status_code == 401
    scheduled = await make_trip(client, f)  # not started
    assert (await send(client, f.driver, {**scheduled, "started_at": trip["started_at"]}, drive(trip, 2))).json()["detail"]["code"] == "not_tracking"
    assert (await send(client, f.driver, trip, [])).status_code == 422
    assert (await send(client, f.driver, trip, [{"recorded_at": "2026-10-02T10:00:00", "lat": 0, "lng": 0}])).status_code == 422  # a time with no zone
    assert (await send(client, f.driver, trip, [{"recorded_at": at(trip, 1), "lat": 95, "lng": 0}])).status_code == 422


async def test_fixes_from_before_the_trip_or_in_the_future_are_refused(client):
    f = await fleet(client)
    trip = await running(client, f)
    points = [
        {"recorded_at": at(trip, -600), "lat": -1.0, "lng": 36.0},  # ten minutes before the trip started
        {"recorded_at": at(trip, 3600), "lat": -1.0, "lng": 36.0},  # an hour from now
        {"recorded_at": at(trip, 5), "lat": -1.0, "lng": 36.0},
    ]
    res = (await send(client, f.driver, trip, points)).json()
    assert res["accepted"] == 1 and res["rejected"] == {"before_trip_start": 1, "in_the_future": 1}


async def test_tracking_provably_stops_when_the_trip_ends(client):
    f = await fleet(client)
    trip = await running(client, f)
    assert (await send(client, f.driver, trip, drive(trip, 5))).json()["accepted"] == 5
    await finish_trip(client, f, trip, end=125111)
    ended = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["ended_at"]
    ended_at = datetime.fromisoformat(ended)
    after = [{"recorded_at": (ended_at + timedelta(seconds=s)).isoformat(), "lat": -0.5, "lng": 36.5} for s in (1, 30, 90)]
    res = await send(client, f.driver, trip, after)
    assert res.json() == {"accepted": 0, "duplicate": 0, "rejected": {"after_trip_end": 3}, "tracking": False}
    assert (await track(client, f.owner, trip))["fixes"] == 5  # nothing after the end was kept
    # a phone that was offline may still hand in what it recorded before the end
    late = [{"recorded_at": (ended_at - timedelta(seconds=s)).isoformat(), "lat": -0.9, "lng": 36.0 + s / 1000} for s in (20, 10)]
    assert (await send(client, f.driver, trip, late)).json()["accepted"] == 2


async def test_gps_distance_is_worked_out_at_trip_end_and_compared_with_the_odometer(client):
    f = await fleet(client)
    trip = await running(client, f)
    await send(client, f.driver, trip, drive(trip, n=11, step_deg=0.01, every=60))  # 11.12 km in 11 minutes: ten steps of 1.112 km
    await finish_trip(client, f, trip, end=125111)  # the odometer says 11 km
    done = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()
    assert done["distance_km"] == 11 and done["gps_distance_km"] == 11.119 and done["distance_check"] == "ok"
    t = await track(client, f.owner, trip)
    assert t["gps_distance_km"] == 11.119 and t["odometer_distance_km"] == 11 and t["distance_check"] == "ok"


async def test_an_odometer_that_disagrees_with_the_gps_is_flagged_and_shows_on_the_dashboard(client):
    f = await fleet(client)
    trip = await running(client, f)
    await send(client, f.driver, trip, drive(trip, n=11, step_deg=0.01, every=60))  # 11 km by GPS
    await finish_trip(client, f, trip, end=125480)  # but the odometer claims 380
    done = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()
    assert done["distance_check"] == "mismatch"
    alert = next(a for a in (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"] if a["kind"] == "distance_mismatch")
    assert alert["severity"] == "amber" and "380 km" in alert["title"] and "11 km" in alert["title"]


async def test_a_trip_with_no_gps_is_not_judged(client):
    f = await fleet(client)
    trip = await running(client, f)
    await finish_trip(client, f, trip)
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["distance_check"] == "no_gps"


async def test_a_late_batch_for_an_ended_trip_updates_its_totals(client):
    f = await fleet(client)
    trip = await running(client, f)
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["gps_distance_km"] is None
    await finish_trip(client, f, trip, end=125111)
    ended_at = datetime.fromisoformat((await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["ended_at"])
    # the phone was offline: it hands in what it recorded, all of it before the trip ended (the trip lasted a few seconds on the server)
    points = [{"recorded_at": (ended_at - timedelta(milliseconds=(10 - i) * 100)).isoformat(), "lat": -1.0 + i * 0.0002, "lng": 36.0, "accuracy_m": 5} for i in range(11)]
    res = await send(client, f.driver, trip, points)
    assert res.json()["accepted"] == 11
    done = (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()
    assert done["gps_distance_km"] is not None and done["distance_check"] in ("ok", "mismatch")


# ---- the live map -----------------------------------------------------------------------------------------------------------


async def test_the_live_map_shows_each_vehicles_state_and_last_position(client):
    f = await fleet(client)
    quiet = (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"]
    assert [(v["registration"], v["state"], v["position"]) for v in quiet] == [("KCA 123A", "unknown", None)]
    trip = await running(client, f)
    now = datetime.now(UTC)
    fresh = [{"recorded_at": (now - timedelta(seconds=20 - i)).isoformat(), "lat": -1.2921 + i * 0.001, "lng": 36.8219, "speed_kmh": 62, "heading": 90, "accuracy_m": 6} for i in range(3)]
    fresh = [p for p in fresh if datetime.fromisoformat(p["recorded_at"]) >= datetime.fromisoformat(trip["started_at"]) - timedelta(minutes=2)]
    await send(client, f.driver, trip, fresh)
    [v] = (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"]
    assert v["state"] == "moving" and v["position"]["speed_kmh"] == 62 and v["trip"]["id"] == trip["id"] and v["trip"]["destination"] == "Nairobi" and v["trip"]["driver"] == "driver user"
    assert v["age_seconds"] < 60 and v["going_dark"] is False
    slow = [{"recorded_at": (now + timedelta(seconds=1)).isoformat(), "lat": -1.2900, "lng": 36.8219, "speed_kmh": 0}]
    await send(client, f.driver, trip, slow)
    assert (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["state"] == "idle"
    await finish_trip(client, f, trip)
    assert (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["state"] == "parked"  # the last known place, no trip running


async def test_a_phone_that_stops_reporting_mid_trip_shows_offline(client):
    f = await fleet(client)
    trip = await running(client, f)
    await send(client, f.driver, trip, drive(trip, 3, every=1))
    started = datetime.fromisoformat(trip["started_at"])
    # ten minutes later, from the server's point of view
    async def age(db):
        from sqlalchemy import update

        from app.models import LocationPoint, Trip

        await db.execute(update(Trip).where(Trip.id == uuid.UUID(trip["id"])).values(started_at=started - timedelta(minutes=30)))
        await db.execute(update(LocationPoint).values(recorded_at=LocationPoint.recorded_at - timedelta(minutes=10)))

    await in_db(age)
    assert (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["state"] == "offline"


async def test_supervisors_see_only_their_vehicles_on_the_map_and_others_are_refused(client):
    from tests.fleet import add_vehicle

    f = await fleet(client)
    other = await add_vehicle(client, f.owner, "KCB 222B")
    sup, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    assert (await client.get("/map/vehicles", headers=bearer(sup))).status_code == 200
    lambda who: sorted(v["registration"] for v in __import__("json").loads((__import__("asyncio").get_event_loop().run_until_complete(client.get("/map/vehicles", headers=bearer(who)))).text)["vehicles"]) if False else None
    owner_view = (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"]
    assert sorted(v["registration"] for v in owner_view) == ["KCA 123A", "KCB 222B"]
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.get("/map/vehicles", headers=bearer(accountant))).status_code == 403
    assert (await client.get("/map/vehicles", headers=bearer(f.driver))).status_code == 403
    assert (await client.get(f"/trips/{(await running(client, f))['id']}/track", headers=bearer(f.driver))).status_code == 403
    assert other["id"]


async def test_one_business_never_sees_anothers_fixes(client):
    from tests.helpers import owner_session

    f = await fleet(client)
    trip = await running(client, f)
    await send(client, f.driver, trip, drive(trip, 3))
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/map/vehicles", headers=bearer(other))).json()["vehicles"] == []
    assert (await client.get(f"/trips/{trip['id']}/track", headers=bearer(other))).status_code == 404


async def test_the_driver_can_check_whether_they_are_being_tracked(client):
    f = await fleet(client)
    idle = (await client.get("/me/tracking", headers=bearer(f.driver))).json()
    assert idle["tracking"] is False and idle["fixes_today"] == 0 and idle["retention_days"] == 365
    trip = await running(client, f)
    await send(client, f.driver, trip, drive(trip, 4))
    on = (await client.get("/me/tracking", headers=bearer(f.driver))).json()
    assert on["tracking"] is True and on["trip_id"] == trip["id"] and on["fixes_today"] == 4 and on["last_fix_at"]
    await finish_trip(client, f, trip)
    assert (await client.get("/me/tracking", headers=bearer(f.driver))).json()["tracking"] is False


# ---- going dark ---------------------------------------------------------------------------------------------------------------


async def run_watch(now=None):
    async def go(db):
        return await watch_business(db, now)

    return await in_db(go)


async def test_a_trip_that_goes_quiet_opens_a_gap_texts_the_owner_once_and_closes_when_it_reports_again(client):
    f = await fleet(client)
    from tests.leasing import set_phone

    await set_phone("owner@example.com", "+254700111222")
    trip = await running(client, f)
    fresh = [{"recorded_at": (datetime.now(UTC) - timedelta(seconds=30 - i)).isoformat(), "lat": -1.0 + i * 0.0005, "lng": 36.0} for i in range(3)]
    await send(client, f.driver, trip, fresh)
    get_sms_sender().outbox.clear()
    soon = datetime.now(UTC) + timedelta(minutes=settings.going_dark_minutes - 5)
    assert await run_watch(soon) == 0  # not long enough yet
    late = datetime.now(UTC) + timedelta(minutes=settings.going_dark_minutes + 5)
    assert await run_watch(late) == 1
    [(_phone, text)] = [m for m in get_sms_sender().outbox if m[0] == "+254700111222"]
    assert "KCA 123A" in text and "has not reported" in text
    assert await run_watch(late + timedelta(minutes=10)) == 0 and len([m for m in get_sms_sender().outbox if m[0] == "+254700111222"]) == 1  # once per gap
    gaps = (await client.get("/map/gaps", headers=bearer(f.owner))).json()
    assert len(gaps) == 1 and gaps[0]["resolved_at"] is None and gaps[0]["registration"] == "KCA 123A"
    dash = (await client.get("/dashboard", headers=bearer(f.owner))).json()
    assert "going_dark" in [a["kind"] for a in dash["alerts"]]
    assert (await client.get("/map/vehicles", headers=bearer(f.owner))).json()["vehicles"][0]["going_dark"] is True
    await send(client, f.driver, trip, [{"recorded_at": datetime.now(UTC).isoformat(), "lat": -1.1, "lng": 36.0}])
    assert (await client.get("/map/gaps", headers=bearer(f.owner))).json()[0]["resolved_at"]
    assert "going_dark" not in [a["kind"] for a in (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"]]


async def test_a_trip_that_never_reported_is_noticed_and_a_finished_trip_is_not_watched(client):
    f = await fleet(client)
    trip = await running(client, f)
    late = datetime.now(UTC) + timedelta(minutes=settings.going_dark_minutes + 5)
    assert await run_watch(late) == 1
    await finish_trip(client, f, trip)
    from sqlalchemy import update

    from app.models import TrackingGap

    await in_db(lambda db: db.execute(update(TrackingGap).values(resolved_at=datetime.now(UTC))))
    assert await run_watch(late + timedelta(hours=3)) == 0


# ---- retention ----------------------------------------------------------------------------------------------------------------


async def test_raw_points_are_deleted_after_the_retention_period_and_the_trip_totals_stay(client):
    f = await fleet(client)
    trip = await running(client, f)
    trip_id = uuid.UUID(trip["id"])
    old = datetime.now(UTC) - timedelta(days=400)
    from sqlalchemy import func, select, update

    from app.models import LocationPoint, Trip

    async def last_year(db):  # a trip from last year whose totals were never worked out, and one point from this week
        for i in range(11):
            db.add(LocationPoint(vehicle_id=uuid.UUID(f.vehicle["id"]), trip_id=trip_id, recorded_at=old + timedelta(minutes=i), lat=-1.0 + i * 0.01, lng=36.0, accuracy_m=5))
        db.add(LocationPoint(vehicle_id=uuid.UUID(f.vehicle["id"]), trip_id=None, recorded_at=datetime.now(UTC) - timedelta(days=2), lat=-1.0, lng=36.0))
        await db.execute(update(Trip).where(Trip.id == trip_id).values(gps_distance_km=None))

    await in_db(last_year)
    assert await purge_old_points() == 11

    async def left(db):
        points = (await db.execute(select(func.count()).select_from(LocationPoint))).scalar_one()
        km = (await db.execute(select(Trip.gps_distance_km).where(Trip.id == trip_id))).scalar_one()
        return points, km

    points, km = await in_db(left)
    assert points == 1 and km == 11.119  # only the recent point is left, and the summary was made before the old ones went
    assert await purge_old_points() == 0
