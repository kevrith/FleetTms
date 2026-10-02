from datetime import UTC, datetime, timedelta

from app.report_delivery import fake_sender
from app.sms import get_sms_sender
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.shots import fleet
from tests.test_clients import add_client, add_route

FUEL = 18000


def when(days=1, hour=6):
    base = datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0)
    return (base + timedelta(days=days)).isoformat()


async def setup(client):
    f = await fleet(client)
    c = await add_client(client, f.owner, billing_method="per_tonne", rate_cents=300000)
    r = await add_route(client, f.owner, c["id"])
    return f, c, r


async def make_quote(client, f, c, r, **extra):
    body = {"client_id": c["id"], "route_id": r["id"], "cargo_description": "Cement, 28 t", "weight_tonnes": "28", "trips": 1, "fuel_price_cents": FUEL, **extra}
    res = await client.post("/quotes", headers=bearer(f.owner), json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def accept(client, f, quote):
    res = await client.post(f"/quotes/{quote['id']}/accept", headers=bearer(f.owner))
    assert res.status_code == 200, res.text
    return res.json()


async def dispatch(client, f, job, vehicle=None, **extra):
    body = {"vehicle_id": (vehicle or f.vehicle)["id"], "scheduled_for": when(), **extra}
    return await client.post(f"/jobs/{job['id']}/dispatch", headers=bearer(f.owner), json=body)


# ---- quotes ---------------------------------------------------------------------------------------


async def test_a_quote_prices_from_the_clients_method_and_shows_the_expected_profit(client):
    f, c, r = await setup(client)
    q = await make_quote(client, f, c, r)
    # 480 km out loaded at 4.5 km/l and back empty at 6 km/l, fuel at KES 180, plus tolls, crew and other costs.
    assert q["number"] == "Q-0001" and q["billing_method"] == "per_tonne" and q["price_cents"] == 300000 * 28
    assert q["fuel_litres"] == 186.67 and q["fuel_cents"] == 3360000 and q["cost_per_trip_cents"] == 3360000 + 600000 + 700000 + 200000
    assert q["expected_profit_cents"] == 8400000 - 4860000 and q["margin_pct"] == 42.1
    assert q["status"] == "draft" and q["valid_until"]


async def test_each_billing_method_prices_differently_and_a_monthly_contract_is_the_fee(client):
    f, c, r = await setup(client)
    trip = await make_quote(client, f, c, r, billing_method="per_trip", rate_cents=9000000, trips=2)
    km = await make_quote(client, f, c, r, billing_method="per_km", rate_cents=20000, trips=2)
    month = await make_quote(client, f, c, r, billing_method="monthly_contract", rate_cents=50000000, trips=20)
    assert trip["price_cents"] == 18000000 and km["price_cents"] == 20000 * 480 * 2 and month["price_cents"] == 50000000
    assert month["total_cost_cents"] == 4860000 * 20


async def test_a_loss_making_quote_shows_a_negative_profit(client):
    f, c, r = await setup(client)
    q = await make_quote(client, f, c, r, billing_method="per_trip", rate_cents=1000000)
    assert q["expected_profit_cents"] < 0 and q["margin_pct"] < 0


async def test_the_quote_needs_a_rate_a_distance_and_a_fuel_price(client):
    f, c, r = await setup(client)
    free = await add_client(client, f.owner, name="No Rate", rate_cents=0)
    cases = [
        ({"client_id": free["id"], "distance_km": 480, "fuel_price_cents": FUEL}, "rate_required"),
        ({"client_id": c["id"], "fuel_price_cents": FUEL}, "distance_required"),
        ({"client_id": c["id"], "route_id": r["id"]}, "fuel_price_required"),
    ]
    for body, code in cases:
        res = await client.post("/quotes", headers=bearer(f.owner), json=body)
        assert res.status_code == 422 and res.json()["detail"]["code"] == code, res.text


async def test_the_pump_price_defaults_to_what_the_fleet_has_been_paying(client):
    f, c, r = await setup(client)
    await client.post("/fuel", headers=bearer(f.driver), json={"vehicle_id": f.vehicle["id"], "litres": "100", "price_per_litre_cents": 19000, "amount_cents": 1900000})
    q = await client.post("/quotes", headers=bearer(f.owner), json={"client_id": c["id"], "route_id": r["id"]})
    assert q.status_code == 201 and q.json()["fuel_price_cents"] == 19000
    defaults = (await client.get(f"/quotes/defaults?client_id={c['id']}&route_id={r['id']}", headers=bearer(f.owner))).json()
    assert defaults["fuel_price_cents"] == 19000 and defaults["distance_km"] == 480 and defaults["billing_method"] == "per_tonne"


async def test_sending_a_quote_by_email_whatsapp_and_sms_never_shows_our_costs(client):
    f, c, r = await setup(client)
    q = await make_quote(client, f, c, r)
    for channel in ("email", "whatsapp"):
        fake_sender(channel).outbox.clear()
    sent = await client.post(f"/quotes/{q['id']}/send", headers=bearer(f.owner), json={"channel": "email"})
    assert sent.status_code == 200 and sent.json()["status"] == "sent" and sent.json()["sent_to"] == "jane@bamburi.example"
    [mail] = fake_sender("email").outbox
    assert mail["pdf"].startswith(b"%PDF") and mail["filename"] == "quote-Q-0001.pdf"
    assert b"profit" not in mail["pdf"].lower()
    wa = await client.post(f"/quotes/{q['id']}/send", headers=bearer(f.owner), json={"channel": "whatsapp"})
    assert wa.status_code == 200 and fake_sender("whatsapp").outbox[0]["recipient"] == "+254712000111"
    await client.post(f"/quotes/{q['id']}/send", headers=bearer(f.owner), json={"channel": "sms"})
    text = next(m for p, m in get_sms_sender().outbox if "Q-0001" in m)
    assert "KES 84,000.00" in text and "profit" not in text.lower()
    fake_sender("email").fail_with = "Email was not accepted: OSError"
    failed = await client.post(f"/quotes/{q['id']}/send", headers=bearer(f.owner), json={"channel": "email"})
    fake_sender("email").fail_with = None
    assert failed.status_code == 502
    nobody = await add_client(client, f.owner, name="No Contacts", phone=None, email=None)
    q2 = await make_quote(client, f, nobody, await add_route(client, f.owner, nobody["id"]))
    assert (await client.post(f"/quotes/{q2['id']}/send", headers=bearer(f.owner), json={"channel": "sms"})).json()["detail"]["code"] == "no_recipient"


async def test_a_declined_or_expired_quote_cannot_be_accepted_and_numbers_count_up(client):
    f, c, r = await setup(client)
    q1, q2 = await make_quote(client, f, c, r), await make_quote(client, f, c, r)
    assert (q1["number"], q2["number"]) == ("Q-0001", "Q-0002")
    declined = await client.post(f"/quotes/{q1['id']}/decline", headers=bearer(f.owner), json={"note": "Went elsewhere"})
    assert declined.json()["status"] == "declined"
    assert (await client.post(f"/quotes/{q1['id']}/accept", headers=bearer(f.owner))).status_code == 409
    old = await make_quote(client, f, c, r, valid_days=1)
    from sqlalchemy import text

    from app.db import get_engine

    async with get_engine().begin() as conn:
        await conn.execute(text("UPDATE quotes SET valid_until = current_date - 3 WHERE number = :n"), {"n": old["number"]})
    assert (await client.get(f"/quotes/{old['id']}", headers=bearer(f.owner))).json()["expired"] is True
    res = await client.post(f"/quotes/{old['id']}/accept", headers=bearer(f.owner))
    assert res.status_code == 409 and res.json()["detail"]["code"] == "expired"


async def test_editing_a_quote_reprices_it_and_a_closed_one_cannot_be_edited(client):
    f, c, r = await setup(client)
    q = await make_quote(client, f, c, r)
    body = {"client_id": c["id"], "route_id": r["id"], "weight_tonnes": "30", "fuel_price_cents": FUEL}
    changed = (await client.put(f"/quotes/{q['id']}", headers=bearer(f.owner), json=body)).json()
    assert changed["price_cents"] == 300000 * 30 and changed["status"] == "draft"
    await accept(client, f, q)
    assert (await client.put(f"/quotes/{q['id']}", headers=bearer(f.owner), json=body)).status_code == 409


# ---- jobs and dispatch ------------------------------------------------------------------------------


async def test_a_quote_is_accepted_becomes_a_job_and_is_dispatched_to_the_driver(client):
    f, c, r = await setup(client)
    q = await make_quote(client, f, c, r, instructions="Call the gate 30 minutes before arrival", pickup_at=when(1, 5), deliver_by=when(1, 20))
    assert q["expected_profit_cents"] > 0
    got = await accept(client, f, q)
    job = got["job"]
    assert got["quote"]["status"] == "accepted" and got["quote"]["job_number"] == "J-0001"
    assert job["number"] == "J-0001" and job["status"] == "planned" and job["price_cents"] == 8400000 and job["expected_profit_cents"] == q["expected_profit_cents"]
    assert (await client.post(f"/quotes/{q['id']}/accept", headers=bearer(f.owner))).status_code == 409  # one job per quote
    res = await dispatch(client, f, job)
    assert res.status_code == 201, res.text
    done = res.json()
    assert done["status"] == "dispatched" and done["trips_dispatched"] == 1 and done["trips"][0]["registration"] == "KCA 123A"
    mine = (await client.get("/me/trips", headers=bearer(f.driver))).json()
    assert len(mine) == 1 and mine[0]["origin"] == "Mombasa" and mine[0]["destination"] == "Nairobi"
    assert mine[0]["job"]["number"] == "J-0001" and mine[0]["job"]["client_name"] == "Bamburi Cement"
    assert mine[0]["job"]["instructions"] == "Call the gate 30 minutes before arrival"
    sms = [m for p, m in get_sms_sender().outbox if "J-0001" in m]
    assert len(sms) == 1 and "Mombasa to Nairobi" in sms[0]


async def test_a_lorry_in_the_workshop_cannot_be_dispatched_or_double_booked(client):
    f, c, r = await setup(client)
    job = (await accept(client, f, await make_quote(client, f, c, r, trips=3)))["job"]
    wo = (await client.post("/work-orders", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "title": "Gearbox overhaul"})).json()
    assert (await dispatch(client, f, job)).status_code == 201  # an order not yet started does not block
    await client.put(f"/work-orders/{wo['id']}", headers=bearer(f.owner), json={"status": "in_progress"})
    res = await dispatch(client, f, job, scheduled_for=when(5))
    assert res.status_code == 409 and res.json()["detail"]["code"] == "in_workshop"
    # Manual trips cannot sneak a lorry out of the workshop either.
    manual = await client.post("/trips", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "scheduled_for": when(7)})
    assert manual.status_code == 409 and manual.json()["detail"]["code"] == "in_workshop"
    await client.post(f"/work-orders/{wo['id']}/complete", headers=bearer(f.owner), json={})
    assert (await dispatch(client, f, job, scheduled_for=when(5))).status_code == 201


