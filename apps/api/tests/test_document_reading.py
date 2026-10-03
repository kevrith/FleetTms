import base64
import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app import document_reader
from app.config import settings
from app.document_reader import ReadError, fake_reader
from tests.helpers import bearer, driver_session, owner_session, staff_session
from tests.shots import fleet, photo_id

TODAY = datetime.now(UTC).date().isoformat()
RECEIPT = {"station": "Total Mlolongo", "fuel_type": "diesel", "litres": "120.5", "price_per_litre": "185.00", "amount": "22,292.50", "mpesa_code": "qwe1234567", "date": TODAY, "confidence": 0.93}


@pytest.fixture(autouse=True)
def _reader():
    settings.document_reader = "fake"
    fake_reader().result, fake_reader().fail_with = None, None
    fake_reader().calls.clear()
    yield
    settings.document_reader, settings.anthropic_api_key, settings.document_reads_per_day = "", "", 200


async def read(client, who, pid, kind="fuel_receipt", **extra):
    return await client.post("/document-readings", headers=bearer(who), json={"photo_id": pid, "kind": kind, **extra})


# ---- a photographed fuel receipt fills litres, amount and station (acceptance) --------------------------------------------------


async def test_a_photographed_fuel_receipt_fills_litres_amount_and_station_and_the_same_photo_backs_the_entry(client):
    f = await fleet(client)
    fake_reader().result = RECEIPT
    pid = await photo_id(client, f.driver, "receipt")
    res = await read(client, f.driver, pid, vehicle_id=f.vehicle["id"])
    assert res.status_code == 201, res.text
    got = res.json()
    assert got["fields"]["station"] == "Total Mlolongo" and got["fields"]["litres"] == 120.5 and got["fields"]["amount"] == 22292.5 and got["fields"]["price_per_litre"] == 185.0
    assert got["fields"]["mpesa_code"] == "QWE1234567" and got["fields"]["fuel_type"] == "diesel" and got["warnings"] == [] and got["missing"] == [] and got["confidence"] == 0.93 and got["status"] == "pending"
    assert fake_reader().calls and fake_reader().calls[0][0] == "fuel_receipt" and fake_reader().calls[0][2] == "image/jpeg"
    done = await client.post(f"/document-readings/{got['id']}/confirm", headers=bearer(f.driver), json={"fields": got["fields"]})
    assert done.status_code == 200 and done.json()["status"] == "confirmed" and done.json()["corrections"] == 0
    c = done.json()["fields"]
    fuel = await client.post("/fuel", headers=bearer(f.driver), json={"vehicle_id": f.vehicle["id"], "litres": str(c["litres"]), "price_per_litre_cents": round(c["price_per_litre"] * 100), "amount_cents": round(c["amount"] * 100), "station": c["station"], "mpesa_code": c["mpesa_code"], "receipt_photo_id": pid})
    assert fuel.status_code == 201, fuel.text  # the photo was only read, not used up
    assert fuel.json()["has_receipt"] is True and fuel.json()["flags"] == []


async def test_a_wrong_reading_is_corrected_before_it_becomes_a_record_and_corrections_are_counted(client):
    f = await fleet(client)
    fake_reader().result = {**RECEIPT, "litres": "12050", "amount": "22292.50"}  # a misplaced decimal point
    pid = await photo_id(client, f.driver, "receipt")
    got = (await read(client, f.driver, pid)).json()
    assert got["fields"]["litres"] == 12050 and any("12050 litres is more than a tank holds" in w for w in got["warnings"]) and any("at 185 is 2,229,250.00" in w for w in got["warnings"])
    done = (await client.post(f"/document-readings/{got['id']}/confirm", headers=bearer(f.driver), json={"fields": {**got["fields"], "litres": "120.5"}})).json()
    assert done["fields"]["litres"] == 120.5 and done["corrections"] == 1 and done["warnings"] == []
    assert (await client.post(f"/document-readings/{got['id']}/confirm", headers=bearer(f.driver), json={"fields": done["fields"]})).json()["detail"]["code"] == "already_answered"


async def test_confirming_needs_the_important_fields_and_a_reading_can_be_rejected(client):
    f = await fleet(client)
    fake_reader().result = {"station": "Total", "confidence": 0.4}
    pid = await photo_id(client, f.driver, "receipt")
    got = (await read(client, f.driver, pid)).json()
    assert got["missing"] == ["litres", "amount"]
    short = await client.post(f"/document-readings/{got['id']}/confirm", headers=bearer(f.driver), json={"fields": got["fields"]})
    assert short.status_code == 422 and short.json()["detail"]["code"] == "fields_missing" and "litres, amount" in short.json()["detail"]["message"]
    assert (await client.post(f"/document-readings/{got['id']}/reject", headers=bearer(f.driver))).status_code == 204
    assert (await client.post(f"/document-readings/{got['id']}/reject", headers=bearer(f.driver))).status_code == 409


# ---- the other kinds -----------------------------------------------------------------------------------------------------


