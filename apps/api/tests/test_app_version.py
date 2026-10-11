"""An app build older than the server's minimum is told to update instead of being served."""

from app.config import settings
from tests.helpers import bearer, owner_session


async def test_a_build_below_the_minimum_is_told_to_update_but_health_still_answers(client, monkeypatch):
    owner, _ = await owner_session(client)
    monkeypatch.setattr(settings, "min_app_version_code", 12)
    old = await client.get("/vehicles", headers={**bearer(owner), "X-App-Version-Code": "11"})
    assert old.status_code == 426 and old.json()["detail"]["code"] == "app_outdated"
    assert (await client.get("/health", headers={"X-App-Version-Code": "3"})).status_code == 200  # the update check itself must work
    for sent in ("12", "40"):
        assert (await client.get("/vehicles", headers={**bearer(owner), "X-App-Version-Code": sent})).status_code == 200


async def test_clients_that_send_no_build_number_are_not_held_back(client, monkeypatch):
    owner, _ = await owner_session(client)  # the web app, and older apps from before the header existed
    monkeypatch.setattr(settings, "min_app_version_code", 12)
    assert (await client.get("/vehicles", headers=bearer(owner))).status_code == 200


async def test_with_no_minimum_set_every_build_is_served(client):
    owner, _ = await owner_session(client)
    assert (await client.get("/vehicles", headers={**bearer(owner), "X-App-Version-Code": "1"})).status_code == 200
