"""
Qwen Manager - GPU Yield Lifecycle API

Manages the qwen-coding container lifecycle (stop/start) so Ray training jobs
can reclaim the RTX 3090 Ti VRAM (~19.7 GB) when needed.

Endpoints:
- POST /training/start  Stop qwen-coding to free GPU for training
- POST /training/end    Restart qwen-coding after training completes
- GET  /health          Manager liveness + container status
- GET  /status          Detailed GPU + container status (used by model_router.py)
"""

import os
import asyncio
import subprocess
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

import docker
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
QWEN_CONTAINER = os.getenv("QWEN_CONTAINER", "qwen-coding")
GPU_INDEX = int(os.getenv("GPU_INDEX", "0"))  # RTX 3090 Ti (device_ids ['0'])
YIELD_WAIT_SECONDS = int(os.getenv("YIELD_WAIT_SECONDS", "5"))

app = FastAPI(
    title="Qwen Manager",
    description="Lifecycle manager for Qwen3.5-35B coding model — enables GPU yield for training",
    version="1.0.0",
)

_docker_client = None
_start_time = datetime.now()


def get_docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


# ── Request / Response models ─────────────────────────────────────────────────

class TrainingStartRequest(BaseModel):
    job_id: str = "unknown"
    gpus: List[int] = [0]
    priority: int = 10
    wait_for_yield: bool = True
    timeout_seconds: int = 30
    metadata: Dict[str, Any] = {}


class TrainingStartResponse(BaseModel):
    status: str  # "ready" | "timeout" | "error"
    model_yielded: bool
    job_id: str
    message: Optional[str] = None
    gpu_memory_before_mb: Optional[int] = None
    gpu_memory_after_mb: Optional[int] = None
    timestamp: str


class TrainingEndRequest(BaseModel):
    job_id: str = "unknown"


class TrainingEndResponse(BaseModel):
    status: str  # "started" | "running" | "error"
    job_id: str
    message: Optional[str] = None
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    qwen_status: str
    manager_uptime_seconds: float


class StatusResponse(BaseModel):
    qwen_container: str
    qwen_status: str
    qwen_health: Optional[str]
    gpu_index: int
    gpu_memory_used_mb: Optional[int]
    gpu_memory_total_mb: Optional[int]
    gpu_utilization_percent: Optional[int]
    training_active: bool
    timestamp: str


# ── GPU helpers ───────────────────────────────────────────────────────────────

def get_gpu_memory(gpu_index: int = 0) -> Dict[str, Any]:
    """Get GPU memory usage via nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
                "-i", str(gpu_index),
            ],
            capture_output=True, text=True, timeout=5,
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
    """Return True if a training process (ray, torch, yolo, train) is using the GPU."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
                "-i", str(gpu_index),
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            training_keywords = ["python", "ray", "yolo", "train", "torch"]
            for line in result.stdout.strip().split("\n"):
                for kw in training_keywords:
                    if kw in line.lower():
                        return True
    except Exception as e:
        logger.error(f"Failed to check training status: {e}")
    return False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/training/start", response_model=TrainingStartResponse)
