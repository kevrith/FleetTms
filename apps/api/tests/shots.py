"""Helpers for Sprint 3 tests: photos, inspections, trips."""

import io
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image

from tests.fleet import add_vehicle
from tests.helpers import bearer, driver_session, owner_session

NAIROBI = ZoneInfo("Africa/Nairobi")


def jpeg(size=(640, 480), taken: datetime | None = None) -> bytes:
    """A unique photo every call (random pixels), optionally with an EXIF capture time like a phone camera writes."""
    img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    buf = io.BytesIO()
    exif = Image.Exif()
    if taken is not None:
        exif[0x0132] = taken.astimezone(NAIROBI).strftime("%Y:%m:%d %H:%M:%S")
    img.save(buf, "JPEG", quality=40, exif=exif)
    return buf.getvalue()


def now_iso(minutes_ago=0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


async def upload(
    client, tokens, kind="odometer", *, data=None, source="camera", captured_at="now", lat=-1.29, lng=36.82,
    client_id=None, offline=False,
):
    form = {"kind": kind, "source": source}
    if client_id:
        form["client_id"] = str(client_id)
    if offline:
        form["offline"] = "true"
    if captured_at == "now":
        captured_at = now_iso()
    if captured_at is not None:
        form["captured_at"] = captured_at
    if lat is not None:
        form["lat"], form["lng"] = str(lat), str(lng)
    return await client.post(
        "/photos", headers=bearer(tokens), data=form, files={"file": ("shot.jpg", data or jpeg(), "image/jpeg")}
    )


async def photo_id(client, tokens, kind="odometer", **kw) -> str:
    res = await upload(client, tokens, kind, **kw)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def fleet(client):
    """Owner, one vehicle (odometer 125000) with a driver and a turnboy assigned. Returns a namespace."""
    owner, _ = await owner_session(client)
    vehicle = await add_vehicle(client, owner, "KCA 123A")
    driver = await driver_session(client, owner, "0712345678")
    turnboy = await driver_session(client, owner, "0722345678", role="turnboy")
    staff = (await client.get("/staff", headers=bearer(owner))).json()
    ids = {r["phone"]: r["membership_id"] for r in staff if r["phone"]}
    for phone, role in (("+254712345678", "driver"), ("+254722345678", "turnboy")):
        res = await client.post(
            f"/vehicles/{vehicle['id']}/crew", headers=bearer(owner), json={"membership_id": ids[phone], "role": role}
        )
        assert res.status_code == 201, res.text
    return type("Fleet", (), {"owner": owner, "vehicle": vehicle, "driver": driver, "turnboy": turnboy, "ids": ids})


async def checklist(client, tokens) -> list[dict]:
    res = await client.get("/inspection/checklist", headers=bearer(tokens))
    assert res.status_code == 200, res.text
    return res.json()


async def inspect(client, tokens, vehicle_id, faults: dict[str, str] | None = None):
    """Submits an inspection. `faults` maps a checklist label to a fault note; every other item is OK."""
    faults = faults or {}
    results = []
    for item in await checklist(client, tokens):
        if item["label"] in faults:
            pid = await photo_id(client, tokens, "defect")
            results.append({"item_id": item["id"], "ok": False, "note": faults[item["label"]], "photo_id": pid})
        else:
            results.append({"item_id": item["id"], "ok": True})
    return await client.post(f"/vehicles/{vehicle_id}/inspections", headers=bearer(tokens), json={"results": results})


async def make_trip(client, f, **extra):
    res = await client.post(
        "/trips", headers=bearer(f.owner),
        json={"vehicle_id": f.vehicle["id"], "cargo_description": "Cement, 400 bags", "origin": "Mombasa", "destination": "Nairobi", **extra},
    )  # fmt: skip
    assert res.status_code == 201, res.text
    return res.json()


async def start(client, tokens, trip_id, value=125100, **reading):
    pid = reading.pop("photo_id", None) or await photo_id(client, tokens, "odometer")
    return await client.post(
        f"/trips/{trip_id}/start", headers=bearer(tokens), json={"photo_id": pid, "value": value, **reading}
    )


def ago(**delta) -> str:
    """An ISO time in the past, for records a phone made while it was offline."""
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


async def sync(client, tokens, actions, device=None):
    body = {"actions": actions}
    if device:
        body["device"] = device
    return await client.post("/sync", headers=bearer(tokens), json=body)
