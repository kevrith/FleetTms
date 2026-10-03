import csv
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app import data_export, storage
from app.models import DataExport
from tests.billing_helpers import days, set_dates
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import in_db
from tests.shots import fleet, photo_id
from tests.test_clients import add_client, add_route


async def make_export(client, who, **body):
    res = await client.post("/data-exports", headers=bearer(who), json=body)
    assert res.status_code == 202, res.text
    # the copy is made after the reply is sent; by the time the request returns here, it has run
    state = (await client.get(f"/data-exports/{res.json()['id']}", headers=bearer(who))).json()
    return state


async def open_zip(client, who, export):
    res = await client.get(f"/data-exports/{export['id']}/download", headers=bearer(who))
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip" and res.headers["content-disposition"].startswith('attachment; filename="fleettms-data-')
    return zipfile.ZipFile(io.BytesIO(res.content))


def rows(z, name):
    return list(csv.DictReader(io.StringIO(z.read(name).decode())))


async def test_an_owner_gets_a_zip_of_everything_the_business_has(client):
    f = await fleet(client)
    c = await add_client(client, f.owner)
    await add_route(client, f.owner, c["id"])
    await client.post("/fuel", headers=bearer(f.driver), json={"vehicle_id": f.vehicle["id"], "litres": "100", "price_per_litre_cents": 18000, "amount_cents": 1800000, "station": "Total Mlolongo"})
    export = await make_export(client, f.owner)
    assert export["status"] == "ready" and export["size_bytes"] > 500 and export["expires_at"] and export["error"] is None
    z = await open_zip(client, f.owner, export)
    names = set(z.namelist())
    assert {"vehicles.csv", "clients.csv", "saved_routes.csv", "fuel_entries.csv", "people.csv", "business.csv", "manifest.json", "README.txt"} <= names
    assert [r["registration"] for r in rows(z, "vehicles.csv")] == ["KCA 123A"] and rows(z, "clients.csv")[0]["name"] == "Bamburi Cement"
    fuel = rows(z, "fuel_entries.csv")[0]
    assert fuel["station"] == "Total Mlolongo" and fuel["amount_cents"] == "1800000" and fuel["litres"] == "100.00" and fuel["captured_at"].endswith("+00:00")
    people = rows(z, "people.csv")
    assert len(people) == 3 and {"owner", "driver", "turnboy"} <= {r for p in people for r in p["roles"].split(";")}
    assert rows(z, "business.csv")[0]["name"] == "Kamau Haulage"
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["rows"]["vehicles"] == 1 and manifest["rows"]["fuel_entries"] == 1 and manifest["rows"]["people"] == 3 and manifest["photos"] is None
    readme = z.read("README.txt").decode()
    assert "Kamau Haulage" in readme and "vehicles.csv: 1" in readme and "cents" in readme and "Photos were not included" in readme
    assert export["tables"]["vehicles"] == 1
    actions = [e["action"] for e in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert {"export.requested", "export.downloaded"} <= set(actions)


async def test_no_secret_is_ever_in_the_copy(client):
    f = await fleet(client)
    await client.post("/trips", headers=bearer(f.owner), json={"vehicle_id": f.vehicle["id"], "origin": "A", "destination": "B"})
    export = await make_export(client, f.owner)
    z = await open_zip(client, f.owner, export)
    for name in z.namelist():
        if name.endswith(".csv"):
            header = z.read(name).decode().splitlines()[0].lower()
            assert not any(w in header for w in ("password", "secret", "hash", "totp")), (name, header)
    everything = b"".join(z.read(n) for n in z.namelist()).decode(errors="ignore").lower()
    assert "password_hash" not in everything and "totp_secret" not in everything
    assert "users.csv" not in z.namelist() and "auth_sessions.csv" not in z.namelist()  # accounts are not business records


async def test_photos_are_included_only_when_asked_for(client):
    f = await fleet(client)
    pid = await photo_id(client, f.driver, "receipt")
    plain = await open_zip(client, f.owner, await make_export(client, f.owner))
    assert not [n for n in plain.namelist() if n.startswith("photos/")] and rows(plain, "photos.csv")[0]["id"] == pid
    await in_db(lambda db: db.execute(update(DataExport).values(created_at=datetime.now(UTC) - timedelta(days=2))))  # keeps the daily limit out of the way
    with_photos = await open_zip(client, f.owner, await make_export(client, f.owner, include_photos=True))
    files = [n for n in with_photos.namelist() if n.startswith("photos/")]
    assert files == [f"photos/{pid}.jpg"] and with_photos.read(files[0])[:2] == b"\xff\xd8"
    assert json.loads(with_photos.read("manifest.json"))["photos"] == {"included": 1, "skipped": 0, "bytes": len(with_photos.read(files[0]))} and "1 included in the photos folder" in with_photos.read("README.txt").decode()


async def test_one_business_never_gets_anothers_records(client):
    f = await fleet(client)
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    await add_vehicle(client, other, "KXX 999X")
    first = await make_export(client, f.owner)
    z = await open_zip(client, f.owner, first)
    assert [r["registration"] for r in rows(z, "vehicles.csv")] == ["KCA 123A"]
    theirs = await make_export(client, other)
    assert (await client.get(f"/data-exports/{theirs['id']}/download", headers=bearer(f.owner))).status_code == 404
    assert (await client.get(f"/data-exports/{theirs['id']}", headers=bearer(f.owner))).status_code == 404
    listed = {e["id"] for e in (await client.get("/data-exports", headers=bearer(f.owner))).json()}
    assert listed == {first["id"]}  # their own copy only: Bravo's is not in the list


async def test_the_owner_can_take_their_data_out_even_when_the_account_is_read_only(client, billing):
    f = await fleet(client)
    await set_dates(trial_ends=days(-30))
    assert (await client.post("/depots", headers=bearer(f.owner), json={"name": "X"})).status_code == 402  # nothing can be added ...
    export = await make_export(client, f.owner)  # ... but everything can be taken out
    assert export["status"] == "ready"
    z = await open_zip(client, f.owner, export)
    assert [r["registration"] for r in rows(z, "vehicles.csv")] == ["KCA 123A"]


async def test_only_the_owner_asks_and_only_one_copy_is_made_at_a_time(client):
    f = await fleet(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    for who in (manager, f.driver):
        assert (await client.post("/data-exports", headers=bearer(who), json={})).status_code == 403
        assert (await client.get("/data-exports", headers=bearer(who))).status_code == 403
    assert (await client.post("/data-exports", json={})).status_code == 401

    async def stuck(db):
        db.add(DataExport(status="running"))

    await in_db(stuck)
    again = await client.post("/data-exports", headers=bearer(f.owner), json={})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "export_running"


async def test_there_is_a_limit_on_copies_a_day(client):
    f = await fleet(client)

    async def many(db):
        for _ in range(5):
            db.add(DataExport(status="ready"))

    await in_db(many)
    capped = await client.post("/data-exports", headers=bearer(f.owner), json={})
    assert capped.status_code == 429 and capped.json()["detail"]["code"] == "too_many_exports"


async def test_a_copy_that_is_not_ready_cannot_be_downloaded_and_old_copies_are_deleted(client):
    f = await fleet(client)
    export = await make_export(client, f.owner)
    async def key_of(db):
        return (await db.execute(select(DataExport.storage_key))).scalar_one()

    key = await in_db(key_of)
    assert storage.read_path(key) is not None
    await in_db(lambda db: db.execute(update(DataExport).values(status="running")))
    assert (await client.get(f"/data-exports/{export['id']}/download", headers=bearer(f.owner))).json()["detail"]["code"] == "not_ready"
    await in_db(lambda db: db.execute(update(DataExport).values(status="ready", expires_at=datetime.now(UTC) - timedelta(hours=1))))
    assert await data_export.purge_expired() == 1
    assert storage.read_path(key) is None
    after = (await client.get(f"/data-exports/{export['id']}", headers=bearer(f.owner))).json()
    assert after["status"] == "expired"
    assert (await client.get(f"/data-exports/{export['id']}/download", headers=bearer(f.owner))).json()["detail"]["code"] == "not_ready"
    assert await data_export.purge_expired() == 0


async def test_every_kind_of_record_the_system_keeps_is_covered_by_the_export(client):
    tables = {t.name for t in data_export.tables_to_export()}
    assert {"vehicles", "trips", "fuel_entries", "expenses", "invoices", "mpesa_transactions", "lease_agreements", "payroll_runs", "location_points", "fraud_alerts", "messages", "audit_logs", "photos", "subscriptions"} <= tables
    assert "data_exports" not in tables
