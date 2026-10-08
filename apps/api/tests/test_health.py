from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_reports_service():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "fleettms-api"
    assert body["database"] in ("up", "down")


async def test_health_answers_head_for_free_uptime_monitors(monkeypatch):
    """HEAD has no body, so it is 200 when the database and Redis are up and 503 when either is down; GET stays 200 and says which."""
    from app import main

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        monkeypatch.setattr(main, "database_is_up", lambda: _answer(True))
        monkeypatch.setattr(main, "redis_is_up", lambda: _answer(True))
        assert (await client.head("/health")).status_code == 200
        monkeypatch.setattr(main, "database_is_up", lambda: _answer(False))
        assert (await client.head("/health")).status_code == 503
        down = await client.get("/health")
        assert down.status_code == 200 and down.json()["database"] == "down"
        monkeypatch.setattr(main, "database_is_up", lambda: _answer(True))
        monkeypatch.setattr(main, "redis_is_up", lambda: _answer(False))
        assert (await client.head("/health")).status_code == 503
        assert (await client.head("/ready")).status_code in (200, 503)


async def _answer(value: bool) -> bool:
    return value
