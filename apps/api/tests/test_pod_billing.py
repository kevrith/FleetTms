import re
from datetime import UTC, datetime

import pytest

from app.sms import get_sms_sender
from tests.helpers import bearer, staff_session
from tests.shots import fleet, inspect, photo_id, sync
from tests.test_clients import add_client, route_body
from tests.test_jobs import accept, dispatch, make_quote

SIGNATURE = [[[0, 0], [10, 6], [20, 12], [30, 6], [40, 0]], [[5, 15], [35, 15]]]


async def setup(client, method="per_trip", rate=8000000, phone="0712000111", **client_extra):
    f = await fleet(client)
    c = await add_client(client, f.owner, billing_method=method, rate_cents=rate, phone=phone, **client_extra)
    route = await client.post(f"/clients/{c['id']}/routes", headers=bearer(f.owner), json=route_body(dropoff_lat=-1.2921, dropoff_lng=36.8219, site_radius_m=500))
    assert route.status_code == 201, route.text
    return f, c, route.json()


async def job_for(client, f, c, r, **extra):
    q = await make_quote(client, f, c, r, **extra)
    return (await accept(client, f, q))["job"]


async def running(client, f, job):
    """Dispatches the job now, does the inspection and starts the trip. Returns the trip id."""
    res = await dispatch(client, f, job, scheduled_for=datetime.now(UTC).isoformat())
    assert res.status_code == 201, res.text
    trip_id = res.json()["trips"][0]["id"]
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    here = (await client.get(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner))).json()["odometer_km"]  # a trip starts where the last one ended
    start = await client.post(f"/trips/{trip_id}/start", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": here})
    assert start.status_code == 200, start.text
    return trip_id


async def load(client, f, trip_id, kg=None, ticket=True, **extra):
    body = {"photo_id": await photo_id(client, f.driver, "cargo")}
    if kg:
        body["loaded_weight_kg"] = kg
    if ticket:
        body["weighbridge_photo_id"] = await photo_id(client, f.driver, "weighbridge")
    return await client.post(f"/trips/{trip_id}/loading", headers=bearer(f.driver), json={**body, **extra})


async def pod_body(client, f, **extra):
    return {
        "recipient_name": "Peter Kamau", "method": "signature", "signature": SIGNATURE,
        "cargo_photo_id": await photo_id(client, f.driver, "pod_cargo"), "note_photo_id": await photo_id(client, f.driver, "delivery_note"),
        "lat": -1.2925, "lng": 36.8223, **extra,
    }  # fmt: skip


async def deliver(client, f, trip_id, **extra):
    return await client.post(f"/trips/{trip_id}/deliver", headers=bearer(f.driver), json={"pod": await pod_body(client, f, **extra)})


async def invoice_of(client, f, trip_id):
    return (await client.get(f"/trips/{trip_id}/invoice", headers=bearer(f.owner))).json()["invoice"]


def last_code():
    texts = [m for _, m in get_sms_sender().outbox if "delivery code" in m]
    return re.search(r"is (\d{6})\.", texts[-1]).group(1)


# ---- proof of delivery --------------------------------------------------------------------------------


async def test_confirming_the_pod_delivers_the_trip_and_generates_the_invoice_with_the_pod_attached(client):
    f, c, r = await setup(client)
    job = await job_for(client, f, c, r, billing_method="per_trip", rate_cents=8000000)
    trip_id = await running(client, f, job)
    res = await deliver(client, f, trip_id)
    assert res.status_code == 200, res.text
    trip = res.json()
    assert trip["status"] == "delivered" and trip["pod"]["recipient_name"] == "Peter Kamau" and trip["pod"]["has_signature"] and trip["pod"]["flags"] == []
    assert trip["pod"]["note_photo"] and trip["pod"]["cargo_photo"]
    inv = await invoice_of(client, f, trip_id)
    assert inv["number"] == "INV-0001" and inv["kind"] == "trip" and inv["status"] == "issued"
    assert inv["subtotal_cents"] == 8000000 and inv["vat_cents"] == 0 and inv["total_cents"] == 8000000 and inv["balance_cents"] == 8000000
    full = (await client.get(f"/invoices/{inv['id']}", headers=bearer(f.owner))).json()
    assert len(full["lines"]) == 1 and "Mombasa to Nairobi" in full["lines"][0]["description"] and job["number"] in full["lines"][0]["description"]
    pdf = await client.get(f"/invoices/{inv['id']}/pdf", headers=bearer(f.owner))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and b"/Count 2" in pdf.content  # the invoice and its proof of delivery
    assert "INV-0001.pdf" in pdf.headers["content-disposition"]
    assert (await client.get(f"/jobs/{job['id']}", headers=bearer(f.owner))).json()["status"] == "in_progress"


async def test_a_trip_for_a_client_job_cannot_be_delivered_without_proof(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    res = await client.post(f"/trips/{trip_id}/deliver", headers=bearer(f.driver))
    assert res.status_code == 422 and res.json()["detail"]["code"] == "pod_required"
    assert (await invoice_of(client, f, trip_id)) is None


async def test_the_delivery_code_goes_to_the_clients_phone_and_works_once(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    sent = await client.post(f"/trips/{trip_id}/pod/code", headers=bearer(f.driver))
    assert sent.status_code == 200 and sent.json()["sent_to_last4"] == "0111"
    again = await client.post(f"/trips/{trip_id}/pod/code", headers=bearer(f.driver))
    assert again.status_code == 429  # one a minute
    body = lambda code: {"recipient_name": "Peter Kamau", "method": "code", "code": code}
    wrong = await deliver(client, f, trip_id, **body("000000"))
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "wrong_code"
    missing = await deliver(client, f, trip_id, **{**body(None), "code": None})
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "code_required"
    ok = await deliver(client, f, trip_id, **body(last_code()))
    assert ok.status_code == 200 and ok.json()["pod"]["method"] == "code" and ok.json()["pod"]["has_signature"] is False
    assert await invoice_of(client, f, trip_id)


async def test_too_many_wrong_codes_lock_the_code(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    await client.post(f"/trips/{trip_id}/pod/code", headers=bearer(f.driver))
    real = last_code()
    guess = "111111" if real != "111111" else "222222"
    for _ in range(5):
        assert (await deliver(client, f, trip_id, method="code", code=guess)).json()["detail"]["code"] == "wrong_code"
    locked = await deliver(client, f, trip_id, method="code", code=real)
    assert locked.status_code == 429 and locked.json()["detail"]["code"] == "too_many_attempts"


async def test_a_client_with_no_phone_cannot_be_texted_a_code(client):
    f, c, r = await setup(client, phone=None)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    res = await client.post(f"/trips/{trip_id}/pod/code", headers=bearer(f.driver))
    assert res.status_code == 422 and res.json()["detail"]["code"] == "client_has_no_phone"
    assert (await deliver(client, f, trip_id)).status_code == 200  # the signature still works


@pytest.mark.parametrize("bad", [{"signature": None}, {"signature": [[[1, 1]]]}, {"recipient_name": "P"}, {"cargo_photo_id": None}, {"note_photo_id": None}])
async def test_the_pod_needs_a_signature_a_name_and_both_photos(client, bad):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    assert (await deliver(client, f, trip_id, **bad)).status_code == 422
    assert (await client.get(f"/trips/{trip_id}", headers=bearer(f.owner))).json()["status"] == "in_progress"  # nothing half-recorded


async def test_delivery_outside_the_clients_site_is_flagged(client):
    f, c, r = await setup(client)
    far = await running(client, f, await job_for(client, f, c, r))
    res = await deliver(client, f, far, lat=-1.40, lng=36.95)
    assert res.status_code == 200 and res.json()["pod"]["flags"] == ["outside_site"]
    assert await invoice_of(client, f, far)  # flagged, never blocked: the cargo was still delivered


async def test_a_pod_with_no_gps_is_flagged(client):
    from tests.shots import upload

    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    body = await pod_body(client, f)
    body.pop("lat"), body.pop("lng")
    body["cargo_photo_id"] = (await upload(client, f.driver, "pod_cargo", lat=None)).json()["id"]
    body["note_photo_id"] = (await upload(client, f.driver, "delivery_note", lat=None)).json()["id"]
    nogps = await client.post(f"/trips/{trip_id}/deliver", headers=bearer(f.driver), json={"pod": body})
    assert nogps.status_code == 200 and nogps.json()["pod"]["flags"] == ["no_location"]


async def test_shortages_and_damage_are_recorded_and_damage_needs_a_photo(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    no_photo = await deliver(client, f, trip_id, damage_notes="Three bags torn", shortage_qty="12", shortage_unit="bags")
    assert no_photo.status_code == 422 and no_photo.json()["detail"]["code"] == "damage_photo_required"
    res = await deliver(client, f, trip_id, damage_notes="Three bags torn", shortage_qty="12", shortage_unit="bags", damage_photo_ids=[await photo_id(client, f.driver, "damage")])
    pod = res.json()["pod"]
    assert res.status_code == 200 and set(pod["flags"]) == {"shortage", "damage"} and pod["shortage_qty"] == 12 and len(pod["damage_photos"]) == 1


async def test_a_pod_made_with_no_signal_syncs_with_its_photos_and_invoices_once(client):
    from tests.shots import upload

    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    cargo, note = "5a1e9c1e-0000-4000-8000-0000000000c1", "5a1e9c1e-0000-4000-8000-0000000000c2"
    assert (await upload(client, f.driver, "pod_cargo", client_id=cargo, offline=True)).status_code == 201
    assert (await upload(client, f.driver, "delivery_note", client_id=note, offline=True)).status_code == 201
    pod = {"recipient_name": "Peter Kamau", "method": "signature", "signature": SIGNATURE, "cargo_photo_client_id": cargo, "note_photo_client_id": note, "lat": -1.2925, "lng": 36.8223}
    action = {"client_id": "5a1e9c1e-0000-4000-8000-0000000000d1", "type": "trip.deliver", "payload": {"trip_id": trip_id, "pod": pod}}
    first = (await sync(client, f.driver, [action])).json()["results"][0]
    again = (await sync(client, f.driver, [action])).json()["results"][0]
    assert first["status"] == "ok" and again["status"] == "duplicate"
    assert len((await client.get("/invoices", headers=bearer(f.owner))).json()) == 1


# ---- load and weighbridge ---------------------------------------------------------------------------------


async def test_an_overload_is_flagged_when_the_cargo_is_weighed_before_the_lorry_leaves(client):
    f, c, r = await setup(client)
    await client.put(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner), json={**f.vehicle, "tare_kg": 6000})
    job = await job_for(client, f, c, r)
    res = await dispatch(client, f, job, scheduled_for=datetime.now(UTC).isoformat())
    trip_id = res.json()["trips"][0]["id"]
    ok = await load(client, f, trip_id, kg=9000)  # 6000 + 9000 is under the 16000 kg limit
    assert ok.status_code == 200 and ok.json()["overload_kg"] == 0 and ok.json()["status"] == "scheduled"
    over = await load(client, f, trip_id, kg=11500)
    assert over.status_code == 200 and over.json()["overload_kg"] == 1500 and over.json()["weighbridge_photo"]
    assert (await client.get("/me/vehicle", headers=bearer(f.driver))).json()["vehicle"]["tare_kg"] == 6000


async def test_a_weight_with_no_ticket_photo_is_refused_and_a_ticket_needs_its_weight(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    ticket_only = await load(client, f, trip_id, kg=None, ticket=True)
    assert ticket_only.status_code == 422 and ticket_only.json()["detail"]["code"] == "weight_required"
    assert (await load(client, f, trip_id, kg=9800, ticket=False)).status_code == 200  # a weight alone is fine for a per-trip job


async def test_a_per_tonne_job_bills_from_the_weighbridge_weight(client):
    f, c, r = await setup(client, method="per_tonne", rate=300000, vat_pct="16")
    job = await job_for(client, f, c, r, billing_method="per_tonne", rate_cents=300000, weight_tonnes="28")
    trip_id = await running(client, f, job)
    refused = await load(client, f, trip_id, kg=None, ticket=False)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "weighbridge_required"
    assert (await load(client, f, trip_id, kg=28400)).status_code == 200  # the ticket says 28.4 t, the quote said 28
    assert (await deliver(client, f, trip_id)).status_code == 200
    inv = await invoice_of(client, f, trip_id)
    assert inv["subtotal_cents"] == 8520000 and inv["vat_cents"] == 1363200 and inv["total_cents"] == 9883200 and inv["vat_pct"] == 16
    line = (await client.get(f"/invoices/{inv['id']}", headers=bearer(f.owner))).json()["lines"][0]
    assert line["quantity"] == 28.4 and line["unit_cents"] == 300000 and "weighbridge" in line["description"]


async def test_a_per_tonne_trip_with_no_ticket_is_invoiced_only_when_the_office_enters_the_weight(client):
    f, c, r = await setup(client, method="per_tonne", rate=300000)
    job = await job_for(client, f, c, r, billing_method="per_tonne", rate_cents=300000, weight_tonnes="28")
    trip_id = await running(client, f, job)
    assert (await load(client, f, trip_id, kg=28000, ticket=True)).status_code == 200
    from sqlalchemy import text

    from app.db import get_engine

    async with get_engine().begin() as conn:  # a trip whose ticket photo was never recorded
        await conn.execute(text("UPDATE trips SET weighbridge_photo_id = NULL, loaded_weight_kg = NULL WHERE id = :t"), {"t": trip_id})
    assert (await deliver(client, f, trip_id)).status_code == 200
    assert await invoice_of(client, f, trip_id) is None
    manual = await client.post(f"/trips/{trip_id}/invoice", headers=bearer(f.owner), json={})
    assert manual.status_code == 422 and manual.json()["detail"]["code"] == "weight_required"
    done = await client.post(f"/trips/{trip_id}/invoice", headers=bearer(f.owner), json={"weight_kg": 27800})
    assert done.status_code == 200 and done.json()["subtotal_cents"] == 8340000
    assert (await client.get(f"/trips/{trip_id}", headers=bearer(f.owner))).json()["status"] == "delivered"


async def test_a_per_km_job_bills_the_route_distance(client):
    f, c, r = await setup(client, method="per_km", rate=20000)
    job = await job_for(client, f, c, r, billing_method="per_km", rate_cents=20000)
    trip_id = await running(client, f, job)
    await deliver(client, f, trip_id)
    assert (await invoice_of(client, f, trip_id))["total_cents"] == 20000 * 480


# ---- contracts ------------------------------------------------------------------------------------------


async def test_a_contract_invoice_shows_the_trips_it_covered_and_is_issued_once_a_month(client):
    f, c, r = await setup(client, method="monthly_contract", rate=50000000)
    job = await job_for(client, f, c, r, billing_method="monthly_contract", rate_cents=50000000, trips=2)
    trip_id = await running(client, f, job)
    await deliver(client, f, trip_id)
    assert await invoice_of(client, f, trip_id) is None  # a contract is not billed per trip
    today = datetime.now(UTC).date().isoformat()
    run = await client.post("/invoices/contracts/run", headers=bearer(f.owner), json={"month": today})
    assert run.status_code == 200 and len(run.json()["issued"]) == 1
    inv = (await client.get(f"/invoices/{run.json()['issued'][0]['id']}", headers=bearer(f.owner))).json()
    assert inv["kind"] == "contract" and inv["total_cents"] == 50000000 and inv["period_start"][:7] == today[:7]
    assert len(inv["lines"]) == 2 and "1 trip" in inv["lines"][0]["description"] and "Trip 1" in inv["lines"][1]["description"] and inv["lines"][1]["amount_cents"] == 0
    assert inv["lines"][1]["trip_id"] == trip_id
    assert (await client.post("/invoices/contracts/run", headers=bearer(f.owner), json={"month": today})).json()["issued"] == []  # not twice
    assert (await client.post("/invoices/contracts/run", headers=bearer(f.owner), json={"month": "2030-01-01"})).status_code == 422
    assert (await client.get(f"/invoices/{inv['id']}/pdf", headers=bearer(f.owner))).content.startswith(b"%PDF")


# ---- payments and permissions -------------------------------------------------------------------------------


async def test_partial_payments_move_an_invoice_to_paid_and_overpaying_is_refused(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r, billing_method="per_trip", rate_cents=8000000))
    await deliver(client, f, trip_id)
    inv = await invoice_of(client, f, trip_id)
    pay = lambda amount, **kw: client.post(f"/invoices/{inv['id']}/payments", headers=bearer(f.owner), json={"amount_cents": amount, "method": "mpesa", "reference": "QGH7XYZ123", **kw})
    first = await pay(3000000)
    assert first.status_code == 201 and first.json()["status"] == "partially_paid" and first.json()["balance_cents"] == 5000000
    assert (await pay(6000000)).json()["detail"]["code"] == "overpayment"
    done = await pay(5000000, method="cash")
    assert done.json()["status"] == "paid" and done.json()["balance_cents"] == 0 and len(done.json()["payments"]) == 2
    assert (await client.post(f"/invoices/{inv['id']}/void", headers=bearer(f.owner), json={"reason": "Wrong client"})).json()["detail"]["code"] == "has_payments"
    unpaid = (await client.get("/invoices?unpaid_only=true", headers=bearer(f.owner))).json()
    assert unpaid == []


async def test_an_unpaid_invoice_can_be_voided_and_then_takes_no_payment(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    await deliver(client, f, trip_id)
    inv = await invoice_of(client, f, trip_id)
    voided = await client.post(f"/invoices/{inv['id']}/void", headers=bearer(f.owner), json={"reason": "Raised in error"})
    assert voided.json()["status"] == "void" and voided.json()["balance_cents"] == 0
    assert (await client.post(f"/invoices/{inv['id']}/payments", headers=bearer(f.owner), json={"amount_cents": 100, "method": "cash"})).status_code == 409


async def test_an_invoice_can_be_sent_by_email_and_whatsapp_with_its_pdf(client):
    from app.report_delivery import fake_sender

    f, c, r = await setup(client, email="accounts@bamburi.example")
    trip_id = await running(client, f, await job_for(client, f, c, r))
    await deliver(client, f, trip_id)
    inv = await invoice_of(client, f, trip_id)
    fake_sender("email").outbox.clear()
    sent = await client.post(f"/invoices/{inv['id']}/send", headers=bearer(f.owner), json={"channel": "email"})
    assert sent.status_code == 200 and sent.json()["sent_via"] == "email"
    [mail] = fake_sender("email").outbox
    assert mail["recipient"] == "accounts@bamburi.example" and mail["pdf"].startswith(b"%PDF") and mail["filename"] == "INV-0001.pdf"


async def test_the_accountant_manages_invoices_but_managers_drivers_and_other_businesses_do_not(client):
    f, c, r = await setup(client)
    trip_id = await running(client, f, await job_for(client, f, c, r))
    await deliver(client, f, trip_id)
    inv = await invoice_of(client, f, trip_id)
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert (await client.get("/invoices", headers=bearer(accountant))).json()[0]["number"] == "INV-0001"
    assert (await client.post(f"/invoices/{inv['id']}/payments", headers=bearer(accountant), json={"amount_cents": 100, "method": "cash"})).status_code == 201
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.get("/invoices", headers=bearer(manager))).status_code == 403
    assert (await client.get(f"/trips/{trip_id}/invoice", headers=bearer(manager))).json() == {"invoice": None}  # the trip page works, without money
    assert (await client.get("/invoices", headers=bearer(f.driver))).status_code == 403
    from tests.helpers import owner_session

    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/invoices", headers=bearer(other))).json() == []
    assert (await client.get(f"/invoices/{inv['id']}", headers=bearer(other))).status_code == 404


async def test_invoice_numbers_count_up_per_business(client):
    f, c, r = await setup(client)
    numbers = []
    for _ in range(2):
        job = await job_for(client, f, c, r)
        trip_id = await running(client, f, job)
        await deliver(client, f, trip_id)
        numbers.append((await invoice_of(client, f, trip_id))["number"])
        await client.post(f"/trips/{trip_id}/end", headers=bearer(f.driver), json={"photo_id": await photo_id(client, f.driver, "odometer"), "value": 125580 + 500 * len(numbers)})
    assert numbers == ["INV-0001", "INV-0002"]


async def test_the_dashboard_warns_of_overloads_odd_deliveries_and_uninvoiced_trips(client):
    from tests.test_dashboard import dash, kinds

    f, c, r = await setup(client, method="per_tonne", rate=300000)
    await client.put(f"/vehicles/{f.vehicle['id']}", headers=bearer(f.owner), json={**f.vehicle, "tare_kg": 6000})
    job = await job_for(client, f, c, r, billing_method="per_tonne", rate_cents=300000, weight_tonnes="28", trips=2)
    first = await running(client, f, job)
    await load(client, f, first, kg=12000)
    d = await dash(client, f.owner)
    over = next(a for a in d["alerts"] if a["kind"] == "overload")
    assert over["severity"] == "red" and "2,000 kg over" in over["title"]
    await load(client, f, first, kg=9000)
    assert "overload" not in kinds(await dash(client, f.owner))  # reweighed within the limit
    await deliver(client, f, first, lat=-1.40, lng=36.95)
    from sqlalchemy import text

    from app.db import get_engine

    async with get_engine().begin() as conn:
        await conn.execute(text("DELETE FROM invoice_lines"))
        await conn.execute(text("DELETE FROM invoices"))
    got = kinds(await dash(client, f.owner))
    assert "pod_flagged" in got and "not_invoiced" in got
    accountant, _ = await staff_session(client, f.owner, "accountant", "acc@example.com")
    assert "not_invoiced" in kinds(await dash(client, accountant)) and "pod_flagged" not in kinds(await dash(client, accountant))
