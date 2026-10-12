"""The API's own checks, no stack: a request without a usable tenant or a usable brief never reaches a table."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from api.deps import temporal
from api.main import app
from tests.cat_cafe import BRIEF

TENANT = {"X-Tenant-Id": str(uuid.uuid4())}


async def test_missing_tenant_header_is_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/runs/{uuid.uuid4()}")
    assert response.status_code == 422  # FastAPI's own answer for a missing required header


async def test_malformed_tenant_header_is_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/runs/{uuid.uuid4()}", headers={"X-Tenant-Id": "not-a-uuid"})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "change",
    [
        {"idea": "too short"},
        {"idea": "x" * 2_001},
        {"a_angles": ["cat café"]},
        {"a_angles": ["a", "b", "c", "d", "e"]},
        {"a_angles": ["cat café", "y" * 80]},
        {"place": ""},
    ],
)
async def test_brief_outside_its_caps_is_rejected(change: dict) -> None:
    """FastAPI resolves dependencies before it validates the body, so the Temporal one is replaced; this test runs
    without a stack."""
    app.dependency_overrides[temporal] = lambda: None
    try:
        body = {"thread_id": str(uuid.uuid4()), "brief": BRIEF.model_dump() | change}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/runs", json=body, headers=TENANT)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
