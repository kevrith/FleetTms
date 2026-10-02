from tests.helpers import bearer, owner_session, staff_session
from tests.shots import fleet


async def part(client, owner, name="Oil filter", **extra):
    res = await client.post("/parts", headers=bearer(owner), json={"name": name, "reorder_level": 3, **extra})
    assert res.status_code == 201, res.text
    return res.json()


async def receive(client, owner, p, quantity=10, cost=150000):
    res = await client.post(f"/parts/{p['id']}/receive", headers=bearer(owner), json={"quantity": quantity, "unit_cost_cents": cost})
    assert res.status_code == 200, res.text
    return res.json()


async def work_order(client, f, title="Replace oil filter"):
    res = await client.post("/work-orders", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "title": title})
    assert res.status_code == 201, res.text
    return res.json()


async def issue(client, f, wo, p, quantity=1):
    return await client.post(f"/work-orders/{wo['id']}/issue", headers=bearer(f.owner), json={"part_id": p["id"], "quantity": quantity})


async def vehicle_repair_cost(client, f):
    rows = (await client.get("/expenses", headers=bearer(f.owner))).json()
    return sum(e["amount_cents"] for e in rows if e["vehicle_id"] == f.vehicle["id"] and e["category"] in ("repair", "service"))


async def test_receiving_stock_averages_the_unit_cost(client):
    f = await fleet(client)
    p = await part(client, f.owner)
    assert (await receive(client, f.owner, p, 10, 100000))["unit_cost_cents"] == 100000
    after = await receive(client, f.owner, p, 10, 200000)
    assert after["quantity"] == 20 and after["unit_cost_cents"] == 150000 and after["stock_value_cents"] == 3000000
    assert (await client.post("/parts", headers=bearer(f.owner), json={"name": "Oil filter"})).status_code == 409


async def test_issuing_a_filter_reduces_stock_and_adds_its_cost_to_the_vehicle(client):
    f = await fleet(client)
    p = await receive(client, f.owner, await part(client, f.owner), 10, 150000)
    wo = await work_order(client, f)
    res = await issue(client, f, wo, p, 2)
    assert res.status_code == 201, res.text
    order = res.json()
    assert order["parts_cents"] == 300000 and order["parts"][0]["fitted"] is False and order["unfitted_parts"] == 1
    assert (await client.get("/parts", headers=bearer(f.owner))).json()[0]["quantity"] == 8
    assert await vehicle_repair_cost(client, f) == 300000  # on the vehicle straight away, not only at completion
    moves = (await client.get("/parts/movements", headers=bearer(f.owner))).json()
    assert [m["kind"] for m in moves] == ["issued", "received"] and moves[0]["quantity_delta"] == -2 and moves[0]["work_order_id"] == wo["id"]


async def test_completing_the_work_order_does_not_charge_issued_parts_twice(client):
    f = await fleet(client)
    p = await receive(client, f.owner, await part(client, f.owner), 10, 150000)
    wo = await work_order(client, f)
    await issue(client, f, wo, p, 2)
    await client.put(f"/work-orders/{wo['id']}", headers=bearer(f.owner), json={"parts": [{"name": "Gasket kit", "quantity": 1, "unit_cost_cents": 50000}], "labour_cents": 100000})
    after = (await client.get(f"/work-orders/{wo['id']}", headers=bearer(f.owner))).json()
    assert [x["name"] for x in after["parts"]] == ["Oil filter", "Gasket kit"]  # editing keeps the issued part
    done = await client.post(f"/work-orders/{wo['id']}/complete", headers=bearer(f.owner), json={})
    assert done.status_code == 200 and done.json()["total_cents"] == 300000 + 50000 + 100000
    assert await vehicle_repair_cost(client, f) == 450000


async def test_stock_cannot_go_below_zero(client):
    f = await fleet(client)
    p = await receive(client, f.owner, await part(client, f.owner), 2, 100000)
    wo = await work_order(client, f)
    short = await issue(client, f, wo, p, 3)
    assert short.status_code == 409 and short.json()["detail"]["code"] == "insufficient_stock"
    assert (await issue(client, f, wo, p, 2)).status_code == 201
    assert (await issue(client, f, wo, p, 1)).status_code == 409
    assert (await client.get("/parts", headers=bearer(f.owner))).json()[0]["quantity"] == 0


