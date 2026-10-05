import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Environment, Settings
from app.db.session import get_db_session
from app.main import create_app

# Nothing listens on port 1, so connections fail fast without needing a real database.
UNREACHABLE_DB_URL = "postgresql+asyncpg://test:test@127.0.0.1:1/test"

# Long enough to satisfy the production jwt_secret_key length guard too, so a test that
# happens to construct Settings(environment=PRODUCTION) doesn't fail on this alone.
TEST_JWT_SECRET = "test-only-secret-key-not-for-production-use-0123456789abcdef"

TEST_DATABASE_URL = os.environ.get("FINTRACK_TEST_DATABASE_URL")


def _require_test_database() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("Set FINTRACK_TEST_DATABASE_URL to run tests against a real PostgreSQL")
    return TEST_DATABASE_URL


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment=Environment.TESTING,
        database_url=UNREACHABLE_DB_URL,
        cors_origins=["http://localhost:3000"],
        jwt_secret_key=TEST_JWT_SECRET,
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def db_settings() -> Settings:
    return Settings(
        environment=Environment.TESTING,
        database_url=_require_test_database(),
        cors_origins=["http://localhost:3000"],
        jwt_secret_key=TEST_JWT_SECRET,
        cache_enabled=False,
        rate_limit_enabled=False,
    )


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session bound to one connection/transaction per test, rolled back afterwards.

    Service code is expected to call session.commit() as part of its own transaction
    boundaries (see docs/architecture/component-architecture.md §1). join_transaction_mode=
    "create_savepoint" makes those inner commits release a SAVEPOINT instead of ending the
    outer transaction, so the whole test's writes are still discarded by the rollback below -
    this keeps every test isolated without needing to truncate tables between tests.
    """
    engine = create_async_engine(_require_test_database(), poolclass=NullPool)
    async with engine.connect() as connection:
        trans = await connection.begin()
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


@pytest.fixture
async def db_app(db_settings: Settings, db_session: AsyncSession) -> AsyncIterator[FastAPI]:
    application = create_app(db_settings)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_db_session] = override_get_db_session
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def db_client(db_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=db_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
