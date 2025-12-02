"""
Platform SDK Data Models.

Pydantic models for request/response data with validation.
Follows industry standard patterns (similar to AWS SDK, Stripe SDK).
"""

from enum import Enum
from typing import Optional, Dict, Any, List, Generic, TypeVar
from datetime import datetime
from pydantic import BaseModel, Field


# Generic type for response data
T = TypeVar("T")


class Role(str, Enum):
    """
    Platform roles with hierarchical permissions.

    Permission hierarchy: ADMIN > DEVELOPER > VIEWER
    """

    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"
    SERVICE_ACCOUNT = "service_account"

    @property
    def level(self) -> int:
        """Get numeric level for permission comparison."""
        levels = {
            Role.ADMIN: 100,
            Role.DEVELOPER: 50,
            Role.VIEWER: 10,
            Role.SERVICE_ACCOUNT: 50,  # Same as developer
        }
        return levels.get(self, 0)

    def has_permission(self, required: "Role") -> bool:
        """Check if this role has at least the required permission level."""
        return self.level >= required.level

    @classmethod
    def from_string(cls, value: str) -> "Role":
        """Parse role from string, defaulting to VIEWER."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.VIEWER


class Permission(str, Enum):
    """
    Granular permissions for operations.

    Each operation requires one or more permissions.
    """

    # User operations
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"

    # Group operations
    GROUPS_READ = "groups:read"
    GROUPS_CREATE = "groups:create"
    GROUPS_UPDATE = "groups:update"
    GROUPS_DELETE = "groups:delete"
    GROUPS_MANAGE_MEMBERS = "groups:manage_members"

    # Application operations
    APPLICATIONS_READ = "applications:read"
    APPLICATIONS_CREATE = "applications:create"
    APPLICATIONS_UPDATE = "applications:update"
    APPLICATIONS_DELETE = "applications:delete"

    # Role operations
    ROLES_READ = "roles:read"
    ROLES_CREATE = "roles:create"
    ROLES_UPDATE = "roles:update"
    ROLES_DELETE = "roles:delete"

    # Registration operations
    REGISTRATIONS_READ = "registrations:read"
    REGISTRATIONS_CREATE = "registrations:create"
    REGISTRATIONS_UPDATE = "registrations:update"
    REGISTRATIONS_DELETE = "registrations:delete"

    # API Key operations
    API_KEYS_READ = "api_keys:read"
    API_KEYS_CREATE = "api_keys:create"
    API_KEYS_UPDATE = "api_keys:update"
    API_KEYS_DELETE = "api_keys:delete"


# Role to permissions mapping
ROLE_PERMISSIONS: Dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),  # Admin has all permissions
    Role.DEVELOPER: {
        # Users - read + limited self-management
        Permission.USERS_READ,
        # Groups - read only
        Permission.GROUPS_READ,
        # Applications - read only
        Permission.APPLICATIONS_READ,
        # Roles - read only
        Permission.ROLES_READ,
        # Registrations - read + manage own
        Permission.REGISTRATIONS_READ,
        Permission.REGISTRATIONS_CREATE,  # Can register to apps
        Permission.REGISTRATIONS_UPDATE,  # Can update own registrations
    },
    Role.VIEWER: {
        # Read-only access
        Permission.USERS_READ,
        Permission.GROUPS_READ,
        Permission.APPLICATIONS_READ,
        Permission.ROLES_READ,
        Permission.REGISTRATIONS_READ,
    },
}


def get_permissions_for_role(role: Role) -> set[Permission]:
    """Get all permissions for a given role."""
    return ROLE_PERMISSIONS.get(role, set())


def role_has_permission(role: Role, permission: Permission) -> bool:
    """Check if a role has a specific permission."""
    return permission in get_permissions_for_role(role)


class APIResponse(BaseModel, Generic[T]):
    """
    Standard API response wrapper.

    Provides consistent response structure across all SDK operations.
    Similar to AWS SDK response patterns.

    Attributes:
        success: Whether the operation succeeded
        data: Response data (type varies by operation)
        error: Error message if failed
        status_code: HTTP status code
        request_id: Unique request identifier for debugging
        metadata: Additional response metadata
    """

    success: bool = Field(description="Whether the operation succeeded")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Response data")
    error: Optional[str] = Field(
        default=None, description="Error message if operation failed"
    )
    status_code: int = Field(default=200, description="HTTP status code")
    request_id: Optional[str] = Field(
        default=None, description="Unique request identifier"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @classmethod
    def ok(
        cls,
        data: Optional[Dict[str, Any]] = None,
        status_code: int = 200,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "APIResponse":
        """Create a success response."""
        return cls(
            success=True,
            data=data,
            status_code=status_code,
            request_id=request_id,
            metadata=metadata or {},
        )

    @classmethod
    def fail(
        cls,
        error: str,
        status_code: int = 400,
        data: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "APIResponse":
        """Create a failure response."""
        return cls(
            success=False,
            error=error,
            data=data,
            status_code=status_code,
            request_id=request_id,
            metadata=metadata or {},
        )

    def raise_for_status(self) -> None:
        """Raise exception if response indicates failure."""
        from .exceptions import (
            PlatformSDKError,
            AuthenticationError,
            PermissionDeniedError,
            RateLimitError,
            ValidationError,
        )

        if self.success:
            return

        error_msg = self.error or "Unknown error"

        if self.status_code == 401:
            raise AuthenticationError(error_msg, self.status_code)
        elif self.status_code == 403:
            raise PermissionDeniedError(error_msg, status_code=self.status_code)
        elif self.status_code == 429:
            raise RateLimitError(error_msg, status_code=self.status_code)
        elif self.status_code == 400:
            raise ValidationError(error_msg, status_code=self.status_code)
        else:
            raise PlatformSDKError(error_msg, self.status_code)


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Paginated response for list operations.

    Supports cursor-based and offset-based pagination.
    """

    items: List[Dict[str, Any]] = Field(
        default_factory=list, description="List of items"
    )
    total: int = Field(default=0, description="Total number of items")
    page: int = Field(default=1, description="Current page number")
    page_size: int = Field(default=25, description="Items per page")
    has_more: bool = Field(
        default=False, description="Whether more items are available"
    )
    next_cursor: Optional[str] = Field(default=None, description="Cursor for next page")


