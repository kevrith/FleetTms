from tests.billing_helpers import subscription
from tests.fleet import add_vehicle
from tests.helpers import PASSWORD, bearer, driver_session, owner_session, staff_session
from tests.test_jobs import dispatch

FIRST = {"client_name": "Bamburi Cement", "pickup": "Mombasa", "dropoff": "Nairobi", "distance_km": 480, "rate_cents": 12_000_000}


async def test_a_new_owner_goes_from_signup_to_a_dispatched_first_job_in_a_handful_of_steps(client):
    """The acceptance flow, step by step: every call the guided screen makes. How long a person takes is not measured here."""
    owner, _ = await owner_session(client, "Kamau Haulage", "owner@example.com")  # 1 sign up
    start = (await client.get("/onboarding", headers=bearer(owner))).json()
    assert start["done"] == 0 and not start["dismissed"] and [i["key"] for i in start["items"] if not i["done"]][:3] == ["vehicles", "team", "clients"]
    vehicle = await add_vehicle(client, owner, "KCA 123A")  # 2 add a lorry
    await driver_session(client, owner, "0712345678")  # 3 invite the driver
    job = await client.post("/onboarding/first-job", headers=bearer(owner), json={**FIRST, "cargo_description": "Cement, 400 bags", "weight_tonnes": 28})  # 4 the first job
    assert job.status_code == 201, job.text
    made = job.json()
    assert made["job"]["number"] == "J-0001" and made["job"]["status"] == "planned" and made["job"]["price_cents"] > 0
    staff = (await client.get("/staff", headers=bearer(owner))).json()
    driver_id = next(s["membership_id"] for s in staff if s["phone"] == "+254712345678")
    await client.post(f"/vehicles/{vehicle['id']}/crew", headers=bearer(owner), json={"membership_id": driver_id, "role": "driver"})
    from types import SimpleNamespace

    f = SimpleNamespace(owner=owner, vehicle=vehicle)
    dispatched = await dispatch(client, f, made["job"])  # 5 dispatch it
    assert dispatched.status_code in (200, 201), dispatched.text
    after = {i["key"]: i["done"] for i in (await client.get("/onboarding", headers=bearer(owner))).json()["items"]}
    assert after["vehicles"] and after["team"] and after["clients"] and after["routes"] and after["job"]


async def test_the_first_job_finds_an_existing_client_and_route_instead_of_making_copies(client):
    owner, _ = await owner_session(client)
    a = (await client.post("/onboarding/first-job", headers=bearer(owner), json=FIRST)).json()
    b = (await client.post("/onboarding/first-job", headers=bearer(owner), json={**FIRST, "client_name": "  bamburi cement "})).json()
    assert a["client_id"] == b["client_id"] and a["route_id"] == b["route_id"] and a["job"]["id"] != b["job"]["id"]
    assert len((await client.get("/clients", headers=bearer(owner))).json()) == 1
    routes = (await client.get("/routes", headers=bearer(owner))).json()
    assert len(routes) == 1 and routes[0]["name"] == "Mombasa to Nairobi" and routes[0]["distance_km"] == 480


async def test_the_first_job_is_checked_and_belongs_to_the_owner(client):
    owner, _ = await owner_session(client)
    assert (await client.post("/onboarding/first-job", headers=bearer(owner), json={**FIRST, "distance_km": 0})).status_code == 422
    assert (await client.post("/onboarding/first-job", headers=bearer(owner), json={**FIRST, "client_name": "X"})).status_code == 422
    assert (await client.post("/onboarding/first-job", headers=bearer(owner), json={**FIRST, "billing_method": "free"})).status_code == 422
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.post("/onboarding/first-job", headers=bearer(manager), json=FIRST)).status_code == 403


async def test_sample_data_gives_something_to_click_around_in_and_does_not_count_as_set_up(client):
    owner, _ = await owner_session(client)
    res = await client.post("/onboarding/sample-data", headers=bearer(owner))
    assert res.status_code == 201, res.text
    ids = res.json()
    assert (await client.post("/onboarding/sample-data", headers=bearer(owner))).json()["detail"]["code"] == "already_there"
    vehicles = (await client.get("/vehicles", headers=bearer(owner))).json()
    assert [v["registration"] for v in vehicles] == ["DEMO 001A"]
    assert (await client.get(f"/jobs/{ids['job_id']}", headers=bearer(owner))).json()["cargo_description"] == "Cement (sample)"
    o = (await client.get("/onboarding", headers=bearer(owner))).json()
    assert o["has_sample_data"] is True and o["done"] == 0  # none of it counts: a sample lorry is not your lorry
    assert (await client.delete("/onboarding/sample-data", headers=bearer(owner))).status_code == 204
    assert (await client.get("/vehicles", headers=bearer(owner))).json() == [] and (await client.get("/clients", headers=bearer(owner))).json() == []
    assert (await client.get("/onboarding", headers=bearer(owner))).json()["has_sample_data"] is False
    assert "onboarding.sample_data_removed" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]


