"""
OAuth2 authentication with FusionAuth
Session management and token validation
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from functools import wraps

import httpx
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2AuthorizationCodeBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .models import User
from .database import get_db


# Environment configuration - Support both FusionAuth and legacy Authentik env vars
FUSIONAUTH_URL = os.getenv(
    "FUSIONAUTH_URL", os.getenv("AUTHENTIK_URL", "http://fusionauth:9011")
)
FUSIONAUTH_CLIENT_ID = os.getenv(
    "FUSIONAUTH_CLIENT_ID",
    os.getenv("FUSIONAUTH_RAY_CLIENT_ID", os.getenv("AUTHENTIK_CLIENT_ID")),
)
FUSIONAUTH_CLIENT_SECRET = os.getenv(
    "FUSIONAUTH_CLIENT_SECRET",
    os.getenv("FUSIONAUTH_RAY_CLIENT_SECRET", os.getenv("AUTHENTIK_CLIENT_SECRET")),
)
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# API Keys for service accounts (CI/CD, testing, developer access)
# These bypass OAuth and provide direct API access with specific roles
# Keys are defined in root .env as FUSIONAUTH_CICD_* and referenced via CICD_* in ray_compute/.env
CICD_ADMIN_KEY = os.getenv("CICD_ADMIN_KEY") or os.getenv("FUSIONAUTH_CICD_SUPER_KEY")
CICD_DEVELOPER_KEY = os.getenv("CICD_DEVELOPER_KEY") or os.getenv(
    "FUSIONAUTH_CICD_DEVELOPER_KEY"
)
CICD_ELEVATED_DEVELOPER_KEY = os.getenv("CICD_ELEVATED_DEVELOPER_KEY") or os.getenv(
    "FUSIONAUTH_CICD_ELEVATED_DEVELOPER_KEY"
)
CICD_VIEWER_KEY = os.getenv("CICD_VIEWER_KEY") or os.getenv(
    "FUSIONAUTH_CICD_VIEWER_KEY"
)

# Public URL for authentication (what users see)
PUBLIC_AUTH_URL = os.getenv(
    "PUBLIC_AUTH_URL", "https://shml-platform.tail38b60a.ts.net/auth"
)
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "platform administrator")

# Role hierarchy: admin > premium > user > viewer
# Viewers can only read, not submit jobs
ROLE_HIERARCHY = {
    "admin": 4,
    "premium": 3,
    "user": 2,
    "viewer": 1,
}


def can_submit_jobs(role: str) -> bool:
    """
    Check if a role has permission to submit jobs.
    Viewers are read-only and cannot submit jobs.
    """
    return role in ["admin", "premium", "user"]


def has_role_permission(user_role: str, required_role: str) -> bool:
    """
    Check if user_role has at least the permissions of required_role.
    Uses role hierarchy for comparison.
    """
    return ROLE_HIERARCHY.get(user_role, 0) >= ROLE_HIERARCHY.get(required_role, 0)


# OAuth2 configuration for FusionAuth
# auto_error=False allows proxy auth to work when no Bearer token is present
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{FUSIONAUTH_URL}/oauth2/authorize",
    tokenUrl=f"{FUSIONAUTH_URL}/oauth2/token",
    auto_error=False,  # Don't auto-raise 401 - we handle auth in get_current_user
)


class AuthError(Exception):
    """Custom authentication error"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


async def verify_fusionauth_token(token: str) -> Dict[str, Any]:
    """
    Verify OAuth token with FusionAuth introspection endpoint
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{FUSIONAUTH_URL}/oauth2/introspect",
                data={
                    "token": token,
                    "client_id": FUSIONAUTH_CLIENT_ID,
                    "client_secret": FUSIONAUTH_CLIENT_SECRET,
                },
                timeout=10.0,
            )

            if response.status_code != 200:
                raise AuthError(
                    status.HTTP_401_UNAUTHORIZED, "Could not validate credentials"
                )

            token_data = response.json()

            if not token_data.get("active"):
                raise AuthError(status.HTTP_401_UNAUTHORIZED, "Token is not active")

            return token_data

        except httpx.RequestError as e:
            raise AuthError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Could not connect to authentication service: {str(e)}",
            )


async def get_userinfo_from_fusionauth(token: str) -> Dict[str, Any]:
    """
    Get user info from FusionAuth userinfo endpoint
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{FUSIONAUTH_URL}/oauth2/userinfo",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )

            if response.status_code != 200:
                return {}

            return response.json()

        except httpx.RequestError:
            return {}


