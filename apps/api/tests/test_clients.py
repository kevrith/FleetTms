import pytest

from tests.helpers import bearer, owner_session, staff_session


async def client_body(**extra):
    return {"name": "Bamburi Cement", "contact_name": "Jane Wekesa", "phone": "0712000111", "email": "jane@bamburi.example", "kra_pin": "P051234567K", "billing_method": "per_tonne", "rate_cents": 150000, **extra}


async def add_client(client, owner, **extra):
    res = await client.post("/clients", headers=bearer(owner), json=await client_body(**extra))
    assert res.status_code == 201, res.text
    return res.json()


def route_body(**extra):
    return {"name": "Mombasa to Nairobi", "pickup": "Mombasa", "dropoff": "Nairobi", "distance_km": 480, "expected_hours": 14, "tolls_cents": 600000, "crew_cents": 700000, "other_cents": 200000, **extra}


async def add_route(client, owner, client_id, **extra):
    res = await client.post(f"/clients/{client_id}/routes", headers=bearer(owner), json=route_body(**extra))
    assert res.status_code == 201, res.text
    return res.json()


async def test_a_client_keeps_contacts_kra_pin_and_default_billing(client):
    owner, _ = await owner_session(client)
    c = await add_client(client, owner)
    assert c["phone"] == "+254712000111" and c["kra_pin"] == "P051234567K" and c["billing_method"] == "per_tonne" and c["rate_cents"] == 150000
    rows = (await client.get("/clients", headers=bearer(owner))).json()
    assert [r["name"] for r in rows] == ["Bamburi Cement"] and rows[0]["routes"] == 0
    updated = await client.put(f"/clients/{c['id']}", headers=bearer(owner), json=await client_body(billing_method="monthly_contract", rate_cents=50000000, payment_terms_days=45))
    assert updated.json()["billing_method"] == "monthly_contract" and updated.json()["payment_terms_days"] == 45


@pytest.mark.parametrize("bad", [{"kra_pin": "12345"}, {"kra_pin": "P05123456KK"}, {"phone": "12"}, {"email": "nope"}, {"billing_method": "per_week"}, {"rate_cents": -1}])
async def test_bad_client_details_are_refused(client, bad):
    owner, _ = await owner_session(client)
    res = await client.post("/clients", headers=bearer(owner), json=await client_body(**bad))
    assert res.status_code == 422


async def test_client_names_are_unique_per_business(client):
    owner, _ = await owner_session(client)
    await add_client(client, owner)
    assert (await client.post("/clients", headers=bearer(owner), json=await client_body())).status_code == 409
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.post("/clients", headers=bearer(other), json=await client_body())).status_code == 201
    assert len((await client.get("/clients", headers=bearer(other))).json()) == 1


async def test_a_clients_route_is_stored_once_and_listed_with_the_client(client):
    owner, _ = await owner_session(client)
    c = await add_client(client, owner)
    r = await add_route(client, owner, c["id"], path_notes="Via Mtito Andei, avoid the Athi River weighbridge queue")
    assert r["client_name"] == "Bamburi Cement" and r["distance_km"] == 480
    assert (await client.post(f"/clients/{c['id']}/routes", headers=bearer(owner), json=route_body())).status_code == 409
    detail = (await client.get(f"/clients/{c['id']}", headers=bearer(owner))).json()
    assert detail["routes"] == 1 and detail["route_list"][0]["path_notes"].startswith("Via Mtito")
    changed = await client.put(f"/routes/{r['id']}", headers=bearer(owner), json=route_body(distance_km=490))
    assert changed.json()["distance_km"] == 490
    assert [x["name"] for x in (await client.get("/routes", headers=bearer(owner))).json()] == ["Mombasa to Nairobi"]


async def test_the_accountant_manages_clients_but_drivers_and_workshop_do_not(client):
    owner, _ = await owner_session(client)
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.post("/clients", headers=bearer(accountant), json=await client_body())).status_code == 201
    workshop, _ = await staff_session(client, owner, "workshop", "w@example.com", with_2fa=False)
    assert (await client.get("/clients", headers=bearer(workshop))).status_code == 403
    assert (await client.get("/routes", headers=bearer(workshop))).status_code == 403
