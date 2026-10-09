"""The tenant dependency alone, no stack: a request without a usable tenant never reaches a table."""

import uuid

from httpx import ASGITransport, AsyncClient

from api.main import app


async def test_missing_tenant_header_is_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/runs/{uuid.uuid4()}")
    assert response.status_code == 422  # FastAPI's own answer for a missing required header


async def test_malformed_tenant_header_is_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/runs/{uuid.uuid4()}", headers={"X-Tenant-Id": "not-a-uuid"})
    assert response.status_code == 400
