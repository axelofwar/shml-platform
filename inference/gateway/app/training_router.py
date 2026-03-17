"""
Native Training API Router - Controls for Option 6 Hybrid Architecture

Provides REST endpoints for:
- Starting/stopping native training jobs
- Pausing/resuming training for inference priority
- Querying training status and progress
- Managing checkpoints

Navigation:
- Related: native_training/native_training_coordinator.py (coordinator)
- Config: native_training/native_trainer.py (training script)
- Docs: native_training/README.md

Integration:
- These endpoints communicate with the training coordinator via subprocess/signals
- Training runs natively (not in Docker) to bypass MPS conflict
- MLflow integration for experiment tracking

Author: SHML Platform
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Platform root - avoid hardcoded paths
PLATFORM_ROOT = os.environ.get("PLATFORM_ROOT", str(Path(__file__).resolve().parents[3]))

# Configuration
TRAINING_ROOT = Path(
    f"{PLATFORM_ROOT}/inference/app/native_training"
)
COORDINATOR_SCRIPT = TRAINING_ROOT / "native_training_coordinator.py"
SANDBOX_SCRIPT = TRAINING_ROOT / "sandbox_training.sh"
CHECKPOINT_DIR = Path(f"{PLATFORM_ROOT}/data/checkpoints")
STATE_FILE = Path(
    f"{PLATFORM_ROOT}/data/training_coordinator_state.json"
)

router = APIRouter(prefix="/training", tags=["training"])


# ============================================================================
# Schemas
# ============================================================================


class TrainingStartRequest(BaseModel):
    """Request to start training"""

    model: str = Field(default="yolov8n.pt", description="Model to train")
    dataset: str = Field(default="wider_face", description="Dataset name")
    epochs: int = Field(default=100, ge=1, le=1000, description="Number of epochs")
    batch_size: int = Field(default=16, ge=1, le=64, description="Batch size")
    imgsz: int = Field(default=640, description="Initial image size")
    resume_from: Optional[str] = Field(
        default=None, description="Checkpoint to resume from"
    )
    experiment_name: Optional[str] = Field(
        default="SOTA-YOLO-Training", description="MLflow experiment"
    )


class TrainingStatusResponse(BaseModel):
    """Training status response"""

    state: str
    is_running: bool
    current_epoch: Optional[int]
    current_step: Optional[int]
    total_epochs: Optional[int]
    progress_percent: Optional[float]
    pause_count: int
    total_pause_time: float
    last_checkpoint: Optional[str]
    best_map: Optional[float]
    model: Optional[str]
    dataset: Optional[str]
    started_at: Optional[str]
    mlflow_run_id: Optional[str]


class QueuePressureResponse(BaseModel):
    """Queue pressure status for pause decisions"""

    pending: int
    processing: int
    avg_wait_time: float
    needs_pause: bool
    can_resume: bool


class CheckpointInfo(BaseModel):
    """Checkpoint information"""

    path: str
    epoch: int
    step: int
    created_at: str
    size_mb: float
    is_latest: bool


# ============================================================================
# Helper Functions
# ============================================================================


def read_coordinator_state() -> Dict[str, Any]:
    """Read coordinator state from JSON file"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read state file: {e}")
    return {"state": "idle", "session": {}}


def find_coordinator_pid() -> Optional[int]:
    """Find running coordinator process"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "native_training_coordinator.py daemon"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split("\n")
            return int(pids[0]) if pids else None
    except Exception:
        pass
    return None


def find_training_pid() -> Optional[int]:
    """Find running training process"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "native_trainer.py"], capture_output=True, text=True
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split("\n")
            return int(pids[0]) if pids else None
    except Exception:
        pass
    return None


