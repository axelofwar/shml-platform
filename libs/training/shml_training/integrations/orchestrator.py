"""
Job orchestration for SHML Training Library.

Implements ToolOrchestra-style routing pattern:
- Small orchestrator routes jobs to appropriate backends
- Supports Ray, local execution, cloud backends
- Handles preemption, priority, and resource allocation
"""

import os
import time
import threading
from typing import Optional, Dict, Any, List, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod
import json

from ..core.hardware import HardwareDetector, HardwareProfile
from ..core.config import TrainingConfig


class JobStatus(Enum):
    """Job execution status."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PREEMPTED = "preempted"


class JobPriority(Enum):
    """Job priority levels."""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    ADMIN = 4  # Can preempt others


class Backend(Enum):
    """Execution backends."""

    LOCAL = "local"
    RAY = "ray"
    SLURM = "slurm"
    KUBERNETES = "kubernetes"


@dataclass
class JobSpec:
    """Specification for a training job."""

    job_id: str
    name: str
    config: TrainingConfig
    priority: JobPriority = JobPriority.NORMAL

    # User info
    user_id: str = "anonymous"
    user_role: str = "developer"  # developer, elevated, admin, super_admin

    # Resource requirements
    min_gpu_memory_gb: float = 0
    preferred_gpu_memory_gb: float = 0
    max_cpu_cores: int = 0
    max_memory_gb: float = 0

    # Execution preferences
    preferred_backend: Optional[Backend] = None
    timeout_seconds: int = 0  # 0 = no timeout
    preemptible: bool = True

    # Callbacks
    on_status_change: Optional[Callable[[JobStatus], None]] = None

    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "priority": self.priority.name,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "min_gpu_memory_gb": self.min_gpu_memory_gb,
            "preferred_gpu_memory_gb": self.preferred_gpu_memory_gb,
            "preemptible": self.preemptible,
            "tags": self.tags,
        }


@dataclass
class JobResult:
    """Result of a training job."""

    job_id: str
    status: JobStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Results
    metrics: Dict[str, float] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)  # name -> path

    # Error info
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0

    @property
    def success(self) -> bool:
        return self.status == JobStatus.COMPLETED


class ExecutionBackend(ABC):
    """Abstract base class for execution backends."""

    @abstractmethod
    def submit(self, job: JobSpec, train_fn: Callable) -> str:
        """Submit job for execution. Returns job handle."""
        pass

    @abstractmethod
    def get_status(self, handle: str) -> JobStatus:
        """Get job status."""
        pass

    @abstractmethod
    def cancel(self, handle: str) -> bool:
        """Cancel job. Returns success."""
        pass

    @abstractmethod
    def get_result(self, handle: str) -> JobResult:
        """Get job result (blocks until complete)."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend is available."""
        pass


class LocalBackend(ExecutionBackend):
    """Local execution backend."""

    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._threads: Dict[str, threading.Thread] = {}

    def submit(self, job: JobSpec, train_fn: Callable) -> str:
        """Submit job for local execution."""
        handle = job.job_id

        self._jobs[handle] = {
            "spec": job,
            "status": JobStatus.PENDING,
            "result": None,
            "start_time": None,
            "end_time": None,
        }

        def run():
            self._jobs[handle]["status"] = JobStatus.RUNNING
            self._jobs[handle]["start_time"] = datetime.now()

            try:
                result = train_fn(job.config)
                self._jobs[handle]["status"] = JobStatus.COMPLETED
                self._jobs[handle]["result"] = result
            except Exception as e:
                import traceback

                self._jobs[handle]["status"] = JobStatus.FAILED
                self._jobs[handle]["error"] = str(e)
                self._jobs[handle]["traceback"] = traceback.format_exc()
            finally:
                self._jobs[handle]["end_time"] = datetime.now()

        thread = threading.Thread(target=run, daemon=True)
        self._threads[handle] = thread
        thread.start()

        return handle

    def get_status(self, handle: str) -> JobStatus:
        if handle not in self._jobs:
            return JobStatus.FAILED
        return self._jobs[handle]["status"]

    def cancel(self, handle: str) -> bool:
        if handle in self._jobs:
            self._jobs[handle]["status"] = JobStatus.CANCELLED
            return True
        return False

    def get_result(self, handle: str) -> JobResult:
        if handle not in self._jobs:
            return JobResult(job_id=handle, status=JobStatus.FAILED)

        # Wait for completion
        if handle in self._threads:
            self._threads[handle].join()

        job_data = self._jobs[handle]
        return JobResult(
            job_id=handle,
            status=job_data["status"],
            start_time=job_data["start_time"],
            end_time=job_data["end_time"],
            metrics=(
                job_data.get("result", {})
                if isinstance(job_data.get("result"), dict)
                else {}
            ),
            error_message=job_data.get("error"),
            error_traceback=job_data.get("traceback"),
        )

    def is_available(self) -> bool:
        return True


