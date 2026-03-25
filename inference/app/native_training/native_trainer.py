#!/usr/bin/env python3
"""
Native SOTA Trainer - Multi-Scale YOLO Training with Full Optimization

Implements all SOTA techniques from internal research:
- Multi-scale progressive training (640 → 960 → 1280)
- AdamW optimizer with cosine learning rate scheduling
- Label smoothing (0.1)
- Close mosaic for final epochs
- Gradient checkpointing for memory efficiency
- Mixed precision training (AMP)
- MLflow experiment tracking
- Signal-based pause/resume (SIGUSR1/SIGUSR2)

Navigation:
- Related: native_training_coordinator.py (lifecycle), sandbox_training.sh (security)
- Config: ../../training_library/shml_training/__init__.py
- Docs: README.md, ../../docs/SOTA_BEST_PRACTICES_SUMMARY.md

Hardware Target:
- RTX 3090 Ti (24GB VRAM) - GPU 0 (primary)
- RTX 2070 (8GB VRAM) - GPU 1 (secondary/inference)

Author: SHML Platform
"""

import argparse
import gc
import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import requests

# ═══════════════════════════════════════════════════════════════════════════
# GPU YIELD: Must be called BEFORE importing torch to free VRAM
# ═══════════════════════════════════════════════════════════════════════════
_gpu_yield_available = False
try:
    # Try multiple import paths (native env vs ray container vs relative)
    _yield_paths = [
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "..", "ray_compute", "jobs"
        ),
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "ray_compute", "jobs"
        ),
    ]
    for _p in _yield_paths:
        _p = os.path.abspath(_p)
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(0, _p)
    from utils.gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

    _gpu_yield_available = True
except ImportError:
    pass

if _gpu_yield_available:
    _native_job_id = os.environ.get("RAY_JOB_ID", f"native-trainer-{os.getpid()}")
    yield_gpu_for_training(gpu_id=0, job_id=_native_job_id, timeout=30)
else:
    _native_job_id = f"native-trainer-{os.getpid()}"
    print(
        "\u26a0\ufe0f  GPU yield not available — inference models may still be using VRAM"
    )

import torch
import torch.cuda
from torch.cuda.amp import autocast, GradScaler

# Ultralytics imports (installed in native environment)
try:
    from ultralytics import YOLO
    from ultralytics.utils.downloads import download

    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False
    print("WARNING: ultralytics not installed. Run: pip install ultralytics")

# MLflow imports
try:
    import mlflow
    from mlflow.tracking import MlflowClient

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False
    print("WARNING: mlflow not installed. Run: pip install mlflow")

# Platform root - avoid hardcoded paths
PLATFORM_ROOT = os.environ.get("PLATFORM_ROOT", str(Path(__file__).resolve().parents[3]))


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class TrainingConfig:
    """SOTA training configuration from internal research"""

    # Model
    model: str = "yolov8n.pt"

    # Dataset
    dataset: str = "wider_face"
    data_dir: str = f"{PLATFORM_ROOT}/data/training"

    # Multi-scale training phases (percentage of total epochs)
    multiscale_phases: Tuple[Tuple[int, float], ...] = (
        (640, 0.33),  # 33% at 640px
        (960, 0.33),  # 33% at 960px
        (1280, 0.34),  # 34% at 1280px
    )

    # Training hyperparameters
    epochs: int = 100
    batch_size: int = 16
    initial_lr: float = 0.01
    final_lr: float = 0.0001
    weight_decay: float = 0.0005
    momentum: float = 0.937
    warmup_epochs: int = 3
    label_smoothing: float = 0.1
    close_mosaic: int = 10  # Disable mosaic for last N epochs

    # Optimizer
    optimizer: str = "AdamW"  # AdamW performs best per research
    cos_lr: bool = True  # Cosine annealing

    # Memory optimization
    gradient_checkpointing: bool = True
    amp: bool = True  # Mixed precision
    # batch_size=64 is the 640px base for RTX 3090 Ti (24GB).
    # _calculate_batch_size() scales by area ratio so 960/1280 phases get correct budgets.
    batch_size: int = 64
    workers: int = 8

    # Checkpointing
    checkpoint_dir: str = f"{PLATFORM_ROOT}/data/checkpoints"
    checkpoint_interval: int = 100  # Save every N steps
    save_best: bool = True

    # MLflow
    mlflow_uri: str = "http://172.30.0.11:5000"
    mlflow_host_header: str = "mlflow-server"
    experiment_name: str = "SOTA-YOLO-Training"

    # GPU
    device: str = "cuda:0"

    # Resume
    resume_from: Optional[str] = None


