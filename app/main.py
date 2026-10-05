from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, metrics
from app.api.v1 import accounts as accounts_v1
from app.api.v1 import admin as admin_v1
from app.api.v1 import audit as audit_v1
from app.api.v1 import auth as auth_v1
from app.api.v1 import budgets as budgets_v1
from app.api.v1 import categories as categories_v1
from app.api.v1 import goals as goals_v1
from app.api.v1 import notifications as notifications_v1
from app.api.v1 import recurring_transactions as recurring_transactions_v1
from app.api.v1 import reports as reports_v1
from app.api.v1 import transactions as transactions_v1
from app.api.v1 import transfers as transfers_v1
from app.api.v1 import users as users_v1
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.redis_client import create_redis
from app.db.session import create_engine, create_session_factory
from app.middleware.metrics import MetricsMiddleware
from app.middleware.request_logging import REQUEST_ID_HEADER, RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    logger = structlog.get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        redis = create_redis(settings)
        app.state.redis = redis
        logger.info("app_started", environment=settings.environment.value)
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()
            logger.info("app_stopped")

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Personal finance management API.",
        lifespan=lifespan,
    )
    # Dependencies read this (not the module-level get_settings() cache) so each app
    # instance - important in tests, which build several with different settings - is
    # always wired to the exact Settings it was constructed with.
    app.state.settings = settings

    # Added last = outermost. Request context wraps everything so all logs carry the request id.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(MetricsMiddleware)

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(auth_v1.router, prefix="/api/v1")
    app.include_router(users_v1.router, prefix="/api/v1")
    app.include_router(accounts_v1.router, prefix="/api/v1")
    app.include_router(categories_v1.router, prefix="/api/v1")
    app.include_router(transactions_v1.router, prefix="/api/v1")
    app.include_router(transfers_v1.router, prefix="/api/v1")
    app.include_router(budgets_v1.router, prefix="/api/v1")
    app.include_router(goals_v1.router, prefix="/api/v1")
    app.include_router(recurring_transactions_v1.router, prefix="/api/v1")
    app.include_router(notifications_v1.router, prefix="/api/v1")
    app.include_router(audit_v1.router, prefix="/api/v1")
    app.include_router(admin_v1.router, prefix="/api/v1")
    app.include_router(reports_v1.router, prefix="/api/v1")
    return app
