"""
Usage Tracking and Quota Management - Phase P2.2
Track GPU/CPU usage, enforce quotas, handle monthly resets

Key Features:
- Real-time usage tracking per user
- Daily/monthly quota enforcement
- Automatic monthly resets
- Over-quota handling (queue or reject)
- Usage analytics for billing
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from fastapi import HTTPException

from .models import User, UserQuota, Job
from .audit import log_audit_event

import logging

logger = logging.getLogger(__name__)


# ==================== Tier Configuration ====================

TIER_LIMITS = {
    "user": {  # Free tier
        "name": "Free",
        "max_gpu_hours_per_day": 0.5,  # 30 minutes
        "max_cpu_hours_per_day": 5.0,
        "max_concurrent_jobs": 1,
        "max_gpu_fraction": 0.25,
        "max_job_timeout_hours": 2,
        "priority_weight": 1,
        "techniques_allowed": [],  # No proprietary techniques
        "can_use_custom_docker": False,
        "monthly_gpu_hours": 5,
        "monthly_cpu_hours": 50,
    },
    "premium": {  # Pro tier
        "name": "Pro",
        "max_gpu_hours_per_day": 5.0,
        "max_cpu_hours_per_day": 50.0,
        "max_concurrent_jobs": 5,
        "max_gpu_fraction": 0.5,
        "max_job_timeout_hours": 24,
        "priority_weight": 2,
        "techniques_allowed": ["sapo", "advantage_filter", "curriculum_learning"],
        "can_use_custom_docker": False,
        "monthly_gpu_hours": 100,
        "monthly_cpu_hours": 500,
    },
    "admin": {  # Enterprise/Admin tier
        "name": "Enterprise",
        "max_gpu_hours_per_day": 100.0,
        "max_cpu_hours_per_day": 1000.0,
        "max_concurrent_jobs": 20,
        "max_gpu_fraction": 1.0,
        "max_job_timeout_hours": 168,  # 1 week
        "priority_weight": 5,
        "techniques_allowed": "*",  # All techniques
        "can_use_custom_docker": True,
        "monthly_gpu_hours": "unlimited",
        "monthly_cpu_hours": "unlimited",
    },
}


def get_tier_limits(tier: str) -> Dict[str, Any]:
    """Get tier limits for a user role"""
    return TIER_LIMITS.get(tier, TIER_LIMITS["user"])


# ==================== Usage Calculation ====================


def calculate_job_usage(job: Job) -> Tuple[Decimal, Decimal]:
    """
    Calculate GPU and CPU hours used by a job
    Returns (gpu_hours, cpu_hours)
    """
    if not job.started_at or not job.ended_at:
        return Decimal("0.0"), Decimal("0.0")

    duration_seconds = (job.ended_at - job.started_at).total_seconds()
    duration_hours = Decimal(str(duration_seconds / 3600.0))

    # GPU hours = duration * GPU fraction requested
    gpu_hours = duration_hours * job.gpu_requested

    # CPU hours = duration * CPU cores requested / 10 (normalize to base units)
    # This prevents CPU-only jobs from consuming too much quota
    cpu_hours = duration_hours * Decimal(str(job.cpu_requested / 10.0))

    return gpu_hours, cpu_hours


def get_user_usage(
    user_id: str, db: Session, period: str = "day"
) -> Dict[str, Decimal]:
    """
    Get user's resource usage for a time period

    Args:
        user_id: User ID
        db: Database session
        period: "day", "month", or "all"

    Returns:
        {
            "gpu_hours": Decimal,
            "cpu_hours": Decimal,
            "job_count": int,
            "period_start": datetime,
            "period_end": datetime
        }
    """
    now = datetime.utcnow()

    if period == "day":
        period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # all time
        period_start = datetime(2020, 1, 1)

    # Query jobs in the period
    jobs = (
        db.query(Job)
        .filter(
            and_(
                Job.user_id == user_id,
                Job.created_at >= period_start,
                Job.status.in_(["RUNNING", "SUCCEEDED", "FAILED"]),
            )
        )
        .all()
    )

    total_gpu_hours = Decimal("0.0")
    total_cpu_hours = Decimal("0.0")

    for job in jobs:
        gpu_hours, cpu_hours = calculate_job_usage(job)
        total_gpu_hours += gpu_hours
        total_cpu_hours += cpu_hours

    return {
        "gpu_hours": total_gpu_hours,
        "cpu_hours": total_cpu_hours,
        "job_count": len(jobs),
        "period_start": period_start,
        "period_end": now,
    }


def get_user_quota_remaining(
    user: User, quota: UserQuota, db: Session, period: str = "day"
) -> Dict[str, Any]:
    """
    Get remaining quota for a user

    Returns:
        {
            "gpu_hours_used": Decimal,
            "gpu_hours_limit": Decimal,
            "gpu_hours_remaining": Decimal,
            "cpu_hours_used": Decimal,
            "cpu_hours_limit": Decimal,
            "cpu_hours_remaining": Decimal,
            "concurrent_jobs": int,
            "concurrent_jobs_limit": int,
            "percent_used": float
        }
    """
    usage = get_user_usage(str(user.user_id), db, period=period)
    tier_limits = get_tier_limits(user.role)

    # Get limits from quota or tier defaults
    if period == "day":
        gpu_limit = quota.max_gpu_hours_per_day
        cpu_limit = quota.max_cpu_hours_per_day
    else:  # month
        gpu_limit = Decimal(str(tier_limits.get("monthly_gpu_hours", 100)))
        cpu_limit = Decimal(str(tier_limits.get("monthly_cpu_hours", 1000)))

        if tier_limits.get("monthly_gpu_hours") == "unlimited":
            gpu_limit = Decimal("999999.0")
        if tier_limits.get("monthly_cpu_hours") == "unlimited":
            cpu_limit = Decimal("999999.0")

    gpu_remaining = max(Decimal("0.0"), gpu_limit - usage["gpu_hours"])
    cpu_remaining = max(Decimal("0.0"), cpu_limit - usage["cpu_hours"])

    # Get concurrent jobs
    concurrent_jobs = (
        db.query(Job)
        .filter(
            and_(Job.user_id == user.user_id, Job.status.in_(["PENDING", "RUNNING"]))
        )
        .count()
    )

    # Calculate percent used (based on most constrained resource)
    gpu_percent = float(usage["gpu_hours"] / gpu_limit * 100) if gpu_limit > 0 else 0
    cpu_percent = float(usage["cpu_hours"] / cpu_limit * 100) if cpu_limit > 0 else 0
    percent_used = max(gpu_percent, cpu_percent)

    return {
        "gpu_hours_used": usage["gpu_hours"],
        "gpu_hours_limit": gpu_limit,
        "gpu_hours_remaining": gpu_remaining,
        "cpu_hours_used": usage["cpu_hours"],
        "cpu_hours_limit": cpu_limit,
        "cpu_hours_remaining": cpu_remaining,
        "concurrent_jobs": concurrent_jobs,
        "concurrent_jobs_limit": quota.max_concurrent_jobs,
        "percent_used": percent_used,
        "period": period,
        "tier": user.role,
    }


# ==================== Quota Enforcement ====================


def check_quota_available(
    user: User,
    quota: UserQuota,
    db: Session,
    gpu_hours_needed: float,
    cpu_hours_needed: float,
    period: str = "day",
) -> Tuple[bool, Optional[str]]:
    """
    Check if user has available quota for a job

    Returns:
        (allowed: bool, reason: Optional[str])
    """
    remaining = get_user_quota_remaining(user, quota, db, period=period)

    # Check GPU quota
    if gpu_hours_needed > float(remaining["gpu_hours_remaining"]):
        return False, (
            f"Insufficient GPU quota. Requested: {gpu_hours_needed:.2f}h, "
            f"Available: {float(remaining['gpu_hours_remaining']):.2f}h, "
            f"Limit: {float(remaining['gpu_hours_limit']):.2f}h ({period}). "
            f"Upgrade at https://shml.ai/pricing"
        )

    # Check CPU quota
    if cpu_hours_needed > float(remaining["cpu_hours_remaining"]):
        return False, (
            f"Insufficient CPU quota. Requested: {cpu_hours_needed:.2f}h, "
            f"Available: {float(remaining['cpu_hours_remaining']):.2f}h, "
            f"Limit: {float(remaining['cpu_hours_limit']):.2f}h ({period}). "
            f"Upgrade at https://shml.ai/pricing"
        )

    # Check concurrent jobs
    if remaining["concurrent_jobs"] >= remaining["concurrent_jobs_limit"]:
        return False, (
            f"Maximum concurrent jobs reached ({remaining['concurrent_jobs_limit']}). "
            f"Cancel or wait for jobs to complete. "
            f"Upgrade at https://shml.ai/pricing"
        )

    return True, None


def enforce_quota(
    user: User,
    quota: UserQuota,
    db: Session,
    gpu_hours_needed: float,
    cpu_hours_needed: float,
    job_name: str = "job",
) -> None:
    """
    Enforce quota limits - raises HTTPException if exceeded

    Checks both daily and monthly limits
    """
    # Check daily quota
    allowed, reason = check_quota_available(
        user, quota, db, gpu_hours_needed, cpu_hours_needed, period="day"
    )

    if not allowed:
        logger.warning(
            f"User {user.username} exceeded daily quota for {job_name}: {reason}"
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exceeded",
                "period": "day",
                "message": reason,
                "upgrade_url": "https://shml.ai/pricing",
            },
        )

    # Check monthly quota
    allowed, reason = check_quota_available(
        user, quota, db, gpu_hours_needed, cpu_hours_needed, period="month"
    )

    if not allowed:
        logger.warning(
            f"User {user.username} exceeded monthly quota for {job_name}: {reason}"
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exceeded",
                "period": "month",
                "message": reason,
                "upgrade_url": "https://shml.ai/pricing",
            },
        )


# ==================== Usage Updates ====================


def update_job_usage(
    job_id: str, db: Session, force_recalculate: bool = False
) -> Tuple[Decimal, Decimal]:
    """
    Update job usage metrics in database

    Returns:
        (gpu_hours, cpu_hours)
    """
    job = db.query(Job).filter(Job.job_id == job_id).first()

    if not job:
        logger.error(f"Job {job_id} not found for usage update")
        return Decimal("0.0"), Decimal("0.0")

    # Calculate usage
    gpu_hours, cpu_hours = calculate_job_usage(job)

    # Update job record
    job.gpu_used_hours = gpu_hours
    job.cpu_used_hours = cpu_hours

    db.commit()

    logger.info(
        f"Updated usage for job {job_id}: "
        f"GPU={float(gpu_hours):.2f}h, CPU={float(cpu_hours):.2f}h"
    )

    return gpu_hours, cpu_hours


async def record_job_completion(
    job_id: str, user_id: str, db: Session, status: str
) -> None:
    """
    Record job completion and update usage
    Called when job finishes (success/failure)
    """
    job = db.query(Job).filter(Job.job_id == job_id).first()

    if not job:
        return

    # Update usage
    gpu_hours, cpu_hours = update_job_usage(job_id, db)

    # Log audit event
    await log_audit_event(
        db=db,
        user_id=user_id,
        action="job_usage_recorded",
        resource_type="job",
        resource_id=job_id,
        details={
            "status": status,
            "gpu_hours": float(gpu_hours),
            "cpu_hours": float(cpu_hours),
            "duration_seconds": (
                (job.ended_at - job.started_at).total_seconds()
                if job.started_at and job.ended_at
                else 0
            ),
        },
    )


# ==================== Monthly Reset ====================


def reset_monthly_usage(db: Session) -> Dict[str, Any]:
    """
    Reset monthly usage counters
    Should be called on the 1st of each month (cron job)

    Returns:
        {
            "users_reset": int,
            "jobs_processed": int,
            "timestamp": datetime
        }
    """
    now = datetime.utcnow()

    # This is a no-op since we calculate usage dynamically
    # But we can log it for audit purposes
    users_count = db.query(User).filter(User.is_active == True).count()

    logger.info(
        f"Monthly usage reset triggered at {now.isoformat()}. "
        f"Active users: {users_count}"
    )

    return {
        "users_reset": users_count,
        "jobs_processed": 0,
        "timestamp": now,
        "message": "Usage is calculated dynamically from job records. No reset needed.",
    }


# ==================== Quota Adjustment ====================


def adjust_user_quota(user_id: str, db: Session, **kwargs: Any) -> UserQuota:
    """
    Adjust user quota limits

    Args:
        user_id: User ID
        db: Database session
        **kwargs: Quota fields to update (max_gpu_hours_per_day, etc.)

    Returns:
        Updated UserQuota
    """
    quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()

    if not quota:
        raise HTTPException(status_code=404, detail="User quota not found")

    # Update fields
    for key, value in kwargs.items():
        if hasattr(quota, key):
            setattr(quota, key, value)
            logger.info(f"Updated quota {key}={value} for user {user_id}")

    db.commit()
    db.refresh(quota)

    return quota


def initialize_user_quota(user: User, db: Session) -> UserQuota:
    """
    Initialize quota for a new user based on tier
    """
    tier_limits = get_tier_limits(user.role)

    quota = UserQuota(
        user_id=user.user_id,
        max_concurrent_jobs=tier_limits["max_concurrent_jobs"],
        max_gpu_hours_per_day=Decimal(str(tier_limits["max_gpu_hours_per_day"])),
        max_cpu_hours_per_day=Decimal(str(tier_limits["max_cpu_hours_per_day"])),
        max_job_timeout_hours=tier_limits["max_job_timeout_hours"],
        max_gpu_fraction=Decimal(str(tier_limits["max_gpu_fraction"])),
        priority_weight=tier_limits["priority_weight"],
        can_use_custom_docker=tier_limits["can_use_custom_docker"],
    )

    db.add(quota)
    db.commit()
    db.refresh(quota)

    logger.info(f"Initialized quota for user {user.username} (tier: {user.role})")

    return quota


# ==================== Usage Analytics ====================


def get_platform_usage_stats(db: Session, days: int = 30) -> Dict[str, Any]:
    """
    Get platform-wide usage statistics for billing/analytics

    Returns:
        {
            "total_gpu_hours": float,
            "total_cpu_hours": float,
            "total_jobs": int,
            "active_users": int,
            "usage_by_tier": {...},
            "period_days": int
        }
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    # Get all jobs in period
    jobs = (
        db.query(Job)
        .filter(
            and_(
                Job.created_at >= start_date,
                Job.status.in_(["RUNNING", "SUCCEEDED", "FAILED"]),
            )
        )
        .all()
    )

    total_gpu_hours = Decimal("0.0")
    total_cpu_hours = Decimal("0.0")
    usage_by_tier = {"user": 0, "premium": 0, "admin": 0}
    users_with_jobs = set()

    for job in jobs:
        gpu_hours, cpu_hours = calculate_job_usage(job)
        total_gpu_hours += gpu_hours
        total_cpu_hours += cpu_hours
        users_with_jobs.add(str(job.user_id))

        # Get user tier
        user = db.query(User).filter(User.user_id == job.user_id).first()
        if user:
            usage_by_tier[user.role] = usage_by_tier.get(user.role, 0) + 1

    return {
        "total_gpu_hours": float(total_gpu_hours),
        "total_cpu_hours": float(total_cpu_hours),
        "total_jobs": len(jobs),
        "active_users": len(users_with_jobs),
        "usage_by_tier": usage_by_tier,
        "period_days": days,
        "period_start": start_date.isoformat(),
        "period_end": datetime.utcnow().isoformat(),
    }
