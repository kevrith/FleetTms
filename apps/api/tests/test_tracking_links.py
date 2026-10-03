import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.models import LocationPoint, TrackingLink
from app.sms import get_sms_sender
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import in_db
from tests.shots import inspect, photo_id
from tests.test_pod_billing import deliver, job_for
from tests.test_pod_billing import setup as pod_setup

PUBLIC_KEYS = {"business", "status", "origin", "destination", "cargo", "scheduled_for", "started_at", "expected_arrival", "position", "minutes_remaining", "progress_pct", "as_of"}


async def scheduled_trip(client, **kw):
    """A client job dispatched for now (so a trip exists) but not yet started, and its owner."""
    from datetime import UTC, datetime

    from tests.shots import fleet  # noqa: F401
    from tests.test_jobs import dispatch

    f, c, r = await pod_setup(client, **kw)
    job = await job_for(client, f, c, r)
    res = await dispatch(client, f, job, scheduled_for=datetime.now(UTC).isoformat())
    assert res.status_code == 201, res.text
    return f, c, job, res.json()["trips"][0]["id"]


async def start_trip(client, f, trip_id):
    """The crew does today's inspection and starts the trip."""
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    here = (await client.get(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner))).json()["odometer_km"]
    start = await client.post(f"/trips/{trip_id}/start", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": here})
    assert start.status_code == 200, start.text


async def link(client, who, trip_id, **body):
    res = await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(who), json=body)
    assert res.status_code == 201, res.text
    return res.json()


def token_of(made: dict) -> str:
    return made["url"].rsplit("/t/", 1)[1]


async def fix(client, f, trip_id, lat, lng, speed=60.0, seconds_ago=10):
    res = await client.post(f"/trips/{trip_id}/locations", headers=bearer(f.driver), json={"points": [{"recorded_at": (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat(), "lat": lat, "lng": lng, "speed_kmh": speed, "accuracy_m": 6}]})
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_link_is_secret_shown_once_and_hashed(client):
    f, _c, _job, trip_id = await scheduled_trip(client)
    made = await link(client, f.owner, trip_id)
    token = token_of(made)
    assert made["url"].startswith("http://localhost:5180/t/") and len(token) >= 40 and made["state"] == "active"
    listed = (await client.get(f"/trips/{trip_id}/tracking-links", headers=bearer(f.owner))).json()
    assert len(listed) == 1 and "url" not in listed[0] and "token" not in str(listed[0])

    async def stored(db):
        return [r.token_hash for r in (await db.execute(select(TrackingLink))).scalars()]

    hashes = await in_db(stored)
    assert hashes and token not in hashes  # only a hash is kept
    assert "tracking_link.created" in [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_the_client_sees_progress_and_expected_arrival_and_nothing_else(client):
    f, _c, _job, trip_id = await scheduled_trip(client)
    token = token_of(await link(client, f.owner, trip_id))
    before = (await client.get(f"/track/{token}")).json()
    assert before["status"] == "scheduled" and before["position"] is None and set(before) == PUBLIC_KEYS
    # the lorry sets off: the trip is started and its phone reports from 44 km (0.4 degrees) north of the client's site
    await start_trip(client, f, trip_id)
    assert (await client.get(f"/trips/{trip_id}", headers=bearer(f.owner))).json()["status"] == "in_progress"
    await fix(client, f, trip_id, -0.8921, 36.8219, speed=60, seconds_ago=60)
    await fix(client, f, trip_id, -0.9921, 36.8219, speed=60, seconds_ago=40)
    await fix(client, f, trip_id, -1.0921, 36.8219, speed=60, seconds_ago=20)
    seen = (await client.get(f"/track/{token}")).json()
    assert seen["status"] == "on_the_way" and set(seen) == PUBLIC_KEYS  # no driver, no vehicle, no money, no other trips
    assert seen["position"]["lat"] == -1.0921 and seen["position"]["stale"] is False
    assert seen["origin"] == "Mombasa" and seen["destination"] == "Nairobi" and seen["business"] == "Kamau Haulage"
    assert 40 <= seen["progress_pct"] <= 80 and seen["minutes_remaining"] % 5 == 0 and 15 <= seen["minutes_remaining"] <= 60 and seen["expected_arrival"]
    listed = (await client.get(f"/trips/{trip_id}/tracking-links", headers=bearer(f.owner))).json()
    assert listed[0]["views"] == 2 and listed[0]["last_viewed_at"]


async def test_the_link_stops_working_after_delivery(client):
    f, _c, _job, trip_id = await scheduled_trip(client)
    token = token_of(await link(client, f.owner, trip_id))
    await start_trip(client, f, trip_id)
    assert (await client.get(f"/track/{token}")).status_code == 200
    assert (await deliver(client, f, trip_id)).status_code == 200
    gone = await client.get(f"/track/{token}")
    assert gone.status_code == 410 and gone.json()["detail"]["code"] == "delivered" and "position" not in gone.text
    assert (await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(f.owner), json={})).json()["detail"]["code"] == "already_delivered"


async def test_unknown_revoked_and_expired_links_do_not_work(client):
    f, _c, _job, trip_id = await scheduled_trip(client)
    assert (await client.get("/track/not-a-real-token")).status_code == 404
    made = await link(client, f.owner, trip_id)
    token = token_of(made)
    assert (await client.delete(f"/tracking-links/{made['id']}", headers=bearer(f.owner))).status_code == 204
    revoked = await client.get(f"/track/{token}")
    assert revoked.status_code == 410 and revoked.json()["detail"]["code"] == "revoked"
    again = await link(client, f.owner, trip_id)
    await in_db(lambda db: db.execute(update(TrackingLink).where(TrackingLink.id == uuid.UUID(again["id"])).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))))
    expired = await client.get(f"/track/{token_of(again)}")
    assert expired.status_code == 410 and expired.json()["detail"]["code"] == "expired"
    assert (await client.get(f"/trips/{trip_id}/tracking-links", headers=bearer(f.owner))).json()[0]["state"] in ("expired", "revoked")
    assert (await client.delete(f"/tracking-links/{uuid.uuid4()}", headers=bearer(f.owner))).status_code == 404


