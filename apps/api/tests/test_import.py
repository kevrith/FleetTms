import io

from openpyxl import Workbook

from app.routers.imports import STAFF_COLUMNS, VEHICLE_COLUMNS
from tests.helpers import bearer, owner_session, staff_session

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def workbook(columns, rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(columns)
    for r in rows:
        ws.append([r.get(c) for c in columns])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def vehicle_row(i, **extra):
    return {"registration": f"KCA {100 + i}A", "make": "Isuzu", "capacity_tonnes": 10, "tank_litres": 200,
            "odometer_km": 1000 * i, "ownership_type": "owned", **extra}  # fmt: skip


async def upload(client, tokens, kind, content, dry_run=False):
    return await client.post(
        f"/imports/{kind}?dry_run={str(dry_run).lower()}", headers=bearer(tokens),
        files={"file": ("data.xlsx", content, XLSX)},
    )  # fmt: skip


async def test_twenty_vehicles_import_cleanly(client):
    owner, _ = await owner_session(client)
    await client.post("/depots", headers=bearer(owner), json={"name": "Nairobi Yard"})
    rows = [vehicle_row(i, depot="nairobi yard") for i in range(20)]
    rows[3].update(ownership_type="leased in", lessor_lender_lessee="Wanjiku Transporters")
    rows[4].update(ownership_type="asset financed", lessor_lender_lessee="Equity Bank")
    res = await upload(client, owner, "vehicles", workbook(VEHICLE_COLUMNS, rows))
    assert res.status_code == 200, res.text
    assert res.json()["imported"] == 20 and res.json()["errors"] == []

    vehicles = (await client.get("/vehicles", headers=bearer(owner))).json()
    assert len(vehicles) == 20
    by_reg = {v["registration"]: v for v in vehicles}
    assert by_reg["KCA 103A"]["ownership_type"] == "leased_in"
    parties = {p["name"]: p["kind"] for p in (await client.get("/parties", headers=bearer(owner))).json()}
    assert parties == {"Wanjiku Transporters": "lessor", "Equity Bank": "lender"}


async def test_bad_rows_are_reported_and_nothing_is_imported(client):
    owner, _ = await owner_session(client)
    rows = [vehicle_row(i) for i in range(5)]
    rows[1]["capacity_tonnes"] = "heavy"
    rows[2]["registration"] = rows[0]["registration"]  # duplicate inside the file
    rows[3]["depot"] = "Nowhere"
    rows[4]["ownership_type"] = "leased in"  # no lessor named
    res = await upload(client, owner, "vehicles", workbook(VEHICLE_COLUMNS, rows))
    body = res.json()
    assert body["imported"] == 0
    assert {(e["row"], e["column"]) for e in body["errors"]} == {
        (3, "capacity_tonnes"), (4, "registration"), (5, "depot"), (6, "lessor_lender_lessee"),
    }  # fmt: skip
    assert (await client.get("/vehicles", headers=bearer(owner))).json() == []
    assert (await client.get("/parties", headers=bearer(owner))).json() == []


async def test_existing_registration_is_reported(client):
    owner, _ = await owner_session(client)
    ok = await upload(client, owner, "vehicles", workbook(VEHICLE_COLUMNS, [vehicle_row(0)]))
    assert ok.json()["imported"] == 1
    again = await upload(client, owner, "vehicles", workbook(VEHICLE_COLUMNS, [vehicle_row(0)]))
    assert again.json()["errors"][0]["column"] == "registration"


async def test_dry_run_checks_but_changes_nothing(client):
    owner, _ = await owner_session(client)
    res = await upload(client, owner, "vehicles", workbook(VEHICLE_COLUMNS, [vehicle_row(0)]), dry_run=True)
    assert res.json()["errors"] == [] and res.json()["imported"] == 0
    assert (await client.get("/vehicles", headers=bearer(owner))).json() == []


async def test_bad_files_are_rejected(client):
    owner, _ = await owner_session(client)
    garbage = await upload(client, owner, "vehicles", b"not excel")
    assert garbage.status_code == 422 and garbage.json()["detail"]["code"] == "bad_file"
    wrong_cols = await upload(client, owner, "vehicles", workbook(["registration", "colour"], [{"registration": "KCA 1A"}]))
    assert wrong_cols.json()["detail"]["code"] == "bad_columns"


async def test_staff_import_creates_people_licence_documents_and_invites(client):
    owner, _ = await owner_session(client)
    await client.post("/depots", headers=bearer(owner), json={"name": "Nairobi Yard"})
    rows = [
        {"name": "Peter Otieno", "phone": "0712345678", "roles": "driver", "depot": "Nairobi Yard",
         "licence_number": "DL-1", "licence_class": "CE", "licence_expiry": "2027-06-30"},
        {"name": "Mary Wambui", "email": "mary@example.com", "roles": "manager"},
    ]  # fmt: skip
    res = await upload(client, owner, "staff", workbook(STAFF_COLUMNS, rows))
    assert res.json()["imported"] == 2, res.text
    assert [t["name"] for t in res.json()["invite_tokens"]] == ["Mary Wambui"]  # drivers use SMS codes, no invite

    staff = (await client.get("/staff", headers=bearer(owner))).json()
    peter = next(s for s in staff if s["name"] == "Peter Otieno")
    assert peter["licence_number"] == "DL-1" and peter["roles"] == ["driver"]
    docs = (await client.get(f"/documents?membership_id={peter['membership_id']}", headers=bearer(owner))).json()
    assert docs[0]["doc_type"] == "driving_licence" and docs[0]["expires_on"] == "2027-06-30"


async def test_staff_import_reports_bad_rows_and_imports_nothing(client):
    owner, _ = await owner_session(client)
    rows = [
        {"name": "Good Driver", "phone": "0712345678", "roles": "driver"},
        {"name": "No Phone", "roles": "driver"},
        {"name": "Bad Role", "phone": "0722345678", "roles": "pilot"},
        {"name": "Bad Date", "phone": "0733345678", "roles": "driver", "licence_expiry": "next year"},
    ]
    res = await upload(client, owner, "staff", workbook(STAFF_COLUMNS, rows))
    assert {e["row"] for e in res.json()["errors"]} == {3, 4, 5} and res.json()["imported"] == 0
    assert len((await client.get("/staff", headers=bearer(owner))).json()) == 1  # only the owner


async def test_template_downloads_and_import_is_permissioned(client):
    owner, _ = await owner_session(client)
    res = await client.get("/imports/vehicles/template", headers=bearer(owner))
    assert res.status_code == 200 and res.headers["content-type"] == XLSX
    accountant, _ = await staff_session(client, owner, "accountant", "acc@example.com")
    assert (await client.get("/imports/vehicles/template", headers=bearer(accountant))).status_code == 403
    assert (await upload(client, accountant, "vehicles", b"x")).status_code == 403
