import pytest

from tests.helpers import bearer, staff_session
from tests.shots import fleet


async def tyre(client, owner, serial="MP-1001", **extra):
    body = {"serial": serial, "brand": "Michelin", "size": "315/80R22.5", "cost_cents": 4500000, "supplier": "Tyre Hub", **extra}
    res = await client.post("/tyres", headers=bearer(owner), json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def fit(client, owner, t, vehicle, position="steer_left", **extra):
    return await client.post(f"/tyres/{t['id']}/fit", headers=bearer(owner), json={"vehicle_id": vehicle["id"], "position": position, **extra})


async def set_odometer(client, f, km):
    res = await client.put(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner), json={**f.vehicle, "odometer_km": km})
    assert res.status_code == 200, res.text


async def test_a_tyre_is_recorded_once_by_serial(client):
    f = await fleet(client)
    t = await tyre(client, f.owner, "mp-1001")
    assert t["serial"] == "MP1001" and t["status"] == "in_store"
    dupe = await client.post("/tyres", headers=bearer(f.owner), json={"serial": "MP 1001", "brand": "X", "size": "315/80"})
    assert dupe.status_code == 409


async def test_fitting_books_the_cost_on_the_vehicle_once(client):
    f = await fleet(client)
    t = await tyre(client, f.owner)
    assert (await fit(client, f.owner, t, f.vehicle)).status_code == 200
    expenses = (await client.get("/expenses", headers=bearer(f.owner))).json()
    tyre_costs = [e for e in expenses if e["category"] == "tyres"]
    assert len(tyre_costs) == 1 and tyre_costs[0]["amount_cents"] == 4500000 and tyre_costs[0]["vehicle_id"] == f.vehicle["id"]
    await client.post(f"/tyres/{t['id']}/remove", headers=bearer(f.owner), json={})
    await fit(client, f.owner, t, f.vehicle, "steer_right")
    again = [e for e in (await client.get("/expenses", headers=bearer(f.owner))).json() if e["category"] == "tyres"]
    assert len(again) == 1  # refitting is not a second purchase


async def test_one_tyre_per_position_and_positions_are_validated(client):
    f = await fleet(client)
    a, b = await tyre(client, f.owner, "A1111"), await tyre(client, f.owner, "B2222")
    assert (await fit(client, f.owner, a, f.vehicle, "drive1_left_inner")).status_code == 200
    clash = await fit(client, f.owner, b, f.vehicle, "drive1_left_inner")
    assert clash.status_code == 409 and clash.json()["detail"]["code"] == "position_taken"
    assert (await fit(client, f.owner, b, f.vehicle, "left front")).status_code == 422
    assert (await fit(client, f.owner, a, f.vehicle, "steer_left")).status_code == 409  # already fitted


async def test_kilometres_run_follow_the_vehicle_odometer(client):
    f = await fleet(client)
    t = await tyre(client, f.owner)
    await fit(client, f.owner, t, f.vehicle)
    await set_odometer(client, f, 125000 + 4000)
    row = (await client.get(f"/tyres/{t['id']}", headers=bearer(f.owner))).json()
    assert row["km_run"] == 4000 and row["cost_per_km_cents"] == pytest.approx(4500000 / 4000)
    await set_odometer(client, f, 125000 + 5000)
    removed = await client.post(f"/tyres/{t['id']}/remove", headers=bearer(f.owner), json={"note": "worn"})
    assert removed.json()["km_run"] == 5000 and removed.json()["status"] == "removed"
    await fit(client, f.owner, t, f.vehicle, "steer_right")
    await set_odometer(client, f, 125000 + 6000)
    assert (await client.get(f"/tyres/{t['id']}", headers=bearer(f.owner))).json()["km_run"] == 5000 + 1000


async def test_rotation_swaps_two_tyres_and_resets_the_rotation_clock(client):
    f = await fleet(client)
    a, b = await tyre(client, f.owner, "A1111"), await tyre(client, f.owner, "B2222")
    await fit(client, f.owner, a, f.vehicle, "steer_left")
    await fit(client, f.owner, b, f.vehicle, "drive1_left_outer")
    await set_odometer(client, f, 125000 + 16000)
    due = (await client.get("/tyres/report", headers=bearer(f.owner))).json()["due"]
    assert {d["serial"] for d in due} == {"A1111", "B2222"} and all("rotate" in d["due"] for d in due)
    res = await client.post(f"/tyres/{a['id']}/rotate", headers=bearer(f.owner), json={"position": "drive1_left_outer"})
    assert res.status_code == 200 and res.json()["position"] == "drive1_left_outer"
    positions = {t["serial"]: t["position"] for t in (await client.get(f"/vehicles/{f.vehicle['id']}/tyres", headers=bearer(f.owner))).json()}
    assert positions == {"A1111": "drive1_left_outer", "B2222": "steer_left"}
    assert (await client.get("/tyres/report", headers=bearer(f.owner))).json()["due"] == []


async def test_tread_readings_and_retreads(client):
    f = await fleet(client)
    t = await tyre(client, f.owner)
    await fit(client, f.owner, t, f.vehicle)
    worn = await client.post(f"/tyres/{t['id']}/tread", headers=bearer(f.owner), json={"tread_mm": "2.5"})
    assert worn.json()["last_tread_mm"] == 2.5 and "replace" in worn.json()["due"]
    assert (await client.post(f"/tyres/{t['id']}/retread", headers=bearer(f.owner), json={"cost_cents": 1200000})).status_code == 409
    await client.post(f"/tyres/{t['id']}/remove", headers=bearer(f.owner), json={})
    done = (await client.post(f"/tyres/{t['id']}/retread", headers=bearer(f.owner), json={"cost_cents": 1200000})).json()
    assert done["retreads"] == 1 and done["status"] == "in_store" and done["due"] == []
    costs = sorted(e["amount_cents"] for e in (await client.get("/expenses", headers=bearer(f.owner))).json() if e["category"] == "tyres")
    assert costs == [1200000, 4500000]


