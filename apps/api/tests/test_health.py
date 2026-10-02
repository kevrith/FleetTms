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