class RayBackend(ExecutionBackend):
    """Ray execution backend."""

    def __init__(self, address: Optional[str] = None):
        self._address = address
        self._refs: Dict[str, Any] = {}
        self._ray = None

    def _ensure_ray(self):
        """Ensure Ray is initialized."""
        if self._ray is None:
            try:
                import ray

                self._ray = ray

                if not ray.is_initialized():
                    ray.init(address=self._address)
            except ImportError:
                raise ImportError("Ray not installed. Run: pip install ray")

    def submit(self, job: JobSpec, train_fn: Callable) -> str:
        """Submit job to Ray cluster."""
        self._ensure_ray()

        # Determine resources
        gpu = 1 if job.min_gpu_memory_gb > 0 else 0
        cpu = job.max_cpu_cores or 1

        # Create Ray remote function
        @self._ray.remote(num_gpus=gpu, num_cpus=cpu)
        def ray_train(config):
            return train_fn(config)

        # Submit
        ref = ray_train.remote(job.config)
        self._refs[job.job_id] = ref

        return job.job_id

    def get_status(self, handle: str) -> JobStatus:
        self._ensure_ray()

        if handle not in self._refs:
            return JobStatus.FAILED

        ref = self._refs[handle]
        ready, _ = self._ray.wait([ref], timeout=0)

        if ready:
            return JobStatus.COMPLETED
        return JobStatus.RUNNING

    def cancel(self, handle: str) -> bool:
        self._ensure_ray()

        if handle in self._refs:
            self._ray.cancel(self._refs[handle])
            return True
        return False

    def get_result(self, handle: str) -> JobResult:
        self._ensure_ray()

        if handle not in self._refs:
            return JobResult(job_id=handle, status=JobStatus.FAILED)

        try:
            result = self._ray.get(self._refs[handle])
            return JobResult(
                job_id=handle,
                status=JobStatus.COMPLETED,
                metrics=result if isinstance(result, dict) else {},
            )
        except Exception as e:
            return JobResult(
                job_id=handle,
                status=JobStatus.FAILED,
                error_message=str(e),
            )

    def is_available(self) -> bool:
        try:
            import ray

            return True
        except ImportError:
            return False


