"""
API Key Management endpoints for SHML Platform.

Provides endpoints for:
- Creating new API keys for users
- Listing user's API keys
- Rotating keys with 24h grace period
- Revoking/deleting keys
- Service account impersonation
"""

import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import (
    get_current_user,
    has_role_permission,
    ROLE_HIERARCHY,
    FUSIONAUTH_URL,
    FUSIONAUTH_CLIENT_ID,
    FUSIONAUTH_CLIENT_SECRET,
)
from .database import get_db
from .models import User, ApiKey, UserQuota
from .audit import AuditLogger, AuditAction

router = APIRouter(prefix="/api/v1/keys", tags=["API Keys"])

# Key rotation grace period (24 hours)
KEY_ROTATION_GRACE_HOURS = int(os.getenv("KEY_ROTATION_GRACE_HOURS", "24"))

# FusionAuth group required for impersonation
IMPERSONATION_GROUP = os.getenv("IMPERSONATION_GROUP", "impersonation-enabled")


# ============================================================================
# Pydantic Models
# ============================================================================


class ApiKeyCreateRequest(BaseModel):
    """Request to create a new API key"""

    name: str = Field(..., min_length=1, max_length=100, description="Key name")
    description: Optional[str] = Field(None, max_length=500)
    expires_in_days: Optional[int] = Field(
        None, ge=1, le=365, description="Days until expiration"
    )
    scopes: List[str] = Field(default=["jobs:submit", "jobs:read"])


class ApiKeyResponse(BaseModel):
    """API key response (without the actual key)"""

    id: UUID
    name: str
    key_prefix: str
    scopes: List[str]
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]
    description: Optional[str]

    class Config:
        from_attributes = True


class ApiKeyCreateResponse(BaseModel):
    """Response after creating a key (includes the full key - shown only once)"""

    id: UUID
    name: str
    key: str  # Full key - only shown on creation
    key_prefix: str
    scopes: List[str]
    created_at: datetime
    expires_at: Optional[datetime]
    warning: str = "Save this key now - it cannot be retrieved again!"


class ApiKeyRotateResponse(BaseModel):
    """Response after rotating a key"""

    id: UUID
    name: str
    new_key: str
    new_key_prefix: str
    old_key_valid_until: datetime
    message: str


class ImpersonationRequest(BaseModel):
    """Request to start service account impersonation"""

    service_account: str = Field(
        ...,
        description="Service account to impersonate: admin, elevated_developer, developer, viewer",
    )


class ImpersonationResponse(BaseModel):
    """Response with impersonation token"""

    token: str
    effective_user: str
    effective_role: str
    expires_at: datetime
    actual_user: str
    message: str


# ============================================================================
# Helper Functions
# ============================================================================


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.

    Returns:
        tuple: (full_key, key_hash, key_prefix)
    """
    # Format as shml_<base64url> (shml_ + 32 random chars)
    key = "shml_" + secrets.token_urlsafe(32)

    # Hash for storage
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    # Prefix for identification (first 12 chars: shml_ + 7 random)
    key_prefix = key[:12]

    return key, key_hash, key_prefix


def verify_api_key(api_key: str, db: Session) -> Optional[ApiKey]:
    """
    Verify an API key and return the ApiKey record if valid.

    Checks:
    1. Key hash matches
    2. Key is not revoked
    3. Key is not expired
    4. Also checks previous_key_hash during rotation grace period

    Returns:
        ApiKey record if valid, None otherwise
    """
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    now = datetime.utcnow()

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
            return None

        # Update last used
        api_key_record.last_used_at = now
        db.commit()
        return api_key_record

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
        return api_key_record

    return None


async def check_fusionauth_group_membership(user_id: str, group_name: str) -> bool:
    """
    Check if a user is a member of a FusionAuth group.

    Args:
        user_id: FusionAuth user ID (oauth_sub)
        group_name: Name of the group to check

    Returns:
        True if user is in the group, False otherwise
    """
    # Get API key for FusionAuth admin API
    api_key = os.getenv("FUSIONAUTH_API_KEY")
    if not api_key:
        # Fall back to checking via userinfo endpoint
        return False

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{FUSIONAUTH_URL}/api/user/{user_id}",
                headers={"Authorization": api_key},
                timeout=10.0,
            )

            if response.status_code != 200:
                return False

            user_data = response.json()
            memberships = user_data.get("user", {}).get("memberships", [])

            for membership in memberships:
                if (
                    membership.get("groupId")
                    or membership.get("group", {}).get("name") == group_name
                ):
                    return True

            return False

        except Exception:
            return False


# ============================================================================
# API Key Endpoints
# ============================================================================


@router.get("", response_model=List[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all API keys for the current user.

    Returns keys without the actual key value (only prefix shown).
    """
    keys = (
        db.query(ApiKey)
        .filter(
            ApiKey.user_id == current_user.user_id,
        )
        .order_by(ApiKey.created_at.desc())
        .all()
    )

    return keys


