"""Role-based rate limiting with Redis."""

import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import redis.asyncio as redis

from .config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    RATE_LIMIT_DEVELOPER,
    RATE_LIMIT_VIEWER,
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_WINDOW_SECONDS,
)
from .schemas import RateLimitStatus, UserRole

logger = logging.getLogger(__name__)


class RateLimiter:
    """Redis-based rate limiter with role-based limits."""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None

        # Rate limits by role
        self.limits = {
            UserRole.ADMIN: RATE_LIMIT_ADMIN,  # 0 = unlimited
            UserRole.DEVELOPER: RATE_LIMIT_DEVELOPER,
            UserRole.VIEWER: RATE_LIMIT_VIEWER,
        }

    async def connect(self):
        """Connect to Redis."""
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
        )
        logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

    async def close(self):
        """Close connection."""
        if self.redis:
            await self.redis.close()

    def _get_limit(self, role: UserRole) -> int:
        """Get rate limit for a role."""
        return self.limits.get(role, RATE_LIMIT_VIEWER)

    async def check(self, user_id: str, role: UserRole) -> RateLimitStatus:
        """Check rate limit status for a user."""
        limit = self._get_limit(role)

        # Unlimited for admins
        if limit == 0:
            return RateLimitStatus(
                requests_remaining=999999,
                requests_limit=0,
                reset_at=datetime.utcnow()
                + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS),
                is_limited=False,
                role=role,
            )

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
            reset_at = datetime.utcnow() + timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)

        return RateLimitStatus(
            requests_remaining=max(0, limit - count),
            requests_limit=limit,
            reset_at=reset_at,
            is_limited=count >= limit,
            role=role,
        )

    async def record(self, user_id: str, role: UserRole) -> bool:
        """Record a request. Returns True if allowed, False if rate limited."""
        limit = self._get_limit(role)

        # Unlimited for admins
        if limit == 0:
            return True

        status = await self.check(user_id, role)

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
