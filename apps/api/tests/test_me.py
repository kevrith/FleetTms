import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import StaffProfile
from tests.helpers import bearer
from tests.leasing import in_db, month_start
from tests.shots import ago, begin_trip, fleet, now_iso, photo_id, sync, upload


async def test_a_driver_asks_for_a_repair_and_the_workshop_sees_it_on_their_vehicle(client):
    f = await fleet(client)
    res = await client.post(
        "/me/repair-requests", headers=bearer(f.driver),
        json={"kind": "tyre", "position": "steer_left", "can_drive": False, "description": "Slow puncture, losing air"},
    )  # fmt: skip
    assert res.status_code == 201, res.text
    assert res.json()["priority"] == "urgent" and res.json()["registration"] == "KCA 123A"
    orders = (await client.get("/work-orders", headers=bearer(f.owner))).json()
    assert [o["title"] for o in orders] == ["Tyre (steer left): do not drive"]
    assert orders[0]["vehicle_id"] == f.vehicle["id"] and orders[0]["description"] == "Slow puncture, losing air"
    mine = (await client.get("/me/repair-requests", headers=bearer(f.driver))).json()
    assert [r["status"] for r in mine] == ["open"]
    assert (await client.get("/me/repair-requests", headers=bearer(f.turnboy))).json() == []  # only what each person raised


async def test_a_request_that_can_wait_is_not_urgent(client):
    f = await fleet(client)
    soft = await client.post("/me/repair-requests", headers=bearer(f.driver), json={"kind": "electrical", "description": "Left indicator is dim"})
    brakes = await client.post("/me/repair-requests", headers=bearer(f.driver), json={"kind": "brakes"})
    assert (soft.json()["priority"], brakes.json()["priority"]) == ("normal", "high")


async def test_only_a_tyre_has_a_position_and_it_must_be_a_real_one(client):
    f = await fleet(client)
    engine = await client.post("/me/repair-requests", headers=bearer(f.driver), json={"kind": "engine", "position": "steer_left"})
    nonsense = await client.post("/me/repair-requests", headers=bearer(f.driver), json={"kind": "tyre", "position": "left front"})
    assert engine.status_code == 422 and nonsense.status_code == 422
    assert engine.json()["detail"]["code"] == "bad_position"


async def test_a_repair_request_made_offline_arrives_once_with_the_time_it_was_made(client):
    f = await fleet(client)
    action = {
        "client_id": str(uuid.uuid4()), "type": "repair.request",
        "payload": {"kind": "tyre", "position": "drive1_left_outer", "can_drive": True, "occurred_at": ago(hours=3)},
    }  # fmt: skip
    first = (await sync(client, f.driver, [action])).json()["results"][0]
    again = (await sync(client, f.driver, [action])).json()["results"][0]
    assert first["status"] == "ok" and again["status"] == "duplicate"
    orders = (await client.get("/work-orders", headers=bearer(f.owner))).json()
    assert len(orders) == 1 and orders[0]["priority"] == "high"
    assert datetime.fromisoformat(orders[0]["opened_at"]) < datetime.now(UTC) - timedelta(hours=2)  # the work order is dated when the driver noticed, not when the phone found signal


async def test_someone_with_no_vehicle_cannot_raise_a_repair_request(client):
    f = await fleet(client)
    unassigned = await client.post("/me/repair-requests", headers=bearer(f.owner), json={"kind": "engine"})
    assert unassigned.status_code == 403 and unassigned.json()["detail"]["code"] == "not_your_vehicle"


async def test_trip_history_lists_finished_trips_of_the_crew_that_rode_on_them(client):
    f = await fleet(client)
    trip = await begin_trip(client, f)
    assert (await client.get("/me/trip-history", headers=bearer(f.driver))).json() == []  # still running
    end = await client.post(
        f"/trips/{trip['id']}/end", headers=bearer(f.driver),
        json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125600},
    )  # fmt: skip
    assert end.status_code == 200, end.text
    done = (await client.get("/me/trip-history", headers=bearer(f.driver))).json()
    assert [t["id"] for t in done] == [trip["id"]] and done[0]["status"] == "completed" and done[0]["distance_km"] == 500
    crew = (await client.get("/me/trip-history", headers=bearer(f.turnboy))).json()
    assert [t["id"] for t in crew] == [trip["id"]]  # the turnboy rode on it too
    assert (await client.get("/me/trip-history", headers=bearer(f.owner))).json() == []  # the owner drove nothing