async def test_a_vehicle_or_crew_already_booked_for_that_time_is_refused(client):
    f, c, r = await setup(client)
    job = (await accept(client, f, await make_quote(client, f, c, r, trips=3)))["job"]
    assert (await dispatch(client, f, job)).status_code == 201
    clash = await dispatch(client, f, job, scheduled_for=when(1, 10))  # inside the first trip's 14 hours
    assert clash.status_code == 409 and clash.json()["detail"]["code"] == "vehicle_booked"
    other = await add_vehicle(client, f.owner, "KDD 456B")
    same_driver = await dispatch(client, f, job, vehicle=other, scheduled_for=when(1, 10), driver_membership_id=f.ids["+254712345678"])
    assert same_driver.status_code == 409 and same_driver.json()["detail"]["code"] == "crew_booked"
    assert (await dispatch(client, f, job, scheduled_for=when(3))).status_code == 201  # a free day is fine


async def test_a_multi_trip_job_moves_through_its_statuses_as_trips_are_dispatched_and_done(client):
    f, c, r = await setup(client)
    job = (await accept(client, f, await make_quote(client, f, c, r, weight_tonnes="120", trips=2)))["job"]
    one = (await dispatch(client, f, job)).json()
    assert one["trips_planned"] == 2 and one["trips_dispatched"] == 1 and one["status"] == "dispatched"
    two = (await dispatch(client, f, job, scheduled_for=when(3))).json()
    assert two["trips_dispatched"] == 2
    full = await dispatch(client, f, job, scheduled_for=when(5))
    assert full.status_code == 409 and full.json()["detail"]["code"] == "fully_dispatched"
    # Cancelling a trip puts the job back to needing a lorry.
    first_trip = one["trips"][0]["id"]
    await client.post(f"/trips/{first_trip}/cancel", headers=bearer(f.owner))
    after = (await client.get(f"/jobs/{job['id']}", headers=bearer(f.owner))).json()
    assert after["trips_dispatched"] == 1 and after["status"] == "dispatched"
    assert (await dispatch(client, f, job, scheduled_for=when(1))).status_code == 201