async def test_sample_data_that_has_been_used_is_kept_and_the_sample_lorry_is_billed_like_any_other(client):
    owner, _ = await owner_session(client)
    ids = (await client.post("/onboarding/sample-data", headers=bearer(owner))).json()
    s = await subscription(client, owner)
    assert [v["registration"] for v in s["vehicles"]] == ["DEMO 001A"]  # on the plan like any vehicle: remove it before the first invoice if it is not wanted
    driver = await driver_session(client, owner, "0712345678")
    staff = (await client.get("/staff", headers=bearer(owner))).json()
    driver_id = next(x["membership_id"] for x in staff if x["phone"] == "+254712345678")
    await client.post(f"/vehicles/{ids['vehicle_id']}/crew", headers=bearer(owner), json={"membership_id": driver_id, "role": "driver"})
    from types import SimpleNamespace

    job = (await client.get(f"/jobs/{ids['job_id']}", headers=bearer(owner))).json()
    done = await dispatch(client, SimpleNamespace(owner=owner, vehicle={"id": ids["vehicle_id"]}), job)
    assert done.status_code in (200, 201), done.text
    kept = await client.delete("/onboarding/sample-data", headers=bearer(owner))
    assert kept.status_code == 409 and kept.json()["detail"]["code"] == "sample_in_use"
    assert len((await client.get("/vehicles", headers=bearer(owner))).json()) == 1 and driver


async def test_only_the_owner_adds_or_removes_sample_data(client):
    owner, _ = await owner_session(client)
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.post("/onboarding/sample-data", headers=bearer(manager))).status_code == 403
    assert (await client.delete("/onboarding/sample-data", headers=bearer(manager))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    await client.post("/onboarding/sample-data", headers=bearer(other))
    assert (await client.get("/vehicles", headers=bearer(owner))).json() == []  # theirs is theirs


async def test_an_owner_who_drives_gets_the_driver_role_at_signup(client):
    res = await client.post(
        "/auth/signup",
        json={
            "business_name": "Solo Haulage", "name": "Solo Owner", "email": "solo@example.com", "password": PASSWORD,
            "accept_terms": True, "accept_privacy": True, "accept_dpa": True, "drives_vehicle": True,
        },
    )  # fmt: skip
    assert res.status_code == 201, res.text
    me = (await client.get("/auth/me", headers=bearer(res.json()))).json()
    assert set(me["roles"]) == {"owner", "driver"}
    plain = await client.post(
        "/auth/signup",
        json={
            "business_name": "Other Haulage", "name": "Other Owner", "email": "other@example.com", "password": PASSWORD,
            "accept_terms": True, "accept_privacy": True, "accept_dpa": True,
        },
    )  # fmt: skip
    assert (await client.get("/auth/me", headers=bearer(plain.json()))).json()["roles"] == ["owner"]


async def test_driving_it_myself_makes_the_owner_the_vehicles_driver_and_can_then_run_a_trip(client):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KCA 123A")
    res = await client.post("/onboarding/drive-myself", headers=bearer(owner), json={"vehicle_id": vehicle["id"]})
    assert res.status_code == 200, res.text
    assert set((await client.get("/auth/me", headers=bearer(owner))).json()["roles"]) == {"owner", "driver"}
    crew = [c for c in (await client.get(f"/vehicles/{vehicle['id']}/crew", headers=bearer(owner))).json() if c["ended_at"] is None]
    assert [c["role"] for c in crew] == ["driver"]
    # Again: nothing changes, and no error.
    again = await client.post("/onboarding/drive-myself", headers=bearer(owner), json={"vehicle_id": vehicle["id"]})
    assert again.status_code == 200, again.text
    assert len((await client.get(f"/vehicles/{vehicle['id']}/crew", headers=bearer(owner))).json()) == 1
    trip = await client.post("/trips", headers=bearer(owner), json={"vehicle_id": vehicle["id"], "origin": "Mombasa", "destination": "Nairobi"})
    assert trip.status_code == 201, trip.text


async def test_driving_it_myself_without_a_vehicle_only_adds_the_role_and_is_for_owners(client):
    owner, _ = await owner_session(client)
    assert (await client.post("/onboarding/drive-myself", headers=bearer(owner), json={})).status_code == 200
    assert set((await client.get("/auth/me", headers=bearer(owner))).json()["roles"]) == {"owner", "driver"}
    manager, _ = await staff_session(client, owner, "manager", "mgr@example.com")
    assert (await client.post("/onboarding/drive-myself", headers=bearer(manager), json={})).status_code == 403
