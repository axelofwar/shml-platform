"""Unit tests for rate limiting."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_developer_rate_limit_100_per_minute(self):
        """Developers should have 100 requests per minute limit."""
        from inference.chat_api.app.rate_limit import RateLimiter
        from inference.chat_api.app.schemas import UserRole

        limiter = RateLimiter()
        limiter.redis = AsyncMock()

        # Simulate 99 previous requests (count = 99, so 100th should pass)
        limiter.redis.zremrangebyscore = AsyncMock()
        limiter.redis.zcard = AsyncMock(return_value=99)  # 99 requests made
        limiter.redis.zrange = AsyncMock(return_value=[])
        limiter.redis.zadd = AsyncMock()
        limiter.redis.expire = AsyncMock()

        result = await limiter.record("user123", UserRole.DEVELOPER)
        assert result is True  # 100th request should pass

    @pytest.mark.asyncio
    async def test_developer_exceeds_rate_limit(self):
        """Developer exceeding 100 requests should be rate limited."""
        from inference.chat_api.app.rate_limit import RateLimiter
        from inference.chat_api.app.schemas import UserRole

        limiter = RateLimiter()
        limiter.redis = AsyncMock()

        # Simulate 100 previous requests (at limit, next should fail)
        limiter.redis.zremrangebyscore = AsyncMock()
        limiter.redis.zcard = AsyncMock(return_value=100)  # 100 requests made
        limiter.redis.zrange = AsyncMock(return_value=[("entry", 1234567890.0)])

        result = await limiter.record("user123", UserRole.DEVELOPER)
        assert result is False  # 101st request should be rejected

    @pytest.mark.asyncio
    async def test_admin_unlimited_requests(self):
        """Admins should have unlimited requests."""
        from inference.chat_api.app.rate_limit import RateLimiter
        from inference.chat_api.app.schemas import UserRole

        limiter = RateLimiter()
        limiter.redis = AsyncMock()

        # Simulate any number of requests
        limiter.redis.incr = AsyncMock(return_value=10000)
        limiter.redis.ttl = AsyncMock(return_value=30)
        limiter.redis.expire = AsyncMock()

        result = await limiter.record("admin123", UserRole.ADMIN)
        assert result is True  # Admin always passes

    @pytest.mark.asyncio
    async def test_viewer_rate_limit_20_per_minute(self):
        """Viewers should have 20 requests per minute limit."""
        from inference.chat_api.app.rate_limit import RateLimiter
        from inference.chat_api.app.schemas import UserRole

        limiter = RateLimiter()
        limiter.redis = AsyncMock()

        # Simulate 19 requests made (20th should pass)
        limiter.redis.zremrangebyscore = AsyncMock()
        limiter.redis.zcard = AsyncMock(return_value=19)
        limiter.redis.zrange = AsyncMock(return_value=[])
        limiter.redis.zadd = AsyncMock()
        limiter.redis.expire = AsyncMock()

        result = await limiter.record("viewer123", UserRole.VIEWER)
        assert result is True  # 20th request should pass

    @pytest.mark.asyncio
    async def test_viewer_exceeds_rate_limit(self):
        """Viewer exceeding 20 requests should be rate limited."""
        from inference.chat_api.app.rate_limit import RateLimiter
        from inference.chat_api.app.schemas import UserRole

        limiter = RateLimiter()
        limiter.redis = AsyncMock()

        # Simulate 20 requests made (at limit, next should fail)
        limiter.redis.zremrangebyscore = AsyncMock()
        limiter.redis.zcard = AsyncMock(return_value=20)
        limiter.redis.zrange = AsyncMock(return_value=[("entry", 1234567890.0)])

        result = await limiter.record("viewer123", UserRole.VIEWER)
        assert result is False  # 21st request should be rejected

    @pytest.mark.asyncio
    async def test_rate_limit_check_returns_status(self):
        """Rate limit check should return current status."""
        from inference.chat_api.app.rate_limit import RateLimiter
        from inference.chat_api.app.schemas import UserRole

        limiter = RateLimiter()
        limiter.redis = AsyncMock()

        # Simulate 50 requests made
        limiter.redis.zremrangebyscore = AsyncMock()
        limiter.redis.zcard = AsyncMock(return_value=50)
        limiter.redis.zrange = AsyncMock(return_value=[])

        status = await limiter.check("user123", UserRole.DEVELOPER)

        assert status.requests_remaining == 50  # 100 - 50
        assert status.requests_limit == 100
        assert status.is_limited is False


class TestRateLimitByRole:
    """Test that rate limits are correctly applied per role."""

    @pytest.mark.asyncio
    async def test_each_role_has_correct_limit(self):
        """Verify correct limits per role."""
        from inference.chat_api.app.config import (
            RATE_LIMIT_DEVELOPER,
            RATE_LIMIT_VIEWER,
            RATE_LIMIT_ADMIN,
        )

        assert RATE_LIMIT_DEVELOPER == 100
        assert RATE_LIMIT_VIEWER == 20
        assert RATE_LIMIT_ADMIN == 0  # 0 = unlimited

    @pytest.mark.asyncio
    async def test_api_key_inherits_role_limit(self, sample_api_key_user):
        """API key users should inherit their role's rate limit."""
        from inference.chat_api.app.rate_limit import RateLimiter

        limiter = RateLimiter()
        limiter.redis = AsyncMock()

        # API key user with developer role (99 requests made, 100th should pass)
        limiter.redis.zremrangebyscore = AsyncMock()
        limiter.redis.zcard = AsyncMock(return_value=99)
        limiter.redis.zrange = AsyncMock(return_value=[])
        limiter.redis.zadd = AsyncMock()
        limiter.redis.expire = AsyncMock()

        # Should use developer limit (100)
        result = await limiter.record(sample_api_key_user.id, sample_api_key_user.role)
        assert result is True  # 100th request should pass