async def test_my_pay_shows_only_my_approved_months_and_never_anyone_elses(client):
    f = await fleet(client)

    async def salaries(db):
        for phone, cents in (("+254712345678", 3_000_000), ("+254722345678", 1_800_000)):
            mid = uuid.UUID(f.ids[phone])
            profile = (await db.execute(select(StaffProfile).where(StaffProfile.membership_id == mid))).scalar_one_or_none()
            if profile is None:
                db.add(StaffProfile(membership_id=mid, monthly_salary_cents=cents))
            else:
                profile.monthly_salary_cents = cents

    await in_db(salaries)
    run = (await client.post("/payroll/runs", headers=bearer(f.owner), json={"month": month_start(-1).isoformat()})).json()
    assert (await client.get("/me/pay", headers=bearer(f.driver))).json() == []  # a draft is not pay yet
    await client.post(f"/payroll/runs/{run['id']}/approve", headers=bearer(f.owner))
    driver = (await client.get("/me/pay", headers=bearer(f.driver))).json()
    turnboy = (await client.get("/me/pay", headers=bearer(f.turnboy))).json()
    assert [(p["status"], p["gross_cents"], p["net_cents"]) for p in driver] == [("approved", 3_000_000, 3_000_000)]
    assert [(p["gross_cents"]) for p in turnboy] == [1_800_000]
    assert (await client.get("/me/pay", headers=bearer(f.owner))).json() == []  # the owner has no pay line of their own


async def test_a_repair_request_carries_its_photo_to_the_workshop(client):
    f = await fleet(client)
    shot = await photo_id(client, f.driver, "repair")
    res = await client.post("/me/repair-requests", headers=bearer(f.driver), json={"kind": "tyre", "position": "steer_left", "photo_ids": [shot]})
    assert res.status_code == 201, res.text
    assert [p["id"] for p in res.json()["photos"]] == [shot] and res.json()["photos"][0]["url"]
    orders = (await client.get("/work-orders", headers=bearer(f.owner))).json()
    assert [p["id"] for p in orders[0]["photos"]] == [shot]
    one = (await client.get(f"/work-orders/{orders[0]['id']}", headers=bearer(f.owner))).json()
    assert [p["kind"] for p in one["photos"]] == ["repair"]
    assert [p["id"] for p in (await client.get("/me/repair-requests", headers=bearer(f.driver))).json()[0]["photos"]] == [shot]
    again = await client.post("/me/repair-requests", headers=bearer(f.driver), json={"kind": "tyre", "photo_ids": [shot]})
    assert again.status_code == 422 and again.json()["detail"]["code"] == "photo_invalid"  # a photo backs one request only


async def test_only_your_own_repair_photo_of_the_right_kind_is_accepted(client):
    f = await fleet(client)
    receipt = await photo_id(client, f.driver, "receipt")
    theirs = await photo_id(client, f.turnboy, "repair")
    for shot in (receipt, theirs):
        res = await client.post("/me/repair-requests", headers=bearer(f.driver), json={"kind": "engine", "photo_ids": [shot]})
        assert res.status_code == 422 and res.json()["detail"]["code"] == "photo_invalid"
    assert (await client.get("/work-orders", headers=bearer(f.owner))).json() == []  # nothing half-made


async def test_an_offline_repair_request_finds_its_photo_by_the_id_the_phone_gave_it(client):
    f = await fleet(client)
    cid = uuid.uuid4()
    assert (await upload(client, f.driver, "repair", client_id=cid, offline=True)).status_code == 201
    action = {"client_id": str(uuid.uuid4()), "type": "repair.request", "payload": {"kind": "brakes", "photo_client_ids": [str(cid)], "occurred_at": now_iso()}}
    assert (await sync(client, f.driver, [action])).json()["results"][0]["status"] == "ok"
    assert len((await client.get("/work-orders", headers=bearer(f.owner))).json()[0]["photos"]) == 1