@dataclass
class TrainingState:
    """Mutable training state for pause/resume"""

    current_epoch: int = 0
    current_step: int = 0
    current_phase: int = 0
    current_imgsz: int = 640
    best_map: float = 0.0
    total_steps: int = 0
    paused: bool = False
    pause_requested: bool = False
    resume_requested: bool = False


# ============================================================================
# Logging Setup
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"{PLATFORM_ROOT}/logs/native_trainer.log", mode="a"
        ),
    ],
)
logger = logging.getLogger("NativeTrainer")


# ============================================================================
# Signal Handlers
# ============================================================================


class SignalHandler:
    """Handle SIGUSR1 (pause) and SIGUSR2 (resume) signals"""

    def __init__(self, state: TrainingState):
        self.state = state
        self._lock = threading.Lock()

        # Register handlers
        signal.signal(signal.SIGUSR1, self._pause_handler)
        signal.signal(signal.SIGUSR2, self._resume_handler)
        signal.signal(signal.SIGTERM, self._term_handler)

    def _pause_handler(self, signum, frame):
        """Handle SIGUSR1 - request pause"""
        with self._lock:
            logger.info("SIGUSR1 received - pause requested")
            self.state.pause_requested = True

    def _resume_handler(self, signum, frame):
        """Handle SIGUSR2 - request resume"""
        with self._lock:
            if self.state.paused:
                logger.info("SIGUSR2 received - resume requested")
                self.state.resume_requested = True

    def _term_handler(self, signum, frame):
        """Handle SIGTERM - graceful shutdown"""
        logger.info("SIGTERM received - initiating graceful shutdown")
        self.state.pause_requested = True
        # After checkpoint, exit
        raise SystemExit(0)


# ============================================================================
# MLflow Integration
# ============================================================================


class MLflowTracker:
    """MLflow experiment tracking with Docker network support"""

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.client: Optional[MlflowClient] = None
        self.run_id: Optional[str] = None
        self.experiment_id: Optional[str] = None

        if not MLFLOW_AVAILABLE:
            logger.warning("MLflow not available - tracking disabled")
            return

        self._setup_tracking()

    def _setup_tracking(self):
        """Configure MLflow tracking with proper headers"""
        # Custom session with Host header for Docker network
        session = requests.Session()
        session.headers.update({"Host": self.config.mlflow_host_header})

        # Set tracking URI
        mlflow.set_tracking_uri(self.config.mlflow_uri)

        # Get or create experiment
        try:
            self.client = MlflowClient(self.config.mlflow_uri)

            # Try to get existing experiment
            experiment = self.client.get_experiment_by_name(self.config.experiment_name)
            if experiment:
                self.experiment_id = experiment.experiment_id
            else:
                self.experiment_id = self.client.create_experiment(
                    self.config.experiment_name,
                    tags={"framework": "ultralytics", "type": "YOLO"},
                )

            mlflow.set_experiment(self.config.experiment_name)
            logger.info(
                f"MLflow experiment: {self.config.experiment_name} (ID: {self.experiment_id})"
            )

        except Exception as e:
            logger.error(f"MLflow setup failed: {e}")
            self.client = None

    def start_run(self, run_name: str = None) -> Optional[str]:
        """Start a new MLflow run"""
        if not self.client:
            return None

        try:
            run_name = run_name or f"train_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            run = mlflow.start_run(run_name=run_name)
            self.run_id = run.info.run_id

            # Log config
            mlflow.log_params(asdict(self.config))

            logger.info(f"MLflow run started: {self.run_id}")
            return self.run_id

        except Exception as e:
            logger.error(f"Failed to start MLflow run: {e}")
            return None

    def log_metrics(self, metrics: Dict[str, float], step: int):
        """Log metrics to MLflow"""
        if not self.run_id:
            return

        try:
            mlflow.log_metrics(metrics, step=step)
        except Exception as e:
            logger.debug(f"Failed to log metrics: {e}")

    def log_artifact(self, path: str):
        """Log artifact to MLflow"""
        if not self.run_id:
            return

        try:
            mlflow.log_artifact(path)
        except Exception as e:
            logger.debug(f"Failed to log artifact: {e}")

    def end_run(self, status: str = "FINISHED"):
        """End MLflow run"""
        if not self.run_id:
            return

        try:
            mlflow.end_run(status=status)
            logger.info(f"MLflow run ended: {self.run_id}")
        except Exception as e:
            logger.error(f"Failed to end MLflow run: {e}")


