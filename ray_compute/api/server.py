"""
Ray Job Orchestration API Server
FastAPI-based REST API for job submission, monitoring, and management
Integrated with MLflow for experiment tracking
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
import ray
from ray.job_submission import JobSubmissionClient, JobStatus
import asyncio
import json
import os
import uuid
import time
from datetime import datetime
import psutil
import GPUtil
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="MLflow Compute API",
    description="Job orchestration API for ML training and inference",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Ray client
RAY_ADDRESS = "http://127.0.0.1:8265"
job_client = JobSubmissionClient(RAY_ADDRESS)

# Job storage (in production, use a database)
job_store: Dict[str, Dict[str, Any]] = {}


class JobType(str, Enum):
    TRAINING = "training"
    INFERENCE = "inference"
    DATASET_CURATION = "dataset_curation"
    PIPELINE = "pipeline"
    CUSTOM = "custom"


class ResourceRequirements(BaseModel):
    cpu: int = Field(default=4, ge=1, le=24, description="Number of CPU cores")
    memory_gb: int = Field(default=8, ge=1, le=16, description="Memory in GB")
    gpu: int = Field(default=0, ge=0, le=1, description="Number of GPUs (0 or 1)")
    timeout_minutes: int = Field(default=120, ge=1, le=1440, description="Job timeout in minutes")


class JobSubmission(BaseModel):
    name: str = Field(..., description="Job name")
    job_type: JobType = Field(..., description="Type of job")
    code: str = Field(..., description="Python code to execute")
    requirements: ResourceRequirements = Field(default_factory=ResourceRequirements)
    mlflow_experiment: Optional[str] = Field(None, description="MLflow experiment name")
    mlflow_tags: Optional[Dict[str, str]] = Field(default_factory=dict)
    env_vars: Optional[Dict[str, str]] = Field(default_factory=dict)
    arguments: Optional[Dict[str, Any]] = Field(default_factory=dict)


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
    error: Optional[str] = None


@app.on_event("startup")
async def startup_event():
    """Initialize Ray connection on startup"""
    try:
        ray.init(address="auto", ignore_reinit_error=True)
        logger.info("Connected to Ray cluster")
    except Exception as e:
        logger.error(f"Failed to connect to Ray: {e}")
        raise


@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "service": "MLflow Compute API",
        "version": "1.0.0",
        "status": "running",
        "ray_address": RAY_ADDRESS
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check Ray connection
        ray.cluster_resources()
        ray_status = "healthy"
    except Exception as e:
        ray_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy" if ray_status == "healthy" else "degraded",
        "ray": ray_status,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/resources")
async def get_resources():
    """Get available cluster resources"""
    try:
        cluster_resources = ray.cluster_resources()
        available_resources = ray.available_resources()
        
        # Get GPU info
        gpu_info = []
        try:
            gpus = GPUtil.getGPUs()
            for gpu in gpus:
                gpu_info.append({
                    "id": gpu.id,
                    "name": gpu.name,
                    "memory_total_mb": gpu.memoryTotal,
                    "memory_used_mb": gpu.memoryUsed,
                    "memory_free_mb": gpu.memoryFree,
                    "gpu_utilization": gpu.load * 100,
                    "temperature": gpu.temperature
                })
        except:
            gpu_info = []
        
        return {
            "cluster_total": {
                "cpu": cluster_resources.get("CPU", 0),
                "memory_bytes": cluster_resources.get("memory", 0),
                "gpu": cluster_resources.get("GPU", 0)
            },
            "available": {
                "cpu": available_resources.get("CPU", 0),
                "memory_bytes": available_resources.get("memory", 0),
                "gpu": available_resources.get("GPU", 0)
            },
            "system": {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent
            },
            "gpus": gpu_info
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get resources: {str(e)}")


@app.post("/jobs/submit", response_model=JobInfo)
async def submit_job(job: JobSubmission):
    """Submit a new job to the cluster"""
    try:
        # Validate resources are available
        available = ray.available_resources()
        
        if job.requirements.cpu > available.get("CPU", 0):
            raise HTTPException(
                status_code=503,
                detail=f"Insufficient CPU: requested {job.requirements.cpu}, available {available.get('CPU', 0)}"
            )
        
        if job.requirements.gpu > available.get("GPU", 0):
            raise HTTPException(
                status_code=503,
                detail=f"Insufficient GPU: requested {job.requirements.gpu}, available {available.get('GPU', 0)}"
            )
        
        # Create job script
        job_script = f"""
import os
import sys
import mlflow
import ray

# Set MLflow tracking URI
mlflow.set_tracking_uri("http://localhost:8080")

# Set experiment
experiment_name = {repr(job.mlflow_experiment or "ray-compute")}
mlflow.set_experiment(experiment_name)