async def test_a_job_follows_its_trips_through_to_completion(client):
    from tests.shots import inspect, photo_id

    f, c, r = await setup(client)
    job = (await accept(client, f, await make_quote(client, f, c, r)))["job"]
    trip_id = (await dispatch(client, f, job, scheduled_for=datetime.now(UTC).isoformat())).json()["trips"][0]["id"]
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    start = await client.post(f"/trips/{trip_id}/start", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125100})
    assert start.status_code == 200, start.text
    assert (await client.get(f"/jobs/{job['id']}", headers=bearer(f.owner))).json()["status"] == "in_progress"
    end = await client.post(f"/trips/{trip_id}/end", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125580})
    assert end.status_code == 200, end.text
    done = (await client.get(f"/jobs/{job['id']}", headers=bearer(f.owner))).json()
    assert done["status"] == "completed" and done["trips_completed"] == 1 and done["completed_at"]


async def test_a_repeat_job_reuses_the_clients_saved_route(client):
    f, c, r = await setup(client)
    first = (await accept(client, f, await make_quote(client, f, c, r, instructions="Gate B")))["job"]
    again = await client.post(f"/jobs/{first['id']}/repeat", headers=bearer(f.owner), json={"pickup_at": when(7, 6), "deliver_by": when(7, 20)})
    assert again.status_code == 201, again.text
    job = again.json()
    assert job["number"] == "J-0002" and job["repeat_of_id"] == first["id"] and job["route_id"] == r["id"]
    assert job["route"]["pickup"] == "Mombasa" and job["instructions"] == "Gate B" and job["price_cents"] == first["price_cents"]
    assert job["status"] == "planned" and job["trips_dispatched"] == 0
    assert (await dispatch(client, f, job, scheduled_for=when(7))).json()["trips"][0]["id"]