async def run_coordinator_command(
    action: str, args: List[str] = None
) -> Dict[str, Any]:
    """Run coordinator CLI command"""
    cmd = ["python3", str(COORDINATOR_SCRIPT), action]
    if args:
        cmd.extend(args)

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500, detail=f"Coordinator command failed: {stderr.decode()}"
        )

    # Try to parse as JSON
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {"output": stdout.decode()}


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/status", response_model=TrainingStatusResponse)
async def get_training_status():
    """
    Get current training status.

    Returns detailed information about the training process including:
    - Current state (idle, running, paused, etc.)
    - Progress (epoch, step, percentage)
    - Pause statistics
    - Latest checkpoint
    - MLflow integration
    """
    state = read_coordinator_state()
    session = state.get("session", {})

    # Check if actually running
    training_pid = find_training_pid()
    is_running = training_pid is not None

    current_state = state.get("state", "idle")
    if current_state == "running" and not is_running:
        current_state = "idle"

    # Calculate progress
    total_epochs = session.get("total_epochs")
    current_epoch = session.get("current_epoch")
    progress = None
    if total_epochs and current_epoch is not None:
        progress = (current_epoch / total_epochs) * 100

    return TrainingStatusResponse(
        state=current_state,
        is_running=is_running,
        current_epoch=session.get("current_epoch"),
        current_step=session.get("current_step"),
        total_epochs=total_epochs,
        progress_percent=progress,
        pause_count=session.get("pause_count", 0),
        total_pause_time=session.get("total_pause_time", 0.0),
        last_checkpoint=session.get("last_checkpoint"),
        best_map=session.get("best_map"),
        model=session.get("model"),
        dataset=session.get("dataset"),
        started_at=(
            datetime.fromtimestamp(session["started_at"]).isoformat()
            if session.get("started_at")
            else None
        ),
        mlflow_run_id=session.get("run_id"),
    )


@router.post("/start")
async def start_training(
    request: TrainingStartRequest, background_tasks: BackgroundTasks
):
    """
    Start a new training job.

    Training runs natively (not in Docker) using bubblewrap sandboxing.
    This bypasses the MPS conflict that prevents GPU access in containers.

    The training will automatically pause when inference queue pressure
    is detected and resume when the queue clears.
    """
    # Check if already running
    if find_training_pid():
        raise HTTPException(
            status_code=409,
            detail="Training already running. Stop or wait for completion.",
        )

    # Build command
    cmd = [
        str(SANDBOX_SCRIPT),
        "--model",
        request.model,
        "--data",
        request.dataset,
        "--epochs",
        str(request.epochs),
        "--batch",
        str(request.batch_size),
        "--imgsz",
        str(request.imgsz),
        "--experiment",
        request.experiment_name,
    ]

    if request.resume_from:
        cmd.extend(["--resume", request.resume_from])

    # Start training in background
    def start_background_training():
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            logger.info(f"Training started: {' '.join(cmd)}")
        except Exception as e:
            logger.error(f"Failed to start training: {e}")

    background_tasks.add_task(start_background_training)

    return {
        "status": "starting",
        "message": "Training job queued to start",
        "config": request.dict(),
    }


@router.post("/pause")
async def pause_training():
    """
    Pause training to free GPU for inference.

    Sends SIGUSR1 to the training process, which will:
    1. Save a checkpoint
    2. Release GPU memory
    3. Wait for resume signal

    Use this when inference queue is backed up.
    """
    training_pid = find_training_pid()

    if not training_pid:
        raise HTTPException(status_code=404, detail="No training process running")

    state = read_coordinator_state()
    if state.get("state") == "paused":
        return {"status": "already_paused", "message": "Training is already paused"}

    try:
        os.kill(training_pid, signal.SIGUSR1)
        return {
            "status": "pausing",
            "message": f"Pause signal sent to PID {training_pid}",
            "note": "Training will save checkpoint and release GPU",
        }
    except ProcessLookupError:
        raise HTTPException(status_code=404, detail="Training process not found")
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Permission denied to signal process"
        )


@router.post("/resume")
async def resume_training():
    """
    Resume paused training.

    Sends SIGUSR2 to the training process, which will:
    1. Reload model from checkpoint
    2. Resume training from last step

    Only works if training is currently paused.
    """
    training_pid = find_training_pid()

    if not training_pid:
        raise HTTPException(status_code=404, detail="No training process running")

    state = read_coordinator_state()
    if state.get("state") != "paused":
        return {"status": "not_paused", "message": "Training is not paused"}

    try:
        os.kill(training_pid, signal.SIGUSR2)
        return {
            "status": "resuming",
            "message": f"Resume signal sent to PID {training_pid}",
        }
    except ProcessLookupError:
        raise HTTPException(status_code=404, detail="Training process not found")
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Permission denied to signal process"
        )


