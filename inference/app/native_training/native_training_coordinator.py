#!/usr/bin/env python3
"""
Native Training Coordinator - Option 6 Hybrid Architecture

Manages native training processes with:
- Signal-based pause/resume (SIGUSR1/SIGUSR2)
- Inference queue monitoring
- Checkpoint validation
- MLflow integration
- systemd notification support

Navigation:
- Related: native_trainer.py (actual training), sandbox_training.sh (security wrapper)
- Config: ../mps_controller.py (MPS management), ../training_coordinator.py (state machine)
- Docs: README.md, ../../docs/DYNAMIC_MPS_DESIGN.md

Author: SHML Platform
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

import aiohttp

# Optional: systemd notification
try:
    import sdnotify

    SYSTEMD_AVAILABLE = True
except ImportError:
    SYSTEMD_AVAILABLE = False
    sdnotify = None

# Configuration
CONFIG = {
    # Service endpoints (Docker network IPs)
    "mlflow_uri": "http://172.30.0.11:5000",
    "mlflow_host_header": "mlflow-server",
    "inference_api": "http://localhost:8000",
    "postgres_host": "172.30.0.5",
    "postgres_port": 5432,
    "postgres_db": "mlflow_db",
    "postgres_user": "mlflow",
    # Pause thresholds
    "pause_queue_threshold": 3,  # Pending requests
    "pause_wait_threshold": 30.0,  # Seconds avg wait
    "resume_queue_threshold": 0,  # Must be empty to resume
    "resume_wait_threshold": 5.0,  # Low wait time to resume
    # Timing
    "poll_interval": 2.0,  # Queue check interval
    "checkpoint_timeout": 60.0,  # Max wait for checkpoint
    "resume_delay": 5.0,  # Delay before resuming
    # Paths
    "checkpoint_dir": "/home/axelofwar/Projects/shml-platform/data/checkpoints",
    "training_log": "/home/axelofwar/Projects/shml-platform/logs/training.log",
    "state_file": "/home/axelofwar/Projects/shml-platform/data/training_coordinator_state.json",
}

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(CONFIG["training_log"], mode="a"),
    ],
)
logger = logging.getLogger("NativeTrainingCoordinator")


class TrainingState(Enum):
    """Training lifecycle states"""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    CHECKPOINTING = "checkpointing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class QueueStatus:
    """Inference queue status"""

    pending: int = 0
    processing: int = 0
    avg_wait_time: float = 0.0
    last_check: float = field(default_factory=time.time)

    @property
    def needs_pause(self) -> bool:
        """Check if training should pause for inference"""
        return (
            self.pending >= CONFIG["pause_queue_threshold"]
            or self.avg_wait_time >= CONFIG["pause_wait_threshold"]
        )

    @property
    def can_resume(self) -> bool:
        """Check if training can resume"""
        return (
            self.pending <= CONFIG["resume_queue_threshold"]
            and self.avg_wait_time <= CONFIG["resume_wait_threshold"]
        )


@dataclass
class TrainingSession:
    """Active training session info"""

    pid: Optional[int] = None
    started_at: Optional[float] = None
    paused_at: Optional[float] = None
    total_pause_time: float = 0.0
    pause_count: int = 0
    current_epoch: int = 0
    current_step: int = 0
    last_checkpoint: Optional[str] = None
    experiment_id: Optional[str] = None
    run_id: Optional[str] = None
    model: str = "yolov8n.pt"
    dataset: str = "wider_face"


class NativeTrainingCoordinator:
    """
    Coordinates native training with Docker inference.

    Responsibilities:
    - Start/stop training processes
    - Monitor inference queue pressure
    - Send pause/resume signals
    - Validate checkpoints
    - Track training state
    """

    def __init__(self):
        self.state = TrainingState.IDLE
        self.session: Optional[TrainingSession] = None
        self.queue_status = QueueStatus()
        self._process: Optional[subprocess.Popen] = None
        self._shutdown = False
        self._state_callbacks: List[Callable] = []

        # Load persisted state if exists
        self._load_state()

        # systemd notification
        if SYSTEMD_AVAILABLE:
            self._notifier = sdnotify.SystemdNotifier()
        else:
            self._notifier = None

    def _load_state(self):
        """Load persisted coordinator state"""
        state_file = Path(CONFIG["state_file"])
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)
                self.session = TrainingSession(**data.get("session", {}))
                logger.info(f"Loaded persisted state: {self.state}")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")

    def _save_state(self):
        """Persist coordinator state"""
        state_file = Path(CONFIG["state_file"])
        state_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "state": self.state.value,
            "session": {
                "pid": self.session.pid if self.session else None,
                "started_at": self.session.started_at if self.session else None,
                "paused_at": self.session.paused_at if self.session else None,
                "total_pause_time": (
                    self.session.total_pause_time if self.session else 0
                ),
                "pause_count": self.session.pause_count if self.session else 0,
                "current_epoch": self.session.current_epoch if self.session else 0,
                "current_step": self.session.current_step if self.session else 0,
                "last_checkpoint": (
                    self.session.last_checkpoint if self.session else None
                ),
                "experiment_id": self.session.experiment_id if self.session else None,
                "run_id": self.session.run_id if self.session else None,
            },
            "saved_at": datetime.now().isoformat(),
        }

        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)

    def _set_state(self, new_state: TrainingState):
        """Update state with logging and persistence"""
        old_state = self.state
        self.state = new_state
        logger.info(f"State transition: {old_state.value} -> {new_state.value}")
        self._save_state()

        # Notify systemd
        if self._notifier:
            self._notifier.notify(f"STATUS={new_state.value}")

        # Trigger callbacks
        for callback in self._state_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.error(f"State callback error: {e}")

    def add_state_callback(self, callback: Callable):
        """Register callback for state changes"""
        self._state_callbacks.append(callback)

    async def check_queue_status(self) -> QueueStatus:
        """Query inference API for queue status"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{CONFIG['inference_api']}/queue/status",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.queue_status = QueueStatus(
                            pending=data.get("pending", 0),
                            processing=data.get("processing", 0),
                            avg_wait_time=data.get("avg_wait_time", 0.0),
                        )
        except Exception as e:
            logger.debug(f"Queue status check failed (inference may be down): {e}")
            # Assume no pressure if can't reach inference
            self.queue_status = QueueStatus()

        return self.queue_status

    async def start_training(
        self,
        model: str = "yolov8n.pt",
        dataset: str = "wider_face",
        epochs: int = 100,
        batch_size: int = 16,
        imgsz: int = 640,
        resume_from: Optional[str] = None,
        extra_args: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Start a new training session"""

        if self.state not in (
            TrainingState.IDLE,
            TrainingState.COMPLETED,
            TrainingState.FAILED,
        ):
            logger.error(f"Cannot start training in state: {self.state}")
            return False

        self._set_state(TrainingState.STARTING)

        # Build command
        cmd = [
            "/home/axelofwar/Projects/shml-platform/inference/app/native_training/sandbox_training.sh",
            "--model",
            model,
            "--data",
            dataset,
            "--epochs",
            str(epochs),
            "--batch",
            str(batch_size),
            "--imgsz",
            str(imgsz),
            "--mlflow-uri",
            CONFIG["mlflow_uri"],
        ]

        if resume_from:
            cmd.extend(["--resume", resume_from])

        if extra_args:
            for key, value in extra_args.items():
                cmd.extend([f"--{key}", str(value)])

        try:
            # Start training process
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,  # New process group for signal handling
            )

            # Create session
            self.session = TrainingSession(
                pid=self._process.pid,
                started_at=time.time(),
                model=model,
                dataset=dataset,
            )

            logger.info(f"Training started with PID {self._process.pid}")
            self._set_state(TrainingState.RUNNING)

            # Notify systemd ready
            if self._notifier:
                self._notifier.notify("READY=1")

            return True

        except Exception as e:
            logger.error(f"Failed to start training: {e}")
            self._set_state(TrainingState.FAILED)
            return False

    def pause_training(self) -> bool:
        """Send pause signal to training process"""
        if self.state != TrainingState.RUNNING:
            logger.warning(f"Cannot pause in state: {self.state}")
            return False

        if not self._process or not self.session:
            logger.error("No active training process")
            return False

        self._set_state(TrainingState.PAUSING)

        try:
            # Send SIGUSR1 for graceful pause
            os.kill(self.session.pid, signal.SIGUSR1)
            logger.info(f"Sent SIGUSR1 (pause) to PID {self.session.pid}")

            # Track pause time
            self.session.paused_at = time.time()
            self.session.pause_count += 1

            return True

        except ProcessLookupError:
            logger.error("Training process not found")
            self._set_state(TrainingState.FAILED)
            return False
        except Exception as e:
            logger.error(f"Failed to pause: {e}")
            return False

    def resume_training(self) -> bool:
        """Send resume signal to training process"""
        if self.state != TrainingState.PAUSED:
            logger.warning(f"Cannot resume in state: {self.state}")
            return False

        if not self._process or not self.session:
            logger.error("No active training process")
            return False

        self._set_state(TrainingState.RESUMING)

        try:
            # Send SIGUSR2 for resume
            os.kill(self.session.pid, signal.SIGUSR2)
            logger.info(f"Sent SIGUSR2 (resume) to PID {self.session.pid}")

            # Track pause time
            if self.session.paused_at:
                self.session.total_pause_time += time.time() - self.session.paused_at
                self.session.paused_at = None

            self._set_state(TrainingState.RUNNING)
            return True

        except ProcessLookupError:
            logger.error("Training process not found")
            self._set_state(TrainingState.FAILED)
            return False
        except Exception as e:
            logger.error(f"Failed to resume: {e}")
            return False

    def stop_training(self, timeout: float = 30.0) -> bool:
        """Stop training gracefully"""
        if self.state in (TrainingState.IDLE, TrainingState.COMPLETED):
            return True

        if not self._process or not self.session:
            self._set_state(TrainingState.IDLE)
            return True

        try:
            # First, try graceful shutdown with SIGTERM
            os.kill(self.session.pid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to PID {self.session.pid}")

            # Wait for graceful shutdown
            try:
                self._process.wait(timeout=timeout)
                logger.info("Training stopped gracefully")
            except subprocess.TimeoutExpired:
                # Force kill
                logger.warning("Graceful shutdown timeout, sending SIGKILL")
                os.kill(self.session.pid, signal.SIGKILL)
                self._process.wait(timeout=5)

            self._set_state(TrainingState.COMPLETED)
            return True

        except Exception as e:
            logger.error(f"Failed to stop training: {e}")
            self._set_state(TrainingState.FAILED)
            return False

    async def wait_for_checkpoint(self, timeout: float = None) -> Optional[str]:
        """Wait for checkpoint to be written after pause"""
        timeout = timeout or CONFIG["checkpoint_timeout"]
        checkpoint_dir = Path(CONFIG["checkpoint_dir"])
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check for new checkpoint
            latest = checkpoint_dir / "latest.pt"
            if latest.exists():
                # Verify it's recent (within last 2 minutes)
                mtime = latest.stat().st_mtime
                if mtime > start_time - 10:  # Allow 10s grace
                    checkpoint_path = str(latest.resolve())
                    logger.info(f"Checkpoint validated: {checkpoint_path}")

                    if self.session:
                        self.session.last_checkpoint = checkpoint_path

                    self._set_state(TrainingState.PAUSED)
                    return checkpoint_path

            await asyncio.sleep(1.0)

        logger.error("Timeout waiting for checkpoint")
        return None

    async def coordination_loop(self):
        """Main coordination loop - monitors queue and manages training"""
        logger.info("Starting coordination loop")

        while not self._shutdown:
            try:
                # Check queue status
                status = await self.check_queue_status()

                # Handle state transitions based on queue
                if self.state == TrainingState.RUNNING and status.needs_pause:
                    logger.info(
                        f"Queue pressure detected: pending={status.pending}, "
                        f"avg_wait={status.avg_wait_time:.1f}s"
                    )
                    if self.pause_training():
                        # Wait for checkpoint
                        checkpoint = await self.wait_for_checkpoint()
                        if not checkpoint:
                            logger.error(
                                "Failed to get checkpoint, training may be corrupted"
                            )

                elif self.state == TrainingState.PAUSED and status.can_resume:
                    logger.info("Queue cleared, resuming training")
                    await asyncio.sleep(CONFIG["resume_delay"])
                    self.resume_training()

                # Check if training process ended
                if self._process and self._process.poll() is not None:
                    exit_code = self._process.returncode
                    if exit_code == 0:
                        logger.info("Training completed successfully")
                        self._set_state(TrainingState.COMPLETED)
                    else:
                        logger.error(f"Training failed with exit code {exit_code}")
                        self._set_state(TrainingState.FAILED)
                    self._process = None

                await asyncio.sleep(CONFIG["poll_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Coordination loop error: {e}")
                await asyncio.sleep(CONFIG["poll_interval"])

        logger.info("Coordination loop ended")

    def get_status(self) -> Dict[str, Any]:
        """Get current coordinator status"""
        return {
            "state": self.state.value,
            "session": {
                "pid": self.session.pid if self.session else None,
                "started_at": self.session.started_at if self.session else None,
                "current_epoch": self.session.current_epoch if self.session else None,
                "current_step": self.session.current_step if self.session else None,
                "pause_count": self.session.pause_count if self.session else 0,
                "total_pause_time": (
                    self.session.total_pause_time if self.session else 0
                ),
                "last_checkpoint": (
                    self.session.last_checkpoint if self.session else None
                ),
                "model": self.session.model if self.session else None,
                "dataset": self.session.dataset if self.session else None,
            },
            "queue": {
                "pending": self.queue_status.pending,
                "processing": self.queue_status.processing,
                "avg_wait_time": self.queue_status.avg_wait_time,
                "needs_pause": self.queue_status.needs_pause,
                "can_resume": self.queue_status.can_resume,
            },
        }

    def shutdown(self):
        """Graceful shutdown"""
        self._shutdown = True
        self.stop_training()


# Global coordinator instance
coordinator: Optional[NativeTrainingCoordinator] = None


def get_coordinator() -> NativeTrainingCoordinator:
    """Get or create coordinator singleton"""
    global coordinator
    if coordinator is None:
        coordinator = NativeTrainingCoordinator()
    return coordinator


async def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Native Training Coordinator")
    parser.add_argument(
        "action", choices=["start", "stop", "pause", "resume", "status", "daemon"]
    )
    parser.add_argument("--model", default="yolov8n.pt", help="Model to train")
    parser.add_argument("--dataset", default="wider_face", help="Dataset name")
    parser.add_argument("--epochs", type=int, default=100, help="Number of epochs")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--resume", help="Resume from checkpoint")

    args = parser.parse_args()

    coord = get_coordinator()

    if args.action == "start":
        success = await coord.start_training(
            model=args.model,
            dataset=args.dataset,
            epochs=args.epochs,
            batch_size=args.batch,
            imgsz=args.imgsz,
            resume_from=args.resume,
        )
        print(f"Training {'started' if success else 'failed to start'}")

    elif args.action == "stop":
        coord.stop_training()
        print("Training stopped")

    elif args.action == "pause":
        coord.pause_training()
        print("Pause signal sent")

    elif args.action == "resume":
        coord.resume_training()
        print("Resume signal sent")

    elif args.action == "status":
        status = coord.get_status()
        print(json.dumps(status, indent=2))

    elif args.action == "daemon":
        # Run as daemon
        loop_task = asyncio.create_task(coord.coordination_loop())

        # Handle signals
        def signal_handler(signum, frame):
            coord.shutdown()

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        await loop_task


if __name__ == "__main__":
    asyncio.run(main())
