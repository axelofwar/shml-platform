"""
Nemotron Lifecycle Manager - GPU Yield API for Training Integration

Provides API endpoints that Ray training jobs can call to request GPU resources.
Manages the nemotron-coding container lifecycle (stop/start) to yield/reclaim GPU.

Endpoints:
- POST /training/start - Stop Nemotron to free RTX 3090 Ti for training
- POST /training/end - Restart Nemotron after training completes
- GET /health - Manager health with Nemotron container status
- GET /status - Detailed status of Nemotron and GPU

This service runs on the host network to access Docker socket.
"""

import os
import asyncio
import subprocess
import logging
from datetime import datetime
from typing import Optional, Dict, Any

import docker
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
NEMOTRON_CONTAINER = os.getenv("NEMOTRON_CONTAINER", "nemotron-coding")
GPU_INDEX = int(os.getenv("GPU_INDEX", "0"))  # RTX 3090 Ti
YIELD_WAIT_SECONDS = int(os.getenv("YIELD_WAIT_SECONDS", "5"))

app = FastAPI(
    title="Nemotron Manager",
    description="Lifecycle manager for Nemotron-3 coding model - enables GPU yield for training",
    version="1.0.0",
)

# Docker client (lazy init)
_docker_client = None


def get_docker_client():
    """Get or create Docker client."""
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


# Request/Response models
class TrainingStartRequest(BaseModel):
    """Request to start training (yield GPU)."""

    job_id: str = "unknown"
    gpus: list[int] = [0]
    priority: int = 10
    wait_for_yield: bool = True
    timeout_seconds: int = 30
    metadata: Dict[str, Any] = {}


class TrainingStartResponse(BaseModel):
    """Response from training start (yield) request."""

    status: str  # "ready", "timeout", "error"
    model_yielded: bool
    job_id: str
    message: Optional[str] = None
    gpu_memory_before_mb: Optional[int] = None
    gpu_memory_after_mb: Optional[int] = None
    timestamp: str


class TrainingEndRequest(BaseModel):
    """Request to end training (reclaim GPU)."""

    job_id: str = "unknown"


class TrainingEndResponse(BaseModel):
    """Response from training end request."""

    status: str  # "started", "running", "error"
    job_id: str
    message: Optional[str] = None
    timestamp: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    nemotron_status: str
    manager_uptime_seconds: float


class StatusResponse(BaseModel):
    """Detailed status response."""

    nemotron_container: str
    nemotron_status: str
    nemotron_health: Optional[str]
    gpu_index: int
    gpu_memory_used_mb: Optional[int]
    gpu_memory_total_mb: Optional[int]
    gpu_utilization_percent: Optional[int]
    training_active: bool
    timestamp: str


# Track manager start time
_start_time = datetime.now()


def get_gpu_memory(gpu_index: int = 0) -> Dict[str, Any]:
    """Get GPU memory usage via nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
                "-i",
                str(gpu_index),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            return {
                "memory_used_mb": int(parts[0].strip()),
                "memory_total_mb": int(parts[1].strip()),
                "utilization_percent": int(parts[2].strip()),
            }
    except Exception as e:
        logger.error(f"Failed to get GPU memory: {e}")
    return {}


def check_training_active(gpu_index: int = 0) -> bool:
    """Check if training is active on GPU by looking for training processes."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
                "-i",
                str(gpu_index),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            training_keywords = ["python", "ray", "yolo", "train", "torch"]
            for line in output.split("\n"):
                for kw in training_keywords:
                    if kw in line.lower():
                        return True
    except Exception as e:
        logger.error(f"Failed to check training status: {e}")
    return False