# Start MLflow run
with mlflow.start_run(run_name={repr(job.name)}) as run:
    # Log job metadata
    mlflow.set_tags({repr(job.mlflow_tags)})
    mlflow.log_param("job_type", {repr(job.job_type.value)})
    mlflow.log_param("cpu", {job.requirements.cpu})
    mlflow.log_param("memory_gb", {job.requirements.memory_gb})
    mlflow.log_param("gpu", {job.requirements.gpu})
    
    # Set environment variables
    for key, value in {repr(job.env_vars)}.items():
        os.environ[key] = value
    
    # Execute user code
    {job.code}
    
    print(f"MLflow Run ID: {{run.info.run_id}}")
"""
        
        # Submit job to Ray
        runtime_env = {
            "pip": [
                "torch",
                "ultralytics",
                "mlflow",
                "scikit-learn",
                "pandas",
                "opencv-python-headless"
            ],
            "env_vars": {
                "MLFLOW_TRACKING_URI": "http://localhost:8080",
                **job.env_vars
            }
        }
        
        job_id = job_client.submit_job(
            entrypoint=f"python -c {repr(job_script)}",
            runtime_env=runtime_env,
            metadata={
                "name": job.name,
                "job_type": job.job_type.value,
                "created_at": datetime.now().isoformat()
            }
        )
        
        # Store job info
        job_info = {
            "job_id": job_id,
            "name": job.name,
            "job_type": job.job_type,
            "status": "PENDING",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "ended_at": None,
            "resources": job.requirements,
            "mlflow_run_id": None,
            "error": None
        }
        job_store[job_id] = job_info
        
        logger.info(f"Job submitted: {job_id} ({job.name})")
        
        return JobInfo(**job_info)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit job: {e}")
        raise HTTPException(status_code=500, detail=f"Job submission failed: {str(e)}")


@app.get("/jobs", response_model=List[JobInfo])
async def list_jobs(
    status: Optional[str] = None,
    job_type: Optional[JobType] = None,
    limit: int = 100
):
    """List all jobs with optional filtering"""
    try:
        jobs = []
        for job_id, job_data in job_store.items():
            # Get current status from Ray
            try:
                ray_status = job_client.get_job_status(job_id)
                job_data["status"] = ray_status.value
            except:
                pass
            
            # Apply filters
            if status and job_data["status"] != status:
                continue
            if job_type and job_data["job_type"] != job_type:
                continue
            
            jobs.append(JobInfo(**job_data))
        
        return jobs[:limit]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


@app.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str):
    """Get detailed information about a specific job"""
    try:
        # Get job from Ray
        status = job_client.get_job_status(job_id)
        info = job_client.get_job_info(job_id)
        
        # Update stored info
        if job_id in job_store:
            job_store[job_id]["status"] = status.value
            if info.start_time:
                job_store[job_id]["started_at"] = datetime.fromtimestamp(info.start_time / 1000).isoformat()
            if info.end_time:
                job_store[job_id]["ended_at"] = datetime.fromtimestamp(info.end_time / 1000).isoformat()
            if info.message:
                job_store[job_id]["error"] = info.message
            
            return JobInfo(**job_store[job_id])
        else:
            # Job not in store, create basic info
            return JobInfo(
                job_id=job_id,
                name=info.metadata.get("name", "Unknown"),
                job_type=JobType(info.metadata.get("job_type", "custom")),
                status=status.value,
                created_at=datetime.fromtimestamp(info.start_time / 1000).isoformat() if info.start_time else datetime.now().isoformat(),
                started_at=datetime.fromtimestamp(info.start_time / 1000).isoformat() if info.start_time else None,
                ended_at=datetime.fromtimestamp(info.end_time / 1000).isoformat() if info.end_time else None,
                resources=ResourceRequirements(),
                error=info.message
            )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Job not found: {str(e)}")


@app.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str):
    """Get logs for a specific job"""
    try:
        logs = job_client.get_job_logs(job_id)
        return {"job_id": job_id, "logs": logs}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Logs not found: {str(e)}")


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running job"""
    try:
        job_client.stop_job(job_id)
        
        if job_id in job_store:
            job_store[job_id]["status"] = "STOPPED"
            job_store[job_id]["ended_at"] = datetime.now().isoformat()
        
        return {"job_id": job_id, "status": "cancelled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job (must be stopped first)"""
    try:
        status = job_client.get_job_status(job_id)
        if status not in [JobStatus.STOPPED, JobStatus.SUCCEEDED, JobStatus.FAILED]:
            raise HTTPException(
                status_code=400,
                detail="Job must be stopped before deletion"
            )
        
        job_client.delete_job(job_id)
        if job_id in job_store:
            del job_store[job_id]
        
        return {"job_id": job_id, "status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete job: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8266,
        log_level="info"
    )
