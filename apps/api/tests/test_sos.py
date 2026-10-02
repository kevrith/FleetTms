from app.sms import get_sms_sender
from tests.fleet import add_vehicle
from tests.helpers import PASSWORD, bearer, enable_2fa, login
from tests.shots import ago, fleet, sync


async def staff(client, f, role, email, phone, **extra):
    res = await client.post("/users", headers=bearer(f.owner), json={"name": f"{role} person", "email": email, "phone": phone, "roles": [role], **extra})
    assert res.status_code == 201, res.text
    await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
    tokens = (await login(client, email)).json()
    await enable_2fa(client, tokens)
    return tokens


def texts():
    return [(p, m) for p, m in get_sms_sender().outbox if "SOS" in m]


async def press(client, tokens, **body):
    return await client.post("/sos", headers=bearer(tokens), json={"lat": -1.2921, "lng": 36.8219, **body})


async def test_sos_texts_the_manager_and_the_supervisors_who_cover_the_vehicle_with_the_location(client):
    f = await fleet(client)
    other_vehicle = await add_vehicle(client, f.owner, "KDD 456B")
    await staff(client, f, "manager", "m@example.com", "+254733000001")
    await staff(client, f, "supervisor", "s1@example.com", "+254733000002", vehicle_scope=[f.vehicle["id"]])
    await staff(client, f, "supervisor", "s2@example.com", "+254733000003", vehicle_scope=[other_vehicle["id"]])
    res = await press(client, f.driver)
    assert res.status_code == 201, res.text
    alert = res.json()
    assert alert["status"] == "active" and alert["registration"] == "KCA 123A" and alert["notified"] == 2
    assert {p for p, _ in texts()} == {"+254733000001", "+254733000002"}  # the other vehicle's supervisor is not woken
    _, message = texts()[0]
    assert "driver user" in message and "KCA 123A" in message and "https://maps.google.com/?q=-1.2921,36.8219" in message
    assert alert["delay_s"] <= 5 and alert["map_url"].endswith("-1.2921,36.8219")


async def test_pressing_again_moves_the_pin_instead_of_texting_everyone_twice(client):
    f = await fleet(client)
    await staff(client, f, "manager", "m@example.com", "+254733000001")
    first = (await press(client, f.driver)).json()
    again = (await press(client, f.driver, lat=-1.3, lng=36.9)).json()
    assert again["id"] == first["id"] and again["lat"] == -1.3 and len(texts()) == 1


async def test_live_location_updates_follow_the_alert_and_stop_when_it_closes(client):
    f = await fleet(client)
    sup = await staff(client, f, "manager", "m@example.com", "+254733000001")
    alert = (await press(client, f.driver)).json()
    for lat in (-1.31, -1.32):
        res = await client.post(f"/sos/{alert['id']}/location", headers=bearer(f.driver), json={"lat": lat, "lng": 36.83})
        assert res.status_code == 200
    seen = (await client.get("/sos", headers=bearer(sup))).json()[0]
    assert seen["lat"] == -1.32 and [p["lat"] for p in seen["track"]] == [-1.31, -1.32]
    await client.post(f"/sos/{alert['id']}/resolve", headers=bearer(sup), json={})
    assert (await client.post(f"/sos/{alert['id']}/location", headers=bearer(f.driver), json={"lat": -1.4, "lng": 36.8})).status_code == 409


async def test_acknowledging_shows_the_driver_that_help_is_coming_and_resolving_closes_it(client):
    f = await fleet(client)
    mgr = await staff(client, f, "manager", "m@example.com", "+254733000001")
    alert = (await press(client, f.driver)).json()
    assert (await client.get("/me/sos", headers=bearer(f.driver))).json()["acknowledged"] is False
    ack = await client.post(f"/sos/{alert['id']}/acknowledge", headers=bearer(mgr), json={"note": "Calling him now"})
    assert ack.json()["status"] == "acknowledged" and ack.json()["acknowledged_at"]
    assert (await client.get("/me/sos", headers=bearer(f.driver))).json()["acknowledged"] is True
    done = await client.post(f"/sos/{alert['id']}/resolve", headers=bearer(mgr), json={"note": "Safe, flat tyre"})
    assert done.json()["status"] == "resolved"
    assert (await client.get("/sos", headers=bearer(mgr))).json() == []
    assert len((await client.get("/sos?active_only=false", headers=bearer(mgr))).json()) == 1
    assert (await client.get("/me/sos", headers=bearer(f.driver))).json() is None


async def test_an_sos_pressed_with_no_signal_arrives_later_with_the_original_time_and_only_once(client):
    f = await fleet(client)
    await staff(client, f, "manager", "m@example.com", "+254733000001")
    action = {"client_id": "5a1e9c1e-0000-4000-8000-0000000000aa", "type": "sos.send", "payload": {"lat": -1.29, "lng": 36.82, "captured_at": ago(minutes=12)}}
    first = (await sync(client, f.driver, [action])).json()["results"][0]
    again = (await sync(client, f.driver, [action])).json()["results"][0]
    assert first["status"] == "ok" and again["status"] == "duplicate" and len(texts()) == 1
    row = (await client.get("/sos", headers=bearer(f.owner))).json()[0]
    assert row["delay_s"] >= 11 * 60  # the owner can see it was pressed 12 minutes ago, not just now


async def test_a_rejected_text_does_not_lose_the_alert(client, monkeypatch):
    f = await fleet(client)
    await staff(client, f, "manager", "m@example.com", "+254733000001")

    async def broken(phone, message):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(get_sms_sender(), "send", broken)
    res = await press(client, f.driver)
    assert res.status_code == 201 and res.json()["notified"] == 0
    assert len((await client.get("/sos", headers=bearer(f.owner))).json()) == 1  # still on the owner's list


async def test_only_responders_see_alerts_and_other_businesses_see_none(client):
    from tests.helpers import owner_session

    f = await fleet(client)
    alert = (await press(client, f.driver)).json()
    assert (await client.get("/sos", headers=bearer(f.driver))).status_code == 403
    assert (await client.post(f"/sos/{alert['id']}/acknowledge", headers=bearer(f.driver), json={})).status_code == 403
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    assert (await client.get("/sos", headers=bearer(other))).json() == []
    assert (await client.post(f"/sos/{alert['id']}/acknowledge", headers=bearer(other), json={})).status_code == 404
    other_vehicle_sup = await staff(client, f, "supervisor", "s@example.com", "+254733000009", vehicle_scope=[])
    assert (await client.get("/sos", headers=bearer(other_vehicle_sup))).json() == []
