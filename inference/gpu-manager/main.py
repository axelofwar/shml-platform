"""
Unified GPU Manager - Coordinates GPU Yield Across All Inference Services

Manages the lifecycle of GPU-bound containers for training integration:
- RTX 3090 Ti (GPU 0): Nemotron (primary), Qwen3-VL, Z-Image
- RTX 2070 (GPU 1): coding-model-fallback, embedding-service, pii-blur

Training workflow:
1. Training job calls POST /training/start
2. Manager stops RTX 3090 services (Nemotron primary)
3. Manager starts coding-model-fallback on RTX 2070 (if not running)
4. Training completes, calls POST /training/end
5. Manager stops fallback, restarts Nemotron

PII workflow (when training NOT active):
1. Manager can stop fallback + embedding to free RTX 2070
2. PII-blur loads on freed GPU
3. After PII processing, services restore

Endpoints:
- POST /training/start - Yield RTX 3090 for training, activate fallback
- POST /training/end - Restore RTX 3090 services, deactivate fallback
- POST /pii/start - Free RTX 2070 for PII processing
- POST /pii/end - Restore RTX 2070 services
- GET /health - Manager health with all service statuses
- GET /status - Detailed GPU and service status
- GET /services - List all managed services
"""

import os
import asyncio
import subprocess
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

import docker
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# GPU assignments
GPU_RTX_3090 = 0  # Primary training/inference GPU
GPU_RTX_2070 = 1  # Fallback/PII GPU

# Services by GPU - order matters for stop/start
RTX_3090_SERVICES = [
    "nemotron-coding",  # Primary coding model (22GB VRAM)
    "qwen3-vl-api",  # LLM (yields to training)
    "z-image-api",  # Image gen (on-demand)
]

RTX_2070_SERVICES = [
    "coding-model-fallback",  # Fallback coding (6GB VRAM)
    "embedding-service",  # Embeddings (1.5GB VRAM)
    "sam-audio",  # Audio separation (4GB VRAM)
]

# Fallback service (activated during training)
FALLBACK_SERVICE = "coding-model-fallback"

# PII service (needs RTX 2070 freed)
PII_SERVICE = "pii-blur-api"

# Audio service (can run on CPU or GPU)
AUDIO_SERVICE = "sam-audio"

# Timeouts
YIELD_WAIT_SECONDS = int(os.getenv("YIELD_WAIT_SECONDS", "5"))
CONTAINER_STOP_TIMEOUT = 30
CONTAINER_START_TIMEOUT = 180  # Model loading takes time

app = FastAPI(
    title="Unified GPU Manager",
    description="Coordinates GPU resources across all inference services for training and PII processing",
    version="2.0.0",
)

# Docker client (lazy init)
_docker_client = None


def get_docker_client():
    """Get or create Docker client."""
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


# =============================================================================
# Models
# =============================================================================


class GPUState(str, Enum):
    """GPU allocation state."""

    INFERENCE = "inference"  # Normal inference mode
    TRAINING = "training"  # GPU yielded for training
    PII_PROCESSING = "pii"  # GPU allocated for PII processing
    TRANSITIONING = "transitioning"  # Services starting/stopping


class ServiceState(str, Enum):
    """Container state."""

    RUNNING = "running"
    STOPPED = "stopped"
    NOT_FOUND = "not_found"
    ERROR = "error"
    STARTING = "starting"
    STOPPING = "stopping"


@dataclass
class ServiceInfo:
    """Information about a managed service."""

    name: str
    gpu: int  # GPU index
    state: ServiceState
    health: Optional[str] = None
    vram_estimate_gb: float = 0.0
    priority: int = 5  # Lower = higher priority for restoration


class TrainingStartRequest(BaseModel):
    """Request to start training (yield GPU 0, activate fallback)."""

    job_id: str = "unknown"
    gpus: List[int] = [0]  # Which GPUs to yield
    priority: int = 10
    wait_for_yield: bool = True
    timeout_seconds: int = 60
    activate_fallback: bool = True  # Start fallback model during training
    metadata: Dict[str, Any] = {}


class TrainingStartResponse(BaseModel):
    """Response from training start request."""

    status: str  # "ready", "timeout", "error"
    job_id: str
    services_stopped: List[str]
    services_started: List[str]
    gpu_0_memory_freed_mb: Optional[int] = None
    gpu_1_state: str
    fallback_active: bool
    message: Optional[str] = None
    timestamp: str


