import json
from collections.abc import Awaitable, Callable

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import ConflictError

logger = structlog.get_logger(__name__)

_LOCK_SECONDS = 30

Producer = Callable[[], Awaitable[tuple[int, dict[str, object]]]]


async def run_idempotent(
    redis: Redis | None,
    *,
    enabled: bool,
    ttl_seconds: int,
    user_id: int,
    idempotency_key: str,
    producer: Producer,
) -> tuple[int, dict[str, object]]:
    """Replays the stored response for a repeated Idempotency-Key instead of re-executing.

    A concurrent duplicate that arrives while the first is still running gets 409 rather than
    running twice. The stored response is written only after success, so a failed attempt
    can be retried. Fails open to plain execution if Redis is unavailable - the business
    tables' own guarantees (batch status transitions, unique constraints) still apply.
    """
    if not enabled or redis is None:
        return await producer()

    result_key = f"idem:{user_id}:{idempotency_key}"
    lock_key = f"{result_key}:lock"
    try:
        stored = await redis.get(result_key)
        if stored is not None:
            status_code, body = json.loads(stored)
            return int(status_code), dict(body)
        acquired = await redis.set(lock_key, "1", nx=True, ex=_LOCK_SECONDS)
        if not acquired:
            raise ConflictError(
                "A request with this Idempotency-Key is already in progress",
                code="IDEMPOTENCY_IN_PROGRESS",
            )
    except RedisError as exc:
        logger.warning("idempotency_redis_unavailable", error=type(exc).__name__)
        return await producer()

    try:
        status_code, body = await producer()
        await redis.set(result_key, json.dumps([status_code, body]), ex=ttl_seconds)
        return status_code, body
    finally:
        await redis.delete(lock_key)
