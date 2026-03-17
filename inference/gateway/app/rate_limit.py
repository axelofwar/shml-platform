"""Rate limiting with Redis."""

import time
import logging
from datetime import datetime, timedelta

import redis.asyncio as redis

from .config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)
from .schemas import RateLimitStatus

logger = logging.getLogger(__name__)


class RateLimiter:
    """Redis-based rate limiter using sliding window."""

    def __init__(self):
        self.redis: redis.Redis = None

    async def connect(self):
        """Connect to Redis (reuses queue connection)."""
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
        )

    async def close(self):
        """Close connection."""
        if self.redis:
            await self.redis.close()

    async def check(self, user_id: str) -> RateLimitStatus:
        """Check if user is rate limited. Returns status."""
        key = f"ratelimit:{user_id}"
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW_SECONDS

        # Remove old entries
        await self.redis.zremrangebyscore(key, 0, window_start)

        # Count requests in window
        count = await self.redis.zcard(key)

        # Calculate reset time
        oldest = await self.redis.zrange(key, 0, 0, withscores=True)
        if oldest:
            reset_at = datetime.fromtimestamp(oldest[0][1] + RATE_LIMIT_WINDOW_SECONDS)
        else:
            reset_at = datetime.now() + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)

        return RateLimitStatus(
            requests_remaining=max(0, RATE_LIMIT_REQUESTS - count),
            requests_limit=RATE_LIMIT_REQUESTS,
            reset_at=reset_at,
            is_limited=count >= RATE_LIMIT_REQUESTS,
        )

    async def record(self, user_id: str) -> bool:
        """Record a request. Returns True if allowed, False if rate limited."""
        status = await self.check(user_id)

        if status.is_limited:
            return False

        # Add current request
        key = f"ratelimit:{user_id}"
        now = time.time()
        await self.redis.zadd(key, {f"{now}": now})

        # Set expiry on key
        await self.redis.expire(key, RATE_LIMIT_WINDOW_SECONDS * 2)

        return True


# Global instance
rate_limiter = RateLimiter()