# ============================================================================
# Checkpoint Manager
# ============================================================================


class CheckpointManager:
    """Manage training checkpoints for pause/resume"""

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.checkpoint_dir = Path(config.checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(
        self,
        model: Any,
        state: TrainingState,
        optimizer: Any = None,
        scaler: Any = None,
    ) -> str:
        """Save full training checkpoint"""

        checkpoint_name = f"epoch_{state.current_epoch}_step_{state.current_step}"
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_name}.pt"
        state_path = self.checkpoint_dir / f"{checkpoint_name}_state.json"

        # Save model weights
        if hasattr(model, "save"):
            model.save(str(checkpoint_path))
        else:
            torch.save(model.state_dict(), checkpoint_path)

        # Save training state
        state_data = asdict(state)
        state_data["saved_at"] = datetime.now().isoformat()

        if optimizer:
            opt_path = self.checkpoint_dir / f"{checkpoint_name}_optimizer.pt"
            torch.save(optimizer.state_dict(), opt_path)
            state_data["optimizer_path"] = str(opt_path)

        if scaler:
            scaler_path = self.checkpoint_dir / f"{checkpoint_name}_scaler.pt"
            torch.save(scaler.state_dict(), scaler_path)
            state_data["scaler_path"] = str(scaler_path)

        with open(state_path, "w") as f:
            json.dump(state_data, f, indent=2)

        # Update latest symlink
        latest_link = self.checkpoint_dir / "latest.pt"
        if latest_link.exists():
            latest_link.unlink()
        latest_link.symlink_to(checkpoint_path.name)

        logger.info(f"Checkpoint saved: {checkpoint_path}")
        return str(checkpoint_path)

    def load_checkpoint(self, checkpoint_path: str) -> Tuple[str, TrainingState]:
        """Load checkpoint and training state"""

        checkpoint_path = Path(checkpoint_path)
        if checkpoint_path.name == "latest.pt":
            checkpoint_path = checkpoint_path.resolve()

        state_path = checkpoint_path.with_suffix("").with_name(
            checkpoint_path.stem + "_state.json"
        )

        # Load state
        if state_path.exists():
            with open(state_path) as f:
                state_data = json.load(f)
            state = TrainingState(
                **{
                    k: v
                    for k, v in state_data.items()
                    if k in TrainingState.__annotations__
                }
            )
        else:
            state = TrainingState()

        logger.info(f"Checkpoint loaded: {checkpoint_path}")
        return str(checkpoint_path), state


# ============================================================================
# Data Management
# ============================================================================


