"""
Base service class for Platform SDK services.

Provides common functionality for all services:
- HTTP client access
- Permission context
- Logging
- Response handling
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..http import HTTPClient
    from ..permissions import PermissionContext


class BaseService:
    """
    Base class for all SDK services.

    Provides:
    - HTTP client for API calls
    - Permission context for authorization
    - Logging
    """

    def __init__(
        self,
        http_client: "HTTPClient",
        permission_context: "PermissionContext",
    ):
        """
        Initialize service.

        Args:
            http_client: HTTPClient instance
            permission_context: User's permission context
        """
        self._http = http_client
        self._permission_context = permission_context
        self._logger = logging.getLogger(f"platform_sdk.{self.__class__.__name__}")

    @property
    def role(self):
        """Get current user's role."""
        return self._permission_context.role

    @property
    def permissions(self):
        """Get current user's permissions."""
        return self._permission_context.permissions

    def has_permission(self, permission) -> bool:
        """Check if current user has a permission."""
        return self._permission_context.has_permission(permission)
