"""What a trip earned when there is no invoice: the amount received, and the client and price a driver who is the owner gives up front."""

from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import month_start, seed_trip
from tests.shots import begin_trip, fleet, make_trip

RECEIVED = {"amount_cents": 5_000_000, "note": "M-Pesa from the buyer"}


async def profit(client, who):
    month = month_start(0).isoformat()
    res = await client.get(f"/profit?from_month={month}&to_month={month}&include_trips=true", headers=bearer(who))
    assert res.status_code == 200, res.text
    return res.json()


async def deliver(client, f):
    trip = await begin_trip(client, f)
    assert (await client.post(f"/trips/{trip['id']}/deliver", headers=bearer(f.driver))).status_code == 200
    return trip


async def test_a_trip_with_no_invoice_earns_what_was_recorded_as_received(client):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KCA 123A")
    trip_id = await seed_trip(vehicle["id"], invoice=False)
    before = await profit(client, owner)
    assert before["business"]["revenue"] == 0 and before["business"]["unbilled"] == 1
    res = await client.put(f"/trips/{trip_id}/received", headers=bearer(owner), json=RECEIVED)
    assert res.status_code == 200, res.text
    assert res.json()["received_cents"] == 5_000_000 and res.json()["received_note"] == "M-Pesa from the buyer"
    after = await profit(client, owner)
    assert after["business"]["revenue"] == 5_000_000 and after["business"]["unbilled"] == 0
    assert next(t for t in after["trips"] if t["trip_id"] == str(trip_id))["revenue_cents"] == 5_000_000


async def test_an_invoice_takes_the_place_of_a_recorded_amount(client):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KCA 123A")
    trip_id = await seed_trip(vehicle["id"], revenue_cents=8_000_000)
    assert (await client.put(f"/trips/{trip_id}/received", headers=bearer(owner), json=RECEIVED)).status_code == 200
    assert (await profit(client, owner))["business"]["revenue"] == 8_000_000  # counted once, as the invoice


async def test_a_trip_can_only_be_marked_received_once_it_is_delivered(client):
    f = await fleet(client)
    trip = await make_trip(client, f)
    res = await client.put(f"/trips/{trip['id']}/received", headers=bearer(f.owner), json=RECEIVED)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "not_delivered"
    assert (await client.put(f"/trips/{trip['id']}/received", headers=bearer(f.owner), json={"amount_cents": -1})).status_code == 422


async def test_a_hired_driver_cannot_record_or_see_what_a_trip_was_paid(client):
    f = await fleet(client)
    trip = await deliver(client, f)
    res = await client.put(f"/trips/{trip['id']}/received", headers=bearer(f.driver), json=RECEIVED)
    assert res.status_code == 403
    assert (await client.put(f"/trips/{trip['id']}/received", headers=bearer(f.owner), json=RECEIVED)).status_code == 200
    mine = (await client.get("/me/trips", headers=bearer(f.driver))).json()
    assert mine and all("received_cents" not in t for t in mine)
    assert "received_cents" not in (await client.get(f"/trips/{trip['id']}", headers=bearer(f.driver))).json()
    assert (await client.get(f"/trips/{trip['id']}", headers=bearer(f.owner))).json()["received_cents"] == 5_000_000
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.put(f"/trips/{trip['id']}/received", headers=bearer(manager), json={"amount_cents": 4_000_000})).status_code == 200


async def test_an_owner_who_drives_says_who_pays_and_what_when_making_the_trip(client):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KCA 123A")
    assert (await client.post("/onboarding/drive-myself", headers=bearer(owner), json={"vehicle_id": vehicle["id"]})).status_code == 200
    body = {"origin": "Mombasa", "destination": "Nairobi", "client_name": "Bamburi Cement", "price_cents": 1_200_000}
    res = await client.post("/me/trips", headers=bearer(owner), json=body)
    assert res.status_code == 201, res.text
    trip = res.json()
    assert trip["job"]["client_name"] == "Bamburi Cement" and trip["job"]["billing_method"] == "per_trip"
    job = (await client.get(f"/jobs/{trip['job']['id']}", headers=bearer(owner))).json()
    assert job["price_cents"] == 1_200_000 and job["rate_cents"] == 1_200_000 and job["trips_planned"] == 1
    assert [c["name"] for c in (await client.get("/clients", headers=bearer(owner))).json()] == ["Bamburi Cement"]


async def test_a_hired_driver_cannot_name_a_price_and_a_client_needs_its_price(client):
    f = await fleet(client)
    named = {"origin": "Mombasa", "destination": "Nairobi", "client_name": "Bamburi Cement", "price_cents": 1_200_000}
    res = await client.post("/me/trips", headers=bearer(f.driver), json=named)
    assert res.status_code == 403
    assert (await client.get("/clients", headers=bearer(f.owner))).json() == []  # nothing was made on the way
    half = await client.post("/me/trips", headers=bearer(f.driver), json={"origin": "Mombasa", "destination": "Nairobi", "client_name": "Bamburi Cement"})
    assert half.status_code == 422 and half.json()["detail"]["code"] == "client_and_price"
