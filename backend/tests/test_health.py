"""Test suite for the health and readiness contract of the API."""

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_health_endpoint_reports_service_identity() -> None:
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "factuhub-backend"
    assert body["version"]


async def test_unknown_route_returns_404_instead_of_leaking_internals() -> None:
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
