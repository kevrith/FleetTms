"""Insurance and inspection for every vehicle in one list, setting a date from the phone, and the reminder reaching the owner as a push."""

from datetime import timedelta

from sqlalchemy import update

from app import push
from app.models import Vehicle
from app.reminders import nairobi_today, send_document_reminders
from tests.fleet import add_vehicle
from tests.helpers import bearer, driver_session, owner_session, staff_session
from tests.leasing import in_db

TOKEN = "ExponentPushToken[abcdefghijklmnop]"


def on(days: int) -> str:
    return (nairobi_today() + timedelta(days=days)).isoformat()


async def set_date(client, who, vehicle, kind, days, **extra):
    return await client.put(f"/documents/vehicle/{vehicle['id']}/{kind}", headers=bearer(who), json={"expires_on": on(days), **extra})


async def test_the_overview_puts_what_needs_a_person_first_and_includes_what_was_never_recorded(client):
    owner, _ = await owner_session(client)
    fine = await add_vehicle(client, owner, "KAA 111A")
    lapsed = await add_vehicle(client, owner, "KBB 222B")
    bare = await add_vehicle(client, owner, "KCC 333C")
    soon = await add_vehicle(client, owner, "KDD 444D")
    for kind in ("insurance", "inspection"):
        assert (await set_date(client, owner, fine, kind, 200)).status_code == 200
    assert (await set_date(client, owner, lapsed, "insurance", -3)).status_code == 200
    assert (await set_date(client, owner, lapsed, "inspection", 90)).status_code == 200
    assert (await set_date(client, owner, soon, "insurance", 40)).status_code == 200
    assert (await set_date(client, owner, soon, "inspection", 20)).status_code == 200
    rows = (await client.get("/documents/compliance", headers=bearer(owner))).json()
    assert [r["registration"] for r in rows] == ["KBB 222B", "KCC 333C", "KDD 444D", "KAA 111A"]  # expired, never recorded, due soon, fine
    by = {r["registration"]: r for r in rows}
    assert by["KBB 222B"]["insurance"]["status"] == "expired" and by["KBB 222B"]["insurance"]["days_left"] == -3
    assert by["KCC 333C"]["insurance"] == {"id": None, "expires_on": None, "days_left": None, "status": "missing"} and by["KCC 333C"]["inspection"]["status"] == "missing"
    assert by["KDD 444D"]["insurance"]["status"] == "due_soon" and by["KDD 444D"]["inspection"]["days_left"] == 20
    assert by["KAA 111A"]["insurance"]["status"] == "ok" and by["KAA 111A"]["inspection"]["status"] == "ok"
    del bare


async def test_a_sample_vehicle_and_an_inactive_one_are_not_listed(client):
    owner, _ = await owner_session(client)
    sample = await add_vehicle(client, owner, "KSS 000S")
    gone = await add_vehicle(client, owner, "KGG 999G")
    await add_vehicle(client, owner, "KAA 111A")

    async def mark(db):
        await db.execute(update(Vehicle).where(Vehicle.id == sample["id"]).values(is_sample=True))
        await db.execute(update(Vehicle).where(Vehicle.id == gone["id"]).values(is_active=False))
        await db.commit()

    await in_db(mark)
    assert [r["registration"] for r in (await client.get("/documents/compliance", headers=bearer(owner))).json()] == ["KAA 111A"]


async def test_setting_a_date_makes_the_document_then_changes_the_same_one_and_is_audited(client):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KAA 111A")
    first = await set_date(client, owner, vehicle, "insurance", 30, reference="POL-123")
    assert first.status_code == 200 and first.json()["reference"] == "POL-123"
    renewed = await set_date(client, owner, vehicle, "insurance", 395)
    assert renewed.status_code == 200 and renewed.json()["id"] == first.json()["id"] and renewed.json()["reference"] == "POL-123"
    docs = (await client.get(f"/documents?vehicle_id={vehicle['id']}", headers=bearer(owner))).json()
    assert [(d["doc_type"], d["expires_on"]) for d in docs] == [("insurance", on(395))]
    assert "document.updated" in str((await client.get("/audit", headers=bearer(owner))).json())


