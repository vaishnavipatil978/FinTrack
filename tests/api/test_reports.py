import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment, Settings
from app.db.session import get_db_session
from app.main import create_app
from tests.conftest import TEST_JWT_SECRET, _require_test_database
from tests.helpers import auth_headers, create_account, create_transaction, get_category_id

REDIS_TEST_URL = os.environ.get("FINTRACK_TEST_REDIS_URL", "redis://localhost:6379/15")


async def _create_transfer(
    client: AsyncClient, headers: dict[str, str], src: int, dst: int
) -> None:
    response = await client.post(
        "/api/v1/transfers",
        json={
            "from_account_id": src,
            "to_account_id": dst,
            "amount": "300.00",
            "currency": "INR",
            "transfer_date": "2026-09-10",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


# --- Correctness -----------------------------------------------------------


async def test_monthly_summary_totals_and_top_categories(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    bank = await create_account(db_client, headers, name="Bank", opening_balance="10000.00")
    wallet = await create_account(db_client, headers, name="Wallet", opening_balance="0.00")
    food = await get_category_id(db_client, headers, name="Food")
    rent = await get_category_id(db_client, headers, name="Rent")
    salary = await get_category_id(db_client, headers, name="Salary")

    await create_transaction(
        db_client,
        headers,
        account_id=bank["id"],
        category_id=salary,
        type="INCOME",
        amount="5000.00",
        transaction_date="2026-09-01",
    )
    await create_transaction(
        db_client,
        headers,
        account_id=bank["id"],
        category_id=rent,
        amount="1200.00",
        transaction_date="2026-09-02",
    )
    await create_transaction(
        db_client,
        headers,
        account_id=bank["id"],
        category_id=food,
        amount="300.00",
        transaction_date="2026-09-03",
    )
    voided = await create_transaction(
        db_client,
        headers,
        account_id=bank["id"],
        category_id=food,
        amount="999.00",
        transaction_date="2026-09-04",
    )
    await db_client.delete(f"/api/v1/transactions/{voided['id']}", headers=headers)
    # Transfers move money, they don't earn or spend it - must not count.
    await _create_transfer(db_client, headers, bank["id"], wallet["id"])

    response = await db_client.get(
        "/api/v1/reports/monthly-summary", params={"month": 9, "year": 2026}, headers=headers
    )

    body = response.json()
    assert body["total_income"] == "5000.00"
    assert body["total_expense"] == "1500.00"
    assert body["net_savings"] == "3500.00"
    assert [c["category_name"] for c in body["top_categories"]] == ["Rent", "Food"]


async def test_empty_month_returns_zeros_not_an_error(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.get(
        "/api/v1/reports/monthly-summary", params={"month": 1, "year": 2001}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_income"] == "0.00"
    assert body["total_expense"] == "0.00"
    assert body["top_categories"] == []


async def test_category_breakdown_percentages(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    bank = await create_account(db_client, headers, opening_balance="10000.00")
    food = await get_category_id(db_client, headers, name="Food")
    rent = await get_category_id(db_client, headers, name="Rent")
    await create_transaction(
        db_client,
        headers,
        account_id=bank["id"],
        category_id=food,
        amount="300.00",
        transaction_date="2026-09-03",
    )
    await create_transaction(
        db_client,
        headers,
        account_id=bank["id"],
        category_id=rent,
        amount="900.00",
        transaction_date="2026-09-02",
    )

    response = await db_client.get(
        "/api/v1/reports/category-breakdown", params={"month": 9, "year": 2026}, headers=headers
    )

    body = response.json()
    assert body["total"] == "1200.00"
    pcts = {item["category_name"]: item["pct_of_total"] for item in body["items"]}
    assert pcts == {"Rent": "75.00", "Food": "25.00"}


async def test_balances_total_per_currency_and_exclude_archived(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    await create_account(db_client, headers, name="A", opening_balance="100.00")
    await create_account(db_client, headers, name="B", opening_balance="250.00")
    archived = await create_account(db_client, headers, name="Old", opening_balance="9999.00")
    await db_client.post(f"/api/v1/accounts/{archived['id']}/archive", headers=headers)

    response = await db_client.get("/api/v1/reports/balances", headers=headers)

    body = response.json()
    assert body["totals_by_currency"] == {"INR": "350.00"}
    assert {a["name"] for a in body["accounts"]} == {"A", "B"}


async def test_budgets_goals_snapshot_shape(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.get(
        "/api/v1/reports/budgets-goals-snapshot", params={"month": 9, "year": 2026}, headers=headers
    )

    assert response.status_code == 200
    assert set(response.json()) == {"period_month", "period_year", "budgets", "goals"}


async def test_reports_are_scoped_to_the_caller(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    await create_account(db_client, owner, name="Owner", opening_balance="500.00")
    intruder = await auth_headers(db_client, email="intruder@example.com")

    body = (await db_client.get("/api/v1/reports/balances", headers=intruder)).json()

    assert body["accounts"] == []
    assert body["totals_by_currency"] == {}


# --- Cache behaviour (Stage 9 / caching-strategy.md) -----------------------


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client: Redis = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


async def test_monthly_summary_is_cached_and_a_write_invalidates_it(
    redis: Redis, db_session: AsyncSession
) -> None:
    settings = Settings(
        environment=Environment.TESTING,
        database_url=_require_test_database(),
        jwt_secret_key=TEST_JWT_SECRET,
        cors_origins=["http://localhost:3000"],
        redis_url=REDIS_TEST_URL,
        cache_enabled=True,
        rate_limit_enabled=False,
    )
    application = create_app(settings)

    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_db_session] = override
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await auth_headers(client)
            bank = await create_account(client, headers, opening_balance="5000.00")
            food = await get_category_id(client, headers, name="Food")
            params = {"month": 9, "year": 2026}

            first = await client.get(
                "/api/v1/reports/monthly-summary", params=params, headers=headers
            )
            keys = [k async for k in redis.scan_iter(match="report:*")]
            assert len(keys) == 1  # populated on first read

            await create_transaction(
                client,
                headers,
                account_id=bank["id"],
                category_id=food,
                amount="700.00",
                transaction_date="2026-09-05",
            )

            second = await client.get(
                "/api/v1/reports/monthly-summary", params=params, headers=headers
            )

    assert first.json()["total_expense"] == "0.00"
    assert second.json()["total_expense"] == "700.00"  # not the stale cached zero
