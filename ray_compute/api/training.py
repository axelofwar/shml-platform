"""
Training API Endpoints - Phase P2.1
Server-side training execution with proprietary techniques
Users submit configs, server executes with shml_training library

Key Features:
- Config-only submission (no code exposure)
- Server-side technique execution
- Tier-based access control
- Multi-tenant resource allocation
"""

import os
import json
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from ray.job_submission import JobSubmissionClient, JobStatus

from .auth import get_current_user, require_role
from .database import get_db
from .models import User, Job as JobModel, UserQuota
from .audit import log_audit_event
from .usage_tracking import (
    enforce_quota,
    get_user_quota_remaining,
    get_tier_limits,
    update_job_usage,
    record_job_completion,
)
from .scheduler import (
    TrainingScheduler,
    get_queue_position,
    estimate_start_time,
    get_queue_stats,
)

# Initialize router
router = APIRouter(prefix="/training", tags=["training"])

# Ray client
RAY_ADDRESS = os.getenv("RAY_DASHBOARD_ADDRESS", "http://ray-head:8265")
job_client = JobSubmissionClient(RAY_ADDRESS)

# Proprietary techniques path (server-side only)
TECHNIQUES_PATH = os.getenv(
    "SHML_TECHNIQUES_PATH", "/opt/shml-pro"  # Mounted proprietary code location
)


# ==================== Models ====================


class ModelArchitecture(str, Enum):
    """Supported model architectures"""

    YOLOV8N = "yolov8n"
    YOLOV8S = "yolov8s"
    YOLOV8M = "yolov8m"
    YOLOV8L = "yolov8l"
    YOLOV8X = "yolov8x"


class DatasetSource(str, Enum):
    """Supported dataset sources"""

    WIDER_FACE = "wider_face"
    CUSTOM_GCS = "custom_gcs"
    CUSTOM_S3 = "custom_s3"
    CUSTOM_HTTP = "custom_http"


class TechniqueConfig(BaseModel):
    """Configuration for proprietary techniques"""

    name: Literal["sapo", "advantage_filter", "curriculum_learning"]
    enabled: bool = True
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TrainingHyperparameters(BaseModel):
    """Training hyperparameters"""

    epochs: int = Field(default=100, ge=1, le=500)
    batch_size: int = Field(default=16, ge=1, le=128)
    learning_rate: float = Field(default=0.01, gt=0, le=1.0)
    optimizer: Literal["SGD", "Adam", "AdamW"] = "SGD"
    momentum: float = Field(default=0.937, ge=0, le=1.0)
    weight_decay: float = Field(default=0.0005, ge=0, le=1.0)
    warmup_epochs: int = Field(default=3, ge=0, le=10)
    patience: int = Field(default=50, ge=1, le=200)
    imgsz: int = Field(default=640, ge=320, le=1280)
    augment: bool = True

    @validator("imgsz")
    def validate_imgsz(cls, v):
        """Image size must be multiple of 32"""
        if v % 32 != 0:
            raise ValueError("Image size must be a multiple of 32")
        return v


class ComputeConfig(BaseModel):
    """Compute resource configuration"""

    gpu_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    cpu_cores: int = Field(default=4, ge=1, le=32)
    memory_gb: int = Field(default=8, ge=2, le=64)
    timeout_hours: int = Field(default=24, ge=1, le=168)
    priority: Literal["low", "normal", "high"] = "normal"


