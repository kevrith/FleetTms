"""Helpers for Sprint 2 tests: vehicles, parties, crew."""

from tests.helpers import bearer


def vehicle_body(registration="KCA 123A", **overrides):
    return {
        "registration": registration, "make": "Isuzu", "model": "FVR", "capacity_tonnes": "10",
        "tank_litres": 200, "expected_kmpl_loaded": "4.5", "expected_kmpl_empty": "6",
        "odometer_km": 125000, "gvw_limit_kg": 16000, "axle_config": "2", **overrides,
    }  # fmt: skip


async def add_vehicle(client, tokens, registration="KCA 123A", **overrides):
    res = await client.post("/vehicles", headers=bearer(tokens), json=vehicle_body(registration, **overrides))
    assert res.status_code == 201, res.text
    return res.json()


async def add_party(client, tokens, kind="lessor", name="Wanjiku Transporters"):
    res = await client.post("/parties", headers=bearer(tokens), json={"kind": kind, "name": name, "phone": "0711222333"})
    assert res.status_code == 201, res.text
    return res.json()


async def staff_id(client, tokens, name_contains):
    rows = (await client.get("/staff", headers=bearer(tokens))).json()
    return next(r["membership_id"] for r in rows if name_contains in r["name"])