async def start_training(request: TrainingStartRequest):
    """Stop qwen-coding to free GPU for training."""
    logger.info(f"Training start requested by job: {request.job_id}")

    gpu_before = get_gpu_memory(GPU_INDEX)
    memory_before = gpu_before.get("memory_used_mb")
    client = get_docker_client()

    try:
        container = client.containers.get(QWEN_CONTAINER)

        if container.status == "running":
            logger.info(f"Stopping {QWEN_CONTAINER}...")
            container.stop(timeout=30)

            if request.wait_for_yield:
                for _ in range(request.timeout_seconds):
                    await asyncio.sleep(1)
                    gpu_after = get_gpu_memory(GPU_INDEX)
                    memory_after = gpu_after.get("memory_used_mb", memory_before)
                    # Qwen holds ~19.7 GB — wait until >10 GB freed
                    if memory_before and memory_after < memory_before - 10000:
                        logger.info(f"GPU freed: {memory_before}MB → {memory_after}MB")
                        return TrainingStartResponse(
                            status="ready", model_yielded=True, job_id=request.job_id,
                            message=f"qwen-coding stopped, {memory_before - memory_after}MB freed",
                            gpu_memory_before_mb=memory_before,
                            gpu_memory_after_mb=memory_after,
                            timestamp=datetime.now().isoformat(),
                        )

                gpu_after = get_gpu_memory(GPU_INDEX)
                return TrainingStartResponse(
                    status="timeout", model_yielded=True, job_id=request.job_id,
                    message="Container stopped but GPU memory not yet fully freed",
                    gpu_memory_before_mb=memory_before,
                    gpu_memory_after_mb=gpu_after.get("memory_used_mb"),
                    timestamp=datetime.now().isoformat(),
                )

            await asyncio.sleep(YIELD_WAIT_SECONDS)
            gpu_after = get_gpu_memory(GPU_INDEX)
            return TrainingStartResponse(
                status="ready", model_yielded=True, job_id=request.job_id,
                message="qwen-coding stopped",
                gpu_memory_before_mb=memory_before,
                gpu_memory_after_mb=gpu_after.get("memory_used_mb"),
                timestamp=datetime.now().isoformat(),
            )

        else:
            logger.info(f"{QWEN_CONTAINER} already stopped (status: {container.status})")
            gpu_after = get_gpu_memory(GPU_INDEX)
            return TrainingStartResponse(
                status="ready", model_yielded=False, job_id=request.job_id,
                message=f"Container already {container.status}",
                gpu_memory_before_mb=memory_before,
                gpu_memory_after_mb=gpu_after.get("memory_used_mb"),
                timestamp=datetime.now().isoformat(),
            )

    except docker.errors.NotFound:
        logger.warning(f"Container {QWEN_CONTAINER} not found")
        gpu_after = get_gpu_memory(GPU_INDEX)
        return TrainingStartResponse(
            status="ready", model_yielded=False, job_id=request.job_id,
            message="Container not found (GPU already available)",
            gpu_memory_before_mb=memory_before,
            gpu_memory_after_mb=gpu_after.get("memory_used_mb"),
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Failed to stop qwen-coding: {e}")
        return TrainingStartResponse(
            status="error", model_yielded=False, job_id=request.job_id,
            message=str(e), gpu_memory_before_mb=memory_before,
            gpu_memory_after_mb=None, timestamp=datetime.now().isoformat(),
        )


@app.post("/training/end", response_model=TrainingEndResponse)
async def end_training(request: TrainingEndRequest):
    """Restart qwen-coding after training completes."""
    logger.info(f"Training end requested by job: {request.job_id}")
    client = get_docker_client()

    try:
        container = client.containers.get(QWEN_CONTAINER)

        if container.status != "running":
            logger.info(f"Starting {QWEN_CONTAINER}...")
            container.start()

            # Wait up to 120s for healthy (Qwen 35B takes ~90s to load)
            for _ in range(120):
                await asyncio.sleep(1)
                container.reload()
                if container.status == "running":
                    health = (
                        container.attrs.get("State", {})
                        .get("Health", {})
                        .get("Status")
                    )
                    if health == "healthy":
                        logger.info(f"{QWEN_CONTAINER} is healthy")
                        return TrainingEndResponse(
                            status="started", job_id=request.job_id,
                            message="qwen-coding restarted and healthy",
                            timestamp=datetime.now().isoformat(),
                        )

            return TrainingEndResponse(
                status="started", job_id=request.job_id,
                message="Container started but health check pending (~90s warmup)",
                timestamp=datetime.now().isoformat(),
            )
        else:
            return TrainingEndResponse(
                status="running", job_id=request.job_id,
                message="Container already running",
                timestamp=datetime.now().isoformat(),
            )

    except docker.errors.NotFound:
        return TrainingEndResponse(
            status="error", job_id=request.job_id,
            message=f"Container {QWEN_CONTAINER} not found",
            timestamp=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Failed to restart qwen-coding: {e}")
        return TrainingEndResponse(
            status="error", job_id=request.job_id,
            message=str(e), timestamp=datetime.now().isoformat(),
        )


@app.get("/health", response_model=HealthResponse)
async def health():
    client = get_docker_client()
    try:
        container = client.containers.get(QWEN_CONTAINER)
        qwen_status = container.status
    except docker.errors.NotFound:
        qwen_status = "not_found"
    except Exception as e:
        qwen_status = f"error: {e}"

    return HealthResponse(
        status="healthy",
        qwen_status=qwen_status,
        manager_uptime_seconds=(datetime.now() - _start_time).total_seconds(),
    )


@app.get("/status", response_model=StatusResponse)
async def status():
    """Detailed status — polled by model_router.py `training_active` check."""
    client = get_docker_client()
    try:
        container = client.containers.get(QWEN_CONTAINER)
        qwen_status = container.status
        health = container.attrs.get("State", {}).get("Health", {}).get("Status")
    except docker.errors.NotFound:
        qwen_status = "not_found"
        health = None
    except Exception:
        qwen_status = "error"
        health = None

    gpu_info = get_gpu_memory(GPU_INDEX)
    training_active = check_training_active(GPU_INDEX)

    return StatusResponse(
        qwen_container=QWEN_CONTAINER,
        qwen_status=qwen_status,
        qwen_health=health,
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