@router.post(
    "", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED
)
async def create_api_key(
    request_data: ApiKeyCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new API key for the current user.

    The full key is only shown once on creation - save it securely!
    """
    # Check for duplicate name
    existing = (
        db.query(ApiKey)
        .filter(
            ApiKey.user_id == current_user.user_id,
            ApiKey.name == request_data.name,
            ApiKey.revoked_at.is_(None),
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An active key with name '{request_data.name}' already exists",
        )

    # Generate the key
    full_key, key_hash, key_prefix = generate_api_key()

    # Calculate expiration
    expires_at = None
    if request_data.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=request_data.expires_in_days)

    # Create the key record
    api_key = ApiKey(
        name=request_data.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        user_id=current_user.user_id,
        scopes=request_data.scopes,
        expires_at=expires_at,
        description=request_data.description,
        created_by=current_user.user_id,
    )

    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    # Audit log
    audit = AuditLogger(db)
    audit.log(
        action=AuditAction.API_KEY_CREATE,
        actual_user=current_user,
        auth_method="oauth",
        resource_type="api_key",
        resource_id=str(api_key.id),
        request=request,
        details={
            "key_name": request_data.name,
            "scopes": request_data.scopes,
            "expires_in_days": request_data.expires_in_days,
        },
    )

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key=full_key,
        key_prefix=key_prefix,
        scopes=api_key.scopes or [],
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.post("/{key_id}/rotate", response_model=ApiKeyRotateResponse)
async def rotate_api_key(
    key_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Rotate an API key with a 24-hour grace period.

    Both old and new keys will work during the grace period.
    """
    # Find the key
    api_key = (
        db.query(ApiKey)
        .filter(
            ApiKey.id == key_id,
            ApiKey.user_id == current_user.user_id,
            ApiKey.revoked_at.is_(None),
        )
        .first()
    )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already revoked",
        )

    # Generate new key
    new_key, new_hash, new_prefix = generate_api_key()

    # Store old key for grace period
    api_key.previous_key_hash = api_key.key_hash
    api_key.previous_key_valid_until = datetime.utcnow() + timedelta(
        hours=KEY_ROTATION_GRACE_HOURS
    )

    # Update to new key
    api_key.key_hash = new_hash
    api_key.key_prefix = new_prefix

    db.commit()

    # Audit log
    audit = AuditLogger(db)
    audit.log(
        action=AuditAction.API_KEY_ROTATE,
        actual_user=current_user,
        auth_method="oauth",
        resource_type="api_key",
        resource_id=str(api_key.id),
        request=request,
        details={
            "key_name": api_key.name,
            "grace_period_hours": KEY_ROTATION_GRACE_HOURS,
        },
    )

    return ApiKeyRotateResponse(
        id=api_key.id,
        name=api_key.name,
        new_key=new_key,
        new_key_prefix=new_prefix,
        old_key_valid_until=api_key.previous_key_valid_until,
        message=f"New key generated. Old key will continue to work until {api_key.previous_key_valid_until.isoformat()}",
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Revoke an API key immediately.

    The key will no longer work after this call.
    """
    # Find the key
    api_key = (
        db.query(ApiKey)
        .filter(
            ApiKey.id == key_id,
            ApiKey.user_id == current_user.user_id,
            ApiKey.revoked_at.is_(None),
        )
        .first()
    )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already revoked",
        )

    # Revoke the key
    api_key.revoked_at = datetime.utcnow()
    api_key.revoked_by = current_user.user_id
    api_key.previous_key_hash = None  # Also invalidate any grace period
    api_key.previous_key_valid_until = None

    db.commit()

    # Audit log
    audit = AuditLogger(db)
    audit.log(
        action=AuditAction.API_KEY_REVOKE,
        actual_user=current_user,
        auth_method="oauth",
        resource_type="api_key",
        resource_id=str(api_key.id),
        request=request,
        details={"key_name": api_key.name},
    )


# ============================================================================
# Impersonation Endpoints
# ============================================================================

# Service account role mapping (for impersonation validation)
SERVICE_ACCOUNT_ROLES = {
    "admin": "admin",
    "elevated_developer": "premium",
    "developer": "user",
    "viewer": "viewer",
}


@router.post("/impersonate", response_model=ImpersonationResponse)
async def start_impersonation(
    request_data: ImpersonationRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start service account impersonation.

    Requirements:
    1. User must be in the 'impersonation-enabled' FusionAuth group
    2. User can only impersonate same role level or lower

    Returns a short-lived token for making requests as the service account.
    """
    service_account = request_data.service_account.lower().replace("-", "_")

    # Validate service account type
    if service_account not in SERVICE_ACCOUNT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid service account. Valid options: {', '.join(SERVICE_ACCOUNT_ROLES.keys())}",
        )

    target_role = SERVICE_ACCOUNT_ROLES[service_account]

    # Check role hierarchy - can only impersonate same level or lower
    if not has_role_permission(current_user.role, target_role):
        audit = AuditLogger(db)
        audit.log(
            action=AuditAction.AUTH_IMPERSONATION_START,
            actual_user=current_user,
            auth_method="oauth",
            resource_type="service_account",
            resource_id=service_account,
            request=request,
            success=False,
            error_message=f"Role hierarchy violation: {current_user.role} cannot impersonate {target_role}",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot impersonate a higher role level. Your role: {current_user.role}, target: {target_role}",
        )

    # Check FusionAuth group membership
    has_impersonation_group = await check_fusionauth_group_membership(
        current_user.oauth_sub, IMPERSONATION_GROUP
    )

    # Allow if user is admin OR has the impersonation group
    if current_user.role != "admin" and not has_impersonation_group:
        audit = AuditLogger(db)
        audit.log(
            action=AuditAction.AUTH_IMPERSONATION_START,
            actual_user=current_user,
            auth_method="oauth",
            resource_type="service_account",
            resource_id=service_account,
            request=request,
            success=False,
            error_message=f"User not in {IMPERSONATION_GROUP} group",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Impersonation requires membership in the '{IMPERSONATION_GROUP}' group. Contact an administrator.",
        )

    # Get or create the service account user
    from .auth import (
        get_user_from_api_key,
        CICD_ADMIN_KEY,
        CICD_DEVELOPER_KEY,
        CICD_ELEVATED_DEVELOPER_KEY,
        CICD_VIEWER_KEY,
    )

    # Map service account to API key (we'll use this to get the synthetic user)
    key_map = {
        "admin": CICD_ADMIN_KEY,
        "elevated_developer": CICD_ELEVATED_DEVELOPER_KEY,
        "developer": CICD_DEVELOPER_KEY,
        "viewer": CICD_VIEWER_KEY,
    }

    api_key = key_map.get(service_account)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Service account key not configured for {service_account}",
        )

    effective_user = get_user_from_api_key(api_key, db)
    if not effective_user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve service account user",
        )

    # Generate impersonation token
    from .auth import create_access_token

    expires_delta = timedelta(hours=1)  # Short-lived token
    token_data = {
        "sub": str(effective_user.user_id),
        "email": effective_user.email,
        "role": effective_user.role,
        "impersonation": True,
        "actual_user_id": str(current_user.user_id),
        "actual_user_email": current_user.email,
        "actual_user_role": current_user.role,
    }

    token = create_access_token(data=token_data, expires_delta=expires_delta)
    expires_at = datetime.utcnow() + expires_delta

    # Audit log
    audit = AuditLogger(db)
    audit.log(
        action=AuditAction.AUTH_IMPERSONATION_START,
        actual_user=current_user,
        effective_user=effective_user,
        auth_method="impersonation",
        resource_type="service_account",
        resource_id=service_account,
        request=request,
        details={
            "effective_role": effective_user.role,
            "token_expires_at": expires_at.isoformat(),
        },
    )

    return ImpersonationResponse(
        token=token,
        effective_user=effective_user.email,
        effective_role=effective_user.role,
        expires_at=expires_at,
        actual_user=current_user.email,
        message=f"Now impersonating {service_account}. Token valid for 1 hour.",
    )


# ============================================================================
# Admin Endpoints (for managing all keys)
# ============================================================================


@router.get("/admin/all", response_model=List[ApiKeyResponse])
async def list_all_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all API keys in the system (admin only).
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return keys


@router.delete("/admin/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_revoke_api_key(
    key_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Revoke any API key (admin only).
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )

    api_key = (
        db.query(ApiKey)
        .filter(
            ApiKey.id == key_id,
            ApiKey.revoked_at.is_(None),
        )
        .first()
    )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already revoked",
        )

    api_key.revoked_at = datetime.utcnow()
    api_key.revoked_by = current_user.user_id
    api_key.previous_key_hash = None
    api_key.previous_key_valid_until = None

    db.commit()

    # Audit log
    audit = AuditLogger(db)
    audit.log(
        action=AuditAction.API_KEY_REVOKE,
        actual_user=current_user,
        auth_method="oauth",
        resource_type="api_key",
        resource_id=str(api_key.id),
        request=request,
        details={
            "key_name": api_key.name,
            "key_owner": str(api_key.user_id),
            "admin_action": True,
        },
    )
