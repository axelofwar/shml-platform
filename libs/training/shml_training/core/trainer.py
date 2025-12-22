"""
Base Trainer Class
License: Apache 2.0

Extensible training orchestrator for computer vision models.

Features:
- Framework-agnostic design (PyTorch, Ultralytics, custom)
- Callback-based extensibility
- Hardware-aware auto-configuration
- Checkpoint management with preemption support
- Memory optimization integration
- Progress tracking (AG-UI protocol)

Usage:
    from shml_training.core import Trainer, TrainingConfig

    config = TrainingConfig.auto_configure(
        model_size_billions=7,
        target_batch_size=8,
    )

    trainer = Trainer(config)
    results = trainer.train()
"""

import os
import time
import torch
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime

from .config import TrainingConfig
from .callbacks import TrainingCallback, CallbackList
from .checkpointing import CheckpointManager
from .hardware import HardwareDetector
from .memory import MemoryOptimizer


class Trainer:
    """
    Base trainer class for computer vision models.

    Provides common training infrastructure:
    - Configuration management
    - Hardware detection and optimization
    - Checkpoint management
    - Callback orchestration
    - Error handling and recovery

    Subclass this for framework-specific implementations:
    - UltralyticsTrainer (YOLOv8, YOLOv11, RTDETR)
    - PyTorchTrainer (custom models)
    - HuggingFaceTrainer (transformers)
    """

    def __init__(
        self,
        config: TrainingConfig,
        callbacks: Optional[List[TrainingCallback]] = None,
    ):
        """
        Initialize trainer.

        Args:
            config: Training configuration
            callbacks: List of training callbacks
        """
        self.config = config
        self.callbacks = CallbackList(callbacks or [])

        # Components (lazy initialized)
        self._checkpoint_mgr = None
        self._memory_optimizer = None
        self._hardware_profile = None

        # Training state
        self.current_epoch = 0
        self.global_step = 0
        self.best_metric = None
        self.run_id = None

        # Model and data (to be set by subclasses)
        self.model = None
        self.train_loader = None
        self.val_loader = None

        print(f"Trainer initialized: {self.__class__.__name__}")

    @property
    def checkpoint_manager(self) -> CheckpointManager:
        """Get checkpoint manager (lazy init)."""
        if self._checkpoint_mgr is None:
            checkpoint_dir = getattr(self.config, "checkpoint_dir", "./checkpoints")
            max_checkpoints = getattr(self.config, "max_checkpoints", 5)
            self._checkpoint_mgr = CheckpointManager(checkpoint_dir, max_checkpoints)
        return self._checkpoint_mgr

    @property
    def memory_optimizer(self) -> MemoryOptimizer:
        """Get memory optimizer (lazy init)."""
        if self._memory_optimizer is None:
            self._memory_optimizer = MemoryOptimizer(self.config)
        return self._memory_optimizer

    @property
    def hardware_profile(self):
        """Get hardware profile (lazy init)."""
        if self._hardware_profile is None:
            self._hardware_profile = HardwareDetector.detect()
        return self._hardware_profile

    def train(self) -> Dict[str, Any]:
        """
        Run training loop.

        Returns:
            Dictionary with training results and metrics.
        """
        try:
            # Generate run ID
            self.run_id = f"train-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

            # Notify callbacks
            self.callbacks.on_run_start(self, self.config.to_dict())

            # Setup
            self._setup()

            # Training loop
            for epoch in range(self.current_epoch, self.config.epochs):
                self.current_epoch = epoch

                # Epoch training
                epoch_metrics = self._train_epoch(epoch)

                # Validation
                if self._should_validate(epoch):
                    val_metrics = self._validate_epoch(epoch)
                    epoch_metrics.update(val_metrics)

                # Checkpointing
                if self._should_checkpoint(epoch):
                    checkpoint_path = self._save_checkpoint(epoch, epoch_metrics)
                    self.callbacks.on_checkpoint_saved(
                        self, checkpoint_path, epoch_metrics
                    )

                # Callbacks
                self.callbacks.on_epoch_end(self, epoch, epoch_metrics)

                # Early stopping
                if self._should_early_stop(epoch, epoch_metrics):
                    reason = f"Early stopping at epoch {epoch}"
                    self.callbacks.on_early_stop(self, epoch, reason)
                    break

            # Training complete
            final_metrics = self._finalize()
            self.callbacks.on_run_end(self, final_metrics)

            return {
                "run_id": self.run_id,
                "epochs_trained": self.current_epoch + 1,
                "global_steps": self.global_step,
                "metrics": final_metrics,
            }

        except Exception as e:
            error_msg = str(e)
            tb = traceback.format_exc()
            print(f"\n✗ Training failed: {error_msg}")
            print(tb)

            self.callbacks.on_error(self, e)
            raise

    def _setup(self):
        """
        Setup training components.

        Override this in subclasses to:
        - Load model
        - Prepare datasets
        - Initialize optimizer
        - Setup device
        """
        print(f"\n━━━ Setup ━━━")
        print(f"  Hardware: {self.hardware_profile.total_vram_gb:.1f} GB VRAM")
        print(f"  Device: {self.config.device}")
        print(f"  Epochs: {self.config.epochs}")
        print(f"  Batch size: {self.config.batch_size}")
        print()

    def _train_epoch(self, epoch: int) -> Dict[str, Any]:
        """
        Train one epoch.

        Override this in subclasses to implement training logic.

        Returns:
            Dictionary with epoch metrics (loss, accuracy, etc.)
        """
        self.callbacks.on_epoch_start(self, epoch)

        # Placeholder - subclasses should implement actual training
        print(f"Epoch {epoch + 1}/{self.config.epochs}")

        return {"loss": 0.0, "accuracy": 0.0}

    def _validate_epoch(self, epoch: int) -> Dict[str, Any]:
        """
        Validate one epoch.

        Override this in subclasses to implement validation logic.

        Returns:
            Dictionary with validation metrics.
        """
        self.callbacks.on_validation_start(self, epoch)

        # Placeholder - subclasses should implement actual validation
        val_metrics = {"val_loss": 0.0, "val_accuracy": 0.0}

        self.callbacks.on_validation_end(self, epoch, val_metrics)
        return val_metrics

    def _save_checkpoint(self, epoch: int, metrics: Dict[str, Any]) -> str:
        """
        Save model checkpoint.

        Override this in subclasses for framework-specific checkpoint format.

        Returns:
            Path to saved checkpoint.
        """
        checkpoint_path = f"{self.config.checkpoint_dir}/epoch_{epoch}.pt"
        print(f"  Saving checkpoint: {checkpoint_path}")
        return checkpoint_path

    def _should_validate(self, epoch: int) -> bool:
        """Check if should run validation this epoch."""
        val_interval = getattr(self.config, "val_interval", 1)
        return (epoch + 1) % val_interval == 0

    def _should_checkpoint(self, epoch: int) -> bool:
        """Check if should save checkpoint this epoch."""
        checkpoint_interval = getattr(self.config, "checkpoint_interval", 1)
        return (epoch + 1) % checkpoint_interval == 0

    def _should_early_stop(self, epoch: int, metrics: Dict[str, Any]) -> bool:
        """
        Check if should stop training early.

        Override this to implement custom early stopping logic.
        """
        return False

    def _finalize(self) -> Dict[str, Any]:
        """
        Finalize training and return final metrics.

        Override this in subclasses for final export, evaluation, etc.
        """
        print("\n━━━ Training Complete ━━━")
        return {}

    def resume(self, checkpoint_path: str):
        """
        Resume training from checkpoint.

        Override this in subclasses for framework-specific checkpoint loading.
        """
        print(f"Resuming from checkpoint: {checkpoint_path}")
        # Subclasses should load checkpoint and set self.current_epoch


