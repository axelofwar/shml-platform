"""
Enhanced Ray Job Orchestration API Server
Remote job submission with automatic artifact cleanup
Artifacts are returned to client and deleted from server after job completion
"""

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    Security,
    Depends,
)
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
import secrets
import hashlib
import ray
from ray.job_submission import JobSubmissionClient, JobStatus
import asyncio
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
import psutil
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="MLflow Compute API - Remote Edition",
    description="Job orchestration API with remote artifact management",
    version="2.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "http://127.0.0.1:8265")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:8080")
JOB_WORKSPACE = os.getenv("JOB_WORKSPACE", "/opt/ray/job_workspaces")
ARTIFACT_RETENTION_HOURS = int(os.getenv("ARTIFACT_RETENTION_HOURS", "24"))
API_KEY_ENABLED = os.getenv("API_KEY_ENABLED", "false").lower() == "true"
# SECURITY: API secret key must be set via environment variable when API key auth is enabled
# Generate with: openssl rand -base64 50
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
if API_KEY_ENABLED and not API_SECRET_KEY:
    raise ValueError(
        "API_SECRET_KEY environment variable must be set when API_KEY_ENABLED=true"
    )

# API Key Security (SOTA: stateless, fast, simple)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key(api_key: str = Security(api_key_header)) -> str:
    """Validate API key if authentication is enabled"""
    if not API_KEY_ENABLED:
        return "no-auth"  # Auth disabled for local/trusted networks

    if not api_key:
        raise HTTPException(
            status_code=401, detail="API key required. Include 'X-API-Key' header."
        )

    # Validate API key (in production, check against database)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    expected_hash = hashlib.sha256(API_SECRET_KEY.encode()).hexdigest()

    if key_hash != expected_hash:
        logger.warning(f"Invalid API key attempt")
        raise HTTPException(status_code=403, detail="Invalid API key")

    return api_key


# Initialize Ray client
job_client = JobSubmissionClient(RAY_ADDRESS)

# Job storage (in production, use a database)
job_store: Dict[str, Dict[str, Any]] = {}

# Create workspace directory
os.makedirs(JOB_WORKSPACE, exist_ok=True)


class JobType(str, Enum):
    TRAINING = "training"
    INFERENCE = "inference"
    BENCHMARKING = "benchmarking"
    EVALUATION = "evaluation"
    DATASET_CURATION = "dataset_curation"
    PIPELINE = "pipeline"
    CUSTOM = "custom"


class ResourceRequirements(BaseModel):
    cpu: int = Field(default=4, ge=1, le=20, description="Number of CPU cores")
    memory_gb: int = Field(default=8, ge=1, le=12, description="Memory in GB")
    gpu: int = Field(default=0, ge=0, le=1, description="Number of GPUs (0 or 1)")
    timeout_minutes: int = Field(
        default=120, ge=1, le=1440, description="Job timeout in minutes"
    )


class JobSubmission(BaseModel):
    name: str = Field(..., description="Job name")
    job_type: JobType = Field(..., description="Type of job")
    code: str = Field(..., description="Python code to execute")
    requirements: ResourceRequirements = Field(default_factory=ResourceRequirements)
    mlflow_experiment: Optional[str] = Field(None, description="MLflow experiment name")
    mlflow_tags: Optional[Dict[str, str]] = Field(default_factory=dict)
    env_vars: Optional[Dict[str, str]] = Field(default_factory=dict)
    return_artifacts: bool = Field(
        default=True, description="Return artifacts to client"
    )
    cleanup_after: bool = Field(
        default=True, description="Delete artifacts after retrieval"
    )


class JobInfo(BaseModel):
    job_id: str
    name: str
    job_type: JobType
    status: str
    created_at: str
    started_at: Optional[str]
    ended_at: Optional[str]
    resources: ResourceRequirements
    mlflow_run_id: Optional[str] = None
    artifact_path: Optional[str] = None
    artifacts_ready: bool = False
    error: Optional[str] = None


def get_job_workspace(job_id: str) -> Path:
    """Get workspace directory for a specific job"""
    workspace = Path(JOB_WORKSPACE) / job_id
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


