"""A renewal is sent with its proof and changes nothing until a manager or the owner approves it."""

from datetime import date, timedelta

import pytest

from app.reminders import nairobi_today
from app.renewal_rules import problem
from tests.helpers import bearer, staff_session
from tests.shots import fleet, inspect, make_trip, photo_id, start, upload
from tests.test_clearance import document, set_rule

TODAY = date(2026, 10, 11)
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


@pytest.mark.parametrize(
    ("doc", "proof", "new", "current", "expected"),
    [
        ("driving_licence", "receipt", date(2029, 10, 1), date(2026, 9, 1), None),  # the three-year renewal, paid, no card yet
        ("driving_licence", "digital_licence", date(2027, 9, 1), date(2026, 9, 1), None),  # the one-year renewal NTSA sends
        ("driving_licence", "certificate", date(2027, 9, 1), None, "needs the digital licence or the payment receipt"),
        ("insurance", "receipt", date(2027, 9, 1), None, "needs the certificate"),
        ("insurance", "certificate", date(2026, 10, 11), None, "must be in the future"),
        ("insurance", "certificate", date(2027, 1, 1), date(2027, 6, 1), "not later than the date on record"),
        ("insurance", "certificate", date(2029, 1, 1), None, "too far ahead"),
        ("driving_licence", "receipt", date(2031, 1, 1), None, "too far ahead"),
    ],
)
def test_problem(doc, proof, new, current, expected):
    got = problem(doc_type=doc, proof_kind=proof, new_expires_on=new, current_expires_on=current, today=TODAY)
    assert (got is None) if expected is None else (expected in got)


async def document_photo(client, who, data=None):
    res = await upload(client, who, "document", data=data, source="camera", captured_at=None, lat=None, lng=None)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def licence_renewal(f, photo, days=1000, proof="receipt", **extra):
    return {"doc_type": "driving_licence", "membership_id": f.ids["+254712345678"], "new_expires_on": (nairobi_today() + timedelta(days=days)).isoformat(), "proof_kind": proof, "reference": "ECIT-8841", "photo_id": photo, **extra}


async def test_a_driver_sends_the_receipt_a_manager_approves_and_the_blocked_trip_can_start(client):
    f = await fleet(client)
    await set_rule(client, f)
    await document(client, f, "insurance", 90)
    await document(client, f, "driving_licence", -2, driver=True)  # the licence ran out
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await inspect(client, f.driver, f.vehicle["id"])).status_code == 201
    trip = await make_trip(client, f)
    assert (await start(client, f.driver, trip["id"])).status_code == 409

    sent = await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, await document_photo(client, f.driver)))
    assert sent.status_code == 201, sent.text
    renewal = sent.json()
    assert renewal["status"] == "pending" and renewal["subject"] and renewal["proof"]["url"] and renewal["current_expires_on"]
    assert (await start(client, f.driver, trip["id"])).status_code == 409  # a date typed in changes nothing until it is approved
    assert [r["id"] for r in (await client.get("/renewals", headers=bearer(manager))).json()] == [renewal["id"]]

    assert (await client.post(f"/renewals/{renewal['id']}/approve", headers=bearer(f.driver), json={})).status_code == 403
    done = await client.post(f"/renewals/{renewal['id']}/approve", headers=bearer(manager), json={"note": "Receipt checked on eCitizen"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "approved"
    assert (await client.post(f"/renewals/{renewal['id']}/approve", headers=bearer(manager), json={})).status_code == 409  # decided once
    assert (await start(client, f.driver, trip["id"])).status_code == 200
    # the licence on record now carries the new date, and the audit trail says why
    staff_docs = (await client.get(f"/documents?membership_id={f.ids['+254712345678']}", headers=bearer(f.owner))).json()
    assert any(d["doc_type"] == "driving_licence" and d["expires_on"] > nairobi_today().isoformat() for d in staff_docs)


async def test_a_rejected_renewal_changes_nothing_and_can_be_sent_again(client):
    f = await fleet(client)
    await set_rule(client, f)
    await document(client, f, "driving_licence", -2, driver=True)
    first = (await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, await document_photo(client, f.driver)))).json()
    assert (await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, await document_photo(client, f.driver)))).status_code == 409  # one at a time
    assert (await client.post(f"/renewals/{first['id']}/reject", headers=bearer(f.owner), json={"note": "x"})).status_code == 422  # a reason is needed
    assert (await client.post(f"/renewals/{first['id']}/reject", headers=bearer(f.owner), json={"note": "Receipt is for someone else"})).json()["status"] == "rejected"
    mine = (await client.get("/renewals?status=all", headers=bearer(f.driver))).json()
    assert [r["status"] for r in mine] == ["rejected"] and mine[0]["decision_note"] == "Receipt is for someone else"
    again = await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, await document_photo(client, f.driver)))
    assert again.status_code == 201