async def test_only_insurance_and_inspection_with_a_sensible_date_and_only_for_people_who_manage_vehicles(client):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KAA 111A")
    assert (await set_date(client, owner, vehicle, "permit", 30)).status_code == 422
    assert (await set_date(client, owner, vehicle, "insurance", 20_000)).status_code == 422
    driver = await driver_session(client, owner, "0712345678")
    assert (await set_date(client, driver, vehicle, "insurance", 30)).status_code == 403
    assert (await client.get("/documents/compliance", headers=bearer(driver))).status_code == 403
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await set_date(client, accountant, vehicle, "insurance", 30)).status_code == 403


async def test_an_expiry_reminder_also_reaches_the_owners_phone_as_a_push(client, monkeypatch):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KAA 111A")
    sent: list[dict] = []

    async def capture(messages):
        sent.extend(messages)

    monkeypatch.setattr(push, "_post", capture)
    assert (await client.put("/me/push-token", headers=bearer(owner), json={"token": TOKEN})).status_code == 204
    await set_date(client, owner, vehicle, "insurance", 59)
    assert await send_document_reminders(nairobi_today()) == 0  # no phone number to text, so no text; the push still goes
    assert [m["to"] for m in sent] == [TOKEN]
    assert "KAA 111A" in sent[0]["title"] and "Insurance" in sent[0]["title"] and sent[0]["data"]["type"] == "document"
    sent.clear()
    assert await send_document_reminders(nairobi_today()) == 0 and sent == []  # not again the same day


async def test_a_lapsed_document_is_pushed_every_day_until_it_is_renewed_and_an_old_one_is_not(client, monkeypatch):
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KAA 111A")
    sent: list[dict] = []

    async def capture(messages):
        sent.extend(messages)

    monkeypatch.setattr(push, "_post", capture)
    await client.put("/me/push-token", headers=bearer(owner), json={"token": TOKEN})
    await set_date(client, owner, vehicle, "insurance", -2)
    today = nairobi_today()
    await send_document_reminders(today)
    assert len(sent) == 1 and "has expired" in sent[0]["title"] and "2 days ago" in sent[0]["body"]
    await send_document_reminders(today)
    assert len(sent) == 1  # once a day
    await send_document_reminders(today + timedelta(days=1))
    assert len(sent) == 2 and "3 days ago" in sent[1]["body"]
    await send_document_reminders(today + timedelta(days=40))
    assert len(sent) == 2  # a month of it is enough
    # A renewal recorded as a new document leaves the old one behind: it must not be nagged about.
    await client.post("/documents", headers=bearer(owner), json={"doc_type": "insurance", "vehicle_id": vehicle["id"], "expires_on": on(365)})
    await send_document_reminders(today + timedelta(days=2))
    assert len(sent) == 2


async def test_the_home_screen_carries_a_deadline_for_what_is_close_or_lapsed_and_not_for_what_was_renewed(client):
    owner, _ = await owner_session(client)
    soon, lapsed, fine, bare = [await add_vehicle(client, owner, p) for p in ("KAA 111A", "KBB 222B", "KCC 333C", "KDD 444D")]
    assert (await set_date(client, owner, soon, "insurance", 10)).status_code == 200
    assert (await set_date(client, owner, lapsed, "inspection", -5)).status_code == 200
    for kind in ("insurance", "inspection"):
        assert (await set_date(client, owner, fine, kind, 300)).status_code == 200
    await set_date(client, owner, soon, "inspection", 100)
    await set_date(client, owner, lapsed, "insurance", 100)
    # An old inspection left behind for the lapsed vehicle, after a renewal made as a new document:
    await client.post("/documents", headers=bearer(owner), json={"doc_type": "inspection", "vehicle_id": lapsed["id"], "expires_on": on(200)})
    dash = (await client.get("/dashboard", headers=bearer(owner))).json()
    assert [(d["registration"], d["kind"], d["level"]) for d in dash["deadlines"]] == [("KAA 111A", "insurance", "urgent")]
    kinds = [a["kind"] for a in dash["alerts"]]
    assert "document_expired" not in kinds  # the old record is not a red alert once renewed
    missing = next(a for a in dash["alerts"] if a["kind"] == "documents_missing")
    assert missing["title"].startswith("1 vehicle with no insurance") and missing["link"] == "/compliance"
    del bare