async def test_a_stale_position_is_marked_and_gives_no_arrival_time(client):
    f, _c, _job, trip_id = await scheduled_trip(client)
    token = token_of(await link(client, f.owner, trip_id))
    await start_trip(client, f, trip_id)
    await fix(client, f, trip_id, -1.0921, 36.8219, seconds_ago=20)
    await in_db(lambda db: db.execute(update(LocationPoint).values(recorded_at=LocationPoint.recorded_at - timedelta(minutes=20))))
    seen = (await client.get(f"/track/{token}")).json()
    assert seen["position"]["stale"] is True and seen["minutes_remaining"] is None


async def test_a_link_can_be_texted_to_the_client(client):
    f, _c, _job, trip_id = await scheduled_trip(client)
    get_sms_sender().outbox.clear()
    made = await link(client, f.owner, trip_id, send_sms=True)
    [(phone, text)] = [m for m in get_sms_sender().outbox if "follow your delivery" in m[1]]
    assert phone == "+254712000111" and made["url"] in text and made["sent_to"] == "+254712000111"
    other = await link(client, f.owner, trip_id, send_sms=True, phone="0722000333")
    assert other["sent_to"] == "+254722000333"
    assert (await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(f.owner), json={"send_sms": True, "phone": "12"})).json()["detail"]["code"] == "invalid_phone"


async def test_a_client_with_no_phone_cannot_be_texted_a_link(client):
    f, _c, _job, trip_id = await scheduled_trip(client, phone=None)
    res = await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(f.owner), json={"send_sms": True})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "no_phone"
    assert (await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(f.owner), json={})).status_code == 201  # the link itself still works


async def test_who_may_make_links_and_which_business_they_belong_to(client):
    f, _c, _job, trip_id = await scheduled_trip(client)
    assert (await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(f.driver), json={})).status_code == 403
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(accountant), json={})).status_code == 403
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(manager), json={})).status_code == 201
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.post(f"/trips/{trip_id}/tracking-link", headers=bearer(other), json={})).status_code == 404