async def cleanup_job_artifacts(job_id: str):
    """Clean up job artifacts after retrieval"""
    try:
        workspace = Path(JOB_WORKSPACE) / job_id
        if workspace.exists():
            shutil.rmtree(workspace)
            logger.info(f"Cleaned up artifacts for job {job_id}")
    except Exception as e:
        logger.error(f"Failed to cleanup artifacts for job {job_id}: {e}")


@app.on_event("startup")
async def startup_event():
    """Initialize Ray connection on startup"""
    try:
        # Connect to Ray cluster using the existing head node
        # The Ray Job Submission Client handles the connection via HTTP
        logger.info(f"Ray Job Submission Client configured for: {RAY_ADDRESS}")
        logger.info("Connected to Ray cluster via Job Submission API")
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        raise


@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "service": "MLflow Compute API - Remote Edition",
        "version": "2.0.0",
        "features": [
            "Remote job submission",
            "Automatic artifact cleanup",
            "MLflow integration",
            "GPU scheduling",
        ],
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Check Ray cluster via Job Submission API
    try:
        jobs = job_client.list_jobs()
        ray_status = "healthy"
    except Exception as e:
        ray_status = f"unhealthy: {str(e)}"

    # Check MLflow connectivity
    import requests

    try:
        resp = requests.get(f"{MLFLOW_TRACKING_URI}/health", timeout=2)
        mlflow_status = "healthy" if resp.status_code == 200 else "unhealthy"
    except:
        mlflow_status = "unreachable"

    return {
        "status": "healthy" if ray_status == "healthy" else "degraded",
        "ray": ray_status,
        "mlflow": mlflow_status,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/resources")
async def get_resources():
    """Get available cluster resources"""
    try:
        # Get system resources
        import requests

        # Try to get Ray cluster info from dashboard
        cluster_info = {}
        try:
            resp = requests.get(f"{RAY_ADDRESS}/api/cluster_status", timeout=5)
            if resp.status_code == 200:
                cluster_info = resp.json()
        except:
            pass

        # Get GPU info
        gpu_info = []
        try:
            import GPUtil

            gpus = GPUtil.getGPUs()
            for gpu in gpus:
                gpu_info.append(
                    {
                        "id": gpu.id,
                        "name": gpu.name,
                        "memory_total_mb": gpu.memoryTotal,
                        "memory_used_mb": gpu.memoryUsed,
                        "memory_free_mb": gpu.memoryFree,
                        "gpu_utilization": gpu.load * 100,
                        "temperature": gpu.temperature,
                    }
                )
        except:
            gpu_info = []

        return {
            "cluster_info": cluster_info,
            "system": {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent,
            },
            "gpus": gpu_info,
            "note": "Resource details available via Ray Dashboard API",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get resources: {str(e)}"
        )


@app.post("/jobs/submit", response_model=JobInfo)
async def submit_job(
    job: JobSubmission,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    """Submit a new job to the cluster (requires API key if auth enabled)"""
    try:
        # Note: Resource validation is handled by Ray scheduler
        # Pre-validation could be added by querying Ray dashboard API if needed

        # Create job workspace
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.urandom(4).hex()}"
        workspace = get_job_workspace(job_id)
        output_dir = workspace / "outputs"
        output_dir.mkdir(exist_ok=True)

        # Create job script with artifact collection
        job_script = f"""
import os
import sys
import shutil
import mlflow
import ray
from pathlib import Path

# Set MLflow tracking URI
mlflow.set_tracking_uri("{MLFLOW_TRACKING_URI}")

# Set experiment
experiment_name = {repr(job.mlflow_experiment or "remote-jobs")}
mlflow.set_experiment(experiment_name)

# Job workspace
workspace = Path({repr(str(workspace))})
output_dir = workspace / "outputs"
output_dir.mkdir(exist_ok=True)

# Start MLflow run
with mlflow.start_run(run_name={repr(job.name)}) as run:
    # Log job metadata
    mlflow.set_tags({repr({{**job.mlflow_tags, "job_id": job_id, "remote_job": "true"}})})
    mlflow.log_param("job_type", {repr(job.job_type.value)})
    mlflow.log_param("cpu", {job.requirements.cpu})
    mlflow.log_param("memory_gb", {job.requirements.memory_gb})
    mlflow.log_param("gpu", {job.requirements.gpu})

    # Set environment variables
    for key, value in {repr(job.env_vars)}.items():
        os.environ[key] = value

    # Make output directory available to user code
    os.environ["JOB_OUTPUT_DIR"] = str(output_dir)
    os.environ["MLFLOW_RUN_ID"] = run.info.run_id

    try:
        # Execute user code
        {job.code}

        print(f"\\nMLflow Run ID: {{run.info.run_id}}")
        print(f"Job Output Directory: {{output_dir}}")

        # Save run ID to workspace
        with open(workspace / "mlflow_run_id.txt", "w") as f:
            f.write(run.info.run_id)

    except Exception as e:
        mlflow.log_param("error", str(e))
        raise
"""

        # Submit job to Ray
        runtime_env = {
            "pip": [
                "torch",
                "ultralytics",
                "mlflow",
                "scikit-learn",
                "pandas",
                "opencv-python-headless",
                "requests",
            ],
            "env_vars": {
                "MLFLOW_TRACKING_URI": MLFLOW_TRACKING_URI,
                "JOB_WORKSPACE": str(workspace),
                **job.env_vars,
            },
            "working_dir": str(workspace),
        }

        ray_job_id = job_client.submit_job(
            entrypoint=f"python -c {repr(job_script)}",
            runtime_env=runtime_env,
            metadata={
                "name": job.name,
                "job_type": job.job_type.value,
                "created_at": datetime.now().isoformat(),
                "job_id": job_id,
            },
        )

        # Store job info
        job_info = {
            "job_id": job_id,
            "ray_job_id": ray_job_id,
            "name": job.name,
            "job_type": job.job_type,
            "status": "PENDING",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "ended_at": None,
            "resources": job.requirements,
            "mlflow_run_id": None,
            "artifact_path": str(workspace),
            "artifacts_ready": False,
            "cleanup_after": job.cleanup_after,
            "error": None,
        }
        job_store[job_id] = job_info

        # Schedule cleanup if requested
        if job.cleanup_after:
            background_tasks.add_task(
                schedule_cleanup, job_id, delay_hours=ARTIFACT_RETENTION_HOURS
            )

        logger.info(f"Job submitted: {job_id} (Ray: {ray_job_id})")

        return JobInfo(
            **{
                k: v
                for k, v in job_info.items()
                if k != "ray_job_id" and k != "cleanup_after"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit job: {e}")
        raise HTTPException(status_code=500, detail=f"Job submission failed: {str(e)}")


async def schedule_cleanup(job_id: str, delay_hours: int):
    """Schedule artifact cleanup after delay"""
    await asyncio.sleep(delay_hours * 3600)
    await cleanup_job_artifacts(job_id)


@app.get("/jobs", response_model=List[JobInfo])
async def list_jobs(
    status: Optional[str] = None, job_type: Optional[JobType] = None, limit: int = 100
):
    """List all jobs with optional filtering"""
    try:
        jobs = []
        for job_id, job_data in job_store.items():
            # Get current status from Ray
            try:
                ray_job_id = job_data.get("ray_job_id")
                if ray_job_id:
                    ray_status = job_client.get_job_status(ray_job_id)
                    job_data["status"] = ray_status.value

                    # Check if artifacts are ready
                    if ray_status in [
                        JobStatus.SUCCEEDED,
                        JobStatus.FAILED,
                        JobStatus.STOPPED,
                    ]:
                        workspace = Path(job_data["artifact_path"])
                        if (workspace / "mlflow_run_id.txt").exists():
                            with open(workspace / "mlflow_run_id.txt") as f:
                                job_data["mlflow_run_id"] = f.read().strip()
                        job_data["artifacts_ready"] = True
            except:
                pass

            # Apply filters
            if status and job_data["status"] != status:
                continue
            if job_type and job_data["job_type"] != job_type:
                continue

            jobs.append(
                JobInfo(
                    **{
                        k: v
                        for k, v in job_data.items()
                        if k not in ["ray_job_id", "cleanup_after"]
                    }
                )
            )

        return jobs[:limit]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


@app.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str):
    """Get detailed information about a specific job"""
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = job_store[job_id]

    # Update status from Ray
    try:
        ray_job_id = job_data.get("ray_job_id")
        if ray_job_id:
            status = job_client.get_job_status(ray_job_id)
            info = job_client.get_job_info(ray_job_id)

            job_data["status"] = status.value
            if info.start_time:
                job_data["started_at"] = datetime.fromtimestamp(
                    info.start_time / 1000
                ).isoformat()
            if info.end_time:
                job_data["ended_at"] = datetime.fromtimestamp(
                    info.end_time / 1000
                ).isoformat()
            if info.message:
                job_data["error"] = info.message

            # Check if artifacts are ready
            if status in [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.STOPPED]:
                workspace = Path(job_data["artifact_path"])
                if (workspace / "mlflow_run_id.txt").exists():
                    with open(workspace / "mlflow_run_id.txt") as f:
                        job_data["mlflow_run_id"] = f.read().strip()
                job_data["artifacts_ready"] = True
    except Exception as e:
        logger.error(f"Failed to update job status: {e}")

    return JobInfo(
        **{
            k: v
            for k, v in job_data.items()
            if k not in ["ray_job_id", "cleanup_after"]
        }
    )


@app.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str):
    """Get logs for a specific job"""
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        ray_job_id = job_store[job_id].get("ray_job_id")
        if not ray_job_id:
            raise HTTPException(status_code=404, detail="Ray job ID not found")

        logs = job_client.get_job_logs(ray_job_id)
        return {"job_id": job_id, "logs": logs}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Logs not found: {str(e)}")


@app.get("/jobs/{job_id}/artifacts/download")
async def download_job_artifacts(job_id: str, background_tasks: BackgroundTasks):
    """Download all job artifacts as a zip file"""
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = job_store[job_id]

    if not job_data.get("artifacts_ready"):
        raise HTTPException(status_code=400, detail="Job artifacts not ready yet")

    workspace = Path(job_data["artifact_path"])
    output_dir = workspace / "outputs"

    if not output_dir.exists() or not any(output_dir.iterdir()):
        raise HTTPException(status_code=404, detail="No artifacts found")

    # Create zip file
    zip_path = workspace / f"{job_id}_artifacts.zip"

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in output_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(output_dir)
                    zipf.write(file_path, arcname)

        # Schedule cleanup after download if requested
        if job_data.get("cleanup_after", True):
            background_tasks.add_task(cleanup_job_artifacts, job_id)

        return FileResponse(
            path=str(zip_path),
            filename=f"{job_id}_artifacts.zip",
            media_type="application/zip",
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create artifact archive: {str(e)}"
        )


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running job"""
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        ray_job_id = job_store[job_id].get("ray_job_id")
        if not ray_job_id:
            raise HTTPException(status_code=404, detail="Ray job ID not found")

        job_client.stop_job(ray_job_id)

        job_store[job_id]["status"] = "STOPPED"
        job_store[job_id]["ended_at"] = datetime.now().isoformat()

        return {"job_id": job_id, "status": "cancelled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str, background_tasks: BackgroundTasks):
    """Delete a job and its artifacts"""
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        ray_job_id = job_store[job_id].get("ray_job_id")
        if ray_job_id:
            status = job_client.get_job_status(ray_job_id)
            if status not in [JobStatus.STOPPED, JobStatus.SUCCEEDED, JobStatus.FAILED]:
                raise HTTPException(
                    status_code=400, detail="Job must be stopped before deletion"
                )

            job_client.delete_job(ray_job_id)

        # Schedule artifact cleanup
        background_tasks.add_task(cleanup_job_artifacts, job_id)

        del job_store[job_id]

        return {"job_id": job_id, "status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete job: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8266, log_level="info")
