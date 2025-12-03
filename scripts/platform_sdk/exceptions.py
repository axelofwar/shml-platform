"""
Platform SDK Exceptions.

Provides a hierarchy of exceptions for consistent error handling:
- PlatformSDKError: Base exception
- AuthenticationError: Invalid or missing API key
- PermissionDeniedError: Operation not permitted for user's role
- RateLimitError: Too many requests
- ValidationError: Invalid input data
- ServiceUnavailableError: Backend service unavailable
"""

from typing import Optional, Dict, Any, List


class PlatformSDKError(Exception):
    """Base exception for all Platform SDK errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.insert(0, f"[{self.status_code}]")
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "status_code": self.status_code,
            "details": self.details,
        }


class AuthenticationError(PlatformSDKError):
    """
    Raised when authentication fails.

    Causes:
    - Invalid API key
    - Expired API key
    - Missing API key
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        status_code: int = 401,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, status_code, details)


class PermissionDeniedError(PlatformSDKError):
    """
    Raised when user lacks permission for an operation.

    This exception is raised client-side before making API calls
    when the user's role doesn't include the required permission.

    Attributes:
        operation: The operation that was attempted
        required_roles: Roles that would permit this operation
        user_role: The user's current role
    """

    def __init__(
        self,
        message: str = "Permission denied",
        operation: Optional[str] = None,
        required_roles: Optional[List[str]] = None,
        user_role: Optional[str] = None,
        status_code: int = 403,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.operation = operation
        self.required_roles = required_roles or []
        self.user_role = user_role

        # Build detailed message
        if operation and required_roles and user_role:
            message = (
                f"Permission denied for '{operation}'. "
                f"Required roles: {required_roles}. "
                f"Your role: {user_role}"
            )

        super().__init__(message, status_code, details)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "operation": self.operation,
                "required_roles": self.required_roles,
                "user_role": self.user_role,
            }
        )
        return result


class RateLimitError(PlatformSDKError):
    """
    Raised when rate limit is exceeded.

    Attributes:
        retry_after: Seconds to wait before retrying
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        status_code: int = 429,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.retry_after = retry_after
        if retry_after:
            message = f"{message}. Retry after {retry_after} seconds"
        super().__init__(message, status_code, details)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["retry_after"] = self.retry_after
        return result


class ValidationError(PlatformSDKError):
    """
    Raised when input validation fails.

    Attributes:
        field_errors: Dictionary of field-specific errors
    """

    def __init__(
        self,
        message: str = "Validation failed",
        field_errors: Optional[Dict[str, List[str]]] = None,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.field_errors = field_errors or {}
        if field_errors:
            error_parts = [f"{k}: {', '.join(v)}" for k, v in field_errors.items()]
            message = f"{message}: {'; '.join(error_parts)}"
        super().__init__(message, status_code, details)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["field_errors"] = self.field_errors
        return result


class ServiceUnavailableError(PlatformSDKError):
    """
    Raised when a backend service is unavailable.

    Attributes:
        service: Name of the unavailable service
    """

    def __init__(
        self,
        message: str = "Service unavailable",
        service: Optional[str] = None,
        status_code: int = 503,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.service = service
        if service:
            message = f"{service} service unavailable"
        super().__init__(message, status_code, details)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["service"] = self.service
        return result


class ConnectionError(PlatformSDKError):
    """Raised when connection to service fails."""

    def __init__(
        self,
        message: str = "Connection failed",
        service: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.service = service
        if service:
            message = f"Failed to connect to {service}"
        super().__init__(message, status_code, details)


class TimeoutError(PlatformSDKError):
    """Raised when request times out."""

    def __init__(
        self,
        message: str = "Request timed out",
        timeout: Optional[float] = None,
        status_code: int = 504,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.timeout = timeout
        if timeout:
            message = f"Request timed out after {timeout}s"
        super().__init__(message, status_code, details)
