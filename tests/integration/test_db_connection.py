from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


async def test_ready_returns_200_against_real_postgres(db_settings: Settings) -> None:
    app: FastAPI = create_app(db_settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"