@router.post("/stop")
async def stop_training():
    """
    Stop training gracefully.

    Sends SIGTERM to the training process, which will:
    1. Save a final checkpoint
    2. Log to MLflow
    3. Exit cleanly
    """
    training_pid = find_training_pid()

    if not training_pid:
        return {"status": "not_running", "message": "No training process running"}

    try:
        os.kill(training_pid, signal.SIGTERM)
        return {
            "status": "stopping",
            "message": f"Stop signal sent to PID {training_pid}",
            "note": "Training will save final checkpoint before exiting",
        }
    except ProcessLookupError:
        raise HTTPException(status_code=404, detail="Training process not found")
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Permission denied to signal process"
        )


@router.get("/queue-pressure", response_model=QueuePressureResponse)
async def get_queue_pressure():
    """
    Get queue pressure metrics for pause decisions.

    Returns metrics used to decide when training should pause:
    - pending: Number of requests waiting
    - processing: Number of requests being processed
    - avg_wait_time: Average wait time in seconds
    - needs_pause: True if training should pause
    - can_resume: True if training can resume
    """
    # Import queue from gateway
    try:
        from .queue import request_queue

        status = await request_queue.get_status()

        pending = status.llm_queue_length + status.image_queue_length
        processing = getattr(status, "processing", 0)
        avg_wait = getattr(status, "avg_wait_time", 0.0)

        # Pause thresholds
        needs_pause = pending >= 3 or avg_wait >= 30.0
        can_resume = pending == 0 and avg_wait <= 5.0

        return QueuePressureResponse(
            pending=pending,
            processing=processing,
            avg_wait_time=avg_wait,
            needs_pause=needs_pause,
            can_resume=can_resume,
        )
    except ImportError:
        # Queue not available, assume no pressure
        return QueuePressureResponse(
            pending=0,
            processing=0,
            avg_wait_time=0.0,
            needs_pause=False,
            can_resume=True,
        )


@router.get("/checkpoints", response_model=List[CheckpointInfo])
async def list_checkpoints():
    """
    List available training checkpoints.

    Returns all checkpoints in the checkpoint directory,
    sorted by creation time (newest first).
    """
    checkpoints = []

    if not CHECKPOINT_DIR.exists():
        return checkpoints

    latest = CHECKPOINT_DIR / "latest.pt"
    latest_target = latest.resolve() if latest.exists() else None

    for pt_file in CHECKPOINT_DIR.glob("*.pt"):
        if pt_file.name == "latest.pt":
            continue

        # Parse epoch and step from filename
        try:
            parts = pt_file.stem.split("_")
            epoch = int(parts[1])
            step = int(parts[3])
        except (IndexError, ValueError):
            epoch = 0
            step = 0

        stat = pt_file.stat()

        checkpoints.append(
            CheckpointInfo(
                path=str(pt_file),
                epoch=epoch,
                step=step,
                created_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                size_mb=stat.st_size / (1024 * 1024),
                is_latest=pt_file == latest_target,
            )
        )

    # Sort by creation time (newest first)
    checkpoints.sort(key=lambda x: x.created_at, reverse=True)

    return checkpoints


@router.delete("/checkpoints/{checkpoint_name}")
async def delete_checkpoint(checkpoint_name: str):
    """
    Delete a specific checkpoint.

    Cannot delete the latest checkpoint if training is running.
    """
    checkpoint_path = CHECKPOINT_DIR / checkpoint_name

    if not checkpoint_path.exists():
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    # Don't delete latest if training is running
    latest = CHECKPOINT_DIR / "latest.pt"
    if latest.exists() and latest.resolve() == checkpoint_path:
        if find_training_pid():
            raise HTTPException(
                status_code=409,
                detail="Cannot delete latest checkpoint while training is running",
            )

    try:
        checkpoint_path.unlink()

        # Also delete state file if exists
        state_file = checkpoint_path.with_suffix("").with_name(
            checkpoint_path.stem + "_state.json"
        )
        if state_file.exists():
            state_file.unlink()

        return {"status": "deleted", "path": str(checkpoint_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs")
async def get_training_logs(lines: int = 100):
    """
    Get recent training logs.

    Returns the last N lines from the training log file.
    """
    log_file = Path(f"{PLATFORM_ROOT}/logs/native_trainer.log")

    if not log_file.exists():
        return {"logs": [], "message": "No training logs yet"}

    try:
        result = subprocess.run(
            ["tail", "-n", str(lines), str(log_file)], capture_output=True, text=True
        )

        log_lines = result.stdout.strip().split("\n") if result.stdout else []

        return {
            "logs": log_lines,
            "total_lines": len(log_lines),
            "log_file": str(log_file),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