class TrainingEndRequest(BaseModel):
    """Request to end training (restore GPU 0, deactivate fallback)."""

    job_id: str = "unknown"
    deactivate_fallback: bool = True  # Stop fallback after training


class TrainingEndResponse(BaseModel):
    """Response from training end request."""

    status: str  # "restored", "partial", "error"
    job_id: str
    services_stopped: List[str]
    services_started: List[str]
    message: Optional[str] = None
    timestamp: str


class PIIStartRequest(BaseModel):
    """Request to free RTX 2070 for PII processing."""

    request_id: str = "unknown"
    timeout_seconds: int = 30


class PIIStartResponse(BaseModel):
    """Response from PII start request."""

    status: str
    request_id: str
    services_stopped: List[str]
    gpu_1_memory_freed_mb: Optional[int] = None
    message: Optional[str] = None
    timestamp: str


class PIIEndRequest(BaseModel):
    """Request to restore RTX 2070 services after PII processing."""

    request_id: str = "unknown"


class PIIEndResponse(BaseModel):
    """Response from PII end request."""

    status: str
    request_id: str
    services_started: List[str]
    message: Optional[str] = None
    timestamp: str


class ServiceStatusResponse(BaseModel):
    """Status of a single service."""

    name: str
    state: str
    health: Optional[str]
    gpu: int
    vram_estimate_gb: float


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    gpu_0_state: str
    gpu_1_state: str
    training_active: bool
    pii_active: bool
    manager_uptime_seconds: float


class StatusResponse(BaseModel):
    """Detailed status response."""

    gpu_0_services: List[ServiceStatusResponse]
    gpu_1_services: List[ServiceStatusResponse]
    gpu_0_state: str
    gpu_1_state: str
    gpu_0_memory_used_mb: Optional[int]
    gpu_0_memory_total_mb: Optional[int]
    gpu_1_memory_used_mb: Optional[int]
    gpu_1_memory_total_mb: Optional[int]
    training_active: bool
    pii_active: bool
    fallback_active: bool
    timestamp: str


# =============================================================================
# State Management
# =============================================================================

# Track GPU states
_gpu_states = {
    GPU_RTX_3090: GPUState.INFERENCE,
    GPU_RTX_2070: GPUState.INFERENCE,
}

# Track active jobs
_active_training_job: Optional[str] = None
_active_pii_request: Optional[str] = None

# Track manager start time
_start_time = datetime.now()


# =============================================================================
# GPU Utilities
# =============================================================================


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
        logger.error(f"Failed to get GPU {gpu_index} memory: {e}")
    return {}


# =============================================================================
# Container Management
# =============================================================================


def get_container_status(container_name: str) -> ServiceInfo:
    """Get status of a container."""
    client = get_docker_client()

    # Determine GPU assignment
    gpu = GPU_RTX_3090 if container_name in RTX_3090_SERVICES else GPU_RTX_2070

    # VRAM estimates
    vram_estimates = {
        "nemotron-coding": 22.0,
        "qwen3-vl-api": 8.0,
        "z-image-api": 12.0,
        "coding-model-fallback": 6.0,
        "embedding-service": 1.5,
        "pii-blur-api": 3.0,
    }

    try:
        container = client.containers.get(container_name)
        state = (
            ServiceState(container.status)
            if container.status in ["running", "stopped"]
            else ServiceState.STOPPED
        )
        health = container.attrs.get("State", {}).get("Health", {}).get("Status")

        return ServiceInfo(
            name=container_name,
            gpu=gpu,
            state=state,
            health=health,
            vram_estimate_gb=vram_estimates.get(container_name, 2.0),
        )
    except docker.errors.NotFound:
        return ServiceInfo(
            name=container_name,
            gpu=gpu,
            state=ServiceState.NOT_FOUND,
            vram_estimate_gb=vram_estimates.get(container_name, 2.0),
        )
    except Exception as e:
        logger.error(f"Error getting status for {container_name}: {e}")
        return ServiceInfo(
            name=container_name,
            gpu=gpu,
            state=ServiceState.ERROR,
        )