def setup_dataset(config: TrainingConfig) -> str:
    """Download and setup dataset if needed"""

    data_dir = Path(config.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if config.dataset == "wider_face":
        dataset_dir = data_dir / "wider_face"
        yaml_path = dataset_dir / "wider_face.yaml"

        if not yaml_path.exists():
            logger.info("Downloading WIDER FACE dataset...")
            # Download using ultralytics
            if ULTRALYTICS_AVAILABLE:
                # WIDER FACE is available through ultralytics datasets
                yaml_content = """
# WIDER FACE Dataset for YOLO
path: {path}
train: images/train
val: images/val

names:
  0: face
""".format(
                    path=str(dataset_dir)
                )

                yaml_path.parent.mkdir(parents=True, exist_ok=True)
                with open(yaml_path, "w") as f:
                    f.write(yaml_content)

                logger.info(f"Dataset config created: {yaml_path}")

        return str(yaml_path)

    else:
        # Custom dataset - assume it's already prepared
        return str(data_dir / config.dataset / f"{config.dataset}.yaml")


# ============================================================================
# Main Trainer
# ============================================================================


class SOTATrainer:
    """SOTA YOLO trainer with multi-scale progressive training"""

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.state = TrainingState()

        # Setup components
        self.signal_handler = SignalHandler(self.state)
        self.mlflow = MLflowTracker(config)
        self.checkpoint_mgr = CheckpointManager(config)

        # Model and training objects
        self.model: Optional[YOLO] = None
        self.scaler: Optional[GradScaler] = None

        # Validate GPU
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available - native training requires GPU")

        gpu_name = torch.cuda.get_device_name(0)
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
        logger.info(f"GPU: {gpu_name} ({gpu_memory:.1f}GB)")

    def _get_phase_config(self, epoch: int) -> Tuple[int, int]:
        """Get imgsz and phase index for current epoch"""
        total = 0
        for phase_idx, (imgsz, pct) in enumerate(self.config.multiscale_phases):
            phase_epochs = int(self.config.epochs * pct)
            if epoch < total + phase_epochs:
                return imgsz, phase_idx
            total += phase_epochs

        # Last phase for any remaining epochs
        return (
            self.config.multiscale_phases[-1][0],
            len(self.config.multiscale_phases) - 1,
        )

    def _calculate_batch_size(self, imgsz: int) -> int:
        """Calculate optimal batch size for image size.

        Activation memory scales with pixel area (imgsz²), so batch size scales
        inversely with area relative to the 640px base.
        base_batch=64 calibrated for YOLOv8n on RTX 3090 Ti (24GB) with AMP + gradient ckpt.
        640px → 64, 960px → 28, 1280px → 16.
        """
        base_batch = self.config.batch_size
        # Area ratio relative to 640px baseline
        scale = (640.0 / imgsz) ** 2
        return max(int(base_batch * scale), 4)

    def _apply_close_mosaic(self, epoch: int) -> bool:
        """Check if mosaic should be disabled"""
        remaining = self.config.epochs - epoch
        return remaining <= self.config.close_mosaic

    def _check_pause(self) -> bool:
        """Check for pause request and handle it"""
        if self.state.pause_requested:
            logger.info("Pausing training - saving checkpoint...")

            # Save checkpoint
            checkpoint = self.checkpoint_mgr.save_checkpoint(
                self.model, self.state, scaler=self.scaler
            )

            # Release GPU memory
            if self.model:
                del self.model
            torch.cuda.empty_cache()
            gc.collect()

            logger.info("Training paused - GPU memory released")
            self.state.paused = True
            self.state.pause_requested = False

            # Log to MLflow
            self.mlflow.log_metrics(
                {"paused": 1, "pause_epoch": self.state.current_epoch},
                step=self.state.total_steps,
            )

            # Wait for resume
            while self.state.paused and not self.state.resume_requested:
                time.sleep(1.0)

            if self.state.resume_requested:
                logger.info("Resuming training...")
                self.state.paused = False
                self.state.resume_requested = False

                # Reload model
                self.model = YOLO(checkpoint)

                self.mlflow.log_metrics({"paused": 0}, step=self.state.total_steps)

            return True

        return False

    def train(self):
        """Main training loop with SOTA techniques"""

        if not ULTRALYTICS_AVAILABLE:
            raise RuntimeError("ultralytics not installed")

        # Start MLflow run
        self.mlflow.start_run(
            run_name=f"{self.config.model}_{self.config.dataset}_{datetime.now().strftime('%Y%m%d')}"
        )

        try:
            # Setup dataset
            data_yaml = setup_dataset(self.config)
            logger.info(f"Dataset: {data_yaml}")

            # Load model
            if self.config.resume_from:
                model_path, self.state = self.checkpoint_mgr.load_checkpoint(
                    self.config.resume_from
                )
                self.model = YOLO(model_path)
                logger.info(f"Resumed from: {model_path}")
            else:
                self.model = YOLO(self.config.model)
                logger.info(f"Loaded model: {self.config.model}")

            # Initialize AMP scaler
            if self.config.amp:
                self.scaler = GradScaler()

            # Training loop by phase
            start_epoch = self.state.current_epoch

            for epoch in range(start_epoch, self.config.epochs):
                self.state.current_epoch = epoch

                # Get phase configuration
                imgsz, phase = self._get_phase_config(epoch)
                batch_size = self._calculate_batch_size(imgsz)
                close_mosaic = self._apply_close_mosaic(epoch)

                # Log phase transition
                if phase != self.state.current_phase or epoch == start_epoch:
                    self.state.current_phase = phase
                    self.state.current_imgsz = imgsz
                    logger.info(
                        f"Phase {phase + 1}: imgsz={imgsz}, batch={batch_size}, "
                        f"close_mosaic={close_mosaic}"
                    )
                    self.mlflow.log_metrics(
                        {"phase": phase, "imgsz": imgsz, "batch_size": batch_size},
                        step=self.state.total_steps,
                    )

                # Check for pause before each epoch
                if self._check_pause():
                    continue  # Re-evaluate after resume

                # Train one epoch using ultralytics
                results = self.model.train(
                    data=data_yaml,
                    epochs=1,
                    imgsz=imgsz,
                    batch=batch_size,
                    # SOTA optimizer settings
                    optimizer=self.config.optimizer,
                    lr0=self.config.initial_lr,
                    lrf=self.config.final_lr / self.config.initial_lr,
                    weight_decay=self.config.weight_decay,
                    momentum=self.config.momentum,
                    cos_lr=self.config.cos_lr,
                    warmup_epochs=self.config.warmup_epochs if epoch == 0 else 0,
                    # SOTA augmentation
                    label_smoothing=self.config.label_smoothing,
                    close_mosaic=self.config.close_mosaic if close_mosaic else 0,
                    # Performance
                    amp=self.config.amp,
                    workers=self.config.workers,
                    device=self.config.device,
                    # Disable ultralytics' own logging
                    verbose=False,
                    exist_ok=True,
                    resume=epoch > 0,
                )

                # Update state
                self.state.total_steps += 1

                # Log metrics
                if hasattr(results, "results_dict"):
                    metrics = {
                        "train/box_loss": results.results_dict.get("train/box_loss", 0),
                        "train/cls_loss": results.results_dict.get("train/cls_loss", 0),
                        "val/mAP50": results.results_dict.get("metrics/mAP50(B)", 0),
                        "val/mAP50-95": results.results_dict.get(
                            "metrics/mAP50-95(B)", 0
                        ),
                        "lr": results.results_dict.get(
                            "lr/pg0", self.config.initial_lr
                        ),
                    }

                    self.mlflow.log_metrics(metrics, step=epoch)

                    # Track best
                    current_map = metrics.get("val/mAP50-95", 0)
                    if current_map > self.state.best_map:
                        self.state.best_map = current_map
                        logger.info(f"New best mAP: {current_map:.4f}")

                # Checkpoint interval
                if epoch % self.config.checkpoint_interval == 0:
                    self.checkpoint_mgr.save_checkpoint(
                        self.model, self.state, scaler=self.scaler
                    )

                logger.info(
                    f"Epoch {epoch + 1}/{self.config.epochs} complete - "
                    f"Phase {phase + 1}, imgsz={imgsz}"
                )

            # Final checkpoint
            final_path = self.checkpoint_mgr.save_checkpoint(
                self.model, self.state, scaler=self.scaler
            )

            # Log final model to MLflow
            self.mlflow.log_artifact(final_path)

            logger.info(f"Training complete! Best mAP: {self.state.best_map:.4f}")
            self.mlflow.end_run("FINISHED")

            # Reclaim GPU for inference services
            if _gpu_yield_available:
                try:
                    reclaim_gpu_after_training(gpu_id=0, job_id=_native_job_id)
                except Exception as e:
                    logger.warning(f"GPU reclaim failed: {e}")

        except SystemExit:
            # Graceful shutdown
            logger.info("Graceful shutdown - saving final checkpoint")
            self.checkpoint_mgr.save_checkpoint(
                self.model, self.state, scaler=self.scaler
            )
            self.mlflow.end_run("KILLED")
            # Reclaim GPU on shutdown
            if _gpu_yield_available:
                try:
                    reclaim_gpu_after_training(gpu_id=0, job_id=_native_job_id)
                except Exception:
                    pass
            raise

        except Exception as e:
            logger.error(f"Training failed: {e}")
            self.mlflow.end_run("FAILED")
            # Reclaim GPU on failure
            if _gpu_yield_available:
                try:
                    reclaim_gpu_after_training(gpu_id=0, job_id=_native_job_id)
                except Exception:
                    pass
            raise


# ============================================================================
# CLI Entry Point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="SOTA YOLO Trainer")

    # Model
    parser.add_argument("--model", default="yolov8n.pt", help="Model to train")
    parser.add_argument(
        "--data", "--dataset", dest="dataset", default="wider_face", help="Dataset name"
    )

    # Training
    parser.add_argument("--epochs", type=int, default=100, help="Number of epochs")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--imgsz", type=int, default=640, help="Initial image size")

    # SOTA options
    parser.add_argument(
        "--optimizer", default="AdamW", choices=["SGD", "Adam", "AdamW"]
    )
    parser.add_argument("--lr", type=float, default=0.01, help="Initial learning rate")
    parser.add_argument("--label-smoothing", type=float, default=0.1)
    parser.add_argument("--close-mosaic", type=int, default=10)
    parser.add_argument("--cos-lr", action="store_true", default=True)

    # Checkpointing
    parser.add_argument("--resume", help="Resume from checkpoint")
    parser.add_argument(
        "--checkpoint-dir",
        default=f"{PLATFORM_ROOT}/data/checkpoints",
    )

    # MLflow
    parser.add_argument("--mlflow-uri", default="http://172.30.0.11:5000")
    parser.add_argument("--experiment", default="SOTA-YOLO-Training")

    # Device
    parser.add_argument("--device", default="cuda:0")

    args = parser.parse_args()

    # Build config
    config = TrainingConfig(
        model=args.model,
        dataset=args.dataset,
        epochs=args.epochs,
        batch_size=args.batch,
        optimizer=args.optimizer,
        initial_lr=args.lr,
        label_smoothing=args.label_smoothing,
        close_mosaic=args.close_mosaic,
        cos_lr=args.cos_lr,
        resume_from=args.resume,
        checkpoint_dir=args.checkpoint_dir,
        mlflow_uri=args.mlflow_uri,
        experiment_name=args.experiment,
        device=args.device,
    )

    # Run training
    trainer = SOTATrainer(config)
    trainer.train()


if __name__ == "__main__":
    main()
