"""A person's data protection requests to their employer: asking, the clock, the copy, deletion and refusal."""

import io
import uuid
import zipfile
from datetime import timedelta

from sqlalchemy import update

from app.config import settings
from app.db import get_sessionmaker
from app.models import DataSubjectRequest, LocationPoint
from app.reminders import nairobi_today
from app.tenancy import current_business_id
from tests.helpers import bearer, owner_session, staff_session
from tests.shots import begin_trip, fleet


async def raise_request(client, who, kind="access", details=None):
    res = await client.post("/me/data-requests", headers=bearer(who), json={"kind": kind, "details": details})
    assert res.status_code == 201, res.text
    return res.json()


async def business_of(client, tokens):
    return uuid.UUID((await client.get("/auth/me", headers=bearer(tokens))).json()["business"]["id"])


def names_in(zip_bytes):
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    return zf, set(zf.namelist())


async def test_a_driver_asks_to_see_their_data_and_the_owner_sees_it_with_the_date_it_is_due(client):
    f = await fleet(client)
    mine = await raise_request(client, f.driver, "access", "I would like a copy of what you hold about me.")
    assert mine["status"] == "open" and mine["due_on"] == (nairobi_today() + timedelta(days=settings.dsar_due_days)).isoformat() and mine["overdue"] is False
    rows = (await client.get("/data-requests", headers=bearer(f.owner))).json()
    assert [(r["kind"], r["person"], r["days_left"]) for r in rows] == [("access", "driver user", settings.dsar_due_days)]
    assert (await client.get("/data-requests/summary", headers=bearer(f.owner))).json() == {"open": 1, "overdue": 0, "answer_within_days": settings.dsar_due_days}
    assert [r["id"] for r in (await client.get("/me/data-requests", headers=bearer(f.driver))).json()] == [mine["id"]]
    assert (await client.get("/me/data-requests", headers=bearer(f.turnboy))).json() == []  # nobody sees anyone else's
    assert "privacy.request_made" in [a["action"] for a in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_a_request_not_answered_in_time_shows_as_overdue(client):
    f = await fleet(client)
    mine = await raise_request(client, f.driver, "correct", "My licence number is wrong.")
    bid = await business_of(client, f.owner)
    async with get_sessionmaker()() as db:
        current_business_id.set(bid)
        await db.execute(update(DataSubjectRequest).values(due_on=nairobi_today() - timedelta(days=2)))
        await db.commit()
        current_business_id.set(None)
    row = (await client.get("/data-requests", headers=bearer(f.owner))).json()[0]
    assert row["overdue"] is True and row["days_left"] == -2 and row["id"] == mine["id"]
    assert (await client.get("/data-requests/summary", headers=bearer(f.owner))).json()["overdue"] == 1


async def test_the_copy_holds_everything_about_that_person_and_nothing_about_anyone_else_or_any_secret(client):
    f = await fleet(client)
    bid = await business_of(client, f.owner)
    trip = await begin_trip(client, f)
    assert (await client.post("/expenses", headers=bearer(f.driver), json={"category": "toll", "amount_cents": 50_000, "vehicle_id": f.vehicle["id"], "trip_id": trip["id"]})).status_code == 201
    assert (await client.post("/expenses", headers=bearer(f.turnboy), json={"category": "parking", "amount_cents": 20_000, "vehicle_id": f.vehicle["id"], "trip_id": trip["id"]})).status_code == 201
    driver_user = (await client.get("/auth/me", headers=bearer(f.driver))).json()["user"]["id"]
    async with get_sessionmaker()() as db:
        current_business_id.set(bid)
        db.add(LocationPoint(recorded_at=trip_start(), vehicle_id=uuid.UUID(f.vehicle["id"]), trip_id=uuid.UUID(trip["id"]), user_id=uuid.UUID(driver_user), lat=-1.3, lng=36.8))
        await db.commit()
        current_business_id.set(None)
    other, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    await client.post("/depots", headers=bearer(other), json={"name": "Bravo Yard"})

    request = await raise_request(client, f.driver, "portability")
    res = await client.get(f"/data-requests/{request['id']}/export", headers=bearer(f.owner))
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    zf, files = names_in(res.content)
    assert {"users.csv", "memberships.csv", "expenses.csv", "location_points.csv", "audit_logs.csv", "manifest.json", "README.txt"} <= files
    users = zf.read("users.csv").decode()
    assert "driver user" in users and "turnboy user" not in users and "+254712345678" in users
    expenses = zf.read("expenses.csv").decode()
    assert "50000" in expenses and "20000" not in expenses  # their toll, not the turnboy's parking
    everything = " ".join(zf.read(n).decode(errors="ignore") for n in files)
    for secret in ("password_hash", "totp_secret", "refresh_hash", "code_hash", "Bravo"):
        assert secret not in everything
    assert "privacy.person_data_exported" in [a["action"] for a in (await client.get("/audit", headers=bearer(f.owner))).json()]


def trip_start():
    from datetime import UTC, datetime

    return datetime.now(UTC) - timedelta(hours=1)


async def test_a_request_to_delete_removes_the_person_but_not_the_work_they_did(client):
    f = await fleet(client)
    trip = await begin_trip(client, f)
    assert (await client.post("/expenses", headers=bearer(f.driver), json={"category": "toll", "amount_cents": 50_000, "vehicle_id": f.vehicle["id"], "trip_id": trip["id"]})).status_code == 201
    request = await raise_request(client, f.driver, "delete", "I have left. Please delete my data.")
    rid = request["id"]
    early = await client.post(f"/data-requests/{rid}/complete", headers=bearer(f.owner), json={"resolution": "Done"})
    assert early.status_code == 409 and early.json()["detail"]["code"] == "not_applied"
    done = await client.post(f"/data-requests/{rid}/apply-deletion", headers=bearer(f.owner))
    assert done.status_code == 200 and done.json() == {"removed": True, "anonymous": True}
    assert (await client.get("/auth/me", headers=bearer(f.driver))).status_code in (401, 403)  # signed out everywhere
    staff = (await client.get("/staff", headers=bearer(f.owner))).json()
    assert "driver user" not in [s["name"] for s in staff] and "+254712345678" not in [s["phone"] for s in staff]
    assert len((await client.get("/expenses", headers=bearer(f.owner))).json()) == 1  # their toll payment is still the business's record
    closed = await client.post(f"/data-requests/{rid}/complete", headers=bearer(f.owner), json={"resolution": "Staff details removed and the person made anonymous."})
    assert closed.status_code == 200 and closed.json()["status"] == "completed"
    assert (await client.post(f"/data-requests/{rid}/complete", headers=bearer(f.owner), json={"resolution": "Again"})).status_code == 409
    actions = [a["action"] for a in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert "privacy.person_removed" in actions and "privacy.request_completed" in actions


async def test_the_only_owner_cannot_be_removed_and_only_a_delete_request_can_remove_someone(client):
    owner, _ = await owner_session(client)
    mine = await raise_request(client, owner, "delete")
    refused = await client.post(f"/data-requests/{mine['id']}/apply-deletion", headers=bearer(owner))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "last_owner"
    asked_to_see = await raise_request(client, owner, "access")
    assert (await client.post(f"/data-requests/{asked_to_see['id']}/apply-deletion", headers=bearer(owner))).json()["detail"]["code"] == "not_a_deletion"


async def test_a_refusal_needs_a_reason_and_the_person_can_read_it(client):
    f = await fleet(client)
    request = await raise_request(client, f.driver, "delete", "Delete everything.")
    assert (await client.post(f"/data-requests/{request['id']}/refuse", headers=bearer(f.owner), json={"reason": "No"})).status_code == 422
    reason = "Fuel and expense records must be kept for five years under tax law; the rest was removed."
    refused = await client.post(f"/data-requests/{request['id']}/refuse", headers=bearer(f.owner), json={"reason": reason})
    assert refused.status_code == 200 and refused.json()["status"] == "refused"
    mine = (await client.get("/me/data-requests", headers=bearer(f.driver))).json()[0]
    assert mine["status"] == "refused" and mine["resolution"] == reason
    assert (await client.post(f"/data-requests/{request['id']}/refuse", headers=bearer(f.owner), json={"reason": reason})).status_code == 409


async def test_an_owner_can_record_a_request_made_in_person_so_the_clock_starts(client):
    f = await fleet(client)
    res = await client.post("/data-requests", headers=bearer(f.owner), json={"kind": "object", "details": "Does not want to be tracked after hours.", "membership_id": f.ids["+254722345678"]})
    assert res.status_code == 201 and res.json()["person"] == "turnboy user"
    assert (await client.post("/data-requests", headers=bearer(f.owner), json={"kind": "access", "membership_id": str(uuid.uuid4())})).status_code == 404
    assert "privacy.request_logged" in [a["action"] for a in (await client.get("/audit", headers=bearer(f.owner))).json()]


async def test_only_the_owner_answers_requests_and_no_other_business_can_see_them(client):
    f = await fleet(client)
    request = await raise_request(client, f.driver, "access")
    manager, _ = await staff_session(client, f.owner, "manager", "manager@example.com", with_2fa=True)
    rid = request["id"]
    for who in (manager, f.driver, f.turnboy):
        assert (await client.get("/data-requests", headers=bearer(who))).status_code == 403
        assert (await client.get(f"/data-requests/{rid}/export", headers=bearer(who))).status_code == 403
        assert (await client.post(f"/data-requests/{rid}/complete", headers=bearer(who), json={"resolution": "Done"})).status_code == 403
    other, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    assert (await client.get("/data-requests", headers=bearer(other))).json() == []
    assert (await client.get(f"/data-requests/{rid}/export", headers=bearer(other))).status_code == 404
    assert (await client.post(f"/data-requests/{rid}/refuse", headers=bearer(other), json={"reason": "Not yours to answer at all."})).status_code == 404


async def test_people_can_use_their_rights_even_when_the_account_is_read_only(client, billing):
    f = await fleet(client)
    assert (await client.post("/subscription/cancel", headers=bearer(f.owner), json={})).status_code == 200
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "Yard"})).status_code == 402  # really read-only
    request = await raise_request(client, f.driver, "access")
    assert (await client.get(f"/data-requests/{request['id']}/export", headers=bearer(f.owner))).status_code == 200
    assert (await client.post(f"/data-requests/{request['id']}/complete", headers=bearer(f.owner), json={"resolution": "Copy given."})).status_code == 200
