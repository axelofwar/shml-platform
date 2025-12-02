"""
SFML Platform SDK - Unified SDK for ML Platform Services.

This SDK provides role-based access to platform services including:
- FusionAuth (Identity & Access Management)
- MLflow (Experiment Tracking & Model Registry) [Coming Soon]
- Ray (Distributed Computing) [Coming Soon]
- Grafana (Monitoring & Observability) [Coming Soon]

Usage:
    from platform_sdk import PlatformSDK

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
