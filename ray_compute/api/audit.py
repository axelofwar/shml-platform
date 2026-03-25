"""
Audit logging module for SHML Platform.

Provides comprehensive audit trail for all API actions with support for:
- Service account impersonation tracking
- API key usage logging
- Job submission and lifecycle events
- Monthly partitioning for efficient querying
- Archival strategy support
"""

import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum

from sqlalchemy import Column, String, DateTime, Text, Index, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Session
from fastapi import Request

from .database import engine
from .models import Base


class AuditAction(str, Enum):
    """Enumeration of auditable actions."""

    # Authentication
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"
    AUTH_API_KEY_USED = "auth.api_key_used"
    AUTH_IMPERSONATION_START = "auth.impersonation_start"
    AUTH_IMPERSONATION_END = "auth.impersonation_end"

    # API Key Management
    API_KEY_CREATE = "api_key.create"
    API_KEY_ROTATE = "api_key.rotate"
    API_KEY_REVOKE = "api_key.revoke"
    API_KEY_DELETE = "api_key.delete"

    # Job Operations
    JOB_SUBMIT = "job.submit"
    JOB_CANCEL = "job.cancel"
    JOB_DELETE = "job.delete"
    JOB_RESTART = "job.restart"
    JOB_DOWNLOAD = "job.download"

    # User Management
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_ROLE_CHANGE = "user.role_change"
    USER_SUSPEND = "user.suspend"
    USER_ACTIVATE = "user.activate"

    # Cluster Operations
    CLUSTER_SCALE = "cluster.scale"
    CLUSTER_CONFIG_CHANGE = "cluster.config_change"


class AuditLog(Base):
    """
    Audit log table for tracking all platform actions.

    Partitioned by month for efficient querying and archival.
    Stores both actual user (who made the request) and effective user
    (who the action was performed as, for impersonation).
    """

    __tablename__ = "api_audit_log"
    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_actual_user", "actual_user_id"),
        Index("ix_audit_effective_user", "effective_user_id"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
        {"schema": "audit"},
    )

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Timestamp (used for partitioning)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Action details
    action = Column(String(100), nullable=False, index=True)

    # User tracking
    actual_user_id = Column(UUID(as_uuid=True), nullable=True)  # Who made the request
    actual_user_email = Column(String(255), nullable=True)
    effective_user_id = Column(
        UUID(as_uuid=True), nullable=True
    )  # Who the action is "as"
    effective_user_email = Column(String(255), nullable=True)

    # Authentication method
    auth_method = Column(String(50), nullable=False)  # oauth, api_key, impersonation
    api_key_id = Column(UUID(as_uuid=True), nullable=True)  # If API key was used

    # Resource affected
    resource_type = Column(String(50), nullable=True)  # job, user, cluster, etc.
    resource_id = Column(String(255), nullable=True)

    # Request metadata
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)
    request_path = Column(String(500), nullable=True)
    request_method = Column(String(10), nullable=True)

    # Additional context (flexible JSON)
    details = Column(JSONB, nullable=True)

    # Outcome
    success = Column(String(10), nullable=False, default="true")
    error_message = Column(Text, nullable=True)


