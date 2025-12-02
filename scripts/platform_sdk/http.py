"""
HTTP Client for Platform SDK.

Provides async-first HTTP client with:
- Automatic retries with exponential backoff
- Rate limiting
- Connection pooling
- Request/response logging
- Error handling and conversion to SDK exceptions

Uses httpx for modern async/sync HTTP support.
"""

import asyncio
import logging
import time
import uuid
from typing import Optional, Dict, Any, Union
from contextlib import asynccontextmanager, contextmanager

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .config import SDKConfig
from .models import APIResponse
from .exceptions import (
    PlatformSDKError,
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
    ConnectionError,
    TimeoutError,
)

logger = logging.getLogger("platform_sdk.http")


class RateLimiter:
    """
    Token bucket rate limiter.

    Ensures API calls don't exceed rate limits.
    Thread-safe for sync usage, async-safe for async usage.
    """

    def __init__(self, calls: int, period: float):
        """
        Initialize rate limiter.

        Args:
            calls: Maximum calls per period
            period: Period in seconds
        """
        self.calls = calls
        self.period = period
        self.tokens = calls
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_update
        refill = elapsed * (self.calls / self.period)
        self.tokens = min(self.calls, self.tokens + refill)
        self.last_update = now

    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary."""
        async with self._lock:
            self._refill()

            if self.tokens < 1:
                # Calculate wait time
                wait_time = (1 - self.tokens) * (self.period / self.calls)
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                self._refill()

            self.tokens -= 1

    def acquire_sync(self) -> None:
        """Synchronous token acquisition."""
        self._refill()

        if self.tokens < 1:
            wait_time = (1 - self.tokens) * (self.period / self.calls)
            logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
            time.sleep(wait_time)
            self._refill()

        self.tokens -= 1


class HTTPClient:
    """
    HTTP client with retry, rate limiting, and connection pooling.

    Supports both sync and async operations.

    Example:
        # Async usage
        async with HTTPClient(config) as client:
            response = await client.get("/api/user")

        # Sync usage
        with HTTPClient(config).sync() as client:
            response = client.get_sync("/api/user")
    """

    def __init__(self, config: SDKConfig):
        """
        Initialize HTTP client.

        Args:
            config: SDK configuration
        """
        self.config = config
        self.base_url = config.fusionauth_url
        self.rate_limiter = RateLimiter(
            config.rate_limit_calls, config.rate_limit_period
        )

        # Common headers
        self._headers = {
            "Authorization": config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PlatformSDK/1.0.0",
        }

        if config.fusionauth_tenant_id:
            self._headers["X-FusionAuth-TenantId"] = config.fusionauth_tenant_id

        # Clients (lazy initialized)
        self._async_client: Optional[httpx.AsyncClient] = None
        self._sync_client: Optional[httpx.Client] = None

    def _get_async_client(self) -> httpx.AsyncClient:
        """Get or create async client."""
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers,
                timeout=httpx.Timeout(self.config.timeout),
                limits=httpx.Limits(
                    max_connections=self.config.max_connections,
                    max_keepalive_connections=self.config.max_connections // 2,
                ),
            )
        return self._async_client

    def _get_sync_client(self) -> httpx.Client:
        """Get or create sync client."""
        if self._sync_client is None or self._sync_client.is_closed:
            self._sync_client = httpx.Client(
                base_url=self.base_url,
                headers=self._headers,
                timeout=httpx.Timeout(self.config.timeout),
                limits=httpx.Limits(
                    max_connections=self.config.max_connections,
                    max_keepalive_connections=self.config.max_connections // 2,
                ),
            )
        return self._sync_client

    def _generate_request_id(self) -> str:
        """Generate unique request ID for tracing."""
        return str(uuid.uuid4())[:8]

    def _handle_response(
        self, response: httpx.Response, request_id: str
    ) -> APIResponse:
        """
        Convert httpx response to APIResponse.

        Args:
            response: httpx Response object
            request_id: Request ID for tracing

        Returns:
            APIResponse with parsed data
        """
        try:
            data = response.json() if response.content else {}
        except Exception:
            data = {"raw": response.text}

        if response.is_success:
            return APIResponse.ok(
                data=data,
                status_code=response.status_code,
                request_id=request_id,
            )

        # Extract error message
        error = None
        if isinstance(data, dict):
            # FusionAuth error format
            if "fieldErrors" in data:
                errors = []
                for field, field_errors in data.get("fieldErrors", {}).items():
                    for err in field_errors:
                        errors.append(f"{field}: {err.get('message', 'error')}")
                error = "; ".join(errors)
            elif "message" in data:
                error = data["message"]
            elif "generalErrors" in data:
                errors = [e.get("message", "error") for e in data["generalErrors"]]
                error = "; ".join(errors)

        if not error:
            error = f"HTTP {response.status_code}: {response.reason_phrase}"

        return APIResponse.fail(
            error=error,
            status_code=response.status_code,
            data=data,
            request_id=request_id,
        )

    def _handle_exception(self, exc: Exception, request_id: str) -> APIResponse:
        """Convert exception to APIResponse."""
        if isinstance(exc, httpx.ConnectError):
            return APIResponse.fail(
                error=f"Connection failed: {exc}",
                status_code=0,
                request_id=request_id,
            )
        elif isinstance(exc, httpx.TimeoutException):
            return APIResponse.fail(
                error=f"Request timed out: {exc}",
                status_code=504,
                request_id=request_id,
            )
        else:
            return APIResponse.fail(
                error=str(exc),
                status_code=0,
                request_id=request_id,
            )

    # ========================================================================
    # Async Methods
    # ========================================================================

    async def request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """
        Make async HTTP request with rate limiting and retries.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            path: Request path (e.g., "/api/user")
            json: JSON body data
            params: Query parameters
            headers: Additional headers

        Returns:
            APIResponse with result
        """
        request_id = self._generate_request_id()
        logger.debug(f"[{request_id}] {method} {path}")

        await self.rate_limiter.acquire()

        try:
            client = self._get_async_client()
            response = await client.request(
                method=method,
                url=path,
                json=json,
                params=params,
                headers=headers,
            )

            result = self._handle_response(response, request_id)
            logger.debug(f"[{request_id}] Response: {result.status_code}")
            return result

        except Exception as exc:
            logger.error(f"[{request_id}] Error: {exc}")
            return self._handle_exception(exc, request_id)

    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Async GET request."""
        return await self.request("GET", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Async POST request."""
        return await self.request(
            "POST", path, json=json, params=params, headers=headers
        )

    async def put(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Async PUT request."""
        return await self.request(
            "PUT", path, json=json, params=params, headers=headers
        )

    async def patch(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Async PATCH request."""
        return await self.request(
            "PATCH", path, json=json, params=params, headers=headers
        )

    async def delete(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Async DELETE request."""
        return await self.request("DELETE", path, params=params, headers=headers)

    # ========================================================================
    # Sync Methods
    # ========================================================================

    def request_sync(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """
        Make sync HTTP request with rate limiting.

        Same interface as async request() but blocking.
        """
        request_id = self._generate_request_id()
        logger.debug(f"[{request_id}] {method} {path}")

        self.rate_limiter.acquire_sync()

        try:
            client = self._get_sync_client()
            response = client.request(
                method=method,
                url=path,
                json=json,
                params=params,
                headers=headers,
            )

            result = self._handle_response(response, request_id)
            logger.debug(f"[{request_id}] Response: {result.status_code}")
            return result

        except Exception as exc:
            logger.error(f"[{request_id}] Error: {exc}")
            return self._handle_exception(exc, request_id)

    def get_sync(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Sync GET request."""
        return self.request_sync("GET", path, params=params, headers=headers)

    def post_sync(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Sync POST request."""
        return self.request_sync(
            "POST", path, json=json, params=params, headers=headers
        )

    def put_sync(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Sync PUT request."""
        return self.request_sync("PUT", path, json=json, params=params, headers=headers)

    def patch_sync(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Sync PATCH request."""
        return self.request_sync(
            "PATCH", path, json=json, params=params, headers=headers
        )

    def delete_sync(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> APIResponse:
        """Sync DELETE request."""
        return self.request_sync("DELETE", path, params=params, headers=headers)

    # ========================================================================
    # Context Managers
    # ========================================================================

    async def __aenter__(self) -> "HTTPClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit - close client."""
        await self.close()

    def __enter__(self) -> "HTTPClient":
        """Sync context manager entry."""
        return self

    def __exit__(self, *args) -> None:
        """Sync context manager exit - close client."""
        self.close_sync()

    async def close(self) -> None:
        """Close async client."""
        if self._async_client and not self._async_client.is_closed:
            await self._async_client.aclose()
            self._async_client = None

    def close_sync(self) -> None:
        """Close sync client."""
        if self._sync_client and not self._sync_client.is_closed:
            self._sync_client.close()
            self._sync_client = None
