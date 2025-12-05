"""Authentication middleware for Chat API."""

import logging
from typing import Optional, Tuple

from fastapi import Request, HTTPException, Header, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .schemas import User, UserRole
from .database import db

logger = logging.getLogger(__name__)

# HTTP Bearer scheme for API keys
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_auth_request_user: Optional[str] = Header(
        default=None, alias="X-Auth-Request-User"
    ),
    x_auth_request_email: Optional[str] = Header(
        default=None, alias="X-Auth-Request-Email"
    ),
    x_auth_request_groups: Optional[str] = Header(
        default=None, alias="X-Auth-Request-Groups"
    ),
    x_forwarded_user: Optional[str] = Header(default=None, alias="X-Forwarded-User"),
) -> User:
    """
    Authenticate user from either:
    1. OAuth2 headers (set by oauth2-proxy/Traefik after authentication)
    2. API key in Authorization header

    Returns User object with role information.
    """
    # Try API key authentication first
    if authorization and authorization.credentials:
        api_key = authorization.credentials

        # Validate API key
        user = await db.validate_api_key(api_key)
        if user:
            logger.debug(f"Authenticated via API key: user={user.id}, role={user.role}")
            return user
        else:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Try OAuth2 headers (set by oauth2-proxy)
    user_id = x_auth_request_user or x_forwarded_user

    if user_id:
        # Parse groups to determine role
        groups = []
        if x_auth_request_groups:
            # Groups come as comma-separated list
            groups = [g.strip().lower() for g in x_auth_request_groups.split(",")]

        # Determine role from groups
        role = UserRole.VIEWER  # Default
        if "admin" in groups or "administrators" in groups:
            role = UserRole.ADMIN
        elif "developer" in groups or "developers" in groups:
            role = UserRole.DEVELOPER

        user = User(
            id=user_id,
            email=x_auth_request_email,
            role=role,
            groups=groups,
            auth_method="oauth",
        )
        logger.debug(
            f"Authenticated via OAuth: user={user.id}, role={role}, groups={groups}"
        )
        return user

    # No authentication found
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide API key or authenticate via OAuth.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_role(*allowed_roles: UserRole):
    """
    Dependency that requires user to have one of the allowed roles.

    Usage:
        @app.get("/admin-only")
        async def admin_endpoint(user: User = Depends(require_role(UserRole.ADMIN))):
            ...
    """

    async def check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {', '.join(r.value for r in allowed_roles)}",
            )
        return user

    return check_role


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require admin role."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
    return user


def require_developer_or_admin(user: User = Depends(get_current_user)) -> User:
    """Require developer or admin role."""
    if user.role not in (UserRole.DEVELOPER, UserRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Developer or admin access required",
        )
    return user