class TrainingJobRequest(BaseModel):
    """Training job submission request (config-only, no code)"""

    # Job identification
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)

    # Model and dataset
    model: ModelArchitecture
    dataset: DatasetSource
    dataset_url: Optional[str] = Field(None, description="Required for custom datasets")

    # Training configuration
    hyperparameters: TrainingHyperparameters = Field(
        default_factory=TrainingHyperparameters
    )

    # Proprietary techniques (Pro/Enterprise tier only)
    techniques: List[TechniqueConfig] = Field(default_factory=list)

    # Compute resources
    compute: ComputeConfig = Field(default_factory=ComputeConfig)

    # MLflow integration
    mlflow_experiment: Optional[str] = Field(None, description="MLflow experiment name")
    mlflow_tags: Dict[str, str] = Field(default_factory=dict)

    # Callbacks (optional)
    enable_mlflow_callback: bool = True
    enable_prometheus_callback: bool = True

    @validator("dataset_url", always=True)
    def validate_dataset_url(cls, v, values):
        """Validate dataset URL for custom datasets"""
        dataset = values.get("dataset")
        if dataset and dataset != DatasetSource.WIDER_FACE:
            if not v:
                raise ValueError(f"dataset_url is required for {dataset}")
            # Validate URL scheme
            if not any(
                v.startswith(scheme)
                for scheme in ["gs://", "s3://", "http://", "https://"]
            ):
                raise ValueError(
                    "dataset_url must start with gs://, s3://, http://, or https://"
                )
        return v


class TrainingJobResponse(BaseModel):
    """Training job submission response"""

    job_id: str
    ray_job_id: str
    name: str
    status: str
    created_at: datetime
    estimated_duration_hours: Optional[float] = None
    mlflow_experiment: Optional[str] = None
    message: str


class TrainingJobStatus(BaseModel):
    """Training job status with metrics"""

    job_id: str
    ray_job_id: str
    name: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Training progress
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    progress_percent: Optional[float] = None

    # Metrics
    latest_metrics: Optional[Dict[str, Any]] = None

    # MLflow
    mlflow_run_id: Optional[str] = None
    mlflow_experiment: Optional[str] = None

    # Resources
    gpu_hours_used: Optional[float] = None
    cpu_hours_used: Optional[float] = None

    # Error
    error: Optional[str] = None


# ==================== Helper Functions ====================


def check_tier_access(user: User, techniques: List[TechniqueConfig]) -> None:
    """Check if user's tier allows requested techniques"""
    if not techniques:
        return  # Free tier OK if no techniques requested

    # Free tier cannot use proprietary techniques
    if user.role == "user":
        raise HTTPException(
            status_code=403,
            detail="Proprietary techniques require Pro or Enterprise tier. Upgrade at https://shml.ai/pricing",
        )

    # Pro and Enterprise can use all techniques
    if user.role in ["premium", "admin"]:
        return

    raise HTTPException(
        status_code=403, detail="Insufficient permissions for proprietary techniques"
    )


def check_resource_quota(
    user: User,
    quota: UserQuota,
    compute: ComputeConfig,
    hyperparameters: TrainingHyperparameters,
    db: Session,
) -> None:
    """Check if user has available resource quota with usage tracking"""

    # Check GPU fraction
    if compute.gpu_fraction > float(quota.max_gpu_fraction):
        raise HTTPException(
            status_code=403,
            detail=f"GPU fraction {compute.gpu_fraction} exceeds quota {quota.max_gpu_fraction}",
        )

    # Check timeout
    if compute.timeout_hours > quota.max_job_timeout_hours:
        raise HTTPException(
            status_code=403,
            detail=f"Timeout {compute.timeout_hours}h exceeds quota {quota.max_job_timeout_hours}h",
        )

    # Estimate GPU/CPU hours needed for this job
    estimated_duration_hours = compute.timeout_hours * 0.8  # Assume 80% of timeout
    gpu_hours_needed = estimated_duration_hours * compute.gpu_fraction
    cpu_hours_needed = estimated_duration_hours * (compute.cpu_cores / 10.0)

    # Enforce usage quota (daily and monthly)
    enforce_quota(
        user=user,
        quota=quota,
        db=db,
        gpu_hours_needed=gpu_hours_needed,
        cpu_hours_needed=cpu_hours_needed,
        job_name=f"Training job ({hyperparameters.epochs} epochs)",
    )