async def test_the_proof_and_the_date_are_checked_before_a_manager_is_asked(client):
    f = await fleet(client)
    photo = await document_photo(client, f.driver)
    assert (await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, photo, proof="certificate"))).json()["detail"]["code"] == "renewal_invalid"
    assert (await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, photo, days=-5))).status_code == 422
    assert (await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, photo, days=4000))).status_code == 422
    other = await document_photo(client, f.owner)  # someone else's file cannot be used as proof
    assert (await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, other))).json()["detail"]["code"] == "photo_invalid"
    odd = await client.post("/renewals", headers=bearer(f.driver), json={**licence_renewal(f, photo), "vehicle_id": f.vehicle["id"]})
    assert odd.status_code == 422  # a person and a vehicle at once


async def test_a_driver_can_only_renew_their_own_licence(client):
    f = await fleet(client)
    photo = await document_photo(client, f.turnboy)
    theirs = {**licence_renewal(f, photo), "membership_id": f.ids["+254712345678"]}
    res = await client.post("/renewals", headers=bearer(f.turnboy), json=theirs)
    assert res.status_code == 403
    own = await client.post("/renewals", headers=bearer(f.driver), json={**licence_renewal(f, await document_photo(client, f.driver))})
    assert own.status_code == 201
    assert (await client.get("/renewals", headers=bearer(f.turnboy))).json() == []  # the turnboy sees none of the driver's


async def test_an_insurance_certificate_may_be_a_pdf_and_the_owners_own_renewal_is_approved_at_once(client):
    f = await fleet(client)
    await document(client, f, "insurance", -10)
    pdf = await document_photo(client, f.owner, data=PDF)
    res = await client.post("/renewals", headers=bearer(f.owner), json={"doc_type": "insurance", "vehicle_id": f.vehicle["id"], "new_expires_on": (nairobi_today() + timedelta(days=360)).isoformat(), "proof_kind": "certificate", "reference": "POL-77", "photo_id": pdf})
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "approved" and res.json()["proof"]["is_pdf"] is True
    cell = next(r for r in (await client.get("/documents/compliance", headers=bearer(f.owner))).json() if r["registration"] == "KCA 123A")
    assert cell["insurance"]["status"] != "expired"


async def test_a_pdf_must_be_whole_and_only_documents_may_be_pdfs(client):
    f = await fleet(client)
    cut = await upload(client, f.driver, "document", data=b"%PDF-1.4\n1 0 obj", source="camera", captured_at=None, lat=None, lng=None)
    assert cut.status_code == 422
    other = await upload(client, f.driver, "odometer", data=PDF)
    assert other.status_code == 422  # a PDF is no odometer photo


async def test_a_manager_cannot_approve_their_own_renewal(client):
    f = await fleet(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    mine = await client.post("/renewals", headers=bearer(manager), json={"doc_type": "insurance", "vehicle_id": f.vehicle["id"], "new_expires_on": (nairobi_today() + timedelta(days=300)).isoformat(), "proof_kind": "certificate", "photo_id": await document_photo(client, manager)})
    assert mine.status_code == 201 and mine.json()["status"] == "pending"
    assert (await client.post(f"/renewals/{mine.json()['id']}/approve", headers=bearer(manager), json={})).json()["detail"]["code"] == "own_renewal"
    assert (await client.post(f"/renewals/{mine.json()['id']}/approve", headers=bearer(f.owner), json={})).status_code == 200


async def test_one_business_never_sees_anothers_renewals(client):
    from tests.helpers import owner_session

    f = await fleet(client)
    await client.post("/renewals", headers=bearer(f.driver), json=licence_renewal(f, await document_photo(client, f.driver)))
    other, _ = await owner_session(client, business="Other Haulage", email="someone.else@example.com")
    assert (await client.get("/renewals?status=all", headers=bearer(other))).json() == []
    assert photo_id  # imported for the shared helpers


async def test_a_drivers_phone_sends_the_renewal_through_the_offline_queue_and_the_manager_is_told(client):
    from app.sms import get_sms_sender
    from tests.shots import ago, sync

    f = await fleet(client)
    await document(client, f, "driving_licence", -2, driver=True)
    outbox = get_sms_sender().outbox
    outbox.clear()
    from uuid import uuid4

    client_id, action_id = uuid4(), uuid4()
    res = await upload(client, f.driver, "document", source="camera", captured_at=None, lat=None, lng=None, client_id=client_id)
    assert res.status_code == 201, res.text
    payload = {"doc_type": "driving_licence", "new_expires_on": (nairobi_today() + timedelta(days=1000)).isoformat(), "proof_kind": "receipt", "reference": "ECIT-1", "photo_client_id": str(client_id)}
    done = await sync(client, f.driver, [{"client_id": str(action_id), "type": "renewal.submit", "captured_at": ago(minutes=5), "payload": payload}])
    assert done.status_code == 200, done.text
    assert done.json()["results"][0]["status"] == "ok", done.json()
    pending = (await client.get("/renewals", headers=bearer(f.owner))).json()
    assert len(pending) == 1 and pending[0]["subject"] and pending[0]["reference"] == "ECIT-1"
    again = await sync(client, f.driver, [{"client_id": str(action_id), "type": "renewal.submit", "captured_at": ago(minutes=5), "payload": payload}])
    assert again.json()["results"][0]["status"] == "duplicate"  # a resend after a lost reply makes no second renewal
    assert len((await client.get("/renewals", headers=bearer(f.owner))).json()) == 1
