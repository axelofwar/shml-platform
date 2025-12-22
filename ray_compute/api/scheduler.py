"""
Multi-Tenant Job Scheduler - Phase P2.3
Fair scheduling of training jobs on shared GPU infrastructure

Key Features:
- Priority-based scheduling (tier-based)
- FIFO within same priority level
- Queue position tracking
- Estimated start time calculation
- WebSocket notifications for queue updates
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from .models import User, Job, JobQueue, UserQuota
from .usage_tracking import get_tier_limits
import logging

logger = logging.getLogger(__name__)


# ==================== Priority Configuration ====================

TIER_PRIORITY = {
    "admin": 1,  # Enterprise - highest priority
    "premium": 2,  # Pro
    "user": 3,  # Free - lowest priority
}


def get_priority_score(user: User, job: Job) -> Decimal:
    """
    Calculate priority score for a job
    Lower score = higher priority

    Score = base_priority * 1000 + queue_position
    """
    base_priority = TIER_PRIORITY.get(user.role, 5)

    # Add priority weight from quota (admin can boost specific users)
    tier_limits = get_tier_limits(user.role)
    priority_weight = tier_limits.get("priority_weight", 1)

    # Adjust priority based on job characteristics
    adjustments = 0

    # Shorter jobs get slight priority boost (within same tier)
    if job.timeout_hours <= 2:
        adjustments -= 50
    elif job.timeout_hours <= 6:
        adjustments -= 20

    # Explicit priority from job
    if job.priority == "high":
        adjustments -= 100
    elif job.priority == "low":
        adjustments += 100

    return Decimal(str(base_priority * 1000 + adjustments)) / Decimal(
        str(priority_weight)
    )


# ==================== Queue Management ====================


def enqueue_job(job_id: str, user_id: str, db: Session) -> JobQueue:
    """
    Add job to the scheduling queue

    Returns:
        JobQueue entry with priority score
    """
    job = db.query(Job).filter(Job.job_id == job_id).first()
    user = db.query(User).filter(User.user_id == user_id).first()

    if not job or not user:
        raise ValueError(f"Job {job_id} or User {user_id} not found")

    # Calculate priority score
    priority_score = get_priority_score(user, job)

    # Create queue entry
    queue_entry = JobQueue(
        job_id=job_id,
        user_id=user_id,
        priority_score=priority_score,
        queued_at=datetime.utcnow(),
        status="QUEUED",
    )

    db.add(queue_entry)
    db.commit()
    db.refresh(queue_entry)

    logger.info(
        f"Enqueued job {job_id} for user {user.username} "
        f"with priority score {float(priority_score):.2f}"
    )

    return queue_entry


def dequeue_next_job(db: Session) -> Optional[JobQueue]:
    """
    Get next job to run from queue
    Returns job with lowest priority score (highest priority)
    """
    next_job = (
        db.query(JobQueue)
        .filter(JobQueue.status == "QUEUED")
        .order_by(JobQueue.priority_score.asc(), JobQueue.queued_at.asc())
        .first()
    )

    if next_job:
        next_job.status = "RUNNING"
        next_job.started_at = datetime.utcnow()
        db.commit()
        db.refresh(next_job)

        logger.info(f"Dequeued job {next_job.job_id} for execution")

    return next_job


def get_queue_position(job_id: str, db: Session) -> Optional[int]:
    """
    Get position of job in queue (1-indexed)
    Returns None if job not in queue
    """
    queue_entry = (
        db.query(JobQueue)
        .filter(JobQueue.job_id == job_id, JobQueue.status == "QUEUED")
        .first()
    )

    if not queue_entry:
        return None

    # Count jobs with higher priority (lower score) or same priority but earlier queue time
    position = (
        db.query(JobQueue)
        .filter(
            JobQueue.status == "QUEUED",
            or_(
                JobQueue.priority_score < queue_entry.priority_score,
                and_(
                    JobQueue.priority_score == queue_entry.priority_score,
                    JobQueue.queued_at < queue_entry.queued_at,
                ),
            ),
        )
        .count()
    )

    return position + 1  # 1-indexed


def estimate_start_time(job_id: str, db: Session) -> Optional[datetime]:
    """
    Estimate when a queued job will start
    Based on queue position and average job duration
    """
    position = get_queue_position(job_id, db)

    if position is None:
        return None

    if position == 1:
        # Next in queue - check if current job is running
        running_jobs = db.query(Job).filter(Job.status == "RUNNING").all()

        if not running_jobs:
            return datetime.utcnow()  # Start immediately

        # Estimate when current job will finish
        # Use timeout as conservative estimate
        min_finish_time = datetime.utcnow()
        for running_job in running_jobs:
            if running_job.started_at:
                estimated_finish = running_job.started_at + timedelta(
                    hours=running_job.timeout_hours
                )
                if estimated_finish > min_finish_time:
                    min_finish_time = estimated_finish

        return min_finish_time

    # Estimate based on average job duration and queue position
    # Get recent completed jobs to estimate duration
    recent_jobs = (
        db.query(Job)
        .filter(
            Job.status == "SUCCEEDED",
            Job.started_at.isnot(None),
            Job.ended_at.isnot(None),
            Job.ended_at >= datetime.utcnow() - timedelta(days=7),
        )
        .order_by(Job.ended_at.desc())
        .limit(20)
        .all()
    )

    if recent_jobs:
        total_duration = sum(
            (job.ended_at - job.started_at).total_seconds() for job in recent_jobs
        )
        avg_duration_hours = total_duration / len(recent_jobs) / 3600.0
    else:
        avg_duration_hours = 2.0  # Default estimate

    # Estimate: current time + (position - 1) * avg duration
    estimated_wait_hours = (position - 1) * avg_duration_hours
    return datetime.utcnow() + timedelta(hours=estimated_wait_hours)


def remove_from_queue(job_id: str, db: Session, reason: str = "completed") -> None:
    """
    Remove job from queue
    Called when job completes, fails, or is cancelled
    """
    queue_entry = db.query(JobQueue).filter(JobQueue.job_id == job_id).first()

    if queue_entry:
        queue_entry.status = reason.upper()
        queue_entry.completed_at = datetime.utcnow()
        db.commit()

        logger.info(f"Removed job {job_id} from queue (reason: {reason})")


def get_queue_stats(db: Session) -> Dict[str, Any]:
    """
    Get queue statistics
    """
    queued_jobs = db.query(JobQueue).filter(JobQueue.status == "QUEUED").all()
    running_jobs = db.query(JobQueue).filter(JobQueue.status == "RUNNING").all()

    # Count by tier
    queued_by_tier = {"user": 0, "premium": 0, "admin": 0}
    for queue_entry in queued_jobs:
        user = db.query(User).filter(User.user_id == queue_entry.user_id).first()
        if user:
            queued_by_tier[user.role] = queued_by_tier.get(user.role, 0) + 1

    # Average wait time
    if queued_jobs:
        total_wait = sum(
            (datetime.utcnow() - entry.queued_at).total_seconds()
            for entry in queued_jobs
        )
        avg_wait_minutes = total_wait / len(queued_jobs) / 60.0
    else:
        avg_wait_minutes = 0.0

    return {
        "queued_count": len(queued_jobs),
        "running_count": len(running_jobs),
        "queued_by_tier": queued_by_tier,
        "avg_wait_minutes": avg_wait_minutes,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ==================== GPU Allocation ====================


class GPUAllocation:
    """
    Manage GPU allocation for training jobs
    RTX 2070: Reserved for inference (Qwen3-VL)
    RTX 3090: Training queue (supports multiple jobs with fractional allocation)
    """

    def __init__(self):
        self.rtx2070_allocated = False  # Reserved for inference
        self.rtx3090_available = 1.0  # 100% available for training
        self.rtx3090_jobs: Dict[str, float] = {}  # job_id -> gpu_fraction

    def can_allocate(self, gpu_fraction: float) -> bool:
        """Check if GPU has capacity for new job"""
        if gpu_fraction > self.rtx3090_available:
            return False
        return True

    def allocate(self, job_id: str, gpu_fraction: float) -> bool:
        """
        Allocate GPU for a job
        Returns True if successful, False if insufficient capacity
        """
        if not self.can_allocate(gpu_fraction):
            logger.warning(
                f"Cannot allocate {gpu_fraction} GPU for job {job_id}. "
                f"Available: {self.rtx3090_available}"
            )
            return False

        self.rtx3090_jobs[job_id] = gpu_fraction
        self.rtx3090_available -= gpu_fraction

        logger.info(
            f"Allocated {gpu_fraction} GPU for job {job_id}. "
            f"Remaining: {self.rtx3090_available:.2f}"
        )
        return True

    def deallocate(self, job_id: str) -> None:
        """Release GPU allocation for a job"""
        if job_id in self.rtx3090_jobs:
            gpu_fraction = self.rtx3090_jobs.pop(job_id)
            self.rtx3090_available += gpu_fraction

            logger.info(
                f"Deallocated {gpu_fraction} GPU from job {job_id}. "
                f"Available: {self.rtx3090_available:.2f}"
            )

    def get_status(self) -> Dict[str, Any]:
        """Get GPU allocation status"""
        return {
            "rtx2070": {
                "total": 1.0,
                "allocated": 1.0 if self.rtx2070_allocated else 0.0,
                "available": 0.0 if self.rtx2070_allocated else 1.0,
                "purpose": "inference (Qwen3-VL)",
            },
            "rtx3090": {
                "total": 1.0,
                "allocated": 1.0 - self.rtx3090_available,
                "available": self.rtx3090_available,
                "active_jobs": len(self.rtx3090_jobs),
                "jobs": self.rtx3090_jobs,
            },
        }


# Global GPU allocator instance
gpu_allocator = GPUAllocation()


# ==================== Scheduler ====================


class TrainingScheduler:
    """
    Main scheduler for training jobs
    Manages queue, priority, and GPU allocation
    """

    def __init__(self, db: Session):
        self.db = db
        self.gpu_allocator = gpu_allocator

    async def submit_job(
        self, job_id: str, user_id: str, gpu_fraction: float
    ) -> Dict[str, Any]:
        """
        Submit job to scheduler

        Returns:
            {
                "job_id": str,
                "status": "QUEUED" | "RUNNING",
                "queue_position": int,
                "estimated_start_time": datetime,
            }
        """
        # Add to queue
        queue_entry = enqueue_job(job_id, user_id, self.db)

        # Try to start immediately if resources available
        if self.gpu_allocator.can_allocate(gpu_fraction):
            success = self.gpu_allocator.allocate(job_id, gpu_fraction)
            if success:
                # Update queue entry to running
                queue_entry.status = "RUNNING"
                queue_entry.started_at = datetime.utcnow()
                self.db.commit()

                return {
                    "job_id": job_id,
                    "status": "RUNNING",
                    "queue_position": 0,
                    "estimated_start_time": datetime.utcnow().isoformat(),
                    "message": "Job started immediately",
                }

        # Job is queued
        position = get_queue_position(job_id, self.db)
        start_time = estimate_start_time(job_id, self.db)

        return {
            "job_id": job_id,
            "status": "QUEUED",
            "queue_position": position,
            "estimated_start_time": start_time.isoformat() if start_time else None,
            "message": f"Job queued at position {position}",
        }

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a queued or running job
        Returns True if successful
        """
        # Remove from queue
        remove_from_queue(job_id, self.db, reason="cancelled")

        # Release GPU allocation
        self.gpu_allocator.deallocate(job_id)

        # Try to start next job in queue
        asyncio.create_task(self.process_queue())

        return True

    def complete_job(self, job_id: str, status: str) -> None:
        """
        Mark job as completed (success or failure)
        Releases resources and starts next job
        """
        # Remove from queue
        remove_from_queue(job_id, self.db, reason=status)

        # Release GPU allocation
        self.gpu_allocator.deallocate(job_id)

        # Process queue to start next job
        asyncio.create_task(self.process_queue())

    async def process_queue(self) -> None:
        """
        Process queue to start next job if resources available
        Called after job completion or cancellation
        """
        while True:
            # Get next job in queue
            next_entry = dequeue_next_job(self.db)

            if not next_entry:
                break  # No more queued jobs

            # Get job details
            job = self.db.query(Job).filter(Job.job_id == next_entry.job_id).first()

            if not job:
                continue

            # Try to allocate GPU
            if self.gpu_allocator.can_allocate(float(job.gpu_requested)):
                success = self.gpu_allocator.allocate(
                    next_entry.job_id, float(job.gpu_requested)
                )

                if success:
                    logger.info(f"Started job {next_entry.job_id} from queue")
                    break  # Job started
            else:
                # No resources available, put job back in queue
                next_entry.status = "QUEUED"
                next_entry.started_at = None
                self.db.commit()
                break

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get detailed status of a job in the queue"""
        queue_entry = self.db.query(JobQueue).filter(JobQueue.job_id == job_id).first()

        if not queue_entry:
            return {
                "job_id": job_id,
                "status": "NOT_IN_QUEUE",
                "message": "Job not found in queue",
            }

        position = get_queue_position(job_id, self.db)
        start_time = estimate_start_time(job_id, self.db)

        return {
            "job_id": job_id,
            "status": queue_entry.status,
            "priority_score": float(queue_entry.priority_score),
            "queue_position": position,
            "queued_at": queue_entry.queued_at.isoformat(),
            "started_at": (
                queue_entry.started_at.isoformat() if queue_entry.started_at else None
            ),
            "estimated_start_time": start_time.isoformat() if start_time else None,
        }

    def get_queue_overview(self) -> Dict[str, Any]:
        """Get overview of entire queue"""
        stats = get_queue_stats(self.db)
        gpu_status = self.gpu_allocator.get_status()

        return {
            "queue": stats,
            "gpu": gpu_status,
            "timestamp": datetime.utcnow().isoformat(),
        }


# ==================== Background Queue Processor ====================


async def queue_processor_loop(db_session_factory):
    """
    Background task to process queue
    Runs continuously to start jobs as resources become available
    """
    while True:
        try:
            db = db_session_factory()
            scheduler = TrainingScheduler(db)

            # Process queue
            await scheduler.process_queue()

            db.close()

        except Exception as e:
            logger.error(f"Error in queue processor: {e}")

        # Check every 10 seconds
        await asyncio.sleep(10)


# ==================== Webhook Notifications ====================


async def send_queue_notification(
    job_id: str, event: str, data: Dict[str, Any], webhook_url: Optional[str] = None
) -> None:
    """
    Send webhook notification for queue events

    Events:
        - job_queued: Job added to queue
        - job_started: Job started execution
        - job_completed: Job finished
        - position_changed: Queue position updated
    """
    if not webhook_url:
        return  # No webhook configured

    import aiohttp

    payload = {
        "event": event,
        "job_id": job_id,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=5) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"Webhook notification failed for job {job_id}: "
                        f"status={resp.status}"
                    )
    except Exception as e:
        logger.error(f"Failed to send webhook for job {job_id}: {e}")