def generate_training_script(
    request: TrainingJobRequest, user: User, job_id: str, mlflow_run_id: str
) -> str:
    """
    Generate server-side training script with proprietary techniques
    User NEVER sees this code
    """

    # Build techniques initialization
    techniques_code = []
    for tech in request.techniques:
        if not tech.enabled:
            continue

        if tech.name == "sapo":
            config = tech.config or {}
            alpha = config.get("alpha", 0.1)
            beta = config.get("beta", 0.95)
            techniques_code.append(
                f"""
# SAPO Optimizer
from shml_training.techniques import SAPOOptimizer
sapo = SAPOOptimizer(alpha={alpha}, beta={beta})
callbacks.append(sapo)
"""
            )

        elif tech.name == "advantage_filter":
            config = tech.config or {}
            threshold = config.get("threshold", 0.7)
            window = config.get("window", 10)
            techniques_code.append(
                f"""
# Advantage Filter
from shml_training.techniques import AdvantageFilter
advantage_filter = AdvantageFilter(threshold={threshold}, window_size={window})
callbacks.append(advantage_filter)
"""
            )

        elif tech.name == "curriculum_learning":
            config = tech.config or {}
            stages = config.get("stages", 4)
            techniques_code.append(
                f"""
# Curriculum Learning
from shml_training.techniques import CurriculumLearning
curriculum = CurriculumLearning(num_stages={stages})
callbacks.append(curriculum)
"""
            )

    techniques_init = (
        "\n".join(techniques_code) if techniques_code else "# No techniques enabled"
    )

    # Build callbacks
    callbacks_code = []
    if request.enable_mlflow_callback:
        callbacks_code.append(
            f"""
# MLflow Callback
from shml_training.integrations import MLflowCallback
mlflow_callback = MLflowCallback(
    tracking_uri=os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow-server:8080"),
    experiment_name={repr(request.mlflow_experiment or "training-jobs")},
    run_name={repr(request.name)},
    tags={repr({**request.mlflow_tags, "job_id": job_id, "user": user.username})}
)
callbacks.append(mlflow_callback)
"""
        )

    if request.enable_prometheus_callback:
        callbacks_code.append(
            f"""
# Prometheus Callback
from shml_training.integrations import PrometheusCallback
prometheus_callback = PrometheusCallback(
    pushgateway_url=os.environ.get("PROMETHEUS_PUSHGATEWAY_URL", "http://prometheus-pushgateway:9091"),
    job_name={repr(f"training_{job_id}")},
    labels={{"user": {repr(user.username)}, "job_id": {repr(job_id)}}}
)
callbacks.append(prometheus_callback)
"""
        )

    callbacks_init = (
        "\n".join(callbacks_code) if callbacks_code else "# No callbacks enabled"
    )

    # Build dataset loading
    if request.dataset == DatasetSource.WIDER_FACE:
        dataset_code = """
# WIDER Face dataset (pre-downloaded)
dataset_path = "/data/datasets/wider_face"
"""
    else:
        dataset_code = f"""
# Custom dataset
import urllib.request
import zipfile
dataset_url = {repr(request.dataset_url)}
dataset_path = "/tmp/dataset_{job_id}"
os.makedirs(dataset_path, exist_ok=True)

# Download and extract dataset
print(f"Downloading dataset from {{dataset_url}}...")
urllib.request.urlretrieve(dataset_url, f"{{dataset_path}}/dataset.zip")
with zipfile.ZipFile(f"{{dataset_path}}/dataset.zip", 'r') as zip_ref:
    zip_ref.extractall(dataset_path)
print("Dataset downloaded and extracted")
"""

    # Generate complete script
    script = f"""#!/usr/bin/env python3
\"\"\"
Auto-generated training script for job {job_id}
User: {user.username}
Model: {request.model.value}
Dataset: {request.dataset.value}

THIS CODE EXECUTES SERVER-SIDE ONLY
Proprietary techniques are NOT exposed to user
\"\"\"

import os
import sys
from pathlib import Path

# Set license key (server-side only)
os.environ["SHML_LICENSE_KEY"] = os.environ.get("SHML_LICENSE_KEY", "")

# Import training library
from shml_training.core import UltralyticsTrainer, TrainingConfig

# Initialize callbacks list
callbacks = []

{callbacks_init}

{techniques_init}

{dataset_code}

# Configure training
config = TrainingConfig(
    model_name={repr(request.model.value)},
    data_path=dataset_path,
    epochs={request.hyperparameters.epochs},
    batch_size={request.hyperparameters.batch_size},
    learning_rate={request.hyperparameters.learning_rate},
    optimizer={repr(request.hyperparameters.optimizer)},
    momentum={request.hyperparameters.momentum},
    weight_decay={request.hyperparameters.weight_decay},
    warmup_epochs={request.hyperparameters.warmup_epochs},
    patience={request.hyperparameters.patience},
    imgsz={request.hyperparameters.imgsz},
    augment={request.hyperparameters.augment},
    project="training-jobs",
    name={repr(job_id)},
    save_dir=f"/data/checkpoints/{{repr(job_id)}}",
)

# Initialize trainer
trainer = UltralyticsTrainer(config=config, callbacks=callbacks)

# Start training
print(f"Starting training job {{repr(job_id)}}...")
print(f"Model: {{repr(request.model.value)}}")
print(f"Dataset: {{repr(request.dataset.value)}}")
print(f"Epochs: {{request.hyperparameters.epochs}}")
print(f"Techniques enabled: {{len([t for t in {repr([t.name for t in request.techniques])} if t])}}")

try:
    results = trainer.train()
    print(f"Training completed successfully!")
    print(f"Best mAP50: {{results.get('map50', 'N/A')}}")
    print(f"Best checkpoint: {{results.get('best_checkpoint', 'N/A')}}")
except Exception as e:
    print(f"Training failed: {{e}}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""

    return script


# ==================== API Endpoints ====================


@router.post("/jobs", response_model=TrainingJobResponse, status_code=201)
async def submit_training_job(
    request: TrainingJobRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit a training job (Phase P2.1)

    Config-only submission - no code required from user.
    Server executes training with proprietary techniques.

    **Free Tier:** Basic training without proprietary techniques
    **Pro Tier:** Access to SAPO, AdvantageFilter, CurriculumLearning
    **Enterprise Tier:** Pro features + priority scheduling + higher quotas
    """

    # Check tier access for proprietary techniques
    check_tier_access(current_user, request.techniques)

    # Get user quota
    quota = (
        db.query(UserQuota).filter(UserQuota.user_id == current_user.user_id).first()
    )
    if not quota:
        raise HTTPException(status_code=500, detail="User quota not found")

    # Check resource quota with usage tracking
    check_resource_quota(
        current_user, quota, request.compute, request.hyperparameters, db
    )

    # Generate unique job ID
    job_id = f"training_{uuid.uuid4().hex[:12]}"
    mlflow_run_id = str(uuid.uuid4())

    # Generate server-side training script
    try:
        training_script = generate_training_script(
            request, current_user, job_id, mlflow_run_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate training script: {str(e)}"
        )

    # Prepare Ray job submission
    runtime_env = {
        "pip": [
            "torch>=2.0.0",
            "torchvision>=0.15.0",
            "ultralytics>=8.0.0",
            "mlflow>=2.0.0",
            "prometheus-client>=0.16.0",
        ],
        "env_vars": {
            "MLFLOW_TRACKING_URI": os.environ.get(
                "MLFLOW_TRACKING_URI", "http://mlflow-server:8080"
            ),
            "PROMETHEUS_PUSHGATEWAY_URL": os.environ.get(
                "PROMETHEUS_PUSHGATEWAY_URL", "http://prometheus-pushgateway:9091"
            ),
            "SHML_LICENSE_KEY": os.environ.get("SHML_LICENSE_KEY", ""),
            "CUDA_VISIBLE_DEVICES": "0",  # Will be dynamically allocated
        },
        "working_dir": "/opt/shml-training",  # Pre-installed library location
    }

    # Submit job to Ray
    try:
        ray_job_id = job_client.submit_job(
            entrypoint=f"python -c {repr(training_script)}",
            runtime_env=runtime_env,
            metadata={
                "job_id": job_id,
                "user_id": str(current_user.user_id),
                "username": current_user.username,
                "job_type": "training",
                "model": request.model.value,
                "dataset": request.dataset.value,
                "techniques": [t.name for t in request.techniques if t.enabled],
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to submit job to Ray: {str(e)}"
        )

    # Create database record
    job_record = JobModel(
        job_id=job_id,
        ray_job_id=ray_job_id,
        user_id=current_user.user_id,
        name=request.name,
        status="PENDING",
        job_type="training",
        entrypoint=f"Training: {request.model.value} on {request.dataset.value}",
        metadata={
            "description": request.description,
            "model": request.model.value,
            "dataset": request.dataset.value,
            "dataset_url": request.dataset_url,
            "hyperparameters": request.hyperparameters.dict(),
            "techniques": [t.dict() for t in request.techniques],
            "compute": request.compute.dict(),
            "mlflow_experiment": request.mlflow_experiment,
            "mlflow_run_id": mlflow_run_id,
        },
    )

    db.add(job_record)
    db.commit()
    db.refresh(job_record)

    # Log audit event
    await log_audit_event(
        db=db,
        user_id=current_user.user_id,
        action="training_job_submit",
        resource_type="training_job",
        resource_id=job_id,
        details={
            "model": request.model.value,
            "dataset": request.dataset.value,
            "techniques": [t.name for t in request.techniques if t.enabled],
            "ray_job_id": ray_job_id,
        },
    )

    # Estimate duration (rough heuristic)
    estimated_duration = (
        request.hyperparameters.epochs
        * 0.05  # 3 minutes per epoch baseline
        * (
            1.5 if request.model.value in ["yolov8l", "yolov8x"] else 1.0
        )  # Larger models take longer
        * (1.2 if request.techniques else 1.0)  # Techniques add overhead
    )

    return TrainingJobResponse(
        job_id=job_id,
        ray_job_id=ray_job_id,
        name=request.name,
        status="PENDING",
        created_at=job_record.created_at,
        estimated_duration_hours=estimated_duration,
        mlflow_experiment=request.mlflow_experiment or "training-jobs",
        message=f"Training job submitted successfully. Job ID: {job_id}",
    )


@router.get("/jobs/{job_id}", response_model=TrainingJobStatus)
async def get_training_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get training job status and metrics"""

    # Get job from database
    job = db.query(JobModel).filter(JobModel.job_id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Check ownership (admins can see all jobs)
    if current_user.role != "admin" and str(job.user_id) != str(current_user.user_id):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this job"
        )

    # Get Ray job status
    try:
        ray_status = job_client.get_job_status(job.ray_job_id)
        ray_info = job_client.get_job_info(job.ray_job_id)
    except Exception as e:
        ray_status = JobStatus.FAILED
        ray_info = None

    # Calculate duration
    duration_seconds = None
    if job.started_at and job.ended_at:
        duration_seconds = (job.ended_at - job.started_at).total_seconds()
    elif job.started_at:
        duration_seconds = (datetime.utcnow() - job.started_at).total_seconds()

    # Extract progress from metadata (updated by callbacks)
    current_epoch = job.metadata.get("current_epoch")
    total_epochs = job.metadata.get("hyperparameters", {}).get("epochs")
    progress_percent = None
    if current_epoch is not None and total_epochs:
        progress_percent = (current_epoch / total_epochs) * 100

    return TrainingJobStatus(
        job_id=job.job_id,
        ray_job_id=job.ray_job_id,
        name=job.name,
        status=str(ray_status),
        created_at=job.created_at,
        started_at=job.started_at,
        ended_at=job.ended_at,
        duration_seconds=duration_seconds,
        current_epoch=current_epoch,
        total_epochs=total_epochs,
        progress_percent=progress_percent,
        latest_metrics=job.metadata.get("latest_metrics"),
        mlflow_run_id=job.metadata.get("mlflow_run_id"),
        mlflow_experiment=job.metadata.get("mlflow_experiment"),
        gpu_hours_used=job.gpu_time_seconds / 3600 if job.gpu_time_seconds else None,
        cpu_hours_used=job.cpu_time_seconds / 3600 if job.cpu_time_seconds else None,
        error=job.error_message,
    )


@router.get("/jobs/{job_id}/logs")
async def get_training_job_logs(
    job_id: str,
    tail: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get training job logs (streamed)"""

    # Get job and check ownership
    job = db.query(JobModel).filter(JobModel.job_id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if current_user.role != "admin" and str(job.user_id) != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Get logs from Ray
    try:
        logs = job_client.get_job_logs(job.ray_job_id)

        # Return last N lines
        log_lines = logs.split("\n")
        if tail:
            log_lines = log_lines[-tail:]

        return {"job_id": job_id, "lines": len(log_lines), "logs": "\n".join(log_lines)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve logs: {str(e)}"
        )


@router.delete("/jobs/{job_id}")
async def cancel_training_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a running training job"""

    # Get job and check ownership
    job = db.query(JobModel).filter(JobModel.job_id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if current_user.role != "admin" and str(job.user_id) != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Cancel job in Ray
    try:
        success = job_client.stop_job(job.ray_job_id)

        if success:
            # Update database
            job.status = "CANCELLED"
            job.ended_at = datetime.utcnow()
            db.commit()

            # Log audit event
            await log_audit_event(
                db=db,
                user_id=current_user.user_id,
                action="training_job_cancel",
                resource_type="training_job",
                resource_id=job_id,
                details={"ray_job_id": job.ray_job_id},
            )

            return {
                "job_id": job_id,
                "status": "CANCELLED",
                "message": "Job cancelled successfully",
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to cancel job")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")


@router.get("/models")
async def list_available_models():
    """List available model architectures"""
    return {
        "models": [
            {
                "name": model.value,
                "display_name": model.value.upper(),
                "size": {
                    "yolov8n": "Small (3M params)",
                    "yolov8s": "Small (11M params)",
                    "yolov8m": "Medium (25M params)",
                    "yolov8l": "Large (43M params)",
                    "yolov8x": "Extra Large (68M params)",
                }[model.value],
                "recommended_batch_size": {
                    "yolov8n": 32,
                    "yolov8s": 24,
                    "yolov8m": 16,
                    "yolov8l": 12,
                    "yolov8x": 8,
                }[model.value],
            }
            for model in ModelArchitecture
        ]
    }


@router.get("/techniques")
async def list_available_techniques(
    current_user: User = Depends(get_current_user),
):
    """List available proprietary techniques based on user tier"""

    # Free tier sees techniques but can't use them
    base_techniques = [
        {
            "name": "sapo",
            "display_name": "SAPO (Self-Adaptive Preference Optimization)",
            "description": "Dynamic learning rate adaptation for 15-20% faster convergence",
            "performance_gain": "15-20% faster convergence, 3-5% better metrics",
            "tier_required": "Pro",
            "available": current_user.role in ["premium", "admin"],
        },
        {
            "name": "advantage_filter",
            "display_name": "Advantage Filter",
            "description": "Skip batches with zero training signal for 20-40% compute savings",
            "performance_gain": "20-40% compute savings",
            "tier_required": "Pro",
            "available": current_user.role in ["premium", "admin"],
        },
        {
            "name": "curriculum_learning",
            "display_name": "Curriculum Learning",
            "description": "Progressive difficulty training for 20-30% faster convergence",
            "performance_gain": "20-30% faster convergence, 2-5% better metrics",
            "tier_required": "Pro",
            "available": current_user.role in ["premium", "admin"],
        },
    ]

    return {
        "user_tier": current_user.role,
        "techniques": base_techniques,
        "message": (
            "Upgrade to Pro for access to proprietary techniques"
            if current_user.role == "user"
            else None
        ),
    }


@router.get("/quota")
async def get_quota_status(
    period: str = "day",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get current quota usage and remaining allocation

    Query params:
        period: "day" or "month"
    """
    if period not in ["day", "month"]:
        raise HTTPException(status_code=400, detail="Period must be 'day' or 'month'")

    # Get user quota
    quota = (
        db.query(UserQuota).filter(UserQuota.user_id == current_user.user_id).first()
    )
    if not quota:
        raise HTTPException(status_code=404, detail="User quota not found")

    # Get remaining quota
    remaining = get_user_quota_remaining(current_user, quota, db, period=period)

    # Get tier limits
    tier_limits = get_tier_limits(current_user.role)

    return {
        "user": {
            "username": current_user.username,
            "tier": current_user.role,
            "tier_name": tier_limits["name"],
        },
        "period": period,
        "gpu": {
            "used": float(remaining["gpu_hours_used"]),
            "limit": float(remaining["gpu_hours_limit"]),
            "remaining": float(remaining["gpu_hours_remaining"]),
            "unit": "hours",
        },
        "cpu": {
            "used": float(remaining["cpu_hours_used"]),
            "limit": float(remaining["cpu_hours_limit"]),
            "remaining": float(remaining["cpu_hours_remaining"]),
            "unit": "hours",
        },
        "concurrent_jobs": {
            "current": remaining["concurrent_jobs"],
            "limit": remaining["concurrent_jobs_limit"],
        },
        "percent_used": remaining["percent_used"],
        "upgrade_url": (
            "https://shml.ai/pricing" if current_user.role == "user" else None
        ),
    }


@router.get("/tiers")
async def list_tiers():
    """List available subscription tiers and limits"""

    tiers = []
    for role, limits in [("user", "user"), ("premium", "premium"), ("admin", "admin")]:
        tier_info = get_tier_limits(limits)
        tiers.append(
            {
                "tier": role,
                "name": tier_info["name"],
                "pricing": {
                    "user": "Free",
                    "premium": "$29/month",
                    "admin": "$499/month (Enterprise)",
                }[role],
                "limits": {
                    "gpu_hours_per_day": tier_info["max_gpu_hours_per_day"],
                    "cpu_hours_per_day": tier_info["max_cpu_hours_per_day"],
                    "concurrent_jobs": tier_info["max_concurrent_jobs"],
                    "max_gpu_fraction": tier_info["max_gpu_fraction"],
                    "max_timeout_hours": tier_info["max_job_timeout_hours"],
                },
                "features": {
                    "proprietary_techniques": tier_info["techniques_allowed"],
                    "custom_docker": tier_info["can_use_custom_docker"],
                    "priority_weight": tier_info["priority_weight"],
                },
            }
        )

    return {
        "tiers": tiers,
        "signup_url": "https://shml.ai/signup",
        "comparison_url": "https://shml.ai/pricing",
    }


@router.get("/queue")
async def get_queue_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get queue overview with stats and GPU allocation
    Admins see full details, users see their own jobs only
    """
    scheduler = TrainingScheduler(db)
    overview = scheduler.get_queue_overview()

    # If not admin, filter to user's jobs only
    if current_user.role != "admin":
        # Get user's jobs in queue
        user_jobs = (
            db.query(JobModel)
            .filter(
                JobModel.user_id == current_user.user_id,
                JobModel.status.in_(["PENDING", "RUNNING"]),
            )
            .all()
        )

        user_job_ids = [job.job_id for job in user_jobs]

        # Filter GPU status to user's jobs
        if "gpu" in overview and "rtx3090" in overview["gpu"]:
            rtx3090 = overview["gpu"]["rtx3090"]
            rtx3090["jobs"] = {
                job_id: fraction
                for job_id, fraction in rtx3090.get("jobs", {}).items()
                if job_id in user_job_ids
            }

        overview["user_filter"] = current_user.username

    return overview


@router.get("/queue/{job_id}")
async def get_job_queue_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get queue status for a specific job
    Includes position, estimated start time, and priority
    """
    # Check job ownership
    job = db.query(JobModel).filter(JobModel.job_id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if current_user.role != "admin" and str(job.user_id) != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Get queue status
    scheduler = TrainingScheduler(db)
    status = scheduler.get_job_status(job_id)

    return status
