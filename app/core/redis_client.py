from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    # Short timeouts so a Redis outage degrades features quickly instead of stalling requests.
    client: Redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    return client