class UltralyticsTrainer(Trainer):
    """
    Trainer for Ultralytics models (YOLOv8, YOLOv11, RTDETR).

    Wraps the Ultralytics training API with SHML callback system.
    """

    def __init__(
        self,
        config: TrainingConfig,
        model_name: str = "yolov8n.pt",
        callbacks: Optional[List[TrainingCallback]] = None,
    ):
        super().__init__(config, callbacks)
        self.model_name = model_name

    def _setup(self):
        """Setup Ultralytics model."""
        from ultralytics import YOLO

        super()._setup()

        print(f"  Loading model: {self.model_name}")
        self.model = YOLO(self.model_name)
        print(f"  Model loaded: {type(self.model).__name__}")

    def train(self) -> Dict[str, Any]:
        """
        Train using Ultralytics API.

        Delegates to ultralytics.YOLO.train() but wraps with callbacks.
        """
        try:
            self.run_id = f"train-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            self.callbacks.on_run_start(self, self.config.to_dict())

            # Setup model
            self._setup()

            # Build training kwargs from config
            train_kwargs = {
                "epochs": self.config.epochs,
                "batch": self.config.batch_size,
                "imgsz": getattr(self.config, "imgsz", 640),
                "device": self.config.device,
                "project": Path(self.config.checkpoint_dir).parent,
                "name": Path(self.config.checkpoint_dir).name,
                "exist_ok": True,
                "verbose": True,
            }

            # Add optional parameters
            for param in ["lr0", "lrf", "momentum", "weight_decay", "optimizer"]:
                if hasattr(self.config, param):
                    train_kwargs[param] = getattr(self.config, param)

            print(f"\n━━━ Training Parameters ━━━")
            for k, v in train_kwargs.items():
                print(f"  {k}: {v}")
            print()

            # Train (Ultralytics handles the loop)
            results = self.model.train(**train_kwargs)

            # Extract final metrics
            final_metrics = self._extract_ultralytics_metrics(results)

            self.callbacks.on_run_end(self, final_metrics)

            return {
                "run_id": self.run_id,
                "metrics": final_metrics,
                "results": results,
            }

        except Exception as e:
            self.callbacks.on_error(self, e)
            raise

    def _extract_ultralytics_metrics(self, results) -> Dict[str, Any]:
        """Extract metrics from Ultralytics results object."""
        if results is None:
            return {}

        metrics = {}

        # Get results dictionary
        if hasattr(results, "results_dict"):
            metrics = results.results_dict
        elif hasattr(results, "metrics"):
            metrics = results.metrics

        return metrics


__all__ = [
    "Trainer",
    "UltralyticsTrainer",
]
