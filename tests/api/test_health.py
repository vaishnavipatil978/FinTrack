from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import get_db_session


async def test_health_returns_ok_without_touching_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_returns_503_when_database_unreachable(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}


@pytest.fixture
def healthy_db(app: FastAPI) -> None:
    async def fake_session() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = fake_session


@pytest.mark.usefixtures("healthy_db")
async def test_ready_returns_200_when_database_responds(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
