"""
SQLAlchemy ORM models for Ray Compute API
Matches database schema in config/database_schema.sql
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text, 
    Numeric, BigInteger, ARRAY, ForeignKey, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """User accounts with OAuth integration"""
    __tablename__ = "users"
    
    user_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(50), nullable=False, default="user")
    oauth_sub = Column(String(255), unique=True)  # Authentik OAuth subject
    api_key_hash = Column(String(255))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime(timezone=True))
    
    is_active = Column(Boolean, default=True)
    is_suspended = Column(Boolean, default=False)
    suspension_reason = Column(Text)
    suspended_at = Column(DateTime(timezone=True))
    suspended_by = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id"))
    
    # Relationships
    quota = relationship("UserQuota", back_populates="user", uselist=False)
    jobs = relationship("Job", back_populates="user", foreign_keys="Job.user_id")
    
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'premium', 'user')", name="valid_role"),
    )


class UserQuota(Base):
    """Resource quotas per user based on tier"""
    __tablename__ = "user_quotas"
    
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    max_concurrent_jobs = Column(Integer, nullable=False, default=3)
    max_gpu_hours_per_day = Column(Numeric(10, 2), nullable=False, default=24.0)
    max_cpu_hours_per_day = Column(Numeric(10, 2), nullable=False, default=100.0)
    max_storage_gb = Column(Integer, nullable=False, default=50)
    max_artifact_size_gb = Column(Integer, nullable=False, default=50)
    max_job_timeout_hours = Column(Integer, nullable=False, default=48)
    priority_weight = Column(Integer, nullable=False, default=1)
    can_use_custom_docker = Column(Boolean, default=False)
    can_skip_validation = Column(Boolean, default=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="quota")


class Job(Base):
    """Job execution records with full tracking"""
    __tablename__ = "jobs"
    
    job_id = Column(String(255), primary_key=True)
    ray_job_id = Column(String(255), unique=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    
    name = Column(String(255), nullable=False)
    description = Column(Text)
    job_type = Column(String(50), nullable=False)
    language = Column(String(50), nullable=False, default="python")
    status = Column(String(50), nullable=False, default="PENDING")
    priority = Column(String(50), nullable=False, default="normal")
    
    # Resources
    cpu_requested = Column(Integer, nullable=False)
    memory_gb_requested = Column(Integer, nullable=False)
    gpu_requested = Column(Numeric(3, 2), nullable=False, default=0.00)
    timeout_hours = Column(Integer, nullable=False)
    
    # Actual usage
    cpu_used_hours = Column(Numeric(10, 2))
    gpu_used_hours = Column(Numeric(10, 2))
    memory_peak_gb = Column(Numeric(10, 2))
    disk_used_gb = Column(Numeric(10, 2))
    
    # Docker
    base_image = Column(String(255))
    dockerfile_hash = Column(String(64))
    custom_dockerfile = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    queued_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    ended_at = Column(DateTime(timezone=True))
    
    # Output
    output_mode = Column(String(50), default="artifacts")
    artifact_path = Column(Text)
    artifact_size_bytes = Column(BigInteger)
    artifact_retention_days = Column(Integer, default=90)
    artifact_downloaded_at = Column(DateTime(timezone=True))
    mlflow_experiment = Column(String(255))
    mlflow_run_id = Column(String(255))
    
    # Metadata
    tags = Column(ARRAY(Text))
    cost_center = Column(String(255))
    depends_on = Column(ARRAY(String(255)))
    
    # Error handling
    error_message = Column(Text)
    error_traceback = Column(Text)
    exit_code = Column(Integer)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    # Audit
    cancelled_by = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id"))
    cancelled_at = Column(DateTime(timezone=True))
    cancellation_reason = Column(Text)
    
    # Relationships
    user = relationship("User", back_populates="jobs", foreign_keys=[user_id])
    
    __table_args__ = (
        CheckConstraint("priority IN ('low', 'normal', 'high', 'critical')", name="valid_priority"),
    )


class JobQueue(Base):
    """Queue entries for job scheduling"""
    __tablename__ = "job_queue"
    
    queue_id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(255), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    priority_score = Column(Numeric(10, 2), nullable=False, default=0.00)
    enqueued_at = Column(DateTime(timezone=True), server_default=func.now())
    estimated_start_time = Column(DateTime(timezone=True))
    position_in_queue = Column(Integer)


class ArtifactVersion(Base):
    """Artifact versioning and retention tracking"""
    __tablename__ = "artifact_versions"
    
    artifact_id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(255), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    artifact_path = Column(Text, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    checksum = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))
    downloaded_count = Column(Integer, default=0)
    last_accessed = Column(DateTime(timezone=True))
    is_deleted = Column(Boolean, default=False)


class ResourceUsageDaily(Base):
    """Daily aggregated resource usage per user"""
    __tablename__ = "resource_usage_daily"
    
    usage_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    usage_date = Column(DateTime(timezone=True), nullable=False)
    cpu_hours = Column(Numeric(10, 2), default=0.00)
    gpu_hours = Column(Numeric(10, 2), default=0.00)
    storage_gb = Column(Numeric(10, 2), default=0.00)
    jobs_completed = Column(Integer, default=0)
    jobs_failed = Column(Integer, default=0)


class AuditLog(Base):
    """Security and compliance audit log"""
    __tablename__ = "audit_log"
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id"))
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50))
    resource_id = Column(String(255))
    details = Column(Text)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    success = Column(Boolean, default=True)


class SystemAlert(Base):
    """System-wide alerts and notifications"""
    __tablename__ = "system_alerts"
    
    alert_id = Column(Integer, primary_key=True, autoincrement=True)
    severity = Column(String(50), nullable=False)
    alert_type = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))
    resolved_by = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id"))
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id"))
    acknowledged_at = Column(DateTime(timezone=True))
    
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'warning', 'error', 'critical')", name="valid_severity"),
    )
