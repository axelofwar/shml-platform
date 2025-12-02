"""
Permission system for Platform SDK.

Provides:
- Permission decorator for method-level access control
- Permission introspection from API keys
- Role-based permission resolution
"""

import asyncio
import functools
import logging
from typing import Callable, Optional, List, Set, Any, TypeVar, Union

from .models import Role, Permission, ROLE_PERMISSIONS, get_permissions_for_role
from .exceptions import PermissionDeniedError, AuthenticationError

logger = logging.getLogger("platform_sdk.permissions")

F = TypeVar("F", bound=Callable[..., Any])


class PermissionContext:
    """
    Holds permission information for a user/API key.

    Populated by introspecting the API key against FusionAuth.
    """

    def __init__(
        self,
        role: Role = Role.VIEWER,
        permissions: Optional[Set[Permission]] = None,
        user_id: Optional[str] = None,
        groups: Optional[List[str]] = None,
    ):
        """
        Initialize permission context.

        Args:
            role: User's role (admin, developer, viewer)
            permissions: Set of granted permissions (overrides role-based if provided)
            user_id: Associated user ID
            groups: Group memberships
        """
        self.role = role
        self._explicit_permissions = permissions
        self.user_id = user_id
        self.groups = groups or []

    @property
    def permissions(self) -> Set[Permission]:
        """Get all permissions for this context."""
        if self._explicit_permissions is not None:
            return self._explicit_permissions
        return get_permissions_for_role(self.role)

    def has_permission(self, permission: Permission) -> bool:
        """Check if context has a specific permission."""
        return permission in self.permissions

    def has_any_permission(self, permissions: List[Permission]) -> bool:
        """Check if context has any of the given permissions."""
        return any(p in self.permissions for p in permissions)

    def has_all_permissions(self, permissions: List[Permission]) -> bool:
        """Check if context has all of the given permissions."""
        return all(p in self.permissions for p in permissions)

    def check_permission(self, permission: Permission, operation: str = "") -> None:
        """
        Check permission and raise if denied.

        Args:
            permission: Required permission
            operation: Operation name for error message

        Raises:
            PermissionDeniedError if permission not granted
        """
        if not self.has_permission(permission):
            raise PermissionDeniedError(
                operation=operation,
                required_roles=[
                    r.value for r in Role if permission in get_permissions_for_role(r)
                ],
                user_role=self.role.value,
            )

    def __repr__(self) -> str:
        return f"PermissionContext(role={self.role.value}, permissions={len(self.permissions)})"


