"""
Training Callbacks Interface
License: Apache 2.0

Event-driven callback system for training monitoring and control.

Callbacks allow modular injection of functionality at different training stages:
- Logging (MLflow, TensorBoard, W&B)
- Metrics (Prometheus, custom dashboards)
- Checkpointing
- Early stopping
- Learning rate scheduling
- Custom analysis (failure analysis, dataset auditing)

Usage:
    from shml_training.core import Trainer, TrainingCallback

    class MyCallback(TrainingCallback):
        def on_epoch_end(self, trainer, epoch, metrics):
            print(f"Epoch {epoch}: loss={metrics['loss']:.4f}")

    trainer = Trainer(config, callbacks=[MyCallback()])
    trainer.train()
"""

from typing import Any, Dict, Optional
from abc import ABC, abstractmethod


class TrainingCallback(ABC):
    """
    Base class for training callbacks.

    All callback methods are optional - override only what you need.
    Methods are called in order: run → epoch → batch → step.
    """

    def on_run_start(self, trainer: "Trainer", config: Dict[str, Any]):
        """Called once at the start of training run."""
        pass

    def on_run_end(self, trainer: "Trainer", metrics: Dict[str, Any]):
        """Called once at the end of training run."""
        pass

    def on_epoch_start(self, trainer: "Trainer", epoch: int):
        """Called at the start of each epoch."""
        pass

    def on_epoch_end(self, trainer: "Trainer", epoch: int, metrics: Dict[str, Any]):
        """Called at the end of each epoch."""
        pass

    def on_batch_start(self, trainer: "Trainer", batch_idx: int, batch: Any):
        """Called before processing each batch."""
        pass

    def on_batch_end(
        self, trainer: "Trainer", batch_idx: int, batch: Any, outputs: Any
    ):
        """Called after processing each batch."""
        pass

    def on_step(
        self,
        trainer: "Trainer",
        step: int,
        loss: float,
        metrics: Optional[Dict[str, Any]] = None,
    ):
        """Called after each optimization step."""
        pass

    def on_validation_start(self, trainer: "Trainer", epoch: int):
        """Called at the start of validation."""
        pass

    def on_validation_end(
        self, trainer: "Trainer", epoch: int, metrics: Dict[str, Any]
    ):
        """Called at the end of validation."""
        pass

    def on_checkpoint_saved(
        self, trainer: "Trainer", checkpoint_path: str, metrics: Dict[str, Any]
    ):
        """Called after saving a checkpoint."""
        pass

    def on_early_stop(self, trainer: "Trainer", epoch: int, reason: str):
        """Called when training is stopped early."""
        pass

    def on_error(self, trainer: "Trainer", error: Exception):
        """Called when an error occurs during training."""
        pass


class CallbackList:
    """
    Manages a list of callbacks and invokes them in order.

    Usage:
        callbacks = CallbackList([callback1, callback2])
        callbacks.on_epoch_end(trainer, epoch, metrics)
    """

    def __init__(self, callbacks: Optional[list] = None):
        self.callbacks = callbacks or []

    def add_callback(self, callback: TrainingCallback):
        """Add a callback to the list."""
        self.callbacks.append(callback)

    def remove_callback(self, callback: TrainingCallback):
        """Remove a callback from the list."""
        self.callbacks.remove(callback)

    def on_run_start(self, trainer: "Trainer", config: Dict[str, Any]):
        for cb in self.callbacks:
            cb.on_run_start(trainer, config)

    def on_run_end(self, trainer: "Trainer", metrics: Dict[str, Any]):
        for cb in self.callbacks:
            cb.on_run_end(trainer, metrics)

    def on_epoch_start(self, trainer: "Trainer", epoch: int):
        for cb in self.callbacks:
            cb.on_epoch_start(trainer, epoch)

    def on_epoch_end(self, trainer: "Trainer", epoch: int, metrics: Dict[str, Any]):
        for cb in self.callbacks:
            cb.on_epoch_end(trainer, epoch, metrics)

    def on_batch_start(self, trainer: "Trainer", batch_idx: int, batch: Any):
        for cb in self.callbacks:
            cb.on_batch_start(trainer, batch_idx, batch)

    def on_batch_end(
        self, trainer: "Trainer", batch_idx: int, batch: Any, outputs: Any
    ):
        for cb in self.callbacks:
            cb.on_batch_end(trainer, batch_idx, batch, outputs)

    def on_step(
        self,
        trainer: "Trainer",
        step: int,
        loss: float,
        metrics: Optional[Dict[str, Any]] = None,
    ):
        for cb in self.callbacks:
            cb.on_step(trainer, step, loss, metrics)

    def on_validation_start(self, trainer: "Trainer", epoch: int):
        for cb in self.callbacks:
            cb.on_validation_start(trainer, epoch)

    def on_validation_end(
        self, trainer: "Trainer", epoch: int, metrics: Dict[str, Any]
    ):
        for cb in self.callbacks:
            cb.on_validation_end(trainer, epoch, metrics)

    def on_checkpoint_saved(
        self, trainer: "Trainer", checkpoint_path: str, metrics: Dict[str, Any]
    ):
        for cb in self.callbacks:
            cb.on_checkpoint_saved(trainer, checkpoint_path, metrics)

    def on_early_stop(self, trainer: "Trainer", epoch: int, reason: str):
        for cb in self.callbacks:
            cb.on_early_stop(trainer, epoch, reason)

    def on_error(self, trainer: "Trainer", error: Exception):
        for cb in self.callbacks:
            cb.on_error(trainer, error)


__all__ = [
    "TrainingCallback",
    "CallbackList",
]
