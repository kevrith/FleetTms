from tests.helpers import bearer, owner_session, staff_session
from tests.shots import ago, fleet, photo_id, sync


async def report(client, tokens, **body):
    return await client.post("/incidents", headers=bearer(tokens), json={"type": "breakdown", "description": "Engine overheated", "lat": -1.29, "lng": 36.82, **body})


async def test_a_driver_reports_a_breakdown_with_a_photo_and_an_urgent_work_order_follows(client):
    f = await fleet(client)
    pid = await photo_id(client, f.driver, "incident")
    res = await report(client, f.driver, photo_ids=[pid])
    assert res.status_code == 201, res.text
    incident = res.json()
    assert incident["registration"] == "KCA 123A" and incident["driver_name"] == "driver user" and len(incident["photos"]) == 1
    assert incident["lat"] == -1.29 and incident["work_order_id"]
    order = (await client.get(f"/work-orders/{incident['work_order_id']}", headers=bearer(f.owner))).json()
    assert order["priority"] == "urgent" and order["source"] == "incident" and "Engine overheated" in order["title"]
    assert (await client.post("/incidents", headers=bearer(f.driver), json={"type": "breakdown", "photo_ids": [pid]})).status_code == 422  # photo already used


async def test_other_incident_types_do_not_raise_work_orders(client):
    f = await fleet(client)
    for kind in ("accident", "police_stop", "cargo_theft"):
        res = await report(client, f.driver, type=kind)
        assert res.status_code == 201 and res.json()["work_order_id"] is None
    assert (await client.get("/work-orders", headers=bearer(f.owner))).json() == []


async def test_a_driver_cannot_report_for_someone_elses_vehicle_or_set_a_fine(client):
    f = await fleet(client)
    from tests.fleet import add_vehicle

    other_vehicle = await add_vehicle(client, f.owner, "KDD 456B")
    assert (await report(client, f.driver, vehicle_id=other_vehicle["id"])).status_code == 403
    fined = await report(client, f.driver, type="traffic_fine", fine_amount_cents=50000, fine_payer="driver")
    assert fined.status_code == 403 and fined.json()["detail"]["code"] == "fine_by_manager"


async def test_a_fine_the_business_pays_is_a_vehicle_cost_and_one_the_driver_pays_is_not(client):
    f = await fleet(client)
    inc = (await report(client, f.driver, type="traffic_fine", description="Speeding on Mombasa road")).json()
    paid = await client.put(f"/incidents/{inc['id']}/fine", headers=bearer(f.owner), json={"fine_amount_cents": 1000000, "fine_payer": "business", "reference": "TK-77"})
    assert paid.status_code == 200 and paid.json()["fine_payer"] == "business"
    costs = [e for e in (await client.get("/expenses", headers=bearer(f.owner))).json() if e["vehicle_id"] == f.vehicle["id"]]
    assert [c["amount_cents"] for c in costs] == [1000000]
    switched = await client.put(f"/incidents/{inc['id']}/fine", headers=bearer(f.owner), json={"fine_amount_cents": 1000000, "fine_payer": "driver", "deduct_from_payroll": True})
    assert switched.json()["deduct_from_payroll"] is True
    assert [e for e in (await client.get("/expenses", headers=bearer(f.owner))).json() if e["vehicle_id"] == f.vehicle["id"]] == []
    summary = (await client.get("/fines/summary", headers=bearer(f.owner))).json()
    row = summary["by_driver"][0]
    assert row["total_cents"] == 1000000 and row["driver_cents"] == 1000000 and row["to_deduct_cents"] == 1000000 and row["business_cents"] == 0
    assert summary["by_vehicle"][0]["name"] == "KCA 123A"


