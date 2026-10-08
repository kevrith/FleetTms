from datetime import date, timedelta

from app.reminders import send_document_reminders
from app.sms import get_sms_sender
from tests.fleet import add_vehicle
from tests.helpers import bearer, driver_session, owner_session

TODAY = date(2026, 10, 1)


async def owner_with_phone(client):
    owner, _ = await owner_session(client)
    # Reminders go to owners and managers with a phone number, so give the owner one via a second owner login.
    from sqlalchemy import update

    from app.db import get_sessionmaker
    from app.models import User

    async with get_sessionmaker()() as db:
        await db.execute(update(User).where(User.email == "owner@example.com").values(phone="+254700111222"))
        await db.commit()
    return owner


async def add_doc(client, owner, vehicle_id, expires, doc_type="insurance"):
    res = await client.post(
        "/documents", headers=bearer(owner),
        json={"doc_type": doc_type, "vehicle_id": vehicle_id, "expires_on": expires.isoformat(), "reference": "POL-1"},
    )  # fmt: skip
    assert res.status_code == 201, res.text
    return res.json()


async def test_document_crud_and_rules(client):
    owner, _ = await owner_session(client)
    v = await add_vehicle(client, owner)
    doc = await add_doc(client, owner, v["id"], TODAY + timedelta(days=60))
    listed = (await client.get(f"/documents?vehicle_id={v['id']}", headers=bearer(owner))).json()
    assert [d["id"] for d in listed] == [doc["id"]]

    # A driving licence cannot sit on a vehicle, and an insurance cannot sit on a person.
    bad = await client.post(
        "/documents", headers=bearer(owner),
        json={"doc_type": "driving_licence", "vehicle_id": v["id"], "expires_on": "2027-01-01"},
    )  # fmt: skip
    assert bad.status_code == 422
    backwards = await client.post(
        "/documents", headers=bearer(owner),
        json={"doc_type": "insurance", "vehicle_id": v["id"], "issued_on": "2027-01-02", "expires_on": "2027-01-01"},
    )  # fmt: skip
    assert backwards.status_code == 422

    renewed = await client.put(
        f"/documents/{doc['id']}", headers=bearer(owner),
        json={"doc_type": "insurance", "vehicle_id": v["id"], "expires_on": "2028-01-01"},
    )  # fmt: skip
    assert renewed.json()["expires_on"] == "2028-01-01"
    assert (await client.delete(f"/documents/{doc['id']}", headers=bearer(owner))).status_code == 204
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    assert {"document.created", "document.updated", "document.deleted"} <= set(actions)


async def test_staff_licence_document(client):
    owner, _ = await owner_session(client)
    await driver_session(client, owner, "0712345678")
    member = (await client.get("/staff", headers=bearer(owner))).json()[-1]["membership_id"]
    res = await client.post(
        "/documents", headers=bearer(owner),
        json={"doc_type": "driving_licence", "membership_id": member, "expires_on": "2027-06-30"},
    )  # fmt: skip
    assert res.status_code == 201


async def test_documents_are_isolated_between_businesses(client):
    a, _ = await owner_session(client, "Alpha", "a@example.com")
    b, _ = await owner_session(client, "Bravo", "b@example.com")
    v = await add_vehicle(client, b)
    doc = await add_doc(client, b, v["id"], TODAY)
    assert (await client.get(f"/documents?vehicle_id={v['id']}", headers=bearer(a))).status_code == 404
    assert (await client.delete(f"/documents/{doc['id']}", headers=bearer(a))).status_code == 404
    assert (await client.get("/documents/expiring?days=365", headers=bearer(a))).json() == []


async def test_expiring_list_is_soonest_first_and_includes_expired(client, monkeypatch):
    monkeypatch.setattr("app.routers.documents.nairobi_today", lambda: TODAY)
    owner, _ = await owner_session(client)
    v = await add_vehicle(client, owner)
    await add_doc(client, owner, v["id"], TODAY + timedelta(days=10), "inspection")
    await add_doc(client, owner, v["id"], TODAY - timedelta(days=3), "insurance")
    await add_doc(client, owner, v["id"], TODAY + timedelta(days=200), "permit")
    rows = (await client.get("/documents/expiring?days=30", headers=bearer(owner))).json()
    assert [r["doc_type"] for r in rows] == ["insurance", "inspection"]


async def test_reminders_fire_at_60_30_14_7_and_1_days_and_only_once(client):
    owner = await owner_with_phone(client)
    v = await add_vehicle(client, owner, "KCA 123A")
    expiry = TODAY + timedelta(days=60)
    await add_doc(client, owner, v["id"], expiry)
    outbox = get_sms_sender().outbox
    on = lambda days_out: send_document_reminders(expiry - timedelta(days=days_out))

    assert await on(61) == 0  # too early
    assert await on(60) == 1
    assert "KCA 123A" in outbox[-1][1] and "60 days" in outbox[-1][1]
    assert await on(60) == 0  # same day again: no repeat
    assert await on(45) == 0  # nothing due between reminders
    assert await on(30) == 1
    assert await on(15) == 0
    assert await on(14) == 1
    assert await on(7) == 1
    assert await on(6) == 0  # already covered
    assert await on(1) == 1
    assert await on(0) == 0  # the last one went the day before
    assert len(outbox) == 5


async def test_missed_days_send_one_message_not_a_burst(client):
    owner = await owner_with_phone(client)
    v = await add_vehicle(client, owner)
    await add_doc(client, owner, v["id"], TODAY + timedelta(days=5))
    assert await send_document_reminders(TODAY) == 1  # the 60, 30, 14 and 7 day reminders are covered by this one
    assert await send_document_reminders(TODAY + timedelta(days=1)) == 0


async def test_expired_documents_get_no_reminder_and_renewal_starts_fresh(client):
    owner = await owner_with_phone(client)
    v = await add_vehicle(client, owner)
    doc = await add_doc(client, owner, v["id"], TODAY + timedelta(days=7))
    assert await send_document_reminders(TODAY) == 1
    assert await send_document_reminders(TODAY + timedelta(days=8)) == 0  # expired yesterday

    await client.put(
        f"/documents/{doc['id']}", headers=bearer(owner),
        json={"doc_type": "insurance", "vehicle_id": v["id"], "expires_on": (TODAY + timedelta(days=37)).isoformat()},
    )  # fmt: skip
    assert await send_document_reminders(TODAY + timedelta(days=7)) == 1  # the renewed document is due again


async def test_reminders_never_cross_businesses(client):
    owner_a = await owner_with_phone(client)
    b, _ = await owner_session(client, "Bravo", "b@example.com")
    vb = await add_vehicle(client, b, "KBB 001B")
    await add_doc(client, b, vb["id"], TODAY + timedelta(days=7))
    # Business B has no phone to notify, and A's owner must not receive B's reminder.
    await send_document_reminders(TODAY)
    assert get_sms_sender().outbox == []
    del owner_a