async def test_a_job_can_be_set_up_without_a_quote_and_cancelled_before_it_runs(client):
    f, c, r = await setup(client)
    res = await client.post("/jobs", headers=bearer(f.owner), json={"client_id": c["id"], "route_id": r["id"], "cargo_description": "Sugar", "weight_tonnes": "20", "trips": 1})
    assert res.status_code == 201, res.text
    job = res.json()
    assert job["quote_id"] is None and job["price_cents"] == 300000 * 20 and job["billing_method"] == "per_tonne"
    await dispatch(client, f, job)
    cancelled = (await client.post(f"/jobs/{job['id']}/cancel", headers=bearer(f.owner))).json()
    assert cancelled["status"] == "cancelled"
    assert (await client.get("/me/trips", headers=bearer(f.driver))).json() == []  # the lorry and the driver are free again
    assert (await dispatch(client, f, job)).status_code == 409


# ---- calendar -----------------------------------------------------------------------------------------


async def test_the_calendar_shows_free_booked_and_in_service_for_lorries_and_crew(client):
    f, c, r = await setup(client)
    other = await add_vehicle(client, f.owner, "KDD 456B")
    spare = await add_vehicle(client, f.owner, "KEE 789C")
    job = (await accept(client, f, await make_quote(client, f, c, r)))["job"]
    await dispatch(client, f, job)
    wo = (await client.post("/work-orders", headers=bearer(f.owner), json={"vehicle_id": other["id"], "title": "Brakes"})).json()
    await client.put(f"/work-orders/{wo['id']}", headers=bearer(f.owner), json={"status": "in_progress"})
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).astimezone().date()
    cal = (await client.get(f"/dispatch/calendar?from={datetime.now(UTC).date()}&to={(datetime.now(UTC) + timedelta(days=3)).date()}", headers=bearer(f.owner))).json()
    by_plate = {v["registration"]: v for v in cal["vehicles"]}
    assert by_plate["KCA 123A"]["bookings"][0]["job_number"] == "J-0001" and by_plate["KCA 123A"]["bookings"][0]["client_name"] == "Bamburi Cement"
    assert "booked" in {d["status"] for d in by_plate["KCA 123A"]["days"]}
    assert by_plate["KDD 456B"]["in_service"] is True and by_plate["KDD 456B"]["service"]["title"] == "Brakes"
    assert {d["status"] for d in by_plate["KDD 456B"]["days"]} == {"in_service"}
    assert {d["status"] for d in by_plate[spare["registration"]]["days"]} == {"free"}
    crew = {p["name"]: p for p in cal["crew"]}
    assert crew["driver user"]["bookings"] and tomorrow
    assert (await client.get("/dispatch/calendar?from=2026-01-01&to=2026-06-01", headers=bearer(f.owner))).status_code == 422