def requires_permission(*permissions: Permission):
    """
    Decorator to enforce permission requirements on methods.

    Usage:
        @requires_permission(Permission.USERS_READ)
        def list_users(self):
            ...

        @requires_permission(Permission.USERS_CREATE, Permission.USERS_UPDATE)
        def create_or_update_user(self):
            ...  # Requires both permissions

    Args:
        *permissions: One or more required permissions

    Returns:
        Decorated function that checks permissions before execution
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            # Get permission context from service
            ctx = getattr(self, "_permission_context", None)
            if ctx is None:
                raise RuntimeError(
                    f"Permission context not set on {self.__class__.__name__}. "
                    "Ensure the service is initialized with a permission context."
                )

            # Check all required permissions
            for permission in permissions:
                ctx.check_permission(permission, operation=func.__name__)

            return func(self, *args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(self, *args, **kwargs):
            # Get permission context from service
            ctx = getattr(self, "_permission_context", None)
            if ctx is None:
                raise RuntimeError(
                    f"Permission context not set on {self.__class__.__name__}. "
                    "Ensure the service is initialized with a permission context."
                )

            # Check all required permissions
            for permission in permissions:
                ctx.check_permission(permission, operation=func.__name__)

            return await func(self, *args, **kwargs)

        # Store required permissions on the wrapper for introspection
        wrapper = async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        wrapper._required_permissions = permissions
        wrapper._is_permission_protected = True

        return wrapper

    return decorator


def requires_any_permission(*permissions: Permission):
    """
    Decorator requiring at least one of the given permissions.

    Usage:
        @requires_any_permission(Permission.USERS_UPDATE, Permission.USERS_DELETE)
        def modify_user(self):
            ...  # Requires EITHER update OR delete permission
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            ctx = getattr(self, "_permission_context", None)
            if ctx is None:
                raise RuntimeError(
                    f"Permission context not set on {self.__class__.__name__}."
                )

            if not ctx.has_any_permission(list(permissions)):
                raise PermissionDeniedError(
                    operation=func.__name__,
                    required_roles=[
                        r.value
                        for r in Role
                        if any(p in get_permissions_for_role(r) for p in permissions)
                    ],
                    user_role=ctx.role.value,
                )

            return func(self, *args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(self, *args, **kwargs):
            ctx = getattr(self, "_permission_context", None)
            if ctx is None:
                raise RuntimeError(
                    f"Permission context not set on {self.__class__.__name__}."
                )

            if not ctx.has_any_permission(list(permissions)):
                raise PermissionDeniedError(
                    operation=func.__name__,
                    required_roles=[
                        r.value
                        for r in Role
                        if any(p in get_permissions_for_role(r) for p in permissions)
                    ],
                    user_role=ctx.role.value,
                )

            return await func(self, *args, **kwargs)

        wrapper = async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        wrapper._required_permissions = permissions
        wrapper._requires_any = True
        wrapper._is_permission_protected = True

        return wrapper

    return decorator


def requires_role(minimum_role: Role):
    """
    Decorator requiring a minimum role level.

    Usage:
        @requires_role(Role.DEVELOPER)
        def submit_job(self):
            ...  # Requires developer or higher (admin)
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            ctx = getattr(self, "_permission_context", None)
            if ctx is None:
                raise RuntimeError(
                    f"Permission context not set on {self.__class__.__name__}."
                )

            if not ctx.role.has_permission(minimum_role):
                raise PermissionDeniedError(
                    operation=func.__name__,
                    required_roles=[minimum_role.value],
                    user_role=ctx.role.value,
                )

            return func(self, *args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(self, *args, **kwargs):
            ctx = getattr(self, "_permission_context", None)
            if ctx is None:
                raise RuntimeError(
                    f"Permission context not set on {self.__class__.__name__}."
                )

            if not ctx.role.has_permission(minimum_role):
                raise PermissionDeniedError(
                    operation=func.__name__,
                    required_roles=[minimum_role.value],
                    user_role=ctx.role.value,
                )

            return await func(self, *args, **kwargs)

        wrapper = async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        wrapper._minimum_role = minimum_role
        wrapper._is_permission_protected = True

        return wrapper

    return decorator


# Need asyncio import for iscoroutinefunction
import asyncio


class PermissionIntrospector:
    """
    Introspects API key permissions from FusionAuth.

    Determines user role and permissions based on:
    1. API key permissions (if key has specific permissions)
    2. Associated user's roles and group memberships
    """

    def __init__(self, http_client):
        """
        Initialize introspector.

        Args:
            http_client: HTTPClient instance for API calls
        """
        self._http = http_client

    async def introspect(self) -> PermissionContext:
        """
        Introspect the current API key to determine permissions.

        Returns:
            PermissionContext with determined role and permissions
        """
        # Try to get API key info
        response = await self._http.get("/api/api-key")

        if not response.success:
            if response.status_code == 401:
                raise AuthenticationError("Invalid or missing API key")
            # If we can't introspect, assume viewer role
            logger.warning("Could not introspect API key, defaulting to viewer role")
            return PermissionContext(role=Role.VIEWER)

        # Parse API key permissions
        api_keys = response.data.get("apiKeys", [])

        if not api_keys:
            return PermissionContext(role=Role.VIEWER)

        # Find our key (first one should be the authenticated key)
        key_info = api_keys[0]
        permissions_obj = key_info.get("permissionsObject", {})
        meta_data = key_info.get("metaData", {}).get("attributes", {})

        # Check if role is explicitly set in metadata
        if "role" in meta_data:
            role = Role.from_string(meta_data["role"])
            return PermissionContext(role=role)

        # Determine role from permissions object
        role = self._determine_role_from_permissions(permissions_obj)

        return PermissionContext(role=role)

    def introspect_sync(self) -> PermissionContext:
        """Synchronous version of introspect."""
        response = self._http.get_sync("/api/api-key")

        if not response.success:
            if response.status_code == 401:
                raise AuthenticationError("Invalid or missing API key")
            logger.warning("Could not introspect API key, defaulting to viewer role")
            return PermissionContext(role=Role.VIEWER)

        api_keys = response.data.get("apiKeys", [])

        if not api_keys:
            return PermissionContext(role=Role.VIEWER)

        key_info = api_keys[0]
        permissions_obj = key_info.get("permissionsObject", {})
        meta_data = key_info.get("metaData", {}).get("attributes", {})

        if "role" in meta_data:
            role = Role.from_string(meta_data["role"])
            return PermissionContext(role=role)

        role = self._determine_role_from_permissions(permissions_obj)

        return PermissionContext(role=role)

    def _determine_role_from_permissions(self, permissions: dict) -> Role:
        """
        Determine role from FusionAuth API key permissions.

        FusionAuth permissions structure:
        {
            "endpoints": {
                "/api/user": ["GET", "POST", "PUT", "DELETE"],
                "/api/group": ["GET"],
                ...
            }
        }
        """
        endpoints = permissions.get("endpoints", {})

        # If no endpoint restrictions, it's a super key (admin)
        if not endpoints:
            # Check if there are any permissions defined
            if not permissions:
                # Full access = admin
                return Role.ADMIN
            # Some permissions but no endpoints = check deeper

        # Check for admin-level access (full CRUD on users)
        user_perms = set(endpoints.get("/api/user", []))
        if {"GET", "POST", "PUT", "DELETE"}.issubset(user_perms):
            return Role.ADMIN

        # Check for developer-level access (read users, some write)
        if "GET" in user_perms and ("POST" in user_perms or "PUT" in user_perms):
            return Role.DEVELOPER

        # Default to viewer
        return Role.VIEWER
