import json
from typing import Any

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.metrics import CACHE_HITS_TOTAL, CACHE_MISSES_TOTAL

logger = structlog.get_logger(__name__)


class ReportCache:
    """Read-through cache for read-heavy report data - docs/architecture/caching-strategy.md.

    Keys are always namespaced by user_id so one user's data can never be served to another.
    Every operation fails open: a Redis error is logged and treated as a cache miss.
    """

    def __init__(self, redis: Redis | None, *, enabled: bool) -> None:
        self._redis = redis
        self._enabled = enabled and redis is not None

    @staticmethod
    def key(user_id: int, name: str) -> str:
        return f"report:{user_id}:{name}"

    async def get(self, key: str) -> Any | None:
        if not self._enabled or self._redis is None:
            return None
        prefix = key.split(":")[0]
        try:
            raw = await self._redis.get(key)
        except RedisError as exc:
            logger.warning("cache_get_failed", key=key, error=type(exc).__name__)
            return None
        if raw is None:
            CACHE_MISSES_TOTAL.labels(cache_key_prefix=prefix).inc()
            return None
        CACHE_HITS_TOTAL.labels(cache_key_prefix=prefix).inc()
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if not self._enabled or self._redis is None:
            return
        try:
            await self._redis.set(key, json.dumps(value), ex=ttl_seconds)
        except RedisError as exc:
            logger.warning("cache_set_failed", key=key, error=type(exc).__name__)

    async def invalidate_user(self, user_id: int) -> None:
        """Write-path invalidation: any ledger write drops every cached report for that user.
        Over-invalidating a single user's reports is cheap and always correct.
        """
        if not self._enabled or self._redis is None:
            return
        try:
            keys = [key async for key in self._redis.scan_iter(match=f"report:{user_id}:*")]
            if keys:
                await self._redis.delete(*keys)
        except RedisError as exc:
            logger.warning("cache_invalidate_failed", user_id=user_id, error=type(exc).__name__)
