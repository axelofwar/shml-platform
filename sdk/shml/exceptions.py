"""
SHML Exception Hierarchy
=========================

All SDK exceptions inherit from SHMLError so callers can catch broadly
or narrowly.

Hierarchy::

    SHMLError
    ├── AuthenticationError    (401)
    ├── PermissionDeniedError  (403)
    ├── NotFoundError          (404)
    ├── RateLimitError         (429)
    ├── JobError
    │   ├── JobSubmissionError
    │   ├── JobTimeoutError
    │   └── JobCancelledError
    ├── ConfigError
    │   ├── ProfileNotFoundError
    │   └── ValidationError
    └── IntegrationError
        ├── MLflowError
        ├── NessieError
        ├── FiftyOneError
        └── FeatureStoreError
"""

from __future__ import annotations

from typing import Any


class SHMLError(Exception):
    """Base exception for all SHML SDK errors.

    Attributes:
        status_code: HTTP status code if from an API response.
        details: Additional error context as a dict.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


# ── HTTP errors ──────────────────────────────────────────────────────────────


class AuthenticationError(SHMLError):
    """Authentication failed (401).

    Raised when API key is invalid/expired or OAuth token is rejected.
    """

    def __init__(self, message: str = "Authentication failed", **kwargs: Any):
        super().__init__(message, status_code=401, **kwargs)


class PermissionDeniedError(SHMLError):
    """Insufficient permissions (403).

    User is authenticated but lacks the required role.
    """

    def __init__(self, message: str = "Permission denied", **kwargs: Any):
        super().__init__(message, status_code=403, **kwargs)


class NotFoundError(SHMLError):
    """Resource not found (404)."""

    def __init__(self, message: str = "Resource not found", **kwargs: Any):
        super().__init__(message, status_code=404, **kwargs)


class RateLimitError(SHMLError):
    """Rate limit exceeded (429)."""

    def __init__(
        self, message: str = "Rate limit exceeded", retry_after: int | None = None
    ):
        super().__init__(message, status_code=429, details={"retry_after": retry_after})
        self.retry_after = retry_after


# ── Job errors ───────────────────────────────────────────────────────────────


class JobError(SHMLError):
    """Base class for job-related errors."""

    def __init__(self, message: str, job_id: str | None = None, **kwargs: Any):
        super().__init__(message, **kwargs)
        self.job_id = job_id


class JobSubmissionError(JobError):
    """Job could not be submitted."""

    pass


class JobTimeoutError(JobError):
    """Job exceeded its timeout."""

    pass


class JobCancelledError(JobError):
    """Job was cancelled."""

    pass


# ── Config errors ────────────────────────────────────────────────────────────


class ConfigError(SHMLError):
    """Configuration-related errors."""

    pass


class ProfileNotFoundError(ConfigError):
    """Training profile YAML not found."""

    def __init__(self, profile: str, searched: list[str] | None = None):
        searched_str = "\n".join(f"  - {s}" for s in (searched or []))
        msg = f"Profile '{profile}' not found"
        if searched_str:
            msg += f"\nSearched:\n{searched_str}"
        super().__init__(msg)


class ValidationError(ConfigError):
    """Config or input validation failed."""

    def __init__(self, message: str, field: str | None = None, value: Any = None):
        super().__init__(message)
        self.field = field
        self.value = value


# ── Integration errors ───────────────────────────────────────────────────────


class IntegrationError(SHMLError):
    """Base class for platform integration errors.

    These are non-fatal — training continues even if an integration fails.
    """

    def __init__(self, integration: str, message: str, **kwargs: Any):
        super().__init__(f"[{integration}] {message}", **kwargs)
        self.integration = integration


class MLflowError(IntegrationError):
    def __init__(self, message: str, **kwargs: Any):
        super().__init__("MLflow", message, **kwargs)


class NessieError(IntegrationError):
    def __init__(self, message: str, **kwargs: Any):
        super().__init__("Nessie", message, **kwargs)


class FiftyOneError(IntegrationError):
    def __init__(self, message: str, **kwargs: Any):
        super().__init__("FiftyOne", message, **kwargs)


class FeatureStoreError(IntegrationError):
    def __init__(self, message: str, **kwargs: Any):
        super().__init__("FeatureStore", message, **kwargs)


# ── HTTP response → exception mapping ────────────────────────────────────────


def raise_for_status(status_code: int, body: dict[str, Any] | str) -> None:
    """Map HTTP status codes to SHML exceptions.

    Called by Client._handle_response().
    """
    if 200 <= status_code < 300:
        return

    if isinstance(body, str):
        details = {"raw": body}
        message = body
    else:
        details = body
        message = body.get("message", body.get("detail", str(body)))

    exc_map: dict[int, type[SHMLError]] = {
        401: AuthenticationError,
        403: PermissionDeniedError,
        404: NotFoundError,
        429: RateLimitError,
    }

    exc_class = exc_map.get(status_code)
    if exc_class is not None:
        if exc_class is RateLimitError:
            raise exc_class(message)
        else:
            raise exc_class(message, details=details)
    raise SHMLError(message, status_code=status_code, details=details)
