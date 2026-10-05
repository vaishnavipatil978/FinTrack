import time
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.exceptions import RateLimitedError
from app.core.metrics import RATE_LIMIT_REJECTIONS_TOTAL

logger = structlog.get_logger(__name__)

_WINDOW_SECONDS = 60


def rate_limit(scope: str, limit_setting: str) -> Callable[[Request], Awaitable[None]]:
    """Fixed-window per-client-IP limit, Redis-backed (security-architecture.md §3).

    Fails open: if Redis errors, the request is allowed and the failure is logged, so a
    cache outage never locks everyone out of login.
    """

    async def dependency(request: Request) -> None:
        settings: Settings = request.app.state.settings
        if not settings.rate_limit_enabled or not settings.cache_enabled:
            return
        redis = request.app.state.redis
        limit = int(getattr(settings, limit_setting))
        client_ip = request.client.host if request.client else "unknown"
        window = int(time.time()) // _WINDOW_SECONDS
        key = f"ratelimit:{scope}:{client_ip}:{window}"
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, _WINDOW_SECONDS)
        except RedisError as exc:
            logger.warning("rate_limit_redis_unavailable", scope=scope, error=type(exc).__name__)
            return
        if count > limit:
            RATE_LIMIT_REJECTIONS_TOTAL.labels(scope=scope).inc()
            raise RateLimitedError("Too many requests, please try again shortly")

    return dependency