class JobOrchestrator:
    """
    Main orchestrator for training jobs.

    Routes jobs to appropriate backends based on:
    - Resource requirements
    - User role and priority
    - Backend availability
    - Current cluster load

    Usage:
        orchestrator = JobOrchestrator()

        job = JobSpec(
            job_id="train-001",
            name="BERT Fine-tuning",
            config=training_config,
            user_role="admin",
            min_gpu_memory_gb=16,
        )

        result = orchestrator.submit_and_wait(job, train_fn)
    """

    def __init__(
        self,
        ray_address: Optional[str] = None,
        enable_ray: bool = True,
        enable_preemption: bool = True,
    ):
        """
        Args:
            ray_address: Ray cluster address
            enable_ray: Whether to enable Ray backend
            enable_preemption: Whether to enable job preemption
        """
        self._backends: Dict[Backend, ExecutionBackend] = {}
        self._enable_preemption = enable_preemption

        # Always have local backend
        self._backends[Backend.LOCAL] = LocalBackend()

        # Try to add Ray backend
        if enable_ray:
            try:
                ray_backend = RayBackend(ray_address)
                if ray_backend.is_available():
                    self._backends[Backend.RAY] = ray_backend
            except:
                pass

        # Job tracking
        self._active_jobs: Dict[str, Dict[str, Any]] = {}
        self._job_queue: List[JobSpec] = []

        # Hardware info
        self._hardware = HardwareDetector.detect()

    def select_backend(self, job: JobSpec) -> Backend:
        """
        Select best backend for job.

        Args:
            job: Job specification

        Returns:
            Selected backend
        """
        # Prefer user's choice if available
        if job.preferred_backend and job.preferred_backend in self._backends:
            return job.preferred_backend

        # Admin jobs always get full local GPU access
        if job.user_role in ("admin", "super_admin"):
            # Check if Ray is available for distributed
            if Backend.RAY in self._backends and job.preferred_gpu_memory_gb > 24:
                return Backend.RAY
            return Backend.LOCAL

        # Check GPU requirements
        if job.min_gpu_memory_gb > 0:
            # Need GPU - check local availability
            if self._hardware.total_vram_gb >= job.min_gpu_memory_gb:
                return Backend.LOCAL

            # Try Ray cluster
            if Backend.RAY in self._backends:
                return Backend.RAY

        # Default to local for small jobs
        return Backend.LOCAL

    def check_preemption(self, job: JobSpec) -> List[str]:
        """
        Check if new job should preempt existing jobs.

        Returns list of job IDs to preempt.
        """
        if not self._enable_preemption:
            return []

        # Only admin can preempt
        if job.user_role not in ("admin", "super_admin"):
            return []

        to_preempt = []

        for job_id, active in self._active_jobs.items():
            active_job = active["spec"]

            # Can preempt if:
            # 1. New job has higher priority
            # 2. Active job is preemptible
            # 3. Active job is from lower role
            if (
                active_job.preemptible
                and active_job.user_role not in ("admin", "super_admin")
                and job.priority.value >= active_job.priority.value
            ):
                to_preempt.append(job_id)

        return to_preempt

    def submit(
        self,
        job: JobSpec,
        train_fn: Callable,
    ) -> str:
        """
        Submit job for execution.

        Args:
            job: Job specification
            train_fn: Training function taking config, returning metrics dict

        Returns:
            Job handle
        """
        # Check preemption
        to_preempt = self.check_preemption(job)
        for preempt_id in to_preempt:
            self.cancel(preempt_id)
            print(f"Preempted job {preempt_id} for {job.job_id}")

        # Select backend
        backend = self.select_backend(job)

        # Track job
        self._active_jobs[job.job_id] = {
            "spec": job,
            "backend": backend,
            "submitted_at": datetime.now(),
        }

        # Submit to backend
        handle = self._backends[backend].submit(job, train_fn)
        self._active_jobs[job.job_id]["handle"] = handle

        # Trigger callback
        if job.on_status_change:
            job.on_status_change(JobStatus.QUEUED)

        return job.job_id

    def get_status(self, job_id: str) -> JobStatus:
        """Get job status."""
        if job_id not in self._active_jobs:
            return JobStatus.FAILED

        job_info = self._active_jobs[job_id]
        backend = self._backends[job_info["backend"]]
        return backend.get_status(job_info["handle"])

    def cancel(self, job_id: str) -> bool:
        """Cancel a job."""
        if job_id not in self._active_jobs:
            return False

        job_info = self._active_jobs[job_id]
        backend = self._backends[job_info["backend"]]
        success = backend.cancel(job_info["handle"])

        if success:
            job_info["status"] = JobStatus.CANCELLED
            spec = job_info["spec"]
            if spec.on_status_change:
                spec.on_status_change(JobStatus.CANCELLED)

        return success

    def get_result(self, job_id: str) -> JobResult:
        """Get job result (blocks until complete)."""
        if job_id not in self._active_jobs:
            return JobResult(job_id=job_id, status=JobStatus.FAILED)

        job_info = self._active_jobs[job_id]
        backend = self._backends[job_info["backend"]]
        return backend.get_result(job_info["handle"])

    def submit_and_wait(
        self,
        job: JobSpec,
        train_fn: Callable,
    ) -> JobResult:
        """Submit job and wait for result."""
        self.submit(job, train_fn)
        return self.get_result(job.job_id)

    def list_active_jobs(self) -> List[Dict[str, Any]]:
        """List all active jobs."""
        return [
            {
                "job_id": job_id,
                "name": info["spec"].name,
                "status": self.get_status(job_id).name,
                "backend": info["backend"].name,
                "user_id": info["spec"].user_id,
                "user_role": info["spec"].user_role,
                "priority": info["spec"].priority.name,
                "submitted_at": info["submitted_at"].isoformat(),
            }
            for job_id, info in self._active_jobs.items()
        ]

    def get_queue_position(self, job_id: str) -> int:
        """Get job's position in queue (-1 if not found or running)."""
        for i, job in enumerate(self._job_queue):
            if job.job_id == job_id:
                return i
        return -1


# Convenience function for simple job submission
def run_training_job(
    name: str,
    config: TrainingConfig,
    train_fn: Callable,
    user_role: str = "developer",
    priority: JobPriority = JobPriority.NORMAL,
    ray_address: Optional[str] = None,
) -> JobResult:
    """
    Run a training job with automatic orchestration.

    Args:
        name: Job name
        config: Training configuration
        train_fn: Training function
        user_role: User role (affects resource allocation)
        priority: Job priority
        ray_address: Ray cluster address (optional)

    Returns:
        Job result
    """
    import uuid

    job = JobSpec(
        job_id=f"{name}-{uuid.uuid4().hex[:8]}",
        name=name,
        config=config,
        user_role=user_role,
        priority=priority,
        min_gpu_memory_gb=config.gpu_memory_limit_gb or 0,
    )

    orchestrator = JobOrchestrator(ray_address=ray_address)
    return orchestrator.submit_and_wait(job, train_fn)
