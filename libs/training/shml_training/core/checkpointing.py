"""
Checkpointing utilities for SHML Training Library.

Provides robust checkpointing with:
- Automatic saving on preemption signals
- Snapshot management with rotation
- Resume from any checkpoint
"""

import os
import signal
import json
import shutil
import torch
import torch.nn as nn
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Union, Callable
from dataclasses import dataclass, asdict
import threading
import atexit


@dataclass
class CheckpointMetadata:
    """Metadata stored with each checkpoint."""

    epoch: int
    global_step: int
    timestamp: str
    metrics: Dict[str, float]
    config: Dict[str, Any]
    is_best: bool = False
    is_preemption: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointMetadata":
        return cls(**data)


class CheckpointManager:
    """
    Manages training checkpoints with automatic rotation and cleanup.

    Features:
    - Save/load model, optimizer, scheduler, and custom state
    - Automatic checkpoint rotation (keep last N)
    - Best checkpoint tracking
    - Preemption-safe checkpointing
    - Atomic writes to prevent corruption

    Usage:
        manager = CheckpointManager('./checkpoints', keep_last=3)

        # Save checkpoint
        manager.save(
            epoch=10,
            model=model,
            optimizer=optimizer,
            metrics={'loss': 0.5, 'accuracy': 0.95},
        )

        # Load checkpoint
        state = manager.load_latest()
        model.load_state_dict(state['model'])
    """

    def __init__(
        self,
        checkpoint_dir: Union[str, Path],
        keep_last: int = 3,
        keep_best: int = 1,
        best_metric: str = "loss",
        best_mode: str = "min",  # 'min' or 'max'
    ):
        """
        Args:
            checkpoint_dir: Directory to store checkpoints
            keep_last: Number of recent checkpoints to keep
            keep_best: Number of best checkpoints to keep
            best_metric: Metric name for best checkpoint selection
            best_mode: 'min' or 'max' for best metric comparison
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.keep_last = keep_last
        self.keep_best = keep_best
        self.best_metric = best_metric
        self.best_mode = best_mode

        self._best_value: Optional[float] = None
        self._checkpoints: List[Path] = []
        self._best_checkpoints: List[Path] = []

        # Load existing checkpoint history
        self._load_history()

    def _load_history(self) -> None:
        """Load checkpoint history from directory."""
        self._checkpoints = sorted(
            self.checkpoint_dir.glob("checkpoint_*.pt"),
            key=lambda p: p.stat().st_mtime,
        )
        self._best_checkpoints = sorted(
            self.checkpoint_dir.glob("best_*.pt"),
            key=lambda p: p.stat().st_mtime,
        )

    def save(
        self,
        epoch: int,
        model: nn.Module,
        optimizer: Optional[torch.optim.Optimizer] = None,
        scheduler: Optional[Any] = None,
        metrics: Optional[Dict[str, float]] = None,
        config: Optional[Dict[str, Any]] = None,
        global_step: int = 0,
        extra_state: Optional[Dict[str, Any]] = None,
        is_preemption: bool = False,
    ) -> Path:
        """
        Save a checkpoint.

        Args:
            epoch: Current epoch number
            model: Model to save
            optimizer: Optimizer state (optional)
            scheduler: LR scheduler state (optional)
            metrics: Training metrics dict
            config: Training config dict
            global_step: Global training step
            extra_state: Any additional state to save
            is_preemption: Whether this is a preemption checkpoint

        Returns:
            Path to saved checkpoint
        """
        metrics = metrics or {}
        config = config or {}

        # Determine if this is the best checkpoint
        is_best = self._check_is_best(metrics)

        # Build checkpoint state
        state = {
            "epoch": epoch,
            "global_step": global_step,
            "model_state_dict": model.state_dict(),
        }

        if optimizer is not None:
            state["optimizer_state_dict"] = optimizer.state_dict()

        if scheduler is not None:
            state["scheduler_state_dict"] = scheduler.state_dict()

        if extra_state:
            state["extra_state"] = extra_state

        # Add metadata
        metadata = CheckpointMetadata(
            epoch=epoch,
            global_step=global_step,
            timestamp=datetime.now().isoformat(),
            metrics=metrics,
            config=config,
            is_best=is_best,
            is_preemption=is_preemption,
        )
        state["metadata"] = metadata.to_dict()

        # Save checkpoint atomically
        if is_preemption:
            filename = f"preemption_epoch{epoch}_step{global_step}.pt"
        else:
            filename = f"checkpoint_epoch{epoch}_step{global_step}.pt"

        checkpoint_path = self.checkpoint_dir / filename
        temp_path = checkpoint_path.with_suffix(".tmp")

        torch.save(state, temp_path)
        temp_path.rename(checkpoint_path)

        self._checkpoints.append(checkpoint_path)

        # Save best checkpoint
        if is_best:
            best_path = self.checkpoint_dir / f"best_epoch{epoch}.pt"
            shutil.copy(checkpoint_path, best_path)
            self._best_checkpoints.append(best_path)
            self._cleanup_best()

        # Cleanup old checkpoints
        self._cleanup_old()

        # Save metadata separately for quick access
        self._save_metadata(metadata, checkpoint_path)

        return checkpoint_path

    def _check_is_best(self, metrics: Dict[str, float]) -> bool:
        """Check if current metrics are the best so far."""
        if self.best_metric not in metrics:
            return False

        current_value = metrics[self.best_metric]

        if self._best_value is None:
            self._best_value = current_value
            return True

        if self.best_mode == "min":
            is_best = current_value < self._best_value
        else:
            is_best = current_value > self._best_value

        if is_best:
            self._best_value = current_value

        return is_best

    def _cleanup_old(self) -> None:
        """Remove old checkpoints beyond keep_last."""
        # Don't delete preemption checkpoints automatically
        regular_checkpoints = [
            p for p in self._checkpoints if not p.name.startswith("preemption_")
        ]

        while len(regular_checkpoints) > self.keep_last:
            oldest = regular_checkpoints.pop(0)
            if oldest.exists():
                oldest.unlink()
            if oldest in self._checkpoints:
                self._checkpoints.remove(oldest)

    def _cleanup_best(self) -> None:
        """Remove old best checkpoints beyond keep_best."""
        while len(self._best_checkpoints) > self.keep_best:
            oldest = self._best_checkpoints.pop(0)
            if oldest.exists():
                oldest.unlink()

    def _save_metadata(
        self, metadata: CheckpointMetadata, checkpoint_path: Path
    ) -> None:
        """Save metadata to JSON for quick access."""
        metadata_path = checkpoint_path.with_suffix(".json")
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

    def load(
        self,
        checkpoint_path: Union[str, Path],
        model: nn.Module,
        optimizer: Optional[torch.optim.Optimizer] = None,
        scheduler: Optional[Any] = None,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """
        Load a specific checkpoint.

        Args:
            checkpoint_path: Path to checkpoint file
            model: Model to load state into
            optimizer: Optimizer to load state into (optional)
            scheduler: Scheduler to load state into (optional)
            strict: Whether to strictly enforce state_dict keys match

        Returns:
            Dictionary with loaded state and metadata
        """
        checkpoint_path = Path(checkpoint_path)

        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        state = torch.load(checkpoint_path, map_location="cpu")

        # Load model
        model.load_state_dict(state["model_state_dict"], strict=strict)

        # Load optimizer
        if optimizer is not None and "optimizer_state_dict" in state:
            optimizer.load_state_dict(state["optimizer_state_dict"])

        # Load scheduler
        if scheduler is not None and "scheduler_state_dict" in state:
            scheduler.load_state_dict(state["scheduler_state_dict"])

        return {
            "epoch": state.get("epoch", 0),
            "global_step": state.get("global_step", 0),
            "metadata": state.get("metadata", {}),
            "extra_state": state.get("extra_state", {}),
        }

    def load_latest(
        self,
        model: nn.Module,
        optimizer: Optional[torch.optim.Optimizer] = None,
        scheduler: Optional[Any] = None,
        strict: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Load the most recent checkpoint."""
        if not self._checkpoints:
            return None

        latest = self._checkpoints[-1]
        return self.load(latest, model, optimizer, scheduler, strict)

    def load_best(
        self,
        model: nn.Module,
        optimizer: Optional[torch.optim.Optimizer] = None,
        scheduler: Optional[Any] = None,
        strict: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Load the best checkpoint."""
        if not self._best_checkpoints:
            return None

        best = self._best_checkpoints[-1]
        return self.load(best, model, optimizer, scheduler, strict)

    def get_latest_path(self) -> Optional[Path]:
        """Get path to latest checkpoint."""
        return self._checkpoints[-1] if self._checkpoints else None

    def get_best_path(self) -> Optional[Path]:
        """Get path to best checkpoint."""
        return self._best_checkpoints[-1] if self._best_checkpoints else None

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """List all checkpoints with metadata."""
        checkpoints = []

        for path in self._checkpoints:
            metadata_path = path.with_suffix(".json")
            if metadata_path.exists():
                with open(metadata_path) as f:
                    metadata = json.load(f)
            else:
                metadata = {"path": str(path)}

            metadata["path"] = str(path)
            metadata["size_mb"] = path.stat().st_size / 1024**2
            checkpoints.append(metadata)

        return checkpoints


class PreemptionHandler:
    """
    Handles preemption signals for graceful checkpoint saving.

    Supports:
    - SIGTERM (Kubernetes, Ray preemption)
    - SIGINT (Ctrl+C)
    - SIGUSR1 (Manual checkpoint request)

    Usage:
        handler = PreemptionHandler(checkpoint_manager)
        handler.register()

        # In training loop
        if handler.should_checkpoint():
            save_checkpoint()
            handler.acknowledge_checkpoint()
    """

    def __init__(
        self,
        checkpoint_callback: Callable[[], None],
        signals: Optional[List[signal.Signals]] = None,
    ):
        """
        Args:
            checkpoint_callback: Function to call to save checkpoint
            signals: List of signals to handle (default: SIGTERM, SIGINT, SIGUSR1)
        """
        self.checkpoint_callback = checkpoint_callback
        self.signals = signals or [signal.SIGTERM, signal.SIGINT]

        # Add SIGUSR1 on Unix
        if hasattr(signal, "SIGUSR1"):
            self.signals.append(signal.SIGUSR1)

        self._preemption_requested = threading.Event()
        self._checkpoint_done = threading.Event()
        self._original_handlers: Dict[signal.Signals, Any] = {}
        self._registered = False

    def register(self) -> None:
        """Register signal handlers."""
        if self._registered:
            return

        for sig in self.signals:
            try:
                self._original_handlers[sig] = signal.signal(sig, self._handle_signal)
            except (ValueError, OSError):
                # Signal not available on this platform
                pass

        # Also register atexit handler
        atexit.register(self._atexit_handler)

        self._registered = True

    def unregister(self) -> None:
        """Restore original signal handlers."""
        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass

        self._original_handlers.clear()
        self._registered = False

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle preemption signal."""
        sig_name = signal.Signals(signum).name
        print(f"\n⚠️  Received {sig_name} - saving checkpoint...")

        self._preemption_requested.set()

        # Call checkpoint callback
        try:
            self.checkpoint_callback()
            self._checkpoint_done.set()
            print("✅ Checkpoint saved successfully")
        except Exception as e:
            print(f"❌ Checkpoint save failed: {e}")

        # For SIGTERM/SIGINT, exit after checkpoint
        if signum in (signal.SIGTERM, signal.SIGINT):
            raise SystemExit(0)

    def _atexit_handler(self) -> None:
        """Handle program exit."""
        if not self._checkpoint_done.is_set():
            print("\n⚠️  Saving checkpoint on exit...")
            try:
                self.checkpoint_callback()
            except Exception:
                pass

    def should_checkpoint(self) -> bool:
        """Check if checkpoint was requested via signal."""
        return self._preemption_requested.is_set()

    def acknowledge_checkpoint(self) -> None:
        """Acknowledge that checkpoint was handled."""
        self._preemption_requested.clear()
        self._checkpoint_done.set()

    def request_checkpoint(self) -> None:
        """Manually request a checkpoint."""
        self._preemption_requested.set()
