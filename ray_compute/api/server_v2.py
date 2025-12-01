"""
Ray Compute API Server V2
OAuth-enabled job submission and management
"""

import os
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import get_current_user, get_current_admin_user, log_audit_event
from .database import get_db
from .models import User, Job, UserQuota
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Ray Compute API",
    description="GPU-accelerated ML job orchestration with OAuth authentication",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
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


# ============================================================================
# Pydantic Models (Request/Response schemas)
# ============================================================================


class JobSubmitRequest(BaseModel):
    """Job submission request"""

    name: str = Field(..., description="Job name")
    description: Optional[str] = Field(None, description="Job description")
    job_type: str = Field(..., description="Job type: training, inference, pipeline")
    language: str = Field("python", description="python, r, julia, bash")

    # Code
    code: Optional[str] = Field(None, description="Inline code (for simple jobs)")
    script_url: Optional[str] = Field(None, description="URL to script file")
    requirements: Optional[List[str]] = Field(None, description="Python packages")

    # Resources
    cpu: int = Field(2, ge=1, le=24, description="CPU cores")
    memory_gb: int = Field(8, ge=1, le=64, description="RAM in GB")
    gpu: float = Field(0.0, ge=0.0, le=1.0, description="GPU allocation (0.0-1.0)")
    timeout_hours: int = Field(2, ge=1, le=48, description="Max execution time")

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
    max_job_timeout_hours: int
    priority_weight: int
    can_use_custom_docker: bool

    class Config:
        from_attributes = True


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
        # Test database connection
        db.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "ok" if db_status == "healthy" else "degraded",
        "database": db_status,
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
    """Get user resource quotas"""
    quota = (
        db.query(UserQuota).filter(UserQuota.user_id == current_user.user_id).first()
    )

    if not quota:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User quota not found"
        )

    return quota


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
    Submit a new job for execution
    """
    # TODO: Implement job validation, scheduling, and submission
    # For now, return a placeholder response

    await log_audit_event(
        db=db,
        user_id=current_user.user_id,
        action="submit_job",
        resource_type="job",
        details=f"Job: {job_request.name}",
        request=request,
        success=True,
    )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Job submission not yet implemented",
    )


@app.get("/api/v1/jobs", response_model=JobListResponse)
async def list_jobs(
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List user's jobs with pagination
    """
    query = db.query(Job).filter(Job.user_id == current_user.user_id)

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
    Cancel a running or queued job
    """
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


# ============================================================================
# Error Handlers
# ============================================================================


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "path": str(request.url),
        },
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