async def test_report_groups_cost_per_km_by_brand_and_supplier(client):
    f = await fleet(client)
    a = await tyre(client, f.owner, "A1111", brand="Michelin", supplier="Tyre Hub", cost_cents=4000000)
    b = await tyre(client, f.owner, "B2222", brand="Bridgestone", supplier="Tyre Hub", cost_cents=3000000)
    await fit(client, f.owner, a, f.vehicle, "steer_left")
    await fit(client, f.owner, b, f.vehicle, "steer_right")
    await set_odometer(client, f, 125000 + 10000)
    report = (await client.get("/tyres/report", headers=bearer(f.owner))).json()
    brands = {r["name"]: r for r in report["by_brand"]}
    assert brands["Michelin"]["cost_per_km_cents"] == 400 and brands["Bridgestone"]["cost_per_km_cents"] == 300
    assert report["by_supplier"][0]["name"] == "Tyre Hub" and report["by_supplier"][0]["tyres"] == 2


# ---- swap detection at inspection ---------------------------------------------------------------------


async def inspect_with(client, f, serials):
    from tests.shots import checklist

    results = [{"item_id": i["id"], "ok": True} for i in await checklist(client, f.driver)]
    res = await client.post(f"/vehicles/{f.vehicle['id']}/inspections", headers=bearer(f.driver), json={"results": results, "tyre_serials": serials})
    assert res.status_code == 201, res.text


async def alerts(client, f):
    return (await client.get("/tyre-alerts", headers=bearer(f.owner))).json()


async def test_matching_serials_raise_nothing_and_a_swap_raises_an_alert(client):
    f = await fleet(client)
    a, b = await tyre(client, f.owner, "A1111"), await tyre(client, f.owner, "B2222")
    await fit(client, f.owner, a, f.vehicle, "steer_left")
    await fit(client, f.owner, b, f.vehicle, "steer_right")
    await inspect_with(client, f, [{"position": "steer_left", "serial": "a-1111"}, {"position": "steer_right", "serial": "B2222"}])
    assert await alerts(client, f) == []
    # Someone swaps the good tyre on the left for a worn one nobody recorded.
    await inspect_with(client, f, [{"position": "steer_left", "serial": "ZZ9999"}, {"position": "steer_right", "serial": "B2222"}])
    [alert] = await alerts(client, f)
    assert alert["position"] == "steer_left" and alert["expected_serial"] == "A1111" and alert["seen_serial"] == "ZZ9999"
    assert alert["reason"] == "unknown" and alert["registration"] == "KCA 123A"
    await inspect_with(client, f, [{"position": "steer_left", "serial": "ZZ9999"}])
    assert len(await alerts(client, f)) == 1  # the same swap is not raised twice


async def test_a_tyre_from_the_store_or_another_position_is_flagged(client):
    f = await fleet(client)
    a, b = await tyre(client, f.owner, "A1111"), await tyre(client, f.owner, "B2222")
    await tyre(client, f.owner, "S3333")
    await fit(client, f.owner, a, f.vehicle, "steer_left")
    await fit(client, f.owner, b, f.vehicle, "steer_right")
    await inspect_with(client, f, [{"position": "steer_left", "serial": "B2222"}, {"position": "steer_right", "serial": "S3333"}])
    reasons = {x["position"]: x["reason"] for x in await alerts(client, f)}
    assert reasons == {"steer_left": "elsewhere", "steer_right": "elsewhere"}


async def test_an_alert_can_be_resolved_and_drivers_never_see_the_serials(client):
    f = await fleet(client)
    a = await tyre(client, f.owner, "A1111")
    await fit(client, f.owner, a, f.vehicle, "steer_left")
    await inspect_with(client, f, [{"position": "steer_left", "serial": "QQ0000"}])
    [alert] = await alerts(client, f)
    res = await client.post(f"/tyre-alerts/{alert['id']}/resolve", headers=bearer(f.owner), json={"note": "Checked: recorded wrongly"})
    assert res.json()["status"] == "resolved" and await alerts(client, f) == []
    mine = (await client.get("/me/tyre-positions", headers=bearer(f.driver))).json()
    assert mine["positions"] == ["steer_left"] and "A1111" not in str(mine)


async def test_workshop_staff_manage_tyres_but_drivers_and_other_businesses_cannot(client):
    f = await fleet(client)
    workshop, _ = await staff_session(client, f.owner, "workshop", "mechanic@example.com", with_2fa=False)
    assert (await client.post("/tyres", headers=bearer(workshop), json={"serial": "W1234", "brand": "A", "size": "315/80"})).status_code == 201
    assert (await client.get("/tyres", headers=bearer(f.driver))).status_code == 403
    assert (await client.post("/tyres", headers=bearer(f.driver), json={"serial": "D1234", "brand": "A", "size": "315/80"})).status_code == 403
    from tests.helpers import owner_session

    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/tyres", headers=bearer(other))).json() == []
    assert (await client.post("/tyres", headers=bearer(other), json={"serial": "W1234", "brand": "A", "size": "315/80"})).status_code == 201  # serials are per business
