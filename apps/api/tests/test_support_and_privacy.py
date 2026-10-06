import pyotp
from sqlalchemy import select

from app.config import settings
from app.db import get_sessionmaker
from app.models import User
from app.security import hash_password
from tests.helpers import PASSWORD, bearer, driver_session, login, owner_session


async def make_platform_admin(client):
    secret = pyotp.random_base32()
    async with get_sessionmaker()() as db:
        db.add(
            User(
                name="Kastra Support", email="support@example.com", password_hash=hash_password(PASSWORD),
                totp_secret=secret, totp_enabled=True, is_platform_admin=True, is_platform_super=True,
            )
        )
        await db.commit()
    res = await login(client, "support@example.com", secret)
    assert res.status_code == 200, res.text
    return res.json()


async def business_id(client, tokens):
    return (await client.get("/auth/me", headers=bearer(tokens))).json()["business"]["id"]


async def test_platform_admin_has_no_default_access_to_tenant_data(client):
    await owner_session(client)
    admin = await make_platform_admin(client)
    assert admin["business_id"] is None
    assert (await client.get("/users", headers=bearer(admin))).status_code == 403
    assert (await client.get("/depots", headers=bearer(admin))).status_code == 403
    names = (await client.get("/platform/businesses", headers=bearer(admin))).json()
    assert [b["name"] for b in names] == ["Kamau Haulage"]  # names only
    assert set(names[0]) == {"id", "name"}


async def test_cannot_enter_a_company_without_a_grant(client):
    owner, _ = await owner_session(client)
    admin = await make_platform_admin(client)
    res = await client.post(f"/platform/support/{await business_id(client, owner)}/enter", headers=bearer(admin))
    assert res.status_code == 403


async def test_regular_users_cannot_use_platform_endpoints(client):
    owner, _ = await owner_session(client)
    assert (await client.get("/platform/businesses", headers=bearer(owner))).status_code == 403
    bid = await business_id(client, owner)
    assert (await client.post(f"/platform/support/{bid}/enter", headers=bearer(owner))).status_code == 403


async def test_granted_support_is_read_only_and_logged_then_revoked(client):
    owner, _ = await owner_session(client)
    await client.post("/depots", headers=bearer(owner), json={"name": "Alpha Yard"})
    bid = await business_id(client, owner)
    grant = await client.post("/support/grants", headers=bearer(owner), json={"hours": 2, "reason": "Help with import"})
    assert grant.status_code == 201

    admin = await make_platform_admin(client)
    assert (await client.post(f"/platform/support/{bid}/enter", headers=bearer(admin))).status_code == 200
    assert [d["name"] for d in (await client.get("/depots", headers=bearer(admin))).json()] == ["Alpha Yard"]
    assert (await client.get("/users", headers=bearer(admin))).status_code == 200
    # Read-only: no writes, no granting more access.
    assert (await client.post("/depots", headers=bearer(admin), json={"name": "x"})).status_code == 403
    assert (await client.post("/users", headers=bearer(admin), json={"name": "x", "email": "x@example.com", "roles": ["owner"]})).status_code == 403
    assert (await client.post("/support/grants", headers=bearer(admin), json={"hours": 1, "reason": "self"})).status_code == 403

    log = (await client.get("/audit", headers=bearer(owner))).json()
    assert {"support.granted", "support.entered"} <= {e["action"] for e in log}

    grant_id = grant.json()["id"]
    assert (await client.delete(f"/support/grants/{grant_id}", headers=bearer(owner))).status_code == 204
    assert (await client.get("/depots", headers=bearer(admin))).status_code == 403  # access ends at once


async def test_expired_grant_ends_support_access(client):
    from datetime import timedelta

    from sqlalchemy import update

    from app.auth_service import now
    from app.models import SupportGrant
    from app.tenancy import current_business_id

    owner, _ = await owner_session(client)
    bid = await business_id(client, owner)
    await client.post("/support/grants", headers=bearer(owner), json={"hours": 1, "reason": "Short help"})
    admin = await make_platform_admin(client)
    await client.post(f"/platform/support/{bid}/enter", headers=bearer(admin))
    assert (await client.get("/users", headers=bearer(admin))).status_code == 200

    async with get_sessionmaker()() as db:
        import uuid

        current_business_id.set(uuid.UUID(bid))
        await db.execute(update(SupportGrant).values(expires_at=now() - timedelta(minutes=1)))
        await db.commit()
        current_business_id.set(None)
    assert (await client.get("/users", headers=bearer(admin))).status_code == 403


# ---- privacy notices ----------------------------------------------------------------------------


async def test_driver_must_acknowledge_the_monitoring_notice(client):
    owner, _ = await owner_session(client)
    driver = await driver_session(client, owner, "0712345678")
    me = (await client.get("/auth/me", headers=bearer(driver))).json()
    pending = {(p["document"], p["version"]) for p in me["pending_documents"]}
    assert ("monitoring_notice", settings.monitoring_notice_version) in pending
    assert ("terms", settings.terms_version) in pending

    for doc in me["pending_documents"]:
        assert (await client.post("/privacy/accept", headers=bearer(driver), json=doc)).status_code == 204
    assert (await client.get("/auth/me", headers=bearer(driver))).json()["pending_documents"] == []


async def test_outdated_document_version_is_refused(client):
    owner, _ = await owner_session(client)
    driver = await driver_session(client, owner, "0712345678")
    res = await client.post("/privacy/accept", headers=bearer(driver), json={"document": "terms", "version": "ancient"})
    assert res.status_code == 409


async def test_acceptance_is_stored_per_user_and_audited(client):
    owner, _ = await owner_session(client)
    driver = await driver_session(client, owner, "0712345678")
    await client.post("/privacy/accept", headers=bearer(driver), json={"document": "monitoring_notice", "version": settings.monitoring_notice_version})
    log = (await client.get("/audit", headers=bearer(owner), params={"action": "privacy.accepted"})).json()
    assert log and log[0]["entity_id"] == "monitoring_notice"
    async with get_sessionmaker()() as db:
        assert (await db.execute(select(User.id))).all()


async def test_documents_endpoint_lists_current_versions(client):
    res = await client.get("/privacy/documents")
    assert {d["document"] for d in res.json()} == {"terms", "privacy", "dpa", "monitoring_notice"}