async def test_availability_lists_who_is_free_for_a_window(client):
    f, c, r = await setup(client)
    other = await add_vehicle(client, f.owner, "KDD 456B")
    job = (await accept(client, f, await make_quote(client, f, c, r)))["job"]
    await dispatch(client, f, job)
    free = (await client.get("/dispatch/available", headers=bearer(f.owner), params={"start": when(), "hours": 6})).json()
    states = {v["registration"]: (v["free"], v["reason"]) for v in free["vehicles"]}
    assert states == {"KCA 123A": (False, "booked"), "KDD 456B": (True, None)} and other
    people = {p["name"]: p["reason"] for p in free["crew"]}
    assert people["driver user"] == "booked" and people["turnboy user"] == "booked"
    later = (await client.get("/dispatch/available", headers=bearer(f.owner), params={"start": when(4), "hours": 6})).json()
    assert all(v["free"] for v in later["vehicles"])


# ---- who sees what ----------------------------------------------------------------------------------


async def test_supervisors_see_jobs_without_prices_and_drivers_and_other_businesses_see_none(client):
    f, c, r = await setup(client)
    job = (await accept(client, f, await make_quote(client, f, c, r)))["job"]
    sup, _ = await staff_session(client, f.owner, "supervisor", "sup@example.com")
    seen = (await client.get("/jobs", headers=bearer(sup))).json()[0]
    assert seen["number"] == "J-0001" and "price_cents" not in seen and "expected_profit_cents" not in seen
    assert (await client.get("/quotes", headers=bearer(sup))).status_code == 403
    assert (await client.post(f"/jobs/{job['id']}/dispatch", headers=bearer(sup), json={"vehicle_id": f.vehicle["id"], "scheduled_for": when()})).status_code == 403
    assert (await client.get("/jobs", headers=bearer(f.driver))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/jobs", headers=bearer(other))).json() == []
    assert (await client.get(f"/jobs/{job['id']}", headers=bearer(other))).status_code == 404
    assert (await client.get("/quotes", headers=bearer(other))).json() == []
    mgr, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.get("/jobs", headers=bearer(mgr))).json()[0]["price_cents"] == 8400000