async def stop_container(
    container_name: str, timeout: int = CONTAINER_STOP_TIMEOUT
) -> bool:
    """Stop a container gracefully."""
    client = get_docker_client()

    try:
        container = client.containers.get(container_name)
        if container.status == "running":
            logger.info(f"Stopping {container_name}...")
            container.stop(timeout=timeout)
            logger.info(f"Stopped {container_name}")
            return True
        else:
            logger.info(
                f"{container_name} already stopped (status: {container.status})"
            )
            return True
    except docker.errors.NotFound:
        logger.warning(f"Container {container_name} not found")
        return True  # Consider not found as success (already stopped)
    except Exception as e:
        logger.error(f"Failed to stop {container_name}: {e}")
        return False


async def start_container(
    container_name: str,
    wait_healthy: bool = True,
    timeout: int = CONTAINER_START_TIMEOUT,
) -> bool:
    """Start a container and optionally wait for health."""
    client = get_docker_client()

    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            logger.info(f"Starting {container_name}...")
            container.start()

            if wait_healthy:
                for _ in range(timeout):
                    await asyncio.sleep(1)
                    container.reload()
                    if container.status == "running":
                        health = (
                            container.attrs.get("State", {})
                            .get("Health", {})
                            .get("Status")
                        )
                        if health == "healthy":
                            logger.info(f"{container_name} is healthy")
                            return True
                        elif health is None:
                            # No health check defined, consider running as success
                            logger.info(
                                f"{container_name} is running (no health check)"
                            )
                            return True

                logger.warning(f"{container_name} started but health check pending")
                return True  # Started but not healthy yet

            logger.info(f"Started {container_name}")
            return True
        else:
            logger.info(f"{container_name} already running")
            return True
    except docker.errors.NotFound:
        logger.error(f"Container {container_name} not found - cannot start")
        return False
    except Exception as e:
        logger.error(f"Failed to start {container_name}: {e}")
        return False


# =============================================================================
# API Endpoints
# =============================================================================


