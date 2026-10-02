import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import get_engine
from tests.helpers import bearer, owner_session, staff_session


async def entries(client, tokens, **params):
    return (await client.get("/audit", headers=bearer(tokens), params=params)).json()


async def test_role_change_is_audited_with_before_and_after(client):
    owner, _ = await owner_session(client)
    await staff_session(client, owner, "accountant", "acc@example.com", with_2fa=False)
    target = next(m for m in (await client.get("/users", headers=bearer(owner))).json() if m["email"] == "acc@example.com")

    res = await client.put(
        f"/users/{target['membership_id']}/roles", headers=bearer(owner), json={"roles": ["manager", "workshop"]}
    )
    assert res.status_code == 200

    (entry,) = await entries(client, owner, action="user.roles_changed")
    assert entry["before"] == {"roles": ["accountant"]}
    assert entry["after"]["roles"] == ["manager", "workshop"]
    assert entry["entity_id"] == target["membership_id"]
    assert entry["actor_user_id"]


async def test_invite_removal_and_depot_changes_are_audited(client):
    owner, _ = await owner_session(client)
    depot = (await client.post("/depots", headers=bearer(owner), json={"name": "Naivasha Yard"})).json()
    await client.put(f"/depots/{depot['id']}", headers=bearer(owner), json={"name": "Naivasha Depot"})
    await client.delete(f"/depots/{depot['id']}", headers=bearer(owner))
    res = await client.post("/users", headers=bearer(owner), json={"name": "Dan Driver", "phone": "0712345678", "roles": ["driver"]})
    await client.delete(f"/users/{res.json()['membership_id']}", headers=bearer(owner))

    actions = {e["action"] for e in await entries(client, owner)}
    assert {"business.created", "depot.created", "depot.updated", "depot.deleted", "user.invited", "user.removed"} <= actions
    (updated,) = await entries(client, owner, action="depot.updated")
    assert updated["before"]["name"] == "Naivasha Yard" and updated["after"]["name"] == "Naivasha Depot"


async def test_audit_log_has_no_secrets(client):
    owner, _ = await owner_session(client)
    await client.post("/users", headers=bearer(owner), json={"name": "Acc", "email": "acc@example.com", "roles": ["accountant"]})
    blob = str(await entries(client, owner, limit=200))
    for forbidden in ("password", "totp_secret", "invite_token", "refresh"):
        assert forbidden not in blob.lower().replace("auth.2fa_enabled", "")


async def test_audit_log_cannot_be_edited_or_deleted_even_by_sql(client):
    await owner_session(client)
    engine = get_engine()
    for statement in ("UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs"):
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as conn:
                await conn.execute(text(statement))


async def test_a_company_must_keep_one_owner(client):
    owner, _ = await owner_session(client)
    me = (await client.get("/users", headers=bearer(owner))).json()[0]
    demote = await client.put(f"/users/{me['membership_id']}/roles", headers=bearer(owner), json={"roles": ["manager"]})
    assert demote.status_code == 409
    remove = await client.delete(f"/users/{me['membership_id']}", headers=bearer(owner))
    assert remove.status_code == 409


async def test_failed_change_leaves_no_audit_entry(client):
    owner, _ = await owner_session(client)
    me = (await client.get("/users", headers=bearer(owner))).json()[0]
    await client.put(f"/users/{me['membership_id']}/roles", headers=bearer(owner), json={"roles": ["manager"]})
    assert await entries(client, owner, action="user.roles_changed") == []
