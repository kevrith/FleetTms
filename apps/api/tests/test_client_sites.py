"""Where a client takes deliveries: sites the office adds, sites a driver saves from a delivery, choosing the client for a trip, and what a
confirmed site does that an unconfirmed one does not."""

import uuid

from tests.helpers import bearer
from tests.shots import begin_trip, fleet, inspect, start
from tests.test_clients import add_client, add_route
from tests.test_pod_billing import deliver, job_for, running, setup

NAIROBI = {"lat": -1.2921, "lng": 36.8219}
MOMBASA = {"lat": -4.0435, "lng": 39.6682}


async def add_site(client, who, client_id, **extra):
    body = {"name": "Industrial Area yard", "address": "Enterprise Road", **NAIROBI, "radius_m": 400, **extra}
    return await client.post(f"/clients/{client_id}/sites", headers=bearer(who), json=body)


async def deliver_saving(client, f, trip_id, name="Main yard", at=None, **extra):
    """A delivery with proof, where the driver also says 'save this place for next time'."""
    from tests.test_pod_billing import pod_body

    pod = await pod_body(client, f, **(at or {}))
    return await client.post(f"/trips/{trip_id}/deliver", headers=bearer(f.driver), json={"pod": pod, "save_site": {"name": name, **extra}})


# ---- the office keeps a client's places ---------------------------------------------------------------


