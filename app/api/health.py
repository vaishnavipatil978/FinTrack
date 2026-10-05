import asyncio

import structlog
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session

router = APIRouter(tags=["Health"])
logger = structlog.get_logger(__name__)

READINESS_TIMEOUT_SECONDS = 2.0


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Reports that the process is up. Deliberately checks no dependencies."""
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness probe",
    responses={503: {"description": "A required dependency is unavailable"}},
)
async def ready(
    response: Response, session: AsyncSession = Depends(get_db_session)
) -> dict[str, object]:
    """Reports whether this instance can serve traffic (database reachable)."""
    checks: dict[str, str] = {}
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), READINESS_TIMEOUT_SECONDS)
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        logger.warning("readiness_check_failed", dependency="database", error=type(exc).__name__)
        checks["database"] = "unavailable"

    is_ready = all(value == "ok" for value in checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if is_ready else "not_ready", "checks": checks}
