import urllib.parse

from tests.helpers import bearer, driver_session, owner_session, staff_session


async def supplier(client, owner, **extra):
    res = await client.post("/suppliers", headers=bearer(owner), json={"name": "Kiambu Spares", "phone": "0712345678", "category": "spares", **extra})
    assert res.status_code == 201, res.text
    return res.json()


async def part(client, owner, name="Oil filter", **extra):
    res = await client.post("/parts", headers=bearer(owner), json={"name": name, "unit": "pcs", "reorder_level": 4, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def order_body(sup, lines=None, **extra):
    return {"supplier_id": sup["id"], "lines": lines or [{"description": "Oil filter", "quantity": 4, "unit_cost_cents": 120_000}, {"description": "Fan belt", "quantity": 2, "unit_cost_cents": 350_000}], **extra}


async def test_suppliers_are_kept_with_clean_contacts_and_unique_names(client):
    owner, _ = await owner_session(client)
    s = await supplier(client, owner)
    assert s["phone"] == "+254712345678" and s["is_active"] is True
    assert (await client.post("/suppliers", headers=bearer(owner), json={"name": "Kiambu Spares"})).status_code == 409
    assert (await client.post("/suppliers", headers=bearer(owner), json={"name": "Bad Phone", "phone": "12"})).status_code == 422
    assert (await client.post("/suppliers", headers=bearer(owner), json={"name": "Bad Mail", "email": "nope"})).status_code == 422
    changed = await client.put(f"/suppliers/{s['id']}", headers=bearer(owner), json={"name": "Kiambu Spares Ltd", "phone": "0712345678", "is_active": False})
    assert changed.json()["name"] == "Kiambu Spares Ltd" and changed.json()["is_active"] is False
    assert [x["name"] for x in (await client.get("/suppliers", headers=bearer(owner))).json()] == ["Kiambu Spares Ltd"]


async def test_an_order_is_totalled_numbered_and_sent_by_whatsapp_with_the_text_written(client):
    owner, _ = await owner_session(client)
    sup = await supplier(client, owner)
    res = await client.post("/orders", headers=bearer(owner), json=order_body(sup, notes="Deliver to the yard", expected_on="2026-12-01"))
    assert res.status_code == 201, res.text
    order = res.json()
    assert order["number"] == "PO-0001" and order["status"] == "draft" and order["total_cents"] == 4 * 120_000 + 2 * 350_000 and len(order["lines"]) == 2
    assert (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()["number"] == "PO-0002"
    sent = await client.post(f"/orders/{order['id']}/send", headers=bearer(owner))
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    url = sent.json()["whatsapp_url"]
    assert url.startswith("https://wa.me/254712345678?text=")
    text = urllib.parse.unquote(url.split("text=")[1])
    assert "PO-0001" in text and "4 x Oil filter" in text and "2 x Fan belt" in text and "Total: KES 11,800.00" in text and "Deliver to the yard" in text and "Needed by 01 Dec 2026" in text
    again = await client.post(f"/orders/{order['id']}/send", headers=bearer(owner))
    assert again.status_code == 200 and again.json()["sent_at"] == sent.json()["sent_at"]  # resending the link does not reset it
    assert (await client.put(f"/orders/{order['id']}", headers=bearer(owner), json=order_body(sup))).status_code == 409  # no longer a draft


async def test_a_supplier_with_no_phone_cannot_be_sent_an_order(client):
    owner, _ = await owner_session(client)
    sup = await supplier(client, owner, name="No Phone Ltd", phone=None)
    order = (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()
    res = await client.post(f"/orders/{order['id']}/send", headers=bearer(owner))
    assert res.status_code == 422 and res.json()["detail"]["code"] == "no_phone"


async def test_a_draft_can_be_changed_and_an_order_follows_sent_confirmed_collected_paid(client):
    owner, _ = await owner_session(client)
    sup = await supplier(client, owner)
    order = (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()
    edited = await client.put(f"/orders/{order['id']}", headers=bearer(owner), json=order_body(sup, lines=[{"description": "Brake pads", "quantity": 1, "unit_cost_cents": 500_000}]))
    assert edited.json()["total_cents"] == 500_000 and len(edited.json()["lines"]) == 1
    move = lambda s, **kw: client.post(f"/orders/{order['id']}/status", headers=bearer(owner), json={"status": s, **kw})
    assert (await move("collected")).status_code == 409  # not sent yet
    await client.post(f"/orders/{order['id']}/send", headers=bearer(owner))
    assert (await move("confirmed")).json()["confirmed_at"]
    assert (await move("paid")).status_code == 409  # not collected yet
    assert (await move("collected")).json()["collected_at"]
    paid = await move("paid", reference="QGH7XYZ123")
    assert paid.json()["status"] == "paid" and paid.json()["paid_reference"] == "QGH7XYZ123"
    assert (await move("cancelled")).status_code == 409
    assert (await client.get("/orders?status_filter=paid", headers=bearer(owner))).json()[0]["number"] == "PO-0001"
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert {"order.created", "order.sent", "order.confirmed", "order.collected", "order.paid"} <= set(actions)


async def test_collecting_an_order_puts_the_parts_in_the_store_at_a_weighted_cost(client):
    owner, _ = await owner_session(client)
    sup = await supplier(client, owner)
    p = await part(client, owner)
    await client.post(f"/parts/{p['id']}/receive", headers=bearer(owner), json={"quantity": 6, "unit_cost_cents": 100_000})
    order = (await client.post("/orders", headers=bearer(owner), json=order_body(sup, lines=[{"part_id": p["id"], "description": "Oil filter", "quantity": 4, "unit_cost_cents": 150_000}, {"description": "Delivery", "quantity": 1}]))).json()
    await client.post(f"/orders/{order['id']}/send", headers=bearer(owner))
    got = (await client.post(f"/orders/{order['id']}/status", headers=bearer(owner), json={"status": "collected"})).json()
    assert [ln["received_quantity"] for ln in got["lines"]] == [4, 0]
    stocked = next(x for x in (await client.get("/parts", headers=bearer(owner))).json() if x["id"] == p["id"])
    assert stocked["quantity"] == 10 and stocked["unit_cost_cents"] == round((6 * 100_000 + 4 * 150_000) / 10)
    moves = (await client.get(f"/parts/movements?part_id={p['id']}", headers=bearer(owner))).json()
    assert any("PO-0001" in (m["note"] or "") for m in moves)


async def test_cancelling_a_draft_or_sent_order_and_a_bad_step(client):
    owner, _ = await owner_session(client)
    sup = await supplier(client, owner)
    one = (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()
    assert (await client.post(f"/orders/{one['id']}/status", headers=bearer(owner), json={"status": "cancelled"})).json()["status"] == "cancelled"
    assert (await client.post(f"/orders/{one['id']}/status", headers=bearer(owner), json={"status": "bogus"})).status_code == 409
    assert (await client.post("/orders", headers=bearer(owner), json={"supplier_id": sup["id"], "lines": []})).status_code == 422


async def test_low_stock_parts_are_drafted_into_orders_by_the_supplier_named_on_them(client):
    owner, _ = await owner_session(client)
    kiambu = await supplier(client, owner)
    other = await supplier(client, owner, name="Mombasa Tyres", phone="0722345678")
    oil = await part(client, owner, "Oil filter", supplier="Kiambu Spares")
    belt = await part(client, owner, "Fan belt", supplier="Kiambu Spares", reorder_level=2)
    tyre = await part(client, owner, "Tyre 315/80", supplier="Mombasa Tyres", reorder_level=3)
    await part(client, owner, "Bulb", supplier="Kiambu Spares", reorder_level=0)  # no reorder level: never drafted
    stocked = await part(client, owner, "Wipers", supplier="Kiambu Spares", reorder_level=2)
    await client.post(f"/parts/{stocked['id']}/receive", headers=bearer(owner), json={"quantity": 20, "unit_cost_cents": 1000})
    await client.post(f"/parts/{oil['id']}/receive", headers=bearer(owner), json={"quantity": 1, "unit_cost_cents": 100_000})
    await client.post(f"/parts/{belt['id']}/receive", headers=bearer(owner), json={"quantity": 2, "unit_cost_cents": 300_000})
    drafts = (await client.post("/orders/from-low-stock", headers=bearer(owner), json={})).json()
    by_supplier = {d["supplier_name"]: d for d in drafts}
    assert set(by_supplier) == {"Kiambu Spares", "Mombasa Tyres"}
    lines = {ln["description"]: ln["quantity"] for ln in by_supplier["Kiambu Spares"]["lines"]}
    assert lines == {"Oil filter": 4 * 2 - 1, "Fan belt": 2 * 2 - 2} and by_supplier["Kiambu Spares"]["status"] == "draft"
    assert {ln["description"]: ln["quantity"] for ln in by_supplier["Mombasa Tyres"]["lines"]} == {"Tyre 315/80": 6}
    everything = (await client.post("/orders/from-low-stock", headers=bearer(owner), json={"supplier_id": other["id"]})).json()
    assert len(everything) == 1 and len(everything[0]["lines"]) == 3 and everything[0]["supplier_name"] == "Mombasa Tyres" and kiambu["id"] and tyre["id"]


async def test_orders_are_for_the_workshop_roles_and_stay_inside_the_business(client):
    owner, _ = await owner_session(client)
    sup = await supplier(client, owner)
    order = (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()
    workshop, _ = await staff_session(client, owner, "workshop", "shop@example.com", with_2fa=False)
    assert (await client.get("/orders", headers=bearer(workshop))).status_code == 200
    driver = await driver_session(client, owner, "0712345678")
    assert (await client.get("/suppliers", headers=bearer(driver))).status_code == 403
    assert (await client.post("/orders", headers=bearer(driver), json=order_body(sup))).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/orders", headers=bearer(other))).json() == []
    assert (await client.get(f"/orders/{order['id']}", headers=bearer(other))).status_code == 404
    assert (await client.post("/orders", headers=bearer(other), json=order_body(sup))).status_code == 404  # another business's supplier