@app.post("/training/start", response_model=TrainingStartResponse)
async def start_training(request: TrainingStartRequest):
    """
    Stop Nemotron to free GPU for training.

    Called by Ray training jobs before GPU allocation.
    Blocks until GPU memory is freed or timeout.
    """
    logger.info(f"Training start requested by job: {request.job_id}")

    # Get GPU memory before
    gpu_before = get_gpu_memory(GPU_INDEX)
    memory_before = gpu_before.get("memory_used_mb")

    client = get_docker_client()

    try:
        container = client.containers.get(NEMOTRON_CONTAINER)

        if container.status == "running":
            logger.info(f"Stopping {NEMOTRON_CONTAINER}...")
            container.stop(timeout=30)

            # Wait for GPU memory to be freed
            if request.wait_for_yield:
                for _ in range(request.timeout_seconds):
                    await asyncio.sleep(1)
                    gpu_after = get_gpu_memory(GPU_INDEX)
                    memory_after = gpu_after.get("memory_used_mb", memory_before)

                    # Check if significant memory was freed (>10GB)
                    if memory_before and memory_after < memory_before - 10000:
                        logger.info(
                            f"GPU memory freed: {memory_before}MB → {memory_after}MB"
                        )
                        return TrainingStartResponse(
                            status="ready",
                            model_yielded=True,
                            job_id=request.job_id,
                            message=f"Nemotron stopped, {memory_before - memory_after}MB freed",
                            gpu_memory_before_mb=memory_before,
                            gpu_memory_after_mb=memory_after,
                            timestamp=datetime.now().isoformat(),
                        )

                # Timeout waiting for memory
                gpu_after = get_gpu_memory(GPU_INDEX)
                return TrainingStartResponse(
                    status="timeout",
                    model_yielded=True,
                    job_id=request.job_id,
                    message="Container stopped but GPU memory not fully freed",
                    gpu_memory_before_mb=memory_before,
                    gpu_memory_after_mb=gpu_after.get("memory_used_mb"),
                    timestamp=datetime.now().isoformat(),
                )

            # No wait requested
            await asyncio.sleep(YIELD_WAIT_SECONDS)
            gpu_after = get_gpu_memory(GPU_INDEX)
            return TrainingStartResponse(
                status="ready",
                model_yielded=True,
                job_id=request.job_id,
                message="Nemotron stopped",
                gpu_memory_before_mb=memory_before,
                gpu_memory_after_mb=gpu_after.get("memory_used_mb"),
                timestamp=datetime.now().isoformat(),
            )
        else:
            logger.info(
                f"{NEMOTRON_CONTAINER} already stopped (status: {container.status})"
            )
            gpu_after = get_gpu_memory(GPU_INDEX)
            return TrainingStartResponse(
                status="ready",
                model_yielded=False,
                job_id=request.job_id,
                message=f"Container already {container.status}",
                gpu_memory_before_mb=memory_before,
                gpu_memory_after_mb=gpu_after.get("memory_used_mb"),
                timestamp=datetime.now().isoformat(),
            )

    except docker.errors.NotFound:
        logger.warning(f"Container {NEMOTRON_CONTAINER} not found")
        gpu_after = get_gpu_memory(GPU_INDEX)
        return TrainingStartResponse(
            status="ready",
            model_yielded=False,
            job_id=request.job_id,
            message="Container not found (GPU already available)",
            gpu_memory_before_mb=memory_before,
            gpu_memory_after_mb=gpu_after.get("memory_used_mb"),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Failed to stop Nemotron: {e}")
        return TrainingStartResponse(
            status="error",
            model_yielded=False,
            job_id=request.job_id,
            message=str(e),
            gpu_memory_before_mb=memory_before,
            gpu_memory_after_mb=None,
            timestamp=datetime.now().isoformat(),
        )


@app.post("/training/end", response_model=TrainingEndResponse)
async def end_training(request: TrainingEndRequest):
    """
    Restart Nemotron after training completes.

    Called by Ray training jobs after completion to restore coding model.
    """
    logger.info(f"Training end requested by job: {request.job_id}")

    client = get_docker_client()

    try:
        container = client.containers.get(NEMOTRON_CONTAINER)

        if container.status != "running":
            logger.info(f"Starting {NEMOTRON_CONTAINER}...")
            container.start()

            # Wait for health check
            for _ in range(60):  # 60 second timeout
                await asyncio.sleep(1)
                container.reload()
                if container.status == "running":
                    # Check health
                    health = (
                        container.attrs.get("State", {}).get("Health", {}).get("Status")
                    )
                    if health == "healthy":
                        logger.info(f"{NEMOTRON_CONTAINER} is healthy")
                        return TrainingEndResponse(
                            status="started",
                            job_id=request.job_id,
                            message="Nemotron restarted and healthy",
                            timestamp=datetime.now().isoformat(),
                        )

            return TrainingEndResponse(
                status="started",
                job_id=request.job_id,
                message="Container started but health check pending",
                timestamp=datetime.now().isoformat(),
            )
        else:
            return TrainingEndResponse(
                status="running",
                job_id=request.job_id,
                message="Container already running",
                timestamp=datetime.now().isoformat(),
            )

    except docker.errors.NotFound:
        return TrainingEndResponse(
            status="error",
            job_id=request.job_id,
            message=f"Container {NEMOTRON_CONTAINER} not found",
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Failed to restart Nemotron: {e}")
        return TrainingEndResponse(
            status="error",
            job_id=request.job_id,
            message=str(e),
            timestamp=datetime.now().isoformat(),
        )


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check with Nemotron container status."""
    client = get_docker_client()

    try:
        container = client.containers.get(NEMOTRON_CONTAINER)
        nemotron_status = container.status
    except docker.errors.NotFound:
        nemotron_status = "not_found"
    except Exception as e:
        nemotron_status = f"error: {e}"

    uptime = (datetime.now() - _start_time).total_seconds()

    return HealthResponse(
        status="healthy",
        nemotron_status=nemotron_status,
        manager_uptime_seconds=uptime,
    )


@app.get("/status", response_model=StatusResponse)
async def status():
    """Detailed status of Nemotron and GPU."""
    client = get_docker_client()

    try:
        container = client.containers.get(NEMOTRON_CONTAINER)
        nemotron_status = container.status
        health = container.attrs.get("State", {}).get("Health", {}).get("Status")
    except docker.errors.NotFound:
        nemotron_status = "not_found"
        health = None
    except Exception:
        nemotron_status = "error"
        health = None

    gpu_info = get_gpu_memory(GPU_INDEX)
    training_active = check_training_active(GPU_INDEX)

    return StatusResponse(
        nemotron_container=NEMOTRON_CONTAINER,
        nemotron_status=nemotron_status,
        nemotron_health=health,
        gpu_index=GPU_INDEX,
        gpu_memory_used_mb=gpu_info.get("memory_used_mb"),
        gpu_memory_total_mb=gpu_info.get("memory_total_mb"),
        gpu_utilization_percent=gpu_info.get("utilization_percent"),
        training_active=training_active,
        timestamp=datetime.now().isoformat(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