async def test_a_returned_part_goes_back_on_the_shelf_and_off_the_vehicle(client):
    f = await fleet(client)
    p = await receive(client, f.owner, await part(client, f.owner), 5, 100000)
    wo = await work_order(client, f)
    order = (await issue(client, f, wo, p, 2)).json()
    res = await client.post(f"/work-orders/{wo['id']}/parts/{order['parts'][0]['id']}/return", headers=bearer(f.owner))
    assert res.status_code == 200 and res.json()["parts"] == []
    assert (await client.get("/parts", headers=bearer(f.owner))).json()[0]["quantity"] == 5
    assert await vehicle_repair_cost(client, f) == 0


async def test_issued_vs_fitted_lists_parts_nobody_confirmed(client):
    f = await fleet(client)
    p = await receive(client, f.owner, await part(client, f.owner), 5, 100000)
    wo = await work_order(client, f)
    order = (await issue(client, f, wo, p, 2)).json()
    [row] = (await client.get("/parts/unfitted", headers=bearer(f.owner))).json()
    assert row["name"] == "Oil filter" and row["value_cents"] == 200000 and row["closed"] is False
    await client.post(f"/work-orders/{wo['id']}/complete", headers=bearer(f.owner), json={})
    assert (await client.get("/parts/unfitted", headers=bearer(f.owner))).json()[0]["closed"] is True  # leakage: closed, never fitted
    await client.post(f"/work-orders/{wo['id']}/parts/{order['parts'][0]['id']}/fitted", headers=bearer(f.owner), json={"fitted": True})
    assert (await client.get("/parts/unfitted", headers=bearer(f.owner))).json() == []


async def test_low_stock_and_stock_counts(client):
    f = await fleet(client)
    p = await receive(client, f.owner, await part(client, f.owner, reorder_level=5), 8, 100000)
    assert (await client.get("/parts?low_stock=true", headers=bearer(f.owner))).json() == []
    wo = await work_order(client, f)
    await issue(client, f, wo, p, 4)
    assert [x["name"] for x in (await client.get("/parts?low_stock=true", headers=bearer(f.owner))).json()] == ["Oil filter"]
    count = await client.post("/parts/counts", headers=bearer(f.owner), json={"counts": [{"part_id": p["id"], "counted": 2}]})
    body = count.json()
    assert body["variances"][0]["difference"] == -2 and body["net_value_cents"] == -200000
    assert (await client.get("/parts", headers=bearer(f.owner))).json()[0]["quantity"] == 2
    exact = await client.post("/parts/counts", headers=bearer(f.owner), json={"counts": [{"part_id": p["id"], "counted": 2}]})
    assert exact.json()["variances"] == []


async def test_the_store_belongs_to_the_workshop_not_drivers_or_other_businesses(client):
    f = await fleet(client)
    workshop, _ = await staff_session(client, f.owner, "workshop", "store@example.com", with_2fa=False)
    assert (await client.post("/parts", headers=bearer(workshop), json={"name": "Brake pads"})).status_code == 201
    assert (await client.get("/parts", headers=bearer(f.driver))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/parts", headers=bearer(other))).json() == []
    p = (await client.get("/parts", headers=bearer(f.owner))).json()[0]
    assert (await client.post(f"/parts/{p['id']}/receive", headers=bearer(other), json={"quantity": 1, "unit_cost_cents": 1})).status_code == 404


async def test_the_work_order_list_names_the_vehicle_for_workshop_screens(client):
    f = await fleet(client)
    await work_order(client, f)
    workshop, _ = await staff_session(client, f.owner, "workshop", "reg@example.com", with_2fa=False)
    [row] = (await client.get("/work-orders", headers=bearer(workshop))).json()
    assert row["registration"] == "KCA 123A"


async def test_workshop_staff_get_a_minimal_vehicle_list_without_the_full_one(client):
    f = await fleet(client)
    workshop, _ = await staff_session(client, f.owner, "workshop", "veh@example.com", with_2fa=False)
    assert (await client.get("/vehicles", headers=bearer(workshop))).status_code == 403
    [row] = (await client.get("/workshop/vehicles", headers=bearer(workshop))).json()
    assert row["registration"] == "KCA 123A" and row["odometer_km"] == 125000
    assert set(row) == {"id", "registration", "make", "model", "odometer_km"}  # no trust level, ownership or documents
    assert (await client.get("/workshop/vehicles", headers=bearer(f.driver))).status_code == 403
