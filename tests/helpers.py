from typing import Any

from httpx import AsyncClient

DEFAULT_PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test fixture, not a credential


async def register(
    client: AsyncClient,
    *,
    email: str = "owner@example.com",
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Test Owner",
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def login(
    client: AsyncClient, *, email: str = "owner@example.com", password: str = DEFAULT_PASSWORD
) -> dict[str, Any]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return dict(response.json())


async def auth_headers(
    client: AsyncClient,
    *,
    email: str = "owner@example.com",
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Test Owner",
) -> dict[str, str]:
    """Registers a fresh user and returns an Authorization header for them."""
    await register(client, email=email, password=password, full_name=full_name)
    tokens = await login(client, email=email, password=password)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def create_account(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Test Account",
        "type": "BANK",
        "currency": "INR",
        "opening_balance": "1000.00",
        **overrides,
    }
    response = await client.post("/api/v1/accounts", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def get_category_id(
    client: AsyncClient, headers: dict[str, str], *, name: str = "Food"
) -> int:
    response = await client.get("/api/v1/categories", headers=headers)
    assert response.status_code == 200, response.text
    category = next(c for c in response.json() if c["name"] == name)
    return int(category["id"])


async def create_transaction(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    account_id: int,
    category_id: int,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "account_id": account_id,
        "type": "EXPENSE",
        "amount": "100.00",
        "currency": "INR",
        "category_id": category_id,
        "transaction_date": "2026-09-01",
        "description": "Test transaction",
        **overrides,
    }
    response = await client.post("/api/v1/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())