async def test_a_weighbridge_ticket_is_checked_against_itself_and_the_chosen_vehicle(client):
    f = await fleet(client)
    fake_reader().result = {"ticket_no": "WB-7781", "registration": "kcb222b", "gross_kg": "45,200", "tare_kg": 14000, "net_kg": 30000, "cargo": "Cement", "date": TODAY, "confidence": 0.8}
    pid = await photo_id(client, f.driver, "weighbridge")
    got = (await read(client, f.driver, pid, "weighbridge_ticket", vehicle_id=f.vehicle["id"])).json()
    assert got["fields"]["gross_kg"] == 45200 and got["fields"]["registration"] == "KCB 222B"
    assert len(got["warnings"]) == 3 and "less tare 14,000 is 31,200 kg" in got["warnings"][0]
    assert "over this vehicle's legal limit of 16,000 kg" in got["warnings"][1] and "for KCB 222B, but you chose KCA 123A" in got["warnings"][2]


async def test_a_confirmed_insurance_certificate_becomes_the_vehicles_insurance_record(client):
    f = await fleet(client)
    fake_reader().result = {"insurer": "Jubilee", "policy_no": "POL-2026-8841", "registration": "kca123a", "cover_type": "comprehensive", "valid_from": "2026-07-01", "valid_to": "2027-06-30", "confidence": 0.9}
    pid = await photo_id(client, f.owner, "receipt")
    got = (await read(client, f.owner, pid, "insurance_certificate")).json()
    early = await client.post(f"/document-readings/{got['id']}/apply", headers=bearer(f.owner))
    assert early.status_code == 409 and early.json()["detail"]["code"] == "cannot_apply"  # not confirmed yet
    await client.post(f"/document-readings/{got['id']}/confirm", headers=bearer(f.owner), json={"fields": got["fields"]})
    applied = await client.post(f"/document-readings/{got['id']}/apply", headers=bearer(f.owner))
    assert applied.status_code == 200, applied.text
    assert applied.json()["vehicle_id"] == f.vehicle["id"] and applied.json()["expires_on"] == "2027-06-30"  # the vehicle was found by the plate on the certificate
    docs = (await client.get("/documents", params={"vehicle_id": f.vehicle["id"]}, headers=bearer(f.owner))).json()
    assert [(x["doc_type"], x["reference"], x["expires_on"]) for x in docs] == [("insurance", "POL-2026-8841", "2027-06-30")]
    fake_reader().result = RECEIPT
    receipt = (await read(client, f.owner, await photo_id(client, f.owner, "receipt"))).json()
    await client.post(f"/document-readings/{receipt['id']}/confirm", headers=bearer(f.owner), json={"fields": receipt["fields"]})
    assert (await client.post(f"/document-readings/{receipt['id']}/apply", headers=bearer(f.owner))).json()["detail"]["code"] == "cannot_apply"
    assert (await client.post(f"/document-readings/{got['id']}/apply", headers=bearer(f.driver))).status_code == 403


# ---- when reading cannot happen, and who may -----------------------------------------------------------------------------


async def test_reading_that_is_switched_off_or_fails_says_so_and_nothing_is_saved(client):
    f = await fleet(client)
    pid = await photo_id(client, f.driver, "receipt")
    settings.document_reader = ""
    off = await read(client, f.driver, pid)
    assert off.status_code == 503 and off.json()["detail"]["code"] == "reading_unavailable" and "not switched on" in off.json()["detail"]["message"]
    settings.document_reader = "fake"
    fake_reader().fail_with = "The document could not be read just now. Try again, or type it in."
    failed = await read(client, f.driver, pid)
    assert failed.status_code == 503 and "type it in" in failed.json()["detail"]["message"]
    assert (await client.get("/document-readings/summary", headers=bearer(f.owner))).json() == []


async def test_a_photo_belongs_to_whoever_took_it_and_businesses_are_kept_apart(client):
    f = await fleet(client)
    fake_reader().result = RECEIPT
    mine = await photo_id(client, f.driver, "receipt")
    turnboy_photo = await photo_id(client, f.turnboy, "receipt")
    assert (await read(client, f.driver, turnboy_photo)).status_code == 404  # not their photo, and they cannot see vehicles
    assert (await read(client, f.owner, turnboy_photo)).status_code == 201  # the owner can see everything
    assert (await read(client, f.driver, str(uuid.uuid4()))).status_code == 404
    assert (await read(client, f.driver, mine, vehicle_id=str(uuid.uuid4()))).status_code == 404
    got = (await read(client, f.driver, mine)).json()
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await read(client, other, mine)).status_code == 404
    assert (await client.post(f"/document-readings/{got['id']}/confirm", headers=bearer(other), json={"fields": got["fields"]})).status_code == 404
    second = await driver_session(client, f.owner, "0733000111")
    assert (await client.post(f"/document-readings/{got['id']}/confirm", headers=bearer(second), json={"fields": got["fields"]})).status_code == 404  # only the reader or a manager confirms


async def test_the_number_of_readings_a_person_can_make_in_a_day_is_capped(client):
    f = await fleet(client)
    fake_reader().result = RECEIPT
    settings.document_reads_per_day = 2
    pid = await photo_id(client, f.driver, "receipt")
    assert (await read(client, f.driver, pid)).status_code == 201 and (await read(client, f.driver, pid)).status_code == 201
    capped = await read(client, f.driver, pid)
    assert capped.status_code == 429 and capped.json()["detail"]["code"] == "too_many_reads"


async def test_the_summary_shows_how_often_a_reading_was_right_first_time(client):
    f = await fleet(client)
    fake_reader().result = RECEIPT
    for correction in (False, False, True):
        got = (await read(client, f.driver, await photo_id(client, f.driver, "receipt"))).json()
        fields = {**got["fields"], "litres": 99} if correction else got["fields"]
        await client.post(f"/document-readings/{got['id']}/confirm", headers=bearer(f.driver), json={"fields": fields})
    rejected = (await read(client, f.driver, await photo_id(client, f.driver, "receipt"))).json()
    await client.post(f"/document-readings/{rejected['id']}/reject", headers=bearer(f.driver))
    [row] = (await client.get("/document-readings/summary", headers=bearer(f.owner))).json()
    assert row == {"kind": "fuel_receipt", "read": 4, "confirmed": 3, "rejected": 1, "pending": 0, "exact": 2, "fields_corrected": 1, "exact_pct": 67}
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    assert (await client.get("/document-readings/summary", headers=bearer(manager))).status_code == 200
    assert (await client.get("/document-readings/summary", headers=bearer(f.driver))).status_code == 403


# ---- the real service: what is sent and what is done with the answer ----------------------------------------------------------


async def test_the_claude_reader_sends_the_photo_with_a_forced_tool_and_takes_the_tools_answer(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"], seen["body"] = dict(request.headers), json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Here you go"}, {"type": "tool_use", "name": "record_document", "input": {"litres": 120.5, "amount": 22292.5, "confidence": 0.9}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr("app.document_reader.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    key = uuid.uuid4().hex
    monkeypatch.setattr(settings, "anthropic_api_key", key)
    monkeypatch.setattr(settings, "document_reader", "")
    reader = document_reader.get_reader()
    assert reader.name == "claude"
    got = await reader.read("fuel_receipt", b"\xff\xd8photo", "image/jpeg")
    assert got == {"litres": 120.5, "amount": 22292.5, "confidence": 0.9}
    assert seen["headers"]["x-api-key"] == key and seen["headers"]["anthropic-version"] == "2023-06-01"
    body = seen["body"]
    assert body["model"] == settings.document_reader_model and body["tool_choice"] == {"type": "tool", "name": "record_document"}
    image = body["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg" and base64.b64decode(image["source"]["data"]) == b"\xff\xd8photo"
    props = body["tools"][0]["input_schema"]["properties"]
    assert {"station", "litres", "price_per_litre", "amount", "mpesa_code", "confidence"} <= set(props) and "Never guess" in body["messages"][0]["content"][1]["text"]


async def test_the_claude_reader_reports_a_failed_or_empty_answer_without_leaking_details(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(settings, "anthropic_api_key", uuid.uuid4().hex)
    monkeypatch.setattr(settings, "document_reader", "claude")
    for response in (httpx.Response(500, text="internal secret detail"), httpx.Response(200, json={"content": [{"type": "text", "text": "I cannot read this"}]}), httpx.Response(200, text="not json")):
        monkeypatch.setattr("app.document_reader.httpx.AsyncClient", lambda response=response, **kw: real(transport=httpx.MockTransport(lambda request: response), **kw))
        with pytest.raises(ReadError) as e:
            await document_reader.get_reader().read("logbook", b"x", "image/png")
        assert "secret" not in str(e.value) and ("type it in" in str(e.value) or "clearer" in str(e.value))


def test_reading_is_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "document_reader", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(ReadError, match="not switched on"):
        document_reader.get_reader()



# ---- photos of papers are not evidence, so they are not held to the freshness rules ------------------------------------------


async def test_a_photo_of_a_certificate_needs_no_capture_time_and_uploading_it_again_is_not_a_duplicate_claim(client):
    from tests.helpers import bearer as b
    from tests.shots import jpeg, upload

    f = await fleet(client)
    data = jpeg()  # no EXIF capture time, as a scan or an old photo would be
    first = await upload(client, f.owner, "document", data=data, source="web", captured_at=None, lat=None, lng=None)
    assert first.status_code == 201, first.text
    again = await upload(client, f.owner, "document", data=data, source="web", captured_at=None, lat=None, lng=None)
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]  # the same photo, handed back
    assert (await client.get("/fraud/alerts", headers=b(f.owner))).json() == []  # not reported as a receipt used twice
    receipt = jpeg()
    assert (await upload(client, f.driver, "receipt", data=receipt, source="web", captured_at=None, lat=None, lng=None)).status_code == 422  # evidence still needs its capture time
    old = await upload(client, f.owner, "document", data=jpeg(), source="camera", captured_at="2020-01-01T00:00:00+00:00")
    assert old.status_code == 201 and old.json()["late"] is False
