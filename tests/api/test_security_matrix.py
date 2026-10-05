"""Stage 12 - systematic unauthorized/malformed-token coverage across every resource.

Per-resource ownership (cross-user 404) is already covered where each resource's own test
module lives (test_accounts.py, test_transactions.py, test_budgets.py, etc.) - this file's
job is the orthogonal check: every protected GET must reject a missing or garbage token
*before* touching the resource, regardless of whether that resource exists.
"""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from tests.conftest import TEST_JWT_SECRET
from tests.helpers import auth_headers

PROTECTED_GET_PATHS = [
    "/api/v1/users/me",
    "/api/v1/accounts",
    "/api/v1/accounts/1",
    "/api/v1/accounts/1/balance",
    "/api/v1/categories",
    "/api/v1/transactions",
    "/api/v1/transactions/1",
    "/api/v1/transfers",
    "/api/v1/transfers/1",
    "/api/v1/budgets",
    "/api/v1/budgets/1",
    "/api/v1/budgets/summary",
    "/api/v1/goals",
    "/api/v1/goals/1",
    "/api/v1/goals/1/contributions",
    "/api/v1/recurring-transactions",
    "/api/v1/recurring-transactions/1",
    "/api/v1/recurring-transactions/1/occurrences",
    "/api/v1/notifications",
    "/api/v1/notifications/preferences",
    "/api/v1/audit/me",
    "/api/v1/reports/balances",
]


@pytest.mark.parametrize("path", PROTECTED_GET_PATHS)
async def test_missing_token_is_rejected(db_client: AsyncClient, path: str) -> None:
    response = await db_client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("path", PROTECTED_GET_PATHS)
async def test_garbage_token_is_rejected(db_client: AsyncClient, path: str) -> None:
    response = await db_client.get(path, headers={"Authorization": "Bearer not-a-real-jwt"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/budgets",
        "/api/v1/goals",
        "/api/v1/recurring-transactions",
        "/api/v1/notifications",
    ],
)
async def test_expired_token_is_rejected(db_client: AsyncClient, path: str) -> None:
    expired = create_access_token(
        user_id=1, role="USER", secret_key=TEST_JWT_SECRET, algorithm="HS256", expires_minutes=-1
    )

    response = await db_client.get(path, headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/accounts",
        "/api/v1/transactions",
        "/api/v1/budgets",
        "/api/v1/goals",
        "/api/v1/recurring-transactions",
    ],
)
async def test_write_endpoints_also_reject_missing_token(db_client: AsyncClient, path: str) -> None:
    response = await db_client.post(path, json={})

    assert response.status_code == 401


async def test_malformed_json_body_returns_422_not_500(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.post(
        "/api/v1/accounts",
        headers={**headers, "Content-Type": "application/json"},
        content=b"{not valid json",
    )

    assert response.status_code == 422
