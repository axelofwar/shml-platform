"""
Ray Compute API Server V2
OAuth-enabled job submission and management
"""

import os
import uuid
import asyncio
from datetime import datetime
from typing import List, Optional, Dict
from uuid import UUID
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ray.job_submission import JobSubmissionClient, JobStatus

from .auth import (
    get_current_user,
    log_audit_event,
    can_submit_jobs,
    PUBLIC_AUTH_URL,
    ADMIN_CONTACT,
)
from .database import get_db, SessionLocal
from .models import User, Job, UserQuota
from .job_management import router as job_management_router
from .cluster import router as cluster_router
from .logs import router as logs_router
from .mlflow_integration import (
    create_mlflow_run_for_job,
    update_mlflow_run_for_job,
    is_mlflow_server_available,
)
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ray cluster connection
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "http://ray-head:8265")
try:
    job_client = JobSubmissionClient(RAY_ADDRESS)
    logger.info(f"Connected to Ray cluster at {RAY_ADDRESS}")
except Exception as e:
    logger.error(f"Failed to connect to Ray cluster: {e}")
    job_client = None

# Job status sync interval (seconds)
JOB_SYNC_INTERVAL = int(os.getenv("JOB_SYNC_INTERVAL", "10"))


# Background task for job status sync
async def sync_job_statuses():
    """Background task to sync Ray job statuses to database"""
    while True:
        try:
            if job_client is None:
                await asyncio.sleep(JOB_SYNC_INTERVAL)
                continue

            db = SessionLocal()
            try:
                # Get all non-terminal jobs from database
                pending_jobs = (
                    db.query(Job)
                    .filter(Job.status.in_(["PENDING", "RUNNING", "SUBMITTED"]))
                    .all()
                )

                for job in pending_jobs:
                    if job.ray_job_id:
                        try:
                            # Get status from Ray
                            ray_status = job_client.get_job_status(job.ray_job_id)
                            ray_status_str = (
                                ray_status.value
                                if hasattr(ray_status, "value")
                                else str(ray_status)
                            )

                            if ray_status_str != job.status:
                                old_status = job.status
                                job.status = ray_status_str

                                # Update timestamps based on status
                                if ray_status_str == "RUNNING" and not job.started_at:
                                    job.started_at = datetime.utcnow()
                                elif ray_status_str in [
                                    "SUCCEEDED",
                                    "FAILED",
                                    "STOPPED",
                                ]:
                                    job.ended_at = datetime.utcnow()

                                    # Try to get error message for failed jobs
                                    error_msg = None
                                    if ray_status_str == "FAILED":
                                        try:
                                            logs = job_client.get_job_logs(
                                                job.ray_job_id
                                            )
                                            if logs:
                                                # Get last 500 chars of logs as error
                                                error_msg = (
                                                    logs[-500:]
                                                    if len(logs) > 500
                                                    else logs
                                                )
                                                job.error_message = error_msg
                                        except Exception:
                                            pass

                                    # Update MLflow run if present
                                    if job.mlflow_run_id:
                                        try:
                                            # Calculate metrics if job completed
                                            metrics = None
                                            if job.started_at and job.ended_at:
                                                duration_seconds = (
                                                    job.ended_at - job.started_at
                                                ).total_seconds()
                                                metrics = {
                                                    "duration_seconds": duration_seconds,
                                                    "duration_minutes": duration_seconds
                                                    / 60,
                                                }

                                            await update_mlflow_run_for_job(
                                                run_id=job.mlflow_run_id,
                                                status=ray_status_str,
                                                metrics=metrics,
                                                end_time=job.ended_at,
                                                error_message=error_msg,
                                            )
                                        except Exception as e:
                                            logger.error(
                                                f"Failed to update MLflow run for job {job.job_id}: {e}"
                                            )

                                db.commit()
                                logger.info(
                                    f"Job {job.job_id} status updated: {old_status} -> {job.status}"
                                )
                        except Exception as e:
                            logger.debug(
                                f"Could not get status for job {job.job_id}: {e}"
                            )
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error in job status sync: {e}")

        await asyncio.sleep(JOB_SYNC_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - start background tasks"""
    # Start background job status sync
    sync_task = asyncio.create_task(sync_job_statuses())
    logger.info("Started job status sync background task")
    yield
    # Cleanup
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    logger.info("Stopped job status sync background task")


# Initialize FastAPI app
app = FastAPI(
    title="Ray Compute API",
    description="GPU-accelerated ML job orchestration with OAuth authentication",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS configuration
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include additional routers
app.include_router(job_management_router, prefix="/api/v1")
app.include_router(cluster_router, prefix="/api/v1")
app.include_router(logs_router, prefix="/api/v1")

# API Key management router (includes impersonation)
from .api_keys import router as api_keys_router

app.include_router(api_keys_router)

# Training API router (Phase P2.1 - Config-only training submission)
from .training import router as training_router

app.include_router(training_router, prefix="/api/v1")


# ============================================================================
# Pydantic Models (Request/Response schemas)
# ============================================================================


class JobSubmitRequest(BaseModel):
    """Job submission request"""

    name: str = Field(..., description="Job name")
    description: Optional[str] = Field(None, description="Job description")
    job_type: str = Field(..., description="Job type: training, inference, pipeline")
    language: str = Field("python", description="python, r, julia, bash")

    # Code - multiple submission modes supported
    code: Optional[str] = Field(None, description="Inline code (for simple jobs)")
    script_url: Optional[str] = Field(None, description="URL to script file")
    script_content: Optional[str] = Field(
        None, description="Base64-encoded script file content"
    )
    script_name: Optional[str] = Field(
        None, description="Script filename (for script_content)"
    )
    entrypoint: Optional[str] = Field(
        None,
        description="Custom entrypoint command (e.g., 'python train.py --epochs 50')",
    )
    entrypoint_args: Optional[List[str]] = Field(
        None, description="Arguments for the script"
    )
    requirements: Optional[List[str]] = Field(
        None, description="Python packages (one per line)"
    )
    working_dir_files: Optional[Dict[str, str]] = Field(
        None,
        description="Additional files to include in working dir (filename -> base64 content)",
    )

    # Resources
    cpu: int = Field(2, ge=1, le=96, description="CPU cores")
    memory_gb: int = Field(8, ge=1, le=512, description="RAM in GB")
    gpu: float = Field(0.0, ge=0.0, le=1.0, description="GPU fraction (0.0-1.0)")
    timeout_hours: Optional[int] = Field(
        2, ge=1, description="Max execution time (null = no limit, admin only)"
    )
    no_timeout: bool = Field(False, description="Disable timeout (admin only)")

    # Priority
    priority: str = Field("normal", description="low, normal, high, critical")

    # Docker
    base_image: Optional[str] = Field(None, description="Custom Docker base image")
    dockerfile: Optional[str] = Field(None, description="Custom Dockerfile")

    # Output
    output_mode: str = Field("artifacts", description="artifacts, mlflow, both")
    mlflow_experiment: Optional[str] = Field(None, description="MLflow experiment name")
    artifact_retention_days: int = Field(
        90, ge=1, le=365, description="Artifact retention"
    )

    # Metadata
    tags: Optional[List[str]] = Field(None, description="Job tags")
    cost_center: Optional[str] = Field(None, description="Cost allocation")
    depends_on: Optional[List[str]] = Field(None, description="Dependent job IDs")


class JobResponse(BaseModel):
    """Job status response"""

    job_id: str
    name: str
    status: str
    priority: str
    created_at: datetime
    started_at: Optional[datetime]
    ended_at: Optional[datetime]

    cpu_requested: int
    memory_gb_requested: int
    gpu_requested: float

    artifact_path: Optional[str]
    artifact_size_bytes: Optional[int]
    mlflow_run_id: Optional[str]

    error_message: Optional[str]

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    """User profile response"""

    user_id: UUID
    username: str
    email: str
    role: str
    created_at: datetime
    last_login: Optional[datetime]
    is_active: bool

    class Config:
        from_attributes = True


class QuotaResponse(BaseModel):
    """User quota response"""

    max_concurrent_jobs: int
    max_gpu_hours_per_day: float
    max_cpu_hours_per_day: float
    max_storage_gb: int
    max_job_timeout_hours: Optional[int]  # None = unlimited for admins
    max_gpu_fraction: float
    priority_weight: int
    can_use_custom_docker: bool
    can_skip_validation: bool
    allow_no_timeout: bool
    allow_exclusive_gpu: bool

    class Config:
        from_attributes = True


class GPUInfo(BaseModel):
    """GPU information for display"""

    name: str
    index: int
    memory_total_gb: float
    memory_used_gb: float
    utilization_percent: float
    available: bool


class ClusterGPUInfo(BaseModel):
    """Cluster-wide GPU information"""

    gpus: List[GPUInfo]
    total_gpus: int
    available_gpus: int
    explanation: str


# Default quotas by role (used when user has no custom quota)
ROLE_DEFAULT_QUOTAS = {
    "admin": {
        "max_concurrent_jobs": 999,
        "max_gpu_hours_per_day": 99999.0,
        "max_cpu_hours_per_day": 99999.0,
        "max_storage_gb": 99999,
        "max_artifact_size_gb": 99999,
        "max_job_timeout_hours": None,  # Unlimited
        "max_gpu_fraction": 1.0,
        "priority_weight": 10,
        "can_use_custom_docker": True,
        "can_skip_validation": True,
        "allow_no_timeout": True,
        "allow_exclusive_gpu": True,
    },
    "premium": {
        "max_concurrent_jobs": 10,
        "max_gpu_hours_per_day": 48.0,
        "max_cpu_hours_per_day": 200.0,
        "max_storage_gb": 500,
        "max_artifact_size_gb": 100,
        "max_job_timeout_hours": 72,
        "max_gpu_fraction": 0.5,
        "priority_weight": 5,
        "can_use_custom_docker": True,
        "can_skip_validation": False,
        "allow_no_timeout": False,
        "allow_exclusive_gpu": False,
    },
    "user": {
        "max_concurrent_jobs": 3,
        "max_gpu_hours_per_day": 24.0,
        "max_cpu_hours_per_day": 100.0,
        "max_storage_gb": 50,
        "max_artifact_size_gb": 50,
        "max_job_timeout_hours": 48,
        "max_gpu_fraction": 0.25,
        "priority_weight": 1,
        "can_use_custom_docker": False,
        "can_skip_validation": False,
        "allow_no_timeout": False,
        "allow_exclusive_gpu": False,
    },
    "viewer": {
        "max_concurrent_jobs": 0,
        "max_gpu_hours_per_day": 0.0,
        "max_cpu_hours_per_day": 0.0,
        "max_storage_gb": 0,
        "max_artifact_size_gb": 0,
        "max_job_timeout_hours": 0,
        "max_gpu_fraction": 0.0,
        "priority_weight": 0,
        "can_use_custom_docker": False,
        "can_skip_validation": False,
        "allow_no_timeout": False,
        "allow_exclusive_gpu": False,
    },
}


class JobListResponse(BaseModel):
    """Paginated job list"""

    jobs: List[JobResponse]
    total: int
    page: int
    page_size: int


# ============================================================================
# Health & Info Endpoints
# ============================================================================


@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "Ray Compute API",
        "version": "2.0.0",
        "status": "operational",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
@app.get("/ping")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint - available at both /health and /ping"""
    try:
        # Test database connection using raw SQL
        result = db.execute(db.bind.dialect.raw_execute("SELECT 1"))
        db_status = "healthy"
    except AttributeError:
        # Fallback for different SQLAlchemy versions
        try:
            from sqlalchemy import text

            db.execute(text("SELECT 1"))
            db_status = "healthy"
        except Exception as e:
            db_status = f"unhealthy: {str(e)}"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # Check MLflow connection
    mlflow_status = "healthy" if is_mlflow_server_available() else "unavailable"

    # Check Ray connection
    ray_status = "healthy" if job_client is not None else "unavailable"

    return {
        "status": "ok" if db_status == "healthy" else "degraded",
        "database": db_status,
        "mlflow": mlflow_status,
        "ray": ray_status,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ============================================================================
# User Endpoints
# ============================================================================


@app.get("/api/v1/user/me", response_model=UserResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Get current user profile"""
    return current_user


@app.get("/api/v1/user/quota", response_model=QuotaResponse)
async def get_user_quota(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get user resource quotas.

    Returns the user's quota limits based on their role.
    If no custom quota exists, returns role-based defaults.
    """
    quota = (
        db.query(UserQuota).filter(UserQuota.user_id == current_user.user_id).first()
    )

    if quota:
        # Return existing quota with proper handling for admin's unlimited timeout
        return QuotaResponse(
            max_concurrent_jobs=quota.max_concurrent_jobs,
            max_gpu_hours_per_day=float(quota.max_gpu_hours_per_day),
            max_cpu_hours_per_day=float(quota.max_cpu_hours_per_day),
            max_storage_gb=quota.max_storage_gb,
            max_job_timeout_hours=(
                quota.max_job_timeout_hours if not quota.allow_no_timeout else None
            ),
            max_gpu_fraction=float(quota.max_gpu_fraction),
            priority_weight=quota.priority_weight,
            can_use_custom_docker=quota.can_use_custom_docker,
            can_skip_validation=quota.can_skip_validation,
            allow_no_timeout=quota.allow_no_timeout,
            allow_exclusive_gpu=quota.allow_exclusive_gpu,
        )

    # Return role-based defaults if no custom quota
    role = current_user.role or "user"
    defaults = ROLE_DEFAULT_QUOTAS.get(role, ROLE_DEFAULT_QUOTAS["user"])

    return QuotaResponse(**defaults)


@app.get("/api/v1/cluster/gpus", response_model=ClusterGPUInfo)
async def get_cluster_gpus(
    current_user: User = Depends(get_current_user),
):
    """
    Get available GPUs in the cluster with utilization info.

    Requires authentication (viewer role or higher, or API key).
    Returns list of GPUs with current utilization and availability.
    Includes explanation of GPU fraction for users.
    """
    gpus = []

    try:
        # Try to get GPU info from nvidia-smi or Ray cluster status
        import subprocess

        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    gpus.append(
                        GPUInfo(
                            name=parts[1],
                            index=int(parts[0]),
                            memory_total_gb=float(parts[2]) / 1024,
                            memory_used_gb=float(parts[3]) / 1024,
                            utilization_percent=float(parts[4]),
                            available=float(parts[4])
                            < 90,  # Consider available if <90% utilized
                        )
                    )
    except Exception as e:
        logger.warning(f"Failed to get GPU info from nvidia-smi: {e}")

    # Fallback: Return expected GPU configuration if nvidia-smi failed
    if not gpus:
        gpus = [
            GPUInfo(
                name="NVIDIA GeForce RTX 3090",
                index=0,
                memory_total_gb=24.0,
                memory_used_gb=0.0,
                utilization_percent=0.0,
                available=True,
            ),
            GPUInfo(
                name="NVIDIA GeForce RTX 3090",
                index=1,
                memory_total_gb=24.0,
                memory_used_gb=0.0,
                utilization_percent=0.0,
                available=True,
            ),
            GPUInfo(
                name="NVIDIA GeForce RTX 2070",
                index=2,
                memory_total_gb=8.0,
                memory_used_gb=0.0,
                utilization_percent=0.0,
                available=True,
            ),
        ]

    explanation = """GPU Fraction determines how GPU resources are shared:
• 1.0 = Exclusive access (entire GPU for your job only)
• 0.5 = Share with 1 other job (50% of GPU memory/compute)
• 0.25 = Share with up to 3 other jobs (25% of GPU resources)

Higher fractions provide more compute power but limit concurrent jobs.
For training jobs, 0.5-1.0 is recommended. For inference, 0.25 may suffice."""

    return ClusterGPUInfo(
        gpus=gpus,
        total_gpus=len(gpus),
        available_gpus=sum(1 for g in gpus if g.available),
        explanation=explanation,
    )


# ============================================================================
# Job Endpoints
# ============================================================================


@app.post(
    "/api/v1/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED
)
async def submit_job(
    job_request: JobSubmitRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit a new job for execution.

    Requires user role or higher. Viewers (read-only) cannot submit jobs.
    Validates resource requests against user's quota limits.
    """
    # Check if user has permission to submit jobs
    if not can_submit_jobs(current_user.role):
        await log_audit_event(
            db=db,
            user_id=current_user.user_id,
            action="submit_job",
            resource_type="job",
            details=f"Permission denied: viewer role cannot submit jobs",
            request=request,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Viewers do not have permission to submit jobs. Contact an administrator to upgrade your access.",
        )

    # Get user quota for validation
    quota = (
        db.query(UserQuota).filter(UserQuota.user_id == current_user.user_id).first()
    )
    role = current_user.role or "user"
    defaults = ROLE_DEFAULT_QUOTAS.get(role, ROLE_DEFAULT_QUOTAS["user"])

    # Use quota if exists, otherwise use role defaults
    max_gpu_fraction = (
        float(quota.max_gpu_fraction) if quota else defaults["max_gpu_fraction"]
    )
    max_timeout = (
        quota.max_job_timeout_hours if quota else defaults["max_job_timeout_hours"]
    )
    allow_no_timeout = quota.allow_no_timeout if quota else defaults["allow_no_timeout"]
    allow_exclusive_gpu = (
        quota.allow_exclusive_gpu if quota else defaults["allow_exclusive_gpu"]
    )

    # Validate no_timeout permission
    if job_request.no_timeout and not allow_no_timeout:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Your role ({role}) does not allow unlimited timeout. Maximum timeout: {max_timeout} hours.",
        )

    # Validate GPU fraction
    if job_request.gpu > max_gpu_fraction:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"GPU fraction {job_request.gpu} exceeds your limit of {max_gpu_fraction}. "
            + (
                ""
                if allow_exclusive_gpu
                else "Exclusive GPU access (1.0) requires admin role."
            ),
        )

    # Validate timeout
    effective_timeout = None if job_request.no_timeout else job_request.timeout_hours
    if (
        effective_timeout is not None
        and max_timeout is not None
        and effective_timeout > max_timeout
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Timeout {effective_timeout}h exceeds your limit of {max_timeout}h.",
        )

    # Check Ray cluster connection
    if job_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ray cluster not available",
        )

    # Generate job ID
    job_id = f"job-{uuid.uuid4().hex[:12]}"

    # Build runtime environment
    runtime_env = {
        "pip": job_request.requirements or [],
        "env_vars": {
            "SHML_JOB_ID": job_id,
            "SHML_JOB_NAME": job_request.name,
            "SHML_USER": current_user.username,
        },
    }

    # Determine entrypoint based on submission mode
    entrypoint = None
    working_dir_files = {}

    # Debug logging
    logger.info(f"Job {job_id} submission mode detection:")
    logger.info(f"  entrypoint: {bool(job_request.entrypoint)}")
    logger.info(
        f"  script_content: {bool(job_request.script_content)} (len={len(job_request.script_content or '')})"
    )
    logger.info(f"  script_name: {job_request.script_name}")
    logger.info(f"  code: {bool(job_request.code)}")
    logger.info(f"  entrypoint_args: {job_request.entrypoint_args}")

    if job_request.entrypoint:
        # Mode 1: Custom entrypoint command (most flexible)
        entrypoint = job_request.entrypoint

        # Add script content if provided
        if job_request.script_content and job_request.script_name:
            import base64

            try:
                script_decoded = base64.b64decode(job_request.script_content).decode(
                    "utf-8"
                )
                working_dir_files[job_request.script_name] = script_decoded
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to decode script content: {str(e)}",
                )

        # Add additional files if provided
        if job_request.working_dir_files:
            import base64

            for filename, content_b64 in job_request.working_dir_files.items():
                try:
                    working_dir_files[filename] = base64.b64decode(content_b64).decode(
                        "utf-8"
                    )
                except Exception as e:
                    logger.warning(f"Failed to decode file {filename}: {e}")

    elif job_request.script_content and job_request.script_name:
        # Mode 2: Script file with content
        import base64

        try:
            script_decoded = base64.b64decode(job_request.script_content).decode(
                "utf-8"
            )
            working_dir_files[job_request.script_name] = script_decoded

            # Build entrypoint with arguments
            args_str = " ".join(job_request.entrypoint_args or [])
            entrypoint = f"python {job_request.script_name} {args_str}".strip()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to decode script content: {str(e)}",
            )

    elif job_request.code:
        # Mode 3: Inline code (original behavior)
        entrypoint_script = f"""
import os
import sys
import time

# Job: {job_request.name}
# Type: {job_request.job_type}
# User: {current_user.username}

print(f"Starting job: {job_request.name}")
print(f"Job type: {job_request.job_type}")
start_time = time.time()

try:
    # User code
{chr(10).join("    " + line for line in job_request.code.split(chr(10)))}

    elapsed = time.time() - start_time
    print(f"Job completed successfully in {{elapsed:.2f}}s")
except Exception as e:
    print(f"Job failed: {{e}}")
    raise
"""
        entrypoint = f"python -c '''{entrypoint_script}'''"

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either 'code', 'script_content' with 'script_name', or 'entrypoint'",
        )

    # Add working directory files to runtime_env if any
    if working_dir_files:
        # Create a persistent temp directory for the job files
        # Ray will use this as the working_dir and handle file distribution
        import tempfile

        job_tmpdir = tempfile.mkdtemp(prefix=f"ray_job_{job_id}_")
        for filename, content in working_dir_files.items():
            filepath = os.path.join(job_tmpdir, filename)
            os.makedirs(
                os.path.dirname(filepath) if os.path.dirname(filepath) else job_tmpdir,
                exist_ok=True,
            )
            with open(filepath, "w") as f:
                f.write(content)
        runtime_env["working_dir"] = job_tmpdir
        logger.info(f"Created working dir for job {job_id}: {job_tmpdir}")

    try:
        # Submit to Ray cluster
        ray_job_id = job_client.submit_job(
            entrypoint=entrypoint,
            job_id=job_id,
            runtime_env=runtime_env,
            metadata={
                "name": job_request.name,
                "user": current_user.username,
                "job_type": job_request.job_type,
            },
        )
        logger.info(f"Submitted Ray job {ray_job_id} for user {current_user.username}")
    except Exception as e:
        logger.error(f"Failed to submit Ray job: {e}")
        await log_audit_event(
            db=db,
            user_id=current_user.user_id,
            action="submit_job",
            resource_type="job",
            details=f"Failed to submit job: {str(e)}",
            request=request,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit job to Ray cluster: {str(e)}",
        )

    # Create MLflow run if experiment specified
    mlflow_run_id = None
    mlflow_experiment_id = None
    if job_request.mlflow_experiment:
        try:
            mlflow_experiment_id, mlflow_run_id = await create_mlflow_run_for_job(
                experiment_name=job_request.mlflow_experiment,
                job_id=job_id,
                job_name=job_request.name,
                user=current_user.username,
                job_type=job_request.job_type,
                job_params={
                    "cpu": job_request.cpu,
                    "memory_gb": job_request.memory_gb,
                    "gpu": str(job_request.gpu) if job_request.gpu else "0",
                    "timeout_hours": job_request.timeout_hours,
                    "priority": job_request.priority,
                    "language": job_request.language,
                    "description": job_request.description,
                    "tags": ",".join(job_request.tags) if job_request.tags else None,
                },
            )
            logger.info(f"Created MLflow run {mlflow_run_id} for job {job_id}")
        except Exception as e:
            # Log error but don't fail job submission
            logger.error(f"Failed to create MLflow run for job {job_id}: {e}")

    # Create database record
    db_job = Job(
        job_id=job_id,
        ray_job_id=ray_job_id,
        user_id=current_user.user_id,
        name=job_request.name,
        description=job_request.description,
        job_type=job_request.job_type,
        language=job_request.language,
        status="PENDING",
        priority=job_request.priority,
        cpu_requested=job_request.cpu,
        memory_gb_requested=job_request.memory_gb,
        gpu_requested=job_request.gpu,
        timeout_hours=effective_timeout,  # None if no_timeout is True
        output_mode=job_request.output_mode,
        mlflow_experiment=job_request.mlflow_experiment,
        mlflow_run_id=mlflow_run_id,
        artifact_retention_days=job_request.artifact_retention_days,
        tags=job_request.tags,
        cost_center=job_request.cost_center,
        depends_on=job_request.depends_on,
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)

    await log_audit_event(
        db=db,
        user_id=current_user.user_id,
        action="submit_job",
        resource_type="job",
        resource_id=job_id,
        details=f"Job submitted: {job_request.name}"
        + (f" (MLflow run: {mlflow_run_id})" if mlflow_run_id else "")
        + (" [no timeout]" if job_request.no_timeout else ""),
        request=request,
        success=True,
    )

    return db_job


@app.get("/api/v1/jobs", response_model=JobListResponse)
async def list_jobs(
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    all_users: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List jobs with pagination.

    By default, shows only the current user's jobs.
    Admins can set all_users=true to see all jobs across the platform.
    """
    query = db.query(Job)

    # Admins can see all jobs if requested, otherwise filter by user
    if all_users and current_user.role == "admin":
        pass  # No user filter - show all jobs
    else:
        query = query.filter(Job.user_id == current_user.user_id)

    if status_filter:
        query = query.filter(Job.status == status_filter)

    total = query.count()
    jobs = (
        query.order_by(Job.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {"jobs": jobs, "total": total, "page": page, "page_size": page_size}


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get job details
    """
    job = db.query(Job).filter(Job.job_id == job_id).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )

    # Check ownership (admins can see all jobs)
    if job.user_id != current_user.user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this job",
        )

    return job


@app.delete("/api/v1/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    reason: Optional[str] = None,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cancel a running or queued job.

    Requires user role or higher. Viewers (read-only) cannot cancel jobs.
    """
    # Check if user has permission to cancel jobs
    if not can_submit_jobs(current_user.role):
        await log_audit_event(
            db=db,
            user_id=current_user.user_id,
            action="cancel_job",
            resource_type="job",
            resource_id=job_id,
            details=f"Permission denied: viewer role cannot cancel jobs",
            request=request,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Viewers do not have permission to cancel jobs. Contact an administrator to upgrade your access.",
        )

    job = db.query(Job).filter(Job.job_id == job_id).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )

    # Check ownership (admins can cancel any job)
    if job.user_id != current_user.user_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this job",
        )

    if job.status not in ["PENDING", "QUEUED", "RUNNING"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel job in status: {job.status}",
        )

    # TODO: Actually cancel the job in Ray
    job.status = "CANCELLED"
    job.cancelled_by = current_user.user_id
    job.cancelled_at = datetime.utcnow()
    job.cancellation_reason = reason or "User requested cancellation"
    job.ended_at = datetime.utcnow()

    db.commit()

    await log_audit_event(
        db=db,
        user_id=current_user.user_id,
        action="cancel_job",
        resource_type="job",
        resource_id=job_id,
        details=reason,
        request=request,
        success=True,
    )

    return {"status": "cancelled", "job_id": job_id}


@app.post("/api/v1/jobs/{job_id}/cancel")
async def stop_job_alias(
    job_id: str,
    reason: Optional[str] = None,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Alias for cancel_job - stops a running or queued job.
    Provides POST /cancel in addition to DELETE /{job_id}
    """
    return await cancel_job(job_id, reason, request, current_user, db)


# ============================================================================
# Error Handlers
# ============================================================================


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler with authentication guidance"""
    content = {
        "error": exc.detail,
        "status_code": exc.status_code,
        "path": str(request.url),
    }

    # Add helpful authentication instructions for 401 errors
    if exc.status_code == 401:
        content["authentication"] = {
            "message": "You must authenticate to access this resource.",
            "auth_url": PUBLIC_AUTH_URL,
            "instructions": [
                f"1. Contact your {ADMIN_CONTACT} to request an account",
                "2. Once registered, authenticate via OAuth at the auth_url",
                "3. Include the Bearer token in your Authorization header",
                "4. Example: Authorization: Bearer <your_access_token>",
            ],
            "note": "User registration is admin-only. Self-registration is not available.",
        }

    # Add role upgrade instructions for 403 (forbidden) errors
    elif exc.status_code == 403:
        if "viewer" in str(exc.detail).lower():
            content["authorization"] = {
                "message": "Your current role does not have permission for this action.",
                "current_access": "viewer (read-only)",
                "required_access": "user or higher",
                "instructions": [
                    f"Contact your {ADMIN_CONTACT} to request role upgrade",
                    "Admins can change your role in FusionAuth Groups",
                ],
            }
        elif "admin" in str(exc.detail).lower():
            content["authorization"] = {
                "message": "This action requires administrator privileges.",
                "instructions": [
                    f"Contact your {ADMIN_CONTACT} if you need admin access"
                ],
            }

    return JSONResponse(
        status_code=exc.status_code,
        content=content,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """General exception handler"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": (
                str(exc)
                if os.getenv("DEBUG") == "true"
                else "An unexpected error occurred"
            ),
            "path": str(request.url),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server_v2:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("DEBUG", "false").lower() == "true",
    )