@app.post("/training/start", response_model=TrainingStartResponse)
async def start_training(request: TrainingStartRequest):
    """
    Yield RTX 3090 for training and activate fallback model on RTX 2070.

    This is called by Ray training jobs before GPU allocation.
    """
    global _gpu_states, _active_training_job

    logger.info(f"Training start requested by job: {request.job_id}")

    if _active_training_job:
        return TrainingStartResponse(
            status="error",
            job_id=request.job_id,
            services_stopped=[],
            services_started=[],
            gpu_1_state=str(_gpu_states[GPU_RTX_2070]),
            fallback_active=False,
            message=f"Training already active (job: {_active_training_job})",
            timestamp=datetime.now().isoformat(),
        )

    # Get GPU 0 memory before
    gpu_0_before = get_gpu_memory(GPU_RTX_3090)
    memory_before = gpu_0_before.get("memory_used_mb", 0)

    # Mark state as transitioning
    _gpu_states[GPU_RTX_3090] = GPUState.TRANSITIONING
    _active_training_job = request.job_id

    stopped_services = []
    started_services = []

    try:
        # Stop RTX 3090 services (Nemotron first - it's the big one)
        for service in RTX_3090_SERVICES:
            if await stop_container(service):
                stopped_services.append(service)

        # Wait for GPU memory to be freed
        if request.wait_for_yield:
            for _ in range(request.timeout_seconds):
                await asyncio.sleep(1)
                gpu_0_after = get_gpu_memory(GPU_RTX_3090)
                memory_after = gpu_0_after.get("memory_used_mb", memory_before)

                # Check if significant memory was freed (>10GB = model unloaded)
                if memory_after < memory_before - 10000:
                    logger.info(
                        f"GPU 0 memory freed: {memory_before}MB → {memory_after}MB"
                    )
                    break
        else:
            await asyncio.sleep(YIELD_WAIT_SECONDS)

        # Activate fallback model on RTX 2070 if requested
        fallback_active = False
        if request.activate_fallback:
            if await start_container(FALLBACK_SERVICE, wait_healthy=True, timeout=120):
                started_services.append(FALLBACK_SERVICE)
                fallback_active = True

        # Update state
        _gpu_states[GPU_RTX_3090] = GPUState.TRAINING

        gpu_0_after = get_gpu_memory(GPU_RTX_3090)
        memory_freed = memory_before - gpu_0_after.get("memory_used_mb", 0)

        return TrainingStartResponse(
            status="ready",
            job_id=request.job_id,
            services_stopped=stopped_services,
            services_started=started_services,
            gpu_0_memory_freed_mb=memory_freed if memory_freed > 0 else None,
            gpu_1_state=str(_gpu_states[GPU_RTX_2070]),
            fallback_active=fallback_active,
            message=f"RTX 3090 yielded, fallback {'active' if fallback_active else 'not started'}",
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Training start failed: {e}")
        _gpu_states[GPU_RTX_3090] = GPUState.INFERENCE
        _active_training_job = None
        return TrainingStartResponse(
            status="error",
            job_id=request.job_id,
            services_stopped=stopped_services,
            services_started=started_services,
            gpu_1_state=str(_gpu_states[GPU_RTX_2070]),
            fallback_active=False,
            message=str(e),
            timestamp=datetime.now().isoformat(),
        )


@app.post("/training/end", response_model=TrainingEndResponse)
async def end_training(request: TrainingEndRequest):
    """
    Restore RTX 3090 services after training completes.

    Optionally deactivates the fallback model to free RTX 2070.
    """
    global _gpu_states, _active_training_job

    logger.info(f"Training end requested by job: {request.job_id}")

    stopped_services = []
    started_services = []

    try:
        # Stop fallback if requested
        if request.deactivate_fallback:
            if await stop_container(FALLBACK_SERVICE):
                stopped_services.append(FALLBACK_SERVICE)

        # Restart RTX 3090 services (Nemotron is the critical one)
        for service in RTX_3090_SERVICES:
            # Only restart Nemotron by default (others are on-demand)
            if service == "nemotron-coding":
                if await start_container(service, wait_healthy=True, timeout=180):
                    started_services.append(service)

        # Update state
        _gpu_states[GPU_RTX_3090] = GPUState.INFERENCE
        _active_training_job = None

        return TrainingEndResponse(
            status="restored",
            job_id=request.job_id,
            services_stopped=stopped_services,
            services_started=started_services,
            message="RTX 3090 restored to inference mode",
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Training end failed: {e}")
        return TrainingEndResponse(
            status="error",
            job_id=request.job_id,
            services_stopped=stopped_services,
            services_started=started_services,
            message=str(e),
            timestamp=datetime.now().isoformat(),
        )


@app.post("/pii/start", response_model=PIIStartResponse)
async def start_pii_processing(request: PIIStartRequest):
    """
    Free RTX 2070 for PII face detection processing.

    Stops fallback and embedding services to make room for PII-blur.
    Only available when training is NOT active (fallback needed during training).
    """
    global _gpu_states, _active_pii_request

    logger.info(f"PII processing requested: {request.request_id}")

    # Check if training is active
    if _active_training_job:
        return PIIStartResponse(
            status="error",
            request_id=request.request_id,
            services_stopped=[],
            message=f"Cannot free RTX 2070 during training (job: {_active_training_job}) - fallback model is needed",
            timestamp=datetime.now().isoformat(),
        )

    if _active_pii_request:
        return PIIStartResponse(
            status="error",
            request_id=request.request_id,
            services_stopped=[],
            message=f"PII processing already active: {_active_pii_request}",
            timestamp=datetime.now().isoformat(),
        )

    # Get GPU 1 memory before
    gpu_1_before = get_gpu_memory(GPU_RTX_2070)
    memory_before = gpu_1_before.get("memory_used_mb", 0)

    _gpu_states[GPU_RTX_2070] = GPUState.TRANSITIONING
    _active_pii_request = request.request_id

    stopped_services = []

    try:
        # Stop RTX 2070 services to free memory for PII
        for service in RTX_2070_SERVICES:
            if await stop_container(service):
                stopped_services.append(service)

        # Wait for memory to free
        for _ in range(request.timeout_seconds):
            await asyncio.sleep(1)
            gpu_1_after = get_gpu_memory(GPU_RTX_2070)
            memory_after = gpu_1_after.get("memory_used_mb", memory_before)

            if memory_after < 1000:  # Less than 1GB used = freed
                break

        _gpu_states[GPU_RTX_2070] = GPUState.PII_PROCESSING

        gpu_1_after = get_gpu_memory(GPU_RTX_2070)
        memory_freed = memory_before - gpu_1_after.get("memory_used_mb", 0)

        return PIIStartResponse(
            status="ready",
            request_id=request.request_id,
            services_stopped=stopped_services,
            gpu_1_memory_freed_mb=memory_freed if memory_freed > 0 else None,
            message=f"RTX 2070 freed for PII processing ({memory_freed}MB freed)",
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"PII start failed: {e}")
        _gpu_states[GPU_RTX_2070] = GPUState.INFERENCE
        _active_pii_request = None
        return PIIStartResponse(
            status="error",
            request_id=request.request_id,
            services_stopped=stopped_services,
            message=str(e),
            timestamp=datetime.now().isoformat(),
        )


@app.post("/pii/end", response_model=PIIEndResponse)
async def end_pii_processing(request: PIIEndRequest):
    """
    Restore RTX 2070 services after PII processing completes.
    """
    global _gpu_states, _active_pii_request

    logger.info(f"PII processing end: {request.request_id}")

    started_services = []

    try:
        # Restart RTX 2070 services
        for service in RTX_2070_SERVICES:
            if await start_container(service, wait_healthy=True, timeout=120):
                started_services.append(service)

        _gpu_states[GPU_RTX_2070] = GPUState.INFERENCE
        _active_pii_request = None

        return PIIEndResponse(
            status="restored",
            request_id=request.request_id,
            services_started=started_services,
            message="RTX 2070 services restored",
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"PII end failed: {e}")
        return PIIEndResponse(
            status="error",
            request_id=request.request_id,
            services_started=started_services,
            message=str(e),
            timestamp=datetime.now().isoformat(),
        )


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check with GPU state summary."""
    uptime = (datetime.now() - _start_time).total_seconds()

    return HealthResponse(
        status="healthy",
        gpu_0_state=str(_gpu_states[GPU_RTX_3090]),
        gpu_1_state=str(_gpu_states[GPU_RTX_2070]),
        training_active=_active_training_job is not None,
        pii_active=_active_pii_request is not None,
        manager_uptime_seconds=uptime,
    )


@app.get("/status", response_model=StatusResponse)
async def status():
    """Detailed status of all GPUs and services."""

    # Get service statuses
    gpu_0_services = [get_container_status(s) for s in RTX_3090_SERVICES]
    gpu_1_services = [
        get_container_status(s) for s in RTX_2070_SERVICES + [PII_SERVICE]
    ]

    # Get GPU memory
    gpu_0_memory = get_gpu_memory(GPU_RTX_3090)
    gpu_1_memory = get_gpu_memory(GPU_RTX_2070)

    # Check fallback status
    fallback_status = get_container_status(FALLBACK_SERVICE)
    fallback_active = fallback_status.state == ServiceState.RUNNING

    return StatusResponse(
        gpu_0_services=[
            ServiceStatusResponse(
                name=s.name,
                state=str(s.state.value),
                health=s.health,
                gpu=s.gpu,
                vram_estimate_gb=s.vram_estimate_gb,
            )
            for s in gpu_0_services
        ],
        gpu_1_services=[
            ServiceStatusResponse(
                name=s.name,
                state=str(s.state.value),
                health=s.health,
                gpu=s.gpu,
                vram_estimate_gb=s.vram_estimate_gb,
            )
            for s in gpu_1_services
        ],
        gpu_0_state=str(_gpu_states[GPU_RTX_3090].value),
        gpu_1_state=str(_gpu_states[GPU_RTX_2070].value),
        gpu_0_memory_used_mb=gpu_0_memory.get("memory_used_mb"),
        gpu_0_memory_total_mb=gpu_0_memory.get("memory_total_mb"),
        gpu_1_memory_used_mb=gpu_1_memory.get("memory_used_mb"),
        gpu_1_memory_total_mb=gpu_1_memory.get("memory_total_mb"),
        training_active=_active_training_job is not None,
        pii_active=_active_pii_request is not None,
        fallback_active=fallback_active,
        timestamp=datetime.now().isoformat(),
    )


@app.get("/services")
async def list_services():
    """List all managed services."""
    return {
        "gpu_0_services": RTX_3090_SERVICES,
        "gpu_1_services": RTX_2070_SERVICES,
        "fallback_service": FALLBACK_SERVICE,
        "pii_service": PII_SERVICE,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
