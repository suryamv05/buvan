from app.core.config import settings
from app.core.errors import APIError

_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return current
"""


async def check_limit(key: str, *, limit: int, window: int) -> None:
    if not settings.rate_limit_enabled:
        return
    from app.core.redis import redis_client

    try:
        count = int(await redis_client.eval(_SCRIPT, 1, key, window))
    except Exception as exc:
        if settings.environment == "production":
            raise APIError(503, "temporarily_unavailable", "Service is temporarily unavailable") from exc
        return
    if count > limit:
        raise APIError(429, "rate_limited", "Too many requests")
