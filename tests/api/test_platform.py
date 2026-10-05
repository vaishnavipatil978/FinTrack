import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

from app.core.exceptions import NotFoundError


class _Payload(BaseModel):
    amount: int


@pytest.fixture(autouse=True)
def _probe_routes(app: FastAPI) -> None:
    @app.get("/_probe/not-found")
    async def not_found() -> None:
        raise NotFoundError("Account missing", code="ACCOUNT_NOT_FOUND")

    @app.get("/_probe/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.post("/_probe/validate")
    async def validate(payload: _Payload) -> _Payload:
        return payload


async def test_domain_error_uses_standard_envelope(client: AsyncClient) -> None:
    response = await client.get("/_probe/not-found")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "ACCOUNT_NOT_FOUND"
    assert error["message"] == "Account missing"
    assert error["request_id"] == response.headers["X-Request-ID"]


async def test_unhandled_error_does_not_leak_internals(client: AsyncClient) -> None:
    response = await client.get("/_probe/boom")

    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


async def test_validation_error_lists_offending_fields(client: AsyncClient) -> None:
    response = await client.post("/_probe/validate", json={"amount": "abc"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "body.amount"


async def test_unknown_route_uses_standard_envelope(client: AsyncClient) -> None:
    response = await client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_incoming_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "trace-abc-12345"})

    assert response.headers["X-Request-ID"] == "trace-abc-12345"


async def test_malformed_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "bad id\twith junk"})

    assert response.headers["X-Request-ID"] != "bad id\twith junk"
    assert len(response.headers["X-Request-ID"]) == 32


async def test_security_headers_are_set(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" not in response.headers  # non-production


async def test_cors_allows_configured_origin_only(client: AsyncClient) -> None:
    allowed = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    denied = await client.get("/health", headers={"Origin": "http://evil.example"})

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers
