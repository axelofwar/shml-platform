"""
SHML Admin SDK - FusionAuth Administration for the SHML Platform.

This module provides role-based access to platform administration services:
- User management (create, update, delete, verify)
- Group management (membership, permissions)
- Application management (OAuth apps)
- API key management (create, rotate, revoke)
- Role management (assign, remove)

Usage:
    from shml.admin import PlatformSDK

    # Initialize with API key - permissions auto-detected
    sdk = PlatformSDK(api_key="your-api-key")

    # Access services based on your role
    users = sdk.users.list()  # Raises PermissionDeniedError if not authorized

Role-based access:
    - Admin: Full access to all operations
    - Developer: Read access + job submission + own resource management
    - Viewer: Read-only access to permitted resources
"""

from .client import PlatformSDK
from .config import SDKConfig
from .exceptions import (
    PlatformSDKError,
    PermissionDeniedError,
    AuthenticationError,
    RateLimitError,
    ValidationError,
    ServiceUnavailableError,
)
from .models import APIResponse, Permission, Role

__version__ = "1.0.0"
__all__ = [
    "PlatformSDK",
    "SDKConfig",
    "APIResponse",
    "Permission",
    "Role",
    "PlatformSDKError",
    "PermissionDeniedError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
    "ServiceUnavailableError",
]