async def test_a_manager_can_enter_a_fine_when_reporting_and_it_needs_a_payer(client):
    f = await fleet(client)
    ids = f.ids["+254712345678"]
    bad = await report(client, f.owner, type="county_cess", vehicle_id=f.vehicle["id"], driver_membership_id=ids, fine_amount_cents=20000)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "payer_required"
    ok = await report(client, f.owner, type="county_cess", vehicle_id=f.vehicle["id"], driver_membership_id=ids, fine_amount_cents=20000, fine_payer="business")
    assert ok.status_code == 201 and ok.json()["driver_name"] == "driver user"
    wrong = await report(client, f.owner, type="breakdown", vehicle_id=f.vehicle["id"], fine_amount_cents=20000, fine_payer="business")
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "not_a_fine"


async def test_an_accident_can_have_an_insurance_claim_that_moves_through_its_stages(client):
    f = await fleet(client)
    inc = (await report(client, f.driver, type="accident", description="Rear-ended at the roundabout")).json()
    claim = await client.post(f"/incidents/{inc['id']}/claims", headers=bearer(f.owner), json={"insurer": "Jubilee", "policy_no": "P-100", "amount_claimed_cents": 25000000})
    assert claim.status_code == 201 and claim.json()["status"] == "filed"
    cid = claim.json()["id"]
    assert (await client.put(f"/claims/{cid}", headers=bearer(f.owner), json={"status": "paid"})).status_code == 422
    ok = await client.put(f"/claims/{cid}", headers=bearer(f.owner), json={"status": "paid", "claim_no": "CL-9", "amount_paid_cents": 21000000})
    assert ok.json()["status"] == "paid" and ok.json()["amount_paid_cents"] == 21000000
    detail = (await client.get(f"/incidents/{inc['id']}", headers=bearer(f.owner))).json()
    assert detail["claims"][0]["claim_no"] == "CL-9"
    assert [c["incident_type"] for c in (await client.get("/claims", headers=bearer(f.owner))).json()] == ["accident"]
    police = (await report(client, f.driver, type="police_stop")).json()
    assert (await client.post(f"/incidents/{police['id']}/claims", headers=bearer(f.owner), json={"insurer": "Jubilee"})).status_code == 422


async def test_resolving_an_incident_and_who_can_see_what(client):
    f = await fleet(client)
    inc = (await report(client, f.driver, type="accident")).json()
    res = await client.post(f"/incidents/{inc['id']}/resolve", headers=bearer(f.owner), json={"note": "Repaired", "cost_cents": 8000000})
    assert res.json()["status"] == "resolved" and res.json()["cost_cents"] == 8000000
    assert (await client.post(f"/incidents/{inc['id']}/resolve", headers=bearer(f.driver), json={})).status_code == 403
    assert len((await client.get("/me/incidents", headers=bearer(f.driver))).json()) == 1
    assert (await client.get("/incidents", headers=bearer(f.driver))).status_code == 403
    assert (await client.get(f"/incidents/{inc['id']}", headers=bearer(f.driver))).json()["claims"] == []
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/incidents", headers=bearer(other))).json() == []
    assert (await client.get(f"/incidents/{inc['id']}", headers=bearer(other))).status_code == 404
    workshop, _ = await staff_session(client, f.owner, "workshop", "w@example.com", with_2fa=False)
    assert (await client.post("/incidents", headers=bearer(workshop), json={"type": "breakdown"})).status_code == 403


async def test_a_report_made_offline_syncs_once_with_the_time_it_happened(client):
    f = await fleet(client)
    action = {"client_id": "5a1e9c1e-0000-4000-8000-000000000001", "type": "incident.report", "payload": {"type": "breakdown", "description": "Flat tyre", "occurred_at": ago(hours=3)}}
    first = (await sync(client, f.driver, [action])).json()["results"][0]
    again = (await sync(client, f.driver, [action])).json()["results"][0]
    assert first["status"] == "ok" and again["status"] == "duplicate"
    rows = (await client.get("/incidents", headers=bearer(f.owner))).json()
    assert len(rows) == 1 and rows[0]["occurred_at"] < ago(hours=2) and rows[0]["work_order_id"]
