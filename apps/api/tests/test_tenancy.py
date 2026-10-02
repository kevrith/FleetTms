import uuid

import pytest
from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Business, Depot
from app.tenancy import TenantContextError, current_business_id
from tests.helpers import bearer, owner_session


async def two_businesses(client):
    a, _ = await owner_session(client, "Alpha Haulage", "a@example.com")
    b, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    return a, b


async def test_business_a_cannot_see_business_b_depots(client):
    a, b = await two_businesses(client)
    await client.post("/depots", headers=bearer(b), json={"name": "Bravo Yard"})
    await client.post("/depots", headers=bearer(a), json={"name": "Alpha Yard"})

    names = [d["name"] for d in (await client.get("/depots", headers=bearer(a))).json()]
    assert names == ["Alpha Yard"]


async def test_business_a_cannot_read_change_or_delete_b_depot_by_id(client):
    a, b = await two_businesses(client)
    depot_id = (await client.post("/depots", headers=bearer(b), json={"name": "Bravo Yard"})).json()["id"]

    assert (await client.put(f"/depots/{depot_id}", headers=bearer(a), json={"name": "Hacked"})).status_code == 404
    assert (await client.delete(f"/depots/{depot_id}", headers=bearer(a))).status_code == 404
    still = (await client.get("/depots", headers=bearer(b))).json()
    assert [d["name"] for d in still] == ["Bravo Yard"]


async def test_users_and_audit_are_isolated(client):
    a, b = await two_businesses(client)
    users_a = (await client.get("/users", headers=bearer(a))).json()
    assert [u["email"] for u in users_a] == ["a@example.com"]
    audit_b = (await client.get("/audit", headers=bearer(b))).json()
    assert audit_b and all(e["entity_id"] != users_a[0]["user_id"] for e in audit_b)
    assert not any("Alpha" in str(e) for e in audit_b)


async def test_role_change_cannot_target_another_tenants_membership(client):
    a, b = await two_businesses(client)
    other = (await client.get("/users", headers=bearer(b))).json()[0]["membership_id"]
    res = await client.put(f"/users/{other}/roles", headers=bearer(a), json={"roles": ["driver"]})
    assert res.status_code == 404
    res = await client.delete(f"/users/{other}", headers=bearer(a))
    assert res.status_code == 404


async def test_tenant_query_without_context_fails_closed(client):
    await two_businesses(client)
    async with get_sessionmaker()() as db:
        current_business_id.set(None)
        with pytest.raises(TenantContextError):
            await db.execute(select(Depot))


async def test_writing_into_another_tenant_is_blocked(client):
    await two_businesses(client)
    async with get_sessionmaker()() as db:
        ids = (await db.execute(select(Business.id).order_by(Business.name))).scalars().all()
        current_business_id.set(ids[0])
        db.add(Depot(business_id=ids[1], name="Smuggled"))
        with pytest.raises(TenantContextError):
            await db.flush()
    current_business_id.set(None)


async def test_new_tenant_rows_are_stamped_with_current_business(client):
    await owner_session(client)
    async with get_sessionmaker()() as db:
        biz = (await db.execute(select(Business.id))).scalar_one()
        current_business_id.set(biz)
        depot = Depot(name="Stamped")
        db.add(depot)
        await db.flush()
        assert depot.business_id == biz
    current_business_id.set(None)


async def test_unknown_business_context_sees_nothing(client):
    await two_businesses(client)
    async with get_sessionmaker()() as db:
        current_business_id.set(uuid.uuid4())
        assert (await db.execute(select(Depot))).all() == []
    current_business_id.set(None)


async def test_switching_company_never_mixes_data(client):
    a, _ = await owner_session(client, "Alpha Haulage", "shared@example.com")
    b, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    await client.post("/depots", headers=bearer(a), json={"name": "Alpha Yard"})
    await client.post("/depots", headers=bearer(b), json={"name": "Bravo Yard"})

    # Bravo's owner adds the shared user as a manager, so they belong to two companies.
    added = await client.post(
        "/users", headers=bearer(b), json={"name": "Shared", "email": "shared@example.com", "roles": ["manager"]}
    )
    assert added.status_code == 201, added.text
    assert added.json()["invite_token"] is None  # existing account, no new invite

    me = (await client.get("/auth/me", headers=bearer(a))).json()
    assert len(me["companies"]) == 2
    alpha = next(c for c in me["companies"] if c["name"] == "Alpha Haulage")
    bravo = next(c for c in me["companies"] if c["name"] == "Bravo Transporters")

    assert [d["name"] for d in (await client.get("/depots", headers=bearer(a))).json()] == ["Alpha Yard"]
    switched = await client.post("/auth/switch-company", headers=bearer(a), json={"business_id": bravo["business_id"]})
    assert switched.status_code == 200
    assert [d["name"] for d in (await client.get("/depots", headers=bearer(a))).json()] == ["Bravo Yard"]
    # Manager role in Bravo: can view depots but not create them.
    assert (await client.post("/depots", headers=bearer(a), json={"name": "x"})).status_code == 403
    await client.post("/auth/switch-company", headers=bearer(a), json={"business_id": alpha["business_id"]})
    assert [d["name"] for d in (await client.get("/depots", headers=bearer(a))).json()] == ["Alpha Yard"]


async def test_cannot_switch_to_a_company_you_do_not_belong_to(client):
    a, b = await two_businesses(client)
    bravo_id = (await client.get("/auth/me", headers=bearer(b))).json()["business"]["id"]
    res = await client.post("/auth/switch-company", headers=bearer(a), json={"business_id": bravo_id})
    assert res.status_code == 403
