"""
OAuth2 authentication with Authentik
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


# Environment configuration
AUTHENTIK_URL = os.getenv("AUTHENTIK_URL", "http://localhost:9000")
AUTHENTIK_CLIENT_ID = os.getenv("AUTHENTIK_CLIENT_ID")
AUTHENTIK_CLIENT_SECRET = os.getenv("AUTHENTIK_CLIENT_SECRET")
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# OAuth2 configuration
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{AUTHENTIK_URL}/application/o/authorize/",
    tokenUrl=f"{AUTHENTIK_URL}/application/o/token/",
)


class AuthError(Exception):
    """Custom authentication error"""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


async def verify_authentik_token(token: str) -> Dict[str, Any]:
    """
    Verify OAuth token with Authentik introspection endpoint
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{AUTHENTIK_URL}/application/o/introspect/",
                data={
                    "token": token,
                    "client_id": AUTHENTIK_CLIENT_ID,
                    "client_secret": AUTHENTIK_CLIENT_SECRET,
                },
                timeout=10.0
            )
            
            if response.status_code != 200:
                raise AuthError(
                    status.HTTP_401_UNAUTHORIZED,
                    "Could not validate credentials"
                )
            
            token_data = response.json()
            
            if not token_data.get("active"):
                raise AuthError(
                    status.HTTP_401_UNAUTHORIZED,
                    "Token is not active"
                )
            
            return token_data
            
        except httpx.RequestError as e:
            raise AuthError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Could not connect to authentication service: {str(e)}"
            )


async def get_user_from_authentik(token: str, db: Session) -> User:
    """
    Get or create user from Authentik OAuth token
    """
    # Verify token with Authentik
    token_data = await verify_authentik_token(token)
    
    oauth_sub = token_data.get("sub")
    email = token_data.get("email")
    username = token_data.get("preferred_username") or email
    
    if not oauth_sub:
        raise AuthError(
            status.HTTP_401_UNAUTHORIZED,
            "Token missing required claims"
        )
    
    # Get or create user
    user = db.query(User).filter(User.oauth_sub == oauth_sub).first()
    
    if not user:
        # Create new user from OAuth data
        # Determine role from Authentik groups
        groups = token_data.get("groups", [])
        role = "user"  # default
        if "admins" in groups:
            role = "admin"
        elif "premium" in groups:
            role = "premium"
        
        from .models import UserQuota
        
        user = User(
            username=username,
            email=email,
            oauth_sub=oauth_sub,
            role=role,
            is_active=True
        )
        db.add(user)
        db.flush()  # Get user_id before creating quota
        
        # Create default quota for new user
        quota = UserQuota(
            user_id=user.user_id,
            max_concurrent_jobs=5 if role == "user" else (10 if role == "premium" else 20),
            max_gpu_hours_per_day=10.0 if role == "user" else (50.0 if role == "premium" else 200.0),
            max_cpu_hours_per_day=24.0 if role == "user" else (100.0 if role == "premium" else 500.0),
            max_storage_gb=50 if role == "user" else (200 if role == "premium" else 1000),
            priority_weight=1 if role == "user" else (5 if role == "premium" else 10),
            can_use_custom_docker=role in ["admin", "premium"]
        )
        db.add(quota)
        db.commit()
        db.refresh(user)
    
    # Update last login
    user.last_login = datetime.utcnow()
    
    # Update role if changed in Authentik
    groups = token_data.get("groups", [])
    if "admins" in groups and user.role != "admin":
        user.role = "admin"
    elif "premium" in groups and user.role not in ["admin", "premium"]:
        user.role = "premium"
    
    db.commit()
    
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get current authenticated user
    """
    try:
        user = await get_user_from_authentik(token, db)
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        
        if user.is_suspended:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User account is suspended: {user.suspension_reason}"
            )
        
        return user
        
    except AuthError as e:
        import logging
        logging.error(f"AuthError in get_current_user: {e.status_code} - {e.detail}")
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        import logging
        import traceback
        logging.error(f"Unexpected error in get_current_user: {str(e)}")
        logging.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication error: {str(e)}"
        )


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Ensure user is active (convenience dependency)
    """
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Require admin role
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def require_role(*allowed_roles: str):
    """
    Decorator to require specific roles
    Usage: @require_role("admin", "premium")
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user: User = Depends(get_current_user), **kwargs):
            if current_user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Required role: {', '.join(allowed_roles)}"
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
    success: bool = True
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
        success=success
    )
    
    db.add(audit_log)
    db.commit()