class AuditLogger:
    """
    Service for logging audit events.

    Usage:
        audit = AuditLogger(db_session)
        audit.log(
            action=AuditAction.JOB_SUBMIT,
            actual_user=current_user,
            effective_user=impersonated_user,  # Optional
            resource_type="job",
            resource_id=job_id,
            request=request,
            details={"gpu_requested": 0.5}
        )
    """

    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        action: AuditAction,
        actual_user: Optional[Any] = None,
        effective_user: Optional[Any] = None,
        auth_method: str = "oauth",
        api_key_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        request: Optional[Request] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """
        Log an audit event.

        Args:
            action: The action being audited
            actual_user: The user who made the request (User model or dict)
            effective_user: The user the action is performed as (for impersonation)
            auth_method: How the user authenticated (oauth, api_key, impersonation)
            api_key_id: ID of API key if used
            resource_type: Type of resource affected (job, user, etc.)
            resource_id: ID of the affected resource
            request: FastAPI Request object for extracting IP, user agent, path
            details: Additional context as dict
            success: Whether the action succeeded
            error_message: Error message if failed

        Returns:
            The created AuditLog entry
        """
        # Extract user info
        actual_user_id = None
        actual_user_email = None
        if actual_user:
            if hasattr(actual_user, "user_id"):
                actual_user_id = actual_user.user_id
                actual_user_email = getattr(actual_user, "email", None)
            elif isinstance(actual_user, dict):
                actual_user_id = actual_user.get("user_id") or actual_user.get("id")
                actual_user_email = actual_user.get("email")

        effective_user_id = None
        effective_user_email = None
        if effective_user:
            if hasattr(effective_user, "user_id"):
                effective_user_id = effective_user.user_id
                effective_user_email = getattr(effective_user, "email", None)
            elif isinstance(effective_user, dict):
                effective_user_id = effective_user.get("user_id") or effective_user.get(
                    "id"
                )
                effective_user_email = effective_user.get("email")

        # If no effective user specified, it's the same as actual user
        if effective_user is None and actual_user is not None:
            effective_user_id = actual_user_id
            effective_user_email = actual_user_email

        # Extract request metadata
        ip_address = None
        user_agent = None
        request_path = None
        request_method = None

        if request:
            # Get real IP (considering X-Forwarded-For from proxy)
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                ip_address = forwarded.split(",")[0].strip()
            else:
                ip_address = request.client.host if request.client else None

            user_agent = request.headers.get("User-Agent", "")[:500]
            request_path = str(request.url.path)[:500]
            request_method = request.method

        # Create audit entry
        audit_entry = AuditLog(
            action=action.value if isinstance(action, AuditAction) else action,
            actual_user_id=actual_user_id,
            actual_user_email=actual_user_email,
            effective_user_id=effective_user_id,
            effective_user_email=effective_user_email,
            auth_method=auth_method,
            api_key_id=uuid.UUID(api_key_id) if api_key_id else None,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            ip_address=ip_address,
            user_agent=user_agent,
            request_path=request_path,
            request_method=request_method,
            details=details,
            success="true" if success else "false",
            error_message=error_message,
        )

        self.db.add(audit_entry)
        self.db.commit()

        return audit_entry

    def log_job_submission(
        self,
        job_id: str,
        actual_user: Any,
        effective_user: Optional[Any],
        auth_method: str,
        request: Request,
        job_details: Dict[str, Any],
        api_key_id: Optional[str] = None,
    ) -> AuditLog:
        """Convenience method for logging job submissions."""
        return self.log(
            action=AuditAction.JOB_SUBMIT,
            actual_user=actual_user,
            effective_user=effective_user,
            auth_method=auth_method,
            api_key_id=api_key_id,
            resource_type="job",
            resource_id=job_id,
            request=request,
            details=job_details,
        )

    def log_impersonation(
        self,
        actual_user: Any,
        target_service_account: str,
        effective_user: Any,
        request: Request,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """Convenience method for logging impersonation events."""
        return self.log(
            action=AuditAction.AUTH_IMPERSONATION_START,
            actual_user=actual_user,
            effective_user=effective_user,
            auth_method="impersonation",
            resource_type="service_account",
            resource_id=target_service_account,
            request=request,
            details={"target_service_account": target_service_account},
            success=success,
            error_message=error_message,
        )

    def log_api_key_usage(
        self,
        api_key_id: str,
        effective_user: Any,
        request: Request,
        action_performed: str,
    ) -> AuditLog:
        """Convenience method for logging API key usage."""
        return self.log(
            action=AuditAction.AUTH_API_KEY_USED,
            effective_user=effective_user,
            auth_method="api_key",
            api_key_id=api_key_id,
            request=request,
            details={"action_performed": action_performed},
        )


def get_audit_logger(db: Session) -> AuditLogger:
    """Dependency for getting audit logger instance."""
    return AuditLogger(db)


# Re-export for modules that import log_audit_event from this module
from .auth import log_audit_event  # noqa: E402, F401