# ============================================================================
# FusionAuth Models
# ============================================================================


class UserModel(BaseModel):
    """FusionAuth User representation."""

    id: str = Field(description="User UUID")
    email: str = Field(description="User email address")
    username: Optional[str] = Field(default=None, description="Username")
    first_name: Optional[str] = Field(default=None, alias="firstName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    full_name: Optional[str] = Field(default=None, alias="fullName")
    mobile_phone: Optional[str] = Field(default=None, alias="mobilePhone")
    active: bool = Field(default=True, description="Account active status")
    verified: bool = Field(default=False, description="Email verified")
    tenant_id: Optional[str] = Field(default=None, alias="tenantId")
    insert_instant: Optional[int] = Field(default=None, alias="insertInstant")
    last_login_instant: Optional[int] = Field(default=None, alias="lastLoginInstant")
    memberships: List[Dict[str, Any]] = Field(
        default_factory=list, description="Group memberships"
    )
    registrations: List[Dict[str, Any]] = Field(
        default_factory=list, description="Application registrations"
    )

    model_config = {"populate_by_name": True, "extra": "allow"}


class GroupModel(BaseModel):
    """FusionAuth Group representation."""

    id: str = Field(description="Group UUID")
    name: str = Field(description="Group name")
    tenant_id: Optional[str] = Field(default=None, alias="tenantId")
    insert_instant: Optional[int] = Field(default=None, alias="insertInstant")
    data: Dict[str, Any] = Field(default_factory=dict)
    roles: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=dict, description="Application roles assigned to group"
    )

    model_config = {"populate_by_name": True, "extra": "allow"}


class ApplicationModel(BaseModel):
    """FusionAuth Application representation."""

    id: str = Field(description="Application UUID")
    name: str = Field(description="Application name")
    tenant_id: Optional[str] = Field(default=None, alias="tenantId")
    active: bool = Field(default=True)
    roles: List[Dict[str, Any]] = Field(
        default_factory=list, description="Application roles"
    )

    model_config = {"populate_by_name": True, "extra": "allow"}


class RegistrationModel(BaseModel):
    """FusionAuth Registration representation."""

    id: Optional[str] = Field(default=None, description="Registration UUID")
    application_id: str = Field(alias="applicationId")
    user_id: Optional[str] = Field(default=None, alias="userId")
    roles: List[str] = Field(default_factory=list)
    username: Optional[str] = Field(default=None)
    insert_instant: Optional[int] = Field(default=None, alias="insertInstant")

    model_config = {"populate_by_name": True, "extra": "allow"}


class APIKeyModel(BaseModel):
    """FusionAuth API Key representation."""

    id: str = Field(description="API Key UUID")
    key: Optional[str] = Field(
        default=None, description="The actual key (only on create)"
    )
    tenant_id: Optional[str] = Field(default=None, alias="tenantId")
    meta_data: Dict[str, Any] = Field(default_factory=dict, alias="metaData")
    permissions_object: Dict[str, Any] = Field(
        default_factory=dict, alias="permissionsObject", description="Key permissions"
    )
    insert_instant: Optional[int] = Field(default=None, alias="insertInstant")

    model_config = {"populate_by_name": True, "extra": "allow"}
