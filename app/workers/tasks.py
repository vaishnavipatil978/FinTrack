import asyncio
import datetime
import time
import uuid
from typing import Any

import structlog

from app.core.cache import ReportCache
from app.core.config import get_settings
from app.core.exceptions import FinTrackError
from app.core.metrics import BACKGROUND_JOB_DURATION_SECONDS, BACKGROUND_JOB_FAILURES_TOTAL
from app.core.redis_client import create_redis
from app.db.session import create_engine, create_session_factory
from app.models.enums import CsvBatchStatus
from app.repositories import csv_import_repository
from app.services.csv_import_processing_service import CsvImportProcessingService
from app.services.recurring_processing_service import RecurringProcessingService
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

_BASE_RETRY_DELAY_SECONDS = 60
_MAX_RETRIES = 3


async def _invalidate_reports(user_ids: set[int]) -> None:
    """Write-through invalidation for ledger writes made by the worker - same policy the
    API applies (docs/architecture/caching-strategy.md §3). Failures are logged, not raised.
    """
    if not user_ids:
        return
    settings = get_settings()
    redis = create_redis(settings)
    try:
        cache = ReportCache(redis, enabled=settings.cache_enabled)
        for user_id in user_ids:
            await cache.invalidate_user(user_id)
    finally:
        await redis.aclose()


async def _process_due_recurring_rules_async() -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            service = RecurringProcessingService(session)
            today = datetime.datetime.now(datetime.UTC).date()
            created = await service.process_due_rules(
                as_of=today, catchup_limit=settings.recurring_rules_catchup_limit
            )
            await _invalidate_reports({t.user_id for t in created})
            return len(created)
    finally:
        await engine.dispose()


# celery ships no type stubs, so this decorator is untyped from mypy's perspective.
@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.workers.tasks.process_due_recurring_rules_task",
    bind=True,
    max_retries=_MAX_RETRIES,
)
def process_due_recurring_rules_task(self: Any) -> int:
    task_name = "process_due_recurring_rules_task"
    start = time.perf_counter()
    try:
        count = asyncio.run(_process_due_recurring_rules_async())
    except Exception as exc:
        BACKGROUND_JOB_FAILURES_TOTAL.labels(task_name=task_name, reason=type(exc).__name__).inc()
        logger.error("recurring_rules_processing_failed", error=str(exc))
        retries = self.request.retries
        raise self.retry(exc=exc, countdown=_BASE_RETRY_DELAY_SECONDS * (2**retries)) from exc
    finally:
        BACKGROUND_JOB_DURATION_SECONDS.labels(task_name=task_name).observe(
            time.perf_counter() - start
        )
    logger.info("recurring_rules_processed", transactions_created=count)
    return count


async def _process_import_batch_async(batch_id: str, row_ids_to_import: list[int] | None) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            batch = await csv_import_repository.get_by_id(session, batch_id=uuid.UUID(batch_id))
            if batch is None:
                logger.error("csv_import_batch_not_found", batch_id=batch_id)
                return 0

            processing_service = CsvImportProcessingService(session)
            try:
                imported, skipped = await processing_service.process(
                    batch=batch, row_ids_to_import=row_ids_to_import
                )
            except FinTrackError:
                batch.status = CsvBatchStatus.FAILED
                await session.commit()
                raise
            batch.status = CsvBatchStatus.COMPLETED
            batch.imported_rows = imported
            batch.skipped_rows = skipped
            await session.commit()
            await _invalidate_reports({batch.user_id})
            return imported
    finally:
        await engine.dispose()


# celery ships no type stubs, so this decorator is untyped from mypy's perspective.
@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.workers.tasks.process_import_batch_task",
    bind=True,
    max_retries=_MAX_RETRIES,
)
def process_import_batch_task(
    self: Any, batch_id: str, row_ids_to_import: list[int] | None = None
) -> int:
    task_name = "process_import_batch_task"
    start = time.perf_counter()
    try:
        imported = asyncio.run(_process_import_batch_async(batch_id, row_ids_to_import))
    except Exception as exc:
        BACKGROUND_JOB_FAILURES_TOTAL.labels(task_name=task_name, reason=type(exc).__name__).inc()
        logger.error("csv_import_processing_failed", batch_id=batch_id, error=str(exc))
        retries = self.request.retries
        raise self.retry(exc=exc, countdown=_BASE_RETRY_DELAY_SECONDS * (2**retries)) from exc
    finally:
        BACKGROUND_JOB_DURATION_SECONDS.labels(task_name=task_name).observe(
            time.perf_counter() - start
        )
    logger.info("csv_import_processed", batch_id=batch_id, imported_rows=imported)
    return imported
