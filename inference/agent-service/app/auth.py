"""
Authentication and Authorization Middleware

Integrates with OAuth2-Proxy + FusionAuth for role-based access control.
OAuth2-Proxy forwards user info via headers after FusionAuth authentication.
"""

from fastapi import Header, HTTPException, Request
from typing import Optional, List
from enum import Enum
import logging
import os

logger = logging.getLogger(__name__)

# Development mode - allows unauthenticated access with demo user
DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"


class UserRole(str, Enum):
    """User roles matching FusionAuth configuration."""

    VIEWER = "viewer"
    DEVELOPER = "developer"
    ELEVATED_DEVELOPER = "elevated-developer"
    ADMIN = "admin"


class AuthUser:
    """Authenticated user from OAuth2-Proxy headers."""

    def __init__(
        self,
        email: str,
        user_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        preferred_username: Optional[str] = None,
    ):
        self.email = email
        self.user_id = user_id or email  # Fallback to email
        self.roles = roles or [UserRole.DEVELOPER.value]  # Default role
        self.preferred_username = preferred_username or email.split("@")[0]

    @property
    def primary_role(self) -> UserRole:
        """Get highest privilege role."""
        role_hierarchy = [
            UserRole.ADMIN,
            UserRole.ELEVATED_DEVELOPER,
            UserRole.DEVELOPER,
            UserRole.VIEWER,
        ]
        for role in role_hierarchy:
            if role.value in self.roles:
                return role
        return UserRole.DEVELOPER  # Fallback

    def has_role(self, role: UserRole) -> bool:
        """Check if user has specific role."""
        return role.value in self.roles

    def has_any_role(self, roles: List[UserRole]) -> bool:
        """Check if user has any of the specified roles."""
        return any(role.value in self.roles for role in roles)


async def get_current_user(
    x_auth_request_email: Optional[str] = Header(None, alias="X-Auth-Request-Email"),
    x_auth_request_user: Optional[str] = Header(None, alias="X-Auth-Request-User"),
    x_auth_request_groups: Optional[str] = Header(None, alias="X-Auth-Request-Groups"),
    x_auth_request_preferred_username: Optional[str] = Header(
        None, alias="X-Auth-Request-Preferred-Username"
    ),
) -> AuthUser:
    """
    Extract authenticated user from OAuth2-Proxy headers.

    Headers forwarded by OAuth2-Proxy after FusionAuth authentication:
    - X-Auth-Request-Email: user@example.com
    - X-Auth-Request-User: user-id-from-fusionauth
    - X-Auth-Request-Groups: viewer,developer (roles from JWT)
    - X-Auth-Request-Preferred-Username: username

    Returns:
        AuthUser: Authenticated user with roles

    Raises:
        HTTPException: 401 if not authenticated
    """
    # Check for authentication
    if not x_auth_request_email:
        # Development mode - allow access with demo developer user
        if DEV_MODE:
            logger.debug("DEV_MODE: Allowing unauthenticated access")
            return AuthUser(
                email="dev@localhost",
                user_id="dev-user",
                roles=[UserRole.DEVELOPER.value],
                preferred_username="developer",
            )

        # Production - require authentication
        logger.warning("Unauthenticated request blocked")
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please sign in through OAuth2-Proxy.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Parse roles from groups header (comma-separated)
    roles = []
    if x_auth_request_groups:
        roles = [r.strip() for r in x_auth_request_groups.split(",") if r.strip()]

    user = AuthUser(
        email=x_auth_request_email,
        user_id=x_auth_request_user,
        roles=roles,
        preferred_username=x_auth_request_preferred_username,
    )

    logger.debug(f"Authenticated user: {user.email} with roles: {user.roles}")
    return user


def require_role(*required_roles: UserRole):
    """
    Dependency to require specific roles.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role(UserRole.ADMIN))])
        async def admin_endpoint():
            pass
    """

    async def check_role(user: AuthUser = Depends(get_current_user)):
        if not user.has_any_role(list(required_roles)):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required roles: {[r.value for r in required_roles]}",
            )
        return user

    return check_role


def require_min_role(min_role: UserRole):
    """
    Dependency to require minimum role level.

    Role hierarchy: admin > elevated-developer > developer > viewer

    Usage:
        @router.post("/execute", dependencies=[Depends(require_min_role(UserRole.ELEVATED_DEVELOPER))])
        async def execute_code():
            pass
    """
    role_levels = {
        UserRole.VIEWER: 1,
        UserRole.DEVELOPER: 2,
        UserRole.ELEVATED_DEVELOPER: 3,
        UserRole.ADMIN: 4,
    }
    min_level = role_levels[min_role]

    async def check_min_role(user: AuthUser = Depends(get_current_user)):
        user_level = role_levels.get(user.primary_role, 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required role: {min_role.value} or higher. Your role: {user.primary_role.value}",
            )
        return user

    return check_min_role


# For FastAPI dependency injection
from fastapi import Depends