async def test_the_office_adds_edits_and_lists_a_clients_places(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    res = await add_site(client, f.owner, c["id"])
    assert res.status_code == 201, res.text
    site = res.json()
    assert site["status"] == "confirmed" and site["radius_m"] == 400 and site["address"] == "Enterprise Road"
    assert (await add_site(client, f.owner, c["id"])).status_code == 409  # one name per client
    changed = await client.put(f"/sites/{site['id']}", headers=bearer(f.owner), json={"name": "Yard A", **MOMBASA, "radius_m": 250})
    assert changed.status_code == 200 and changed.json()["name"] == "Yard A" and changed.json()["lat"] == MOMBASA["lat"]
    detail = (await client.get(f"/clients/{c['id']}", headers=bearer(f.owner))).json()
    assert [s["name"] for s in detail["site_list"]] == ["Yard A"] and detail["sites"] == 1 and detail["unconfirmed_sites"] == 0
    assert (await client.get("/clients", headers=bearer(f.owner))).json()[0]["sites"] == 1


async def test_a_driver_cannot_add_or_confirm_a_place_by_hand(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    assert (await add_site(client, f.driver, c["id"])).status_code == 403
    site = (await add_site(client, f.owner, c["id"])).json()
    assert (await client.put(f"/sites/{site['id']}", headers=bearer(f.driver), json={"name": "Mine", **NAIROBI})).status_code == 403
    assert (await client.post(f"/sites/{site['id']}/confirm", headers=bearer(f.driver))).status_code == 403


async def test_a_driver_sees_the_clients_and_their_places_but_no_money(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    await add_site(client, f.owner, c["id"])
    rows = (await client.get("/me/clients", headers=bearer(f.driver))).json()
    assert [r["name"] for r in rows] == ["Bamburi Cement"] and rows[0]["has_phone"] is True
    assert [s["name"] for s in rows[0]["sites"]] == ["Industrial Area yard"]
    assert not {"rate_cents", "kra_pin", "billing_method", "phone", "email"} & set(rows[0])
    assert (await client.get("/clients", headers=bearer(f.driver))).status_code == 403


# ---- choosing the client for a trip -------------------------------------------------------------------


async def test_a_driver_picks_the_client_and_place_when_making_a_trip(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    site = (await add_site(client, f.owner, c["id"])).json()
    res = await client.post("/me/trips", headers=bearer(f.driver), json={"origin": "Mombasa", "destination": "Nairobi", "client_id": c["id"], "site_id": site["id"]})
    assert res.status_code == 201, res.text
    trip = res.json()
    assert trip["client"]["name"] == "Bamburi Cement" and trip["job"] is None
    assert trip["site"]["id"] == site["id"] and trip["site"]["lat"] == NAIROBI["lat"] and trip["site"]["status"] == "confirmed"


async def test_a_place_must_belong_to_the_client_picked(client):
    f = await fleet(client)
    a = await add_client(client, f.owner)
    b = await add_client(client, f.owner, name="Savannah Cement")
    other = (await add_site(client, f.owner, b["id"])).json()
    body = {"origin": "Mombasa", "destination": "Nairobi"}
    wrong = await client.post("/me/trips", headers=bearer(f.driver), json={**body, "client_id": a["id"], "site_id": other["id"]})
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "wrong_site"
    alone = await client.post("/me/trips", headers=bearer(f.driver), json={**body, "site_id": other["id"]})
    assert alone.status_code == 422
    missing = await client.post("/me/trips", headers=bearer(f.driver), json={**body, "client_id": str(uuid.uuid4())})
    assert missing.status_code == 404
    two = await client.post("/me/trips", headers=bearer(f.driver), json={**body, "client_id": a["id"], "new_client_name": "Someone"})
    assert two.status_code == 422 and two.json()["detail"]["code"] == "one_client"


async def test_a_client_a_driver_adds_waits_for_the_office_and_is_not_made_twice(client):
    f = await fleet(client)
    body = {"origin": "Mombasa", "destination": "Nairobi", "new_client_name": "Kiambu Hardware"}
    first = await client.post("/me/trips", headers=bearer(f.driver), json=body)
    assert first.status_code == 201, first.text
    assert first.json()["client"]["name"] == "Kiambu Hardware"
    rows = (await client.get("/clients", headers=bearer(f.owner))).json()
    assert [(r["name"], r["needs_review"]) for r in rows] == [("Kiambu Hardware", True)]
    alerts = (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"]
    assert any(a["kind"] == "clients_to_check" for a in alerts)
    cid = rows[0]["id"]
    edited = await client.put(f"/clients/{cid}", headers=bearer(f.owner), json={"name": "Kiambu Hardware Ltd", "phone": "0712000999"})
    assert edited.json()["needs_review"] is False
    assert not any(a["kind"] == "clients_to_check" for a in (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"])


async def test_a_driver_still_cannot_name_a_price_and_the_price_needs_a_client(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    priced = await client.post("/me/trips", headers=bearer(f.driver), json={"origin": "Mombasa", "destination": "Nairobi", "client_id": c["id"], "price_cents": 1_000_000})
    assert priced.status_code == 403
    alone = await client.post("/me/trips", headers=bearer(f.owner), json={"origin": "Mombasa", "destination": "Nairobi", "price_cents": 1_000_000})
    assert alone.status_code in (403, 422)


async def test_an_owner_who_drives_prices_a_trip_for_a_picked_client(client):
    from tests.fleet import add_vehicle
    from tests.helpers import owner_session

    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KCA 123A")
    assert (await client.post("/onboarding/drive-myself", headers=bearer(owner), json={"vehicle_id": vehicle["id"]})).status_code == 200
    c = await add_client(client, owner)
    res = await client.post("/me/trips", headers=bearer(owner), json={"origin": "Mombasa", "destination": "Nairobi", "client_id": c["id"], "price_cents": 1_200_000})
    assert res.status_code == 201, res.text
    assert res.json()["job"]["client_name"] == "Bamburi Cement" and res.json()["client"]["id"] == c["id"]
    assert [x["name"] for x in (await client.get("/clients", headers=bearer(owner))).json()] == ["Bamburi Cement"]


async def test_a_trip_for_a_job_takes_the_jobs_client(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    trip = (await client.get(f"/trips/{trip_id}", headers=bearer(f.owner))).json()
    assert trip["client"]["id"] == c["id"]
    assert trip["site"]["lat"] == NAIROBI["lat"] and trip["site"]["id"] is None  # the route's own coordinates, until a site is chosen


# ---- saving the place at delivery ---------------------------------------------------------------------


async def test_a_driver_saves_the_place_at_delivery_and_it_waits_for_the_office(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    trip = await begin_trip(client, f, client_id=c["id"])
    assert trip["site"] is None and trip["client"]["id"] == c["id"]
    res = await deliver_saving(client, f, trip["id"], name="Ruiru depot", address="Thika Road")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "delivered" and body["site"]["name"] == "Ruiru depot" and body["site"]["status"] == "unconfirmed"
    detail = (await client.get(f"/clients/{c['id']}", headers=bearer(f.owner))).json()
    site = detail["site_list"][0]
    assert site["status"] == "unconfirmed" and site["verified_by_code"] is False and site["address"] == "Thika Road"
    assert (site["lat"], site["lng"]) == (-1.2925, 36.8223)  # where the proof of delivery was taken
    assert detail["unconfirmed_sites"] == 1
    assert any(a["kind"] == "sites_unconfirmed" for a in (await client.get("/dashboard", headers=bearer(f.owner))).json()["alerts"])


async def test_a_saved_place_guides_the_next_trip_and_is_not_held_against_anyone_until_confirmed(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    first = await begin_trip(client, f, client_id=c["id"])
    assert (await deliver_saving(client, f, first["id"])).status_code == 200
    site = (await client.get(f"/clients/{c['id']}", headers=bearer(f.owner))).json()["site_list"][0]
    assert (await client.post(f"/trips/{first['id']}/end", headers=bearer(f.driver), json={"photo_id": await _photo(client, f), "value": 125300})).status_code == 200
    # the next trip for the client, picked by the driver with the saved place
    nxt = await client.post("/me/trips", headers=bearer(f.driver), json={"origin": "Mombasa", "destination": "Ruiru", "client_id": c["id"], "site_id": site["id"]})
    assert nxt.status_code == 201, nxt.text
    assert nxt.json()["site"]["id"] == site["id"] and nxt.json()["site"]["status"] == "unconfirmed"
    trip_id = nxt.json()["id"]
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    assert (await start(client, f.driver, trip_id, value=125300)).status_code == 200
    far = await client.post(f"/trips/{trip_id}/deliver", headers=bearer(f.driver), json={"pod": await _pod(client, f, **MOMBASA)})
    assert far.status_code == 200 and far.json()["pod"]["flags"] == []  # unconfirmed: guidance only
    # once the office confirms the place, a delivery away from it is flagged
    assert (await client.post(f"/sites/{site['id']}/confirm", headers=bearer(f.owner))).json()["status"] == "confirmed"
    assert (await client.post(f"/trips/{trip_id}/end", headers=bearer(f.driver), json={"photo_id": await _photo(client, f), "value": 125400})).status_code == 200
    again = await client.post("/me/trips", headers=bearer(f.driver), json={"origin": "Mombasa", "destination": "Ruiru", "client_id": c["id"], "site_id": site["id"]})
    third = again.json()["id"]
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    assert (await start(client, f.driver, third, value=125400)).status_code == 200
    flagged = await client.post(f"/trips/{third}/deliver", headers=bearer(f.driver), json={"pod": await _pod(client, f, **MOMBASA)})
    assert flagged.status_code == 200 and "outside_site" in flagged.json()["pod"]["flags"]


async def test_a_place_already_saved_is_reused_not_doubled(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    await add_site(client, f.owner, c["id"], name="Industrial Area yard", radius_m=400)
    trip = await begin_trip(client, f, client_id=c["id"])
    res = await deliver_saving(client, f, trip["id"], name="The warehouse", at=NAIROBI)
    assert res.status_code == 200, res.text
    sites = (await client.get(f"/clients/{c['id']}", headers=bearer(f.owner))).json()["site_list"]
    assert [s["name"] for s in sites] == ["Industrial Area yard"]  # it was within that place's radius
    assert res.json()["site"]["id"] == sites[0]["id"]


async def test_nothing_is_saved_without_a_client_or_a_location_or_when_the_route_knows_the_place(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    nobody = await begin_trip(client, f)  # no client on the trip
    res = await deliver_saving(client, f, nobody["id"])
    assert res.status_code == 200 and res.json()["site"] is None
    assert (await client.get(f"/clients/{c['id']}", headers=bearer(f.owner))).json()["site_list"] == []


async def test_a_place_saved_from_a_code_confirmed_delivery_says_so(client):
    f, c, _r = await setup(client)
    # a route with no coordinates: the first delivery shows where the client really is
    bare = await add_route(client, f.owner, c["id"], name="Mombasa to Thika", dropoff="Thika")
    assert bare["site_id"] is None and bare["dropoff_lat"] is None
    trip_id = await running(client, f, await job_for(client, f, c, bare))
    assert (await client.post(f"/trips/{trip_id}/pod/code", headers=bearer(f.driver))).status_code == 200
    from tests.test_pod_billing import last_code, pod_body

    pod = {**await pod_body(client, f), "method": "code", "code": last_code(), "signature": None}
    res = await client.post(f"/trips/{trip_id}/deliver", headers=bearer(f.driver), json={"pod": pod, "save_site": {"name": "Thika store"}})
    assert res.status_code == 200, res.text
    site = (await client.get(f"/clients/{c['id']}", headers=bearer(f.owner))).json()["site_list"][0]
    assert site["name"] == "Thika store" and site["verified_by_code"] is True and site["status"] == "unconfirmed"
    route = next(x for x in (await client.get(f"/clients/{c['id']}", headers=bearer(f.owner))).json()["route_list"] if x["name"] == "Mombasa to Thika")
    assert route["site_id"] == site["id"]  # the next job on this route is guided there too


async def test_a_route_with_a_site_uses_the_site_over_its_own_coordinates(client):
    f, c, r = await setup(client)  # the route's own drop-off is Nairobi, 500 m
    site = (await add_site(client, f.owner, c["id"], name="Mombasa yard", **MOMBASA, radius_m=300)).json()
    moved = await client.put(f"/routes/{r['id']}", headers=bearer(f.owner), json={**{k: r[k] for k in ("name", "pickup", "dropoff", "distance_km", "expected_hours", "tolls_cents", "crew_cents", "other_cents")}, "site_id": site["id"]})
    assert moved.status_code == 200 and moved.json()["site_id"] == site["id"]
    trip_id = await running(client, f, await job_for(client, f, c, moved.json()))
    res = await deliver(client, f, trip_id)  # the proof is taken in Nairobi, now away from the route's site
    assert res.status_code == 200 and "outside_site" in res.json()["pod"]["flags"]
    other = await add_client(client, f.owner, name="Savannah Cement")
    foreign = (await add_site(client, f.owner, other["id"])).json()
    bad = await client.put(f"/routes/{r['id']}", headers=bearer(f.owner), json={**{k: r[k] for k in ("name", "pickup", "dropoff", "distance_km")}, "site_id": foreign["id"]})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "wrong_site"


async def test_updating_a_route_without_a_site_keeps_the_site_it_has(client):
    f, c, r = await setup(client)
    site = (await add_site(client, f.owner, c["id"])).json()
    body = {k: r[k] for k in ("name", "pickup", "dropoff", "distance_km", "expected_hours", "tolls_cents", "crew_cents", "other_cents")}
    assert (await client.put(f"/routes/{r['id']}", headers=bearer(f.owner), json={**body, "site_id": site["id"]})).json()["site_id"] == site["id"]
    assert (await client.put(f"/routes/{r['id']}", headers=bearer(f.owner), json=body)).json()["site_id"] == site["id"]


async def test_the_place_is_saved_when_the_delivery_comes_from_the_phone_queue(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    trip = await begin_trip(client, f, client_id=c["id"])
    action = {"client_id": str(uuid.uuid4()), "type": "trip.deliver", "payload": {"trip_id": trip["id"], "save_site": {"name": "Gate B", **NAIROBI}}}
    from tests.shots import sync

    res = await sync(client, f.driver, [action])
    assert res.status_code == 200 and res.json()["results"][0]["status"] == "ok", res.text
    again = await sync(client, f.driver, [action])  # sent twice: nothing doubles
    assert again.json()["results"][0]["status"] == "duplicate"
    sites = (await client.get(f"/clients/{c['id']}", headers=bearer(f.owner))).json()["site_list"]
    assert [(s["name"], s["lat"]) for s in sites] == [("Gate B", NAIROBI["lat"])]
    mine = (await client.get("/me/trips", headers=bearer(f.driver))).json()
    assert mine[0]["site"]["name"] == "Gate B"


async def _photo(client, f):
    from tests.shots import photo_id

    return await photo_id(client, f.driver, "odometer")


async def _pod(client, f, **where):
    from tests.test_pod_billing import pod_body

    return await pod_body(client, f, **where)
