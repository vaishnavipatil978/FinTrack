"""Stage 9 - Redis-backed behavior against a real Redis (dedicated db 15, flushed per test).

Covers: rate limiting, user-namespaced report caching with invalidation, idempotent replay
of writes, and fail-open degradation when Redis is unreachable.
"""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import ReportCache
from app.core.config import Environment, Settings
from app.db.session import get_db_session
from app.main import create_app
from tests.conftest import TEST_JWT_SECRET, _require_test_database
from tests.helpers import auth_headers, create_account, get_category_id

REDIS_TEST_URL = os.environ.get("FINTRACK_TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client: Redis = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": Environment.TESTING,
        "database_url": _require_test_database(),
        "jwt_secret_key": TEST_JWT_SECRET,
        "cors_origins": ["http://localhost:3000"],
        "redis_url": REDIS_TEST_URL,
        "cache_enabled": True,
        "rate_limit_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


async def _client_for(settings: Settings, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    application: FastAPI = create_app(settings)

    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_db_session] = override
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


# --- Rate limiting ------------------------------------------------------


async def test_login_is_rate_limited_per_client(redis: Redis, db_session: AsyncSession) -> None:
    settings = _settings(rate_limit_auth_per_minute=3)
    async for client in _client_for(settings, db_session):
        statuses = []
        for _ in range(4):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong-password"},
            )
            statuses.append(response.status_code)

    assert statuses[:3] == [401, 401, 401]
    assert statuses[3] == 429


async def test_rate_limit_fails_open_when_redis_unreachable(db_session: AsyncSession) -> None:
    settings = _settings(redis_url="redis://127.0.0.1:1/0", rate_limit_auth_per_minute=1)
    async for client in _client_for(settings, db_session):
        statuses = []
        for _ in range(3):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong-password"},
            )
            statuses.append(response.status_code)

    # Redis is down, so the limiter must not block: requests still reach the handler (401).
    assert statuses == [401, 401, 401]


# --- Report cache ------------------------------------------------------


async def test_cache_round_trip_and_user_namespacing(redis: Redis) -> None:
    cache = ReportCache(redis, enabled=True)
    key_a = ReportCache.key(1, "balances")
    key_b = ReportCache.key(2, "balances")

    await cache.set(key_a, {"total": "10.00"}, ttl_seconds=60)

    assert await cache.get(key_a) == {"total": "10.00"}
    assert await cache.get(key_b) is None  # another user never sees user 1's entry


async def test_invalidate_user_drops_only_that_users_reports(redis: Redis) -> None:
    cache = ReportCache(redis, enabled=True)
    await cache.set(ReportCache.key(1, "balances"), {"a": 1}, ttl_seconds=60)
    await cache.set(ReportCache.key(1, "monthly:2026-09"), {"b": 2}, ttl_seconds=60)
    await cache.set(ReportCache.key(2, "balances"), {"c": 3}, ttl_seconds=60)

    await cache.invalidate_user(1)

    assert await cache.get(ReportCache.key(1, "balances")) is None
    assert await cache.get(ReportCache.key(1, "monthly:2026-09")) is None
    assert await cache.get(ReportCache.key(2, "balances")) == {"c": 3}


async def test_disabled_cache_is_a_no_op(redis: Redis) -> None:
    cache = ReportCache(redis, enabled=False)
    await cache.set("report:1:x", {"a": 1}, ttl_seconds=60)

    assert await redis.get("report:1:x") is None
    assert await cache.get("report:1:x") is None


# --- Idempotent writes ------------------------------------------------------


async def test_repeated_idempotency_key_replays_instead_of_double_posting(
    redis: Redis, db_session: AsyncSession
) -> None:
    settings = _settings(rate_limit_enabled=False)
    async for client in _client_for(settings, db_session):
        headers = await auth_headers(client)
        account = await create_account(client, headers, opening_balance="1000.00")
        food_id = await get_category_id(client, headers, name="Food")
        payload = {
            "account_id": account["id"],
            "type": "EXPENSE",
            "amount": "100.00",
            "currency": "INR",
            "category_id": food_id,
            "transaction_date": "2026-09-01",
            "description": "Once only",
        }
        idem = {**headers, "Idempotency-Key": "retry-me-123"}

        first = await client.post("/api/v1/transactions", json=payload, headers=idem)
        second = await client.post("/api/v1/transactions", json=payload, headers=idem)

        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        balance = (
            await client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
        ).json()
        assert balance["balance"] == "900.00"  # one debit, not two


async def test_different_idempotency_keys_create_separate_transactions(
    redis: Redis, db_session: AsyncSession
) -> None:
    settings = _settings(rate_limit_enabled=False)
    async for client in _client_for(settings, db_session):
        headers = await auth_headers(client)
        account = await create_account(client, headers, opening_balance="1000.00")
        food_id = await get_category_id(client, headers, name="Food")
        payload = {
            "account_id": account["id"],
            "type": "EXPENSE",
            "amount": "100.00",
            "currency": "INR",
            "category_id": food_id,
            "transaction_date": "2026-09-01",
            "description": "Two",
        }

        a = await client.post(
            "/api/v1/transactions",
            json=payload,
            headers={**headers, "Idempotency-Key": "key-a-1234"},
        )
        b = await client.post(
            "/api/v1/transactions",
            json=payload,
            headers={**headers, "Idempotency-Key": "key-b-1234"},
        )

        assert a.json()["id"] != b.json()["id"]