async def get_user_from_fusionauth(token: str, db: Session) -> User:
    """
    Get or create user from FusionAuth OAuth token
    """
    # Verify token with FusionAuth
    token_data = await verify_fusionauth_token(token)

    oauth_sub = token_data.get("sub")
    email = token_data.get("email")
    username = token_data.get("preferred_username") or email

    # If email not in introspection, fetch from userinfo endpoint
    if not email:
        userinfo = await get_userinfo_from_fusionauth(token)
        email = userinfo.get("email")
        username = userinfo.get("preferred_username") or userinfo.get("name") or email

    # Fall back to using sub as username/email if still not available
    if not email:
        email = f"{oauth_sub}@ray-compute.local"
    if not username:
        username = oauth_sub

    if not oauth_sub:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "Token missing required claims")

    # Get or create user
    user = db.query(User).filter(User.oauth_sub == oauth_sub).first()

    if not user:
        # Create new user from OAuth data
        # Determine role from FusionAuth roles (not groups)
        roles = token_data.get("roles", [])
        role = "viewer"  # default - read-only access
        if "admin" in roles:
            role = "admin"
        elif "developer" in roles:
            role = "user"  # Map FusionAuth 'developer' to Ray 'user'
        elif "viewer" in roles:
            role = "viewer"

        from .models import UserQuota

        user = User(
            username=username,
            email=email,
            oauth_sub=oauth_sub,
            role=role,
            is_active=True,
        )
        db.add(user)
        db.flush()  # Get user_id before creating quota

        # Create default quota for new user
        quota = UserQuota(
            user_id=user.user_id,
            max_concurrent_jobs=(
                5 if role == "user" else (10 if role == "premium" else 20)
            ),
            max_gpu_hours_per_day=(
                10.0 if role == "user" else (50.0 if role == "premium" else 200.0)
            ),
            max_cpu_hours_per_day=(
                24.0 if role == "user" else (100.0 if role == "premium" else 500.0)
            ),
            max_storage_gb=(
                50 if role == "user" else (200 if role == "premium" else 1000)
            ),
            priority_weight=1 if role == "user" else (5 if role == "premium" else 10),
            can_use_custom_docker=role in ["admin", "premium"],
        )
        db.add(quota)
        db.commit()
        db.refresh(user)

    # Update last login
    user.last_login = datetime.utcnow()

    # Update role if changed in FusionAuth
    groups = token_data.get("groups", [])
    if "platform-admins" in groups and user.role != "admin":
        user.role = "admin"
    elif "premium" in groups and user.role not in ["admin", "premium"]:
        user.role = "premium"
    elif "ray-users" in groups and user.role not in ["admin", "premium", "user"]:
        user.role = "user"
    elif "ray-viewers" in groups and user.role not in ["admin", "premium", "user"]:
        user.role = "viewer"

    db.commit()

    return user


# Environment variable to enable proxy auth mode (like Grafana's GF_AUTH_PROXY_ENABLED)
PROXY_AUTH_ENABLED = os.getenv("PROXY_AUTH_ENABLED", "true").lower() == "true"


async def get_user_from_proxy_headers(request: Request, db: Session) -> Optional[User]:
    """
    Get or create user from OAuth2-Proxy X-Auth-Request-* headers.
    This enables Traefik forwardAuth integration where OAuth2-Proxy validates
    the session and passes user info via headers.

    Headers expected from OAuth2-Proxy:
    - X-Auth-Request-User: OAuth sub (user ID)
    - X-Auth-Request-Email: User email
    - X-Auth-Request-Groups: Comma-separated list of roles/groups
    - X-Auth-Request-Preferred-Username: (optional) Username
    """
    oauth_sub = request.headers.get("X-Auth-Request-User")
    email = request.headers.get("X-Auth-Request-Email")
    groups_header = request.headers.get("X-Auth-Request-Groups", "")
    username = request.headers.get("X-Auth-Request-Preferred-Username") or email

    if not oauth_sub and not email:
        return None

    # Use email as fallback for oauth_sub if not provided
    if not oauth_sub:
        oauth_sub = email

    if not email:
        email = f"{oauth_sub}@ray-compute.local"

    if not username:
        username = oauth_sub

    # Parse groups/roles from header (comma or space separated)
    groups = [g.strip() for g in groups_header.replace(",", " ").split() if g.strip()]

    # Get or create user - try by oauth_sub first, then by email
    user = db.query(User).filter(User.oauth_sub == oauth_sub).first()
    if not user and email:
        user = db.query(User).filter(User.email == email).first()
        # If found by email, update the oauth_sub
        if user and not user.oauth_sub:
            user.oauth_sub = oauth_sub

    if not user:
        # Determine role from groups
        role = "viewer"  # default - read-only access
        if "admin" in groups:
            role = "admin"
        elif "developer" in groups or "elevated-developer" in groups:
            role = "user"  # Map FusionAuth 'developer' to Ray 'user'
        elif "viewer" in groups:
            role = "viewer"

        from .models import UserQuota

        user = User(
            username=username,
            email=email,
            oauth_sub=oauth_sub,
            role=role,
            is_active=True,
        )
        db.add(user)
        db.flush()

        # Check if quota already exists (in case of race conditions or migrations)
        existing_quota = (
            db.query(UserQuota).filter(UserQuota.user_id == user.user_id).first()
        )
        if not existing_quota:
            # Create default quota for new user
            quota = UserQuota(
                user_id=user.user_id,
                max_concurrent_jobs=(
                    5 if role == "user" else (10 if role == "premium" else 20)
                ),
                max_gpu_hours_per_day=(
                    10.0 if role == "user" else (50.0 if role == "premium" else 200.0)
                ),
                max_cpu_hours_per_day=(
                    24.0 if role == "user" else (100.0 if role == "premium" else 500.0)
                ),
                max_storage_gb=(
                    50 if role == "user" else (200 if role == "premium" else 1000)
                ),
                priority_weight=(
                    1 if role == "user" else (5 if role == "premium" else 10)
                ),
                can_use_custom_docker=role in ["admin", "premium"],
            )
            db.add(quota)
        db.commit()
        db.refresh(user)
    else:
        # Update role if changed in groups
        if "admin" in groups and user.role != "admin":
            user.role = "admin"
        elif (
            "developer" in groups or "elevated-developer" in groups
        ) and user.role not in ["admin", "premium", "user"]:
            user.role = "user"

        # Update last login
        user.last_login = datetime.utcnow()
        db.commit()

    return user


