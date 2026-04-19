"""
NeuralEdge AI - Redis-Backed Sliding Window Rate Limiter

Uses a sorted-set per key with timestamps as scores.  Old entries are
pruned on every check so the window slides forward continuously.

Usage as a FastAPI dependency::

    @router.get("/signals", dependencies=[Depends(rate_limit_dependency(30))])
    async def get_signals():
        ...
"""
import time
import uuid
from typing import Callable

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status

from config import settings

# ---------------------------------------------------------------------------
# Redis connection pool (lazy singleton)
# ---------------------------------------------------------------------------
_pool: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    """Return a shared async Redis connection pool."""
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=False,
        )
    return _pool


# ---------------------------------------------------------------------------
# Rate limiter core
# ---------------------------------------------------------------------------
class RateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets.

    Each call to ``check()`` adds a timestamped member, prunes expired
    entries, and returns whether the caller is within the limit.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def check(self, key: str, limit: int, window: int) -> bool:
        """Return True if the request is ALLOWED, False if rate-limited.

        Args:
            key:    Unique identifier (e.g. ``"rl:user:<uuid>:/api/signals"``).
            limit:  Maximum number of requests in the window.
            window: Window size in seconds.
        """
        now = time.time()
        window_start = now - window

        pipe = self._redis.pipeline(transaction=True)
        # Remove entries older than the window
        pipe.zremrangebyscore(key, 0, window_start)
        # Add current request with unique member to avoid collisions
        member = f"{now}:{uuid.uuid4().hex[:8]}"
        pipe.zadd(key, {member: now})
        # Count entries in window
        pipe.zcard(key)
        # Set TTL so Redis auto-cleans abandoned keys
        pipe.expire(key, window + 1)

        results = await pipe.execute()
        current_count: int = results[2]

        return current_count <= limit


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------
def rate_limit_dependency(
    limit: int,
    window: int = 60,
    key_func: Callable[[Request], str] | None = None,
):
    """Create a FastAPI dependency that enforces rate limiting.

    Args:
        limit:    Max requests per window.
        window:   Window size in seconds (default 60).
        key_func: Optional callable ``(request) -> str`` for custom keys.
                  Defaults to ``"rl:<client_ip>:<path>"``.

    Usage::

        @router.post("/orders", dependencies=[Depends(rate_limit_dependency(5, 60))])
        async def place_order():
            ...
    """

    async def _dependency(request: Request) -> None:
        redis = await _get_redis()
        limiter = RateLimiter(redis)

        if key_func is not None:
            key = key_func(request)
        else:
            # Default: rate-limit by IP + path
            client_ip = request.client.host if request.client else "unknown"
            key = f"rl:{client_ip}:{request.url.path}"

        allowed = await limiter.check(key, limit, window)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({limit} requests per {window}s)",
                headers={"Retry-After": str(window)},
            )

    return _dependency
