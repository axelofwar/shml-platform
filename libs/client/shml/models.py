"""
Pydantic models for SHML Client SDK responses.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Job status values."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    CANCELLED = "CANCELLED"


class Job(BaseModel):
    """Job response model."""

    job_id: str
    name: str
    status: JobStatus
    priority: str = "normal"
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    cpu_requested: int = 2
    memory_gb_requested: int = 8
    gpu_requested: float = 0.0
    artifact_path: Optional[str] = None
    artifact_size_bytes: Optional[int] = None
    mlflow_run_id: Optional[str] = None
    error_message: Optional[str] = None

    class Config:
        use_enum_values = True


class JobSubmitResponse(BaseModel):
    """Response from job submission."""

    job_id: str
    name: str
    status: str
    message: str = "Job submitted successfully"


class User(BaseModel):
    """User profile model."""

    user_id: UUID
    username: str
    email: str
    role: str
    created_at: datetime
    last_login: Optional[datetime] = None
    is_active: bool = True


class Quota(BaseModel):
    """User quota model."""

    max_concurrent_jobs: int
    max_gpu_hours_per_day: float
    max_cpu_hours_per_day: float
    max_storage_gb: int
    max_job_timeout_hours: Optional[int] = None
    max_gpu_fraction: float
    priority_weight: int
    can_use_custom_docker: bool
    can_skip_validation: bool
    allow_no_timeout: bool
    allow_exclusive_gpu: bool


class ApiKey(BaseModel):
    """API key model (without the actual key)."""

    id: UUID
    name: str
    key_prefix: str
    scopes: List[str]
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    description: Optional[str] = None


class ApiKeyWithSecret(BaseModel):
    """API key model with the secret (only on creation)."""

    id: UUID
    name: str
    key: str  # Full key - only shown on creation
    key_prefix: str
    scopes: List[str]
    created_at: datetime
    expires_at: Optional[datetime] = None
    warning: str = "Save this key now - it cannot be retrieved again!"


class ImpersonationToken(BaseModel):
    """Impersonation response model."""

    token: str
    effective_user: str
    effective_role: str
    expires_at: datetime
    actual_user: str
    message: str