def get_user_from_api_key(api_key: str, db: Session) -> Optional[User]:
    """
    Get user from API key authentication.

    Checks in order:
    1. Database-stored user API keys (with rotation support)
    2. Environment-based service account keys (CICD_*_KEY)

    Returns None if API key is invalid.
    """
    import hashlib
    from datetime import datetime as dt
    from .models import UserQuota

    # First, check database for user-created API keys
    try:
        from .models import ApiKey

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        now = dt.utcnow()

        # Check current key hash
        api_key_record = (
            db.query(ApiKey)
            .filter(
                ApiKey.key_hash == key_hash,
                ApiKey.revoked_at.is_(None),
            )
            .first()
        )

        if api_key_record:
            # Check expiration
            if api_key_record.expires_at and api_key_record.expires_at < now:
                return None  # Expired

            # Update last used timestamp
            api_key_record.last_used_at = now
            db.commit()

            # Return the user who owns this key
            if api_key_record.user_id:
                user = (
                    db.query(User)
                    .filter(User.user_id == api_key_record.user_id)
                    .first()
                )
                if user:
                    return user

        # Check previous key hash (rotation grace period)
        api_key_record = (
            db.query(ApiKey)
            .filter(
                ApiKey.previous_key_hash == key_hash,
                ApiKey.revoked_at.is_(None),
                ApiKey.previous_key_valid_until > now,
            )
            .first()
        )

        if api_key_record:
            api_key_record.last_used_at = now
            db.commit()

            if api_key_record.user_id:
                user = (
                    db.query(User)
                    .filter(User.user_id == api_key_record.user_id)
                    .first()
                )
                if user:
                    return user

    except Exception:
        # If ApiKey table doesn't exist yet, continue to env-based keys
        pass

    # Fall back to environment-based service account keys
    service_accounts = {
        "admin": {
            "key": CICD_ADMIN_KEY,
            "email": "cicd-admin@ray-compute.local",
            "username": "cicd-admin",
            "oauth_sub": "cicd-admin-service-account",
            "role": "admin",
            "quota": {
                "max_concurrent_jobs": 999,
                "max_gpu_hours_per_day": 99999.0,
                "max_cpu_hours_per_day": 99999.0,
                "max_storage_gb": 99999,
                "priority_weight": 10,
                "can_use_custom_docker": True,
            },
        },
        "elevated_developer": {
            "key": CICD_ELEVATED_DEVELOPER_KEY,
            "email": "cicd-elevated-developer@ray-compute.local",
            "username": "cicd-elevated-developer",
            "oauth_sub": "cicd-elevated-developer-service-account",
            "role": "premium",
            "quota": {
                "max_concurrent_jobs": 20,
                "max_gpu_hours_per_day": 100.0,
                "max_cpu_hours_per_day": 500.0,
                "max_storage_gb": 500,
                "priority_weight": 7,
                "can_use_custom_docker": True,
            },
        },
        "developer": {
            "key": CICD_DEVELOPER_KEY,
            "email": "cicd-developer@ray-compute.local",
            "username": "cicd-developer",
            "oauth_sub": "cicd-developer-service-account",
            "role": "user",
            "quota": {
                "max_concurrent_jobs": 10,
                "max_gpu_hours_per_day": 48.0,
                "max_cpu_hours_per_day": 200.0,
                "max_storage_gb": 100,
                "priority_weight": 5,
                "can_use_custom_docker": False,
            },
        },
        "viewer": {
            "key": CICD_VIEWER_KEY,
            "email": "cicd-viewer@ray-compute.local",
            "username": "cicd-viewer",
            "oauth_sub": "cicd-viewer-service-account",
            "role": "viewer",
            "quota": {
                "max_concurrent_jobs": 0,
                "max_gpu_hours_per_day": 0.0,
                "max_cpu_hours_per_day": 0.0,
                "max_storage_gb": 0,
                "priority_weight": 0,
                "can_use_custom_docker": False,
            },
        },
    }

    # Find matching service account
    account_config = None
    for account_type, config in service_accounts.items():
        if config["key"] and api_key == config["key"]:
            account_config = config
            break

    if not account_config:
        return None

    # Look for existing user by email
    user = db.query(User).filter(User.email == account_config["email"]).first()

    if user:
        # User exists, just return it
        return user

    # Create new user and quota in one transaction
    try:
        user = User(
            username=account_config["username"],
            email=account_config["email"],
            oauth_sub=account_config["oauth_sub"],
            role=account_config["role"],
            is_active=True,
        )
        db.add(user)
        db.flush()  # Get the user_id

        # Check if quota already exists (shouldn't, but be safe)
        existing_quota = (
            db.query(UserQuota).filter(UserQuota.user_id == user.user_id).first()
        )
        if not existing_quota:
            quota = UserQuota(user_id=user.user_id, **account_config["quota"])
            db.add(quota)

        db.commit()
        db.refresh(user)
        return user
    except Exception as e:
        db.rollback()
        # Try to get the user again in case of race condition
        user = db.query(User).filter(User.email == account_config["email"]).first()
        if user:
            return user
        raise

    return None


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency to get current authenticated user.

    Supports three authentication modes:
    1. API Key: X-API-Key header for CI/CD and developer access
    2. Proxy Auth (PROXY_AUTH_ENABLED=true): Trust X-Auth-Request-* headers from OAuth2-Proxy
       This is used when Traefik forwardAuth validates the request before it reaches this API.
    3. Bearer Token: Direct OAuth2 token validation with FusionAuth
       This is used for API clients and direct access.

    API key is checked first for CI/CD efficiency, then proxy auth (if enabled),
    then Bearer token.
    """
    import logging

    try:
        # Mode 0: Check for API key authentication (CI/CD, developer testing)
        api_key = request.headers.get("X-API-Key")
        if api_key:
            user = get_user_from_api_key(api_key, db)
            if user:
                logging.info(f"Authenticated via API key: {user.email}")
                return user
            # Invalid API key - continue to other methods rather than failing
            logging.warning("Invalid API key provided, trying other auth methods")

        # Mode 1: Check for proxy auth headers (like Grafana's GF_AUTH_PROXY_ENABLED)
        if PROXY_AUTH_ENABLED:
            user = await get_user_from_proxy_headers(request, db)
            if user:
                if not user.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="User account is inactive",
                    )
                if user.is_suspended:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"User account is suspended: {user.suspension_reason}",
                    )
                logging.debug(f"Authenticated via proxy headers: {user.email}")
                return user

        # Mode 2: Fall back to Bearer token validation
        if token:
            user = await get_user_from_fusionauth(token, db)

            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is inactive",
                )

            if user.is_suspended:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User account is suspended: {user.suspension_reason}",
                )

            logging.info(f"Authenticated via Bearer token: {user.email}")
            return user

        # No authentication found
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please login via OAuth2 or provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except AuthError as e:
        logging.error(f"AuthError in get_current_user: {e.status_code} - {e.detail}")
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logging.error(f"Unexpected error in get_current_user: {str(e)}")
        logging.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication error: {str(e)}",
        )


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Ensure user is active (convenience dependency)
    """
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Require admin role
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user


def require_role(*allowed_roles: str):
    """
    Decorator to require specific roles
    Usage: @require_role("admin", "premium")
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(
            *args, current_user: User = Depends(get_current_user), **kwargs
        ):
            if current_user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Required role: {', '.join(allowed_roles)}",
                )
            return await func(*args, current_user=current_user, **kwargs)

        return wrapper

    return decorator


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token (for API keys, not OAuth)
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, API_SECRET_KEY, algorithm="HS256")
    return encoded_jwt


def verify_access_token(token: str) -> Dict[str, Any]:
    """
    Verify JWT access token (for API keys)
    """
    try:
        payload = jwt.decode(token, API_SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def log_audit_event(
    db: Session,
    user_id: Optional[str],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[str] = None,
    request: Optional[Request] = None,
    success: bool = True,
):
    """
    Log security audit event
    """
    from .models import AuditLog

    ip_address = None
    user_agent = None

    if request:
        ip_address = request.client.host
        user_agent = request.headers.get("user-agent")

    audit_log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
    )

    db.add(audit_log)
    db.commit()
