"""
Training configuration for SHML Training Library.

Provides auto-configuration based on hardware detection and SOTA practices.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
import json
import yaml
from pathlib import Path


class TrainingMode(Enum):
    """Training execution modes."""

    LOCAL = "local"
    RAY = "ray"
    FSDP = "fsdp"
    DEEPSPEED = "deepspeed"


class OptimizationLevel(Enum):
    """Memory optimization aggressiveness."""

    NONE = "none"  # No optimizations
    CONSERVATIVE = "conservative"  # Basic optimizations
    AGGRESSIVE = "aggressive"  # All optimizations including CPU offload
    MAXIMUM = "maximum"  # Everything + gradient accumulation


@dataclass
class MemoryBudget:
    """Memory budget calculations for training."""

    model_memory_gb: float
    optimizer_memory_gb: float
    gradient_memory_gb: float
    activation_memory_gb: float
    total_required_gb: float
    available_gpu_gb: float
    available_cpu_gb: float
    can_fit_on_gpu: bool
    requires_cpu_offload: bool
    requires_gradient_checkpointing: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_memory_gb": self.model_memory_gb,
            "optimizer_memory_gb": self.optimizer_memory_gb,
            "gradient_memory_gb": self.gradient_memory_gb,
            "activation_memory_gb": self.activation_memory_gb,
            "total_required_gb": self.total_required_gb,
            "available_gpu_gb": self.available_gpu_gb,
            "available_cpu_gb": self.available_cpu_gb,
            "can_fit_on_gpu": self.can_fit_on_gpu,
            "requires_cpu_offload": self.requires_cpu_offload,
            "requires_gradient_checkpointing": self.requires_gradient_checkpointing,
        }


@dataclass
class MemoryOptimizationConfig:
    """Memory optimization settings (from Unsloth research)."""

    # Chunked cross-entropy loss (60% VRAM reduction)
    chunked_loss: bool = True
    chunked_loss_num_chunks: int = 0  # 0 = auto

    # Gradient checkpointing with CPU offload (0.1% overhead)
    gradient_checkpointing: bool = True
    gradient_checkpointing_offload_to_cpu: bool = False

    # Tiled MLP (2x context for 1.3x time)
    tiled_mlp: bool = False

    # CPU offload for optimizer states / parameters
    cpu_offload_optimizer: bool = False
    cpu_offload_params: bool = False
    pin_memory: bool = True

    # Gradient accumulation
    gradient_accumulation_steps: int = 1

    @classmethod
    def for_level(
        cls, level: OptimizationLevel, memory_budget: Optional[MemoryBudget] = None
    ) -> "MemoryOptimizationConfig":
        """Create config for optimization level."""

        if level == OptimizationLevel.NONE:
            return cls(
                chunked_loss=False,
                gradient_checkpointing=False,
            )

        elif level == OptimizationLevel.CONSERVATIVE:
            return cls(
                chunked_loss=True,
                gradient_checkpointing=True,
            )

        elif level == OptimizationLevel.AGGRESSIVE:
            return cls(
                chunked_loss=True,
                chunked_loss_num_chunks=0,  # auto
                gradient_checkpointing=True,
                gradient_checkpointing_offload_to_cpu=True,
                cpu_offload_optimizer=True,
            )

        else:  # MAXIMUM
            return cls(
                chunked_loss=True,
                chunked_loss_num_chunks=0,
                gradient_checkpointing=True,
                gradient_checkpointing_offload_to_cpu=True,
                tiled_mlp=True,
                cpu_offload_optimizer=True,
                cpu_offload_params=True,
                gradient_accumulation_steps=4,
            )


@dataclass
class CheckpointConfig:
    """Checkpointing configuration."""

    # Checkpoint directory
    checkpoint_dir: str = "./checkpoints"

    # Save frequency
    save_every_n_epochs: int = 1
    save_every_n_steps: int = 0  # 0 = disabled

    # Retention
    keep_last_n: int = 3
    keep_best_n: int = 1

    # Preemption support
    enable_preemption_checkpoints: bool = True
    preemption_signal: str = "SIGTERM"

    # Auto-checkpoint on error
    checkpoint_on_error: bool = True


@dataclass
class ProgressConfig:
    """Progress reporting configuration (AG-UI compatible)."""

    # Enable AG-UI event streaming
    enable_agui_events: bool = True

    # Event endpoint (for streaming to UI)
    agui_endpoint: Optional[str] = None

    # Console logging
    log_to_console: bool = True
    console_log_interval_steps: int = 10

    # Metrics to track
    track_loss: bool = True
    track_learning_rate: bool = True
    track_gpu_memory: bool = True
    track_throughput: bool = True

    # ntfy.sh notifications
    ntfy_topic: Optional[str] = None
    notify_on_epoch: bool = True
    notify_on_complete: bool = True
    notify_on_error: bool = True


@dataclass
class TrainingConfig:
    """Complete training configuration."""

    # Execution mode
    mode: TrainingMode = TrainingMode.LOCAL

    # Hardware
    device: str = "auto"  # auto, cuda, cuda:0, cpu
    num_gpus: int = 0  # 0 = auto-detect

    # Training params
    epochs: int = 100
    batch_size: int = 8
    learning_rate: float = 1e-4
    warmup_steps: int = 100
    max_grad_norm: float = 1.0

    # Precision
    precision: str = "auto"  # auto, fp32, fp16, bf16

    # Memory optimization
    memory: MemoryOptimizationConfig = field(default_factory=MemoryOptimizationConfig)

    # Checkpointing
    checkpoint: CheckpointConfig = field(default_factory=CheckpointConfig)

    # Progress reporting
    progress: ProgressConfig = field(default_factory=ProgressConfig)

    # Data loading
    num_workers: int = 4
    prefetch_factor: int = 2

    # Distributed training
    fsdp_sharding_strategy: str = "FULL_SHARD"
    deepspeed_stage: int = 3

    # Hardware profile (computed)
    _hardware_profile: Optional[Any] = field(default=None, repr=False)
    _memory_budget: Optional[MemoryBudget] = field(default=None, repr=False)

    @classmethod
    def auto_configure(
        cls,
        model_size_billions: float = 7.0,
        target_batch_size: int = 8,
        target_epochs: int = 100,
        optimization_level: OptimizationLevel = OptimizationLevel.AGGRESSIVE,
        mode: Optional[TrainingMode] = None,
    ) -> "TrainingConfig":
        """Auto-configure training based on hardware and model size.

        Args:
            model_size_billions: Model size in billions of parameters
            target_batch_size: Desired batch size
            target_epochs: Number of training epochs
            optimization_level: How aggressive to be with memory optimization
            mode: Training mode (auto-detected if None)

        Returns:
            Optimally configured TrainingConfig
        """
        from .hardware import HardwareDetector

        # Detect hardware
        profile = HardwareDetector.detect()

        # Calculate memory budget
        memory_budget = profile.get_memory_budget(model_size_billions)

        # Auto-detect mode based on hardware
        if mode is None:
            if profile.is_multi_gpu:
                mode = TrainingMode.FSDP
            else:
                mode = TrainingMode.LOCAL

        # Determine optimization level if not specified
        if memory_budget.requires_cpu_offload:
            optimization_level = max(optimization_level, OptimizationLevel.AGGRESSIVE)

        # Configure memory optimization
        memory_config = MemoryOptimizationConfig.for_level(
            optimization_level, memory_budget
        )

        # Adjust batch size if needed
        actual_batch_size = target_batch_size
        if (
            not memory_budget.can_fit_on_gpu
            and memory_config.gradient_accumulation_steps == 1
        ):
            # Reduce batch size and use gradient accumulation
            actual_batch_size = max(1, target_batch_size // 4)
            memory_config.gradient_accumulation_steps = (
                target_batch_size // actual_batch_size
            )

        # Determine precision
        precision = profile.recommended_precision

        # Adjust workers based on CPU cores
        num_workers = min(profile.system.cpu_cores - 2, 8)  # Leave 2 cores for system

        config = cls(
            mode=mode,
            device="auto",
            num_gpus=len(profile.gpus),
            epochs=target_epochs,
            batch_size=actual_batch_size,
            precision=precision,
            memory=memory_config,
            num_workers=num_workers,
        )

        # Store computed values
        config._hardware_profile = profile
        config._memory_budget = memory_budget

        return config

    @classmethod
    def from_yaml(cls, path: str) -> "TrainingConfig":
        """Load configuration from YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingConfig":
        """Create config from dictionary."""
        # Handle nested configs
        if "memory" in data and isinstance(data["memory"], dict):
            data["memory"] = MemoryOptimizationConfig(**data["memory"])
        if "checkpoint" in data and isinstance(data["checkpoint"], dict):
            data["checkpoint"] = CheckpointConfig(**data["checkpoint"])
        if "progress" in data and isinstance(data["progress"], dict):
            data["progress"] = ProgressConfig(**data["progress"])
        if "mode" in data and isinstance(data["mode"], str):
            data["mode"] = TrainingMode(data["mode"])

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mode": self.mode.value,
            "device": self.device,
            "num_gpus": self.num_gpus,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "learning_rate": self.learning_rate,
            "warmup_steps": self.warmup_steps,
            "max_grad_norm": self.max_grad_norm,
            "precision": self.precision,
            "memory": {
                "chunked_loss": self.memory.chunked_loss,
                "chunked_loss_num_chunks": self.memory.chunked_loss_num_chunks,
                "gradient_checkpointing": self.memory.gradient_checkpointing,
                "gradient_checkpointing_offload_to_cpu": self.memory.gradient_checkpointing_offload_to_cpu,
                "tiled_mlp": self.memory.tiled_mlp,
                "cpu_offload_optimizer": self.memory.cpu_offload_optimizer,
                "cpu_offload_params": self.memory.cpu_offload_params,
                "gradient_accumulation_steps": self.memory.gradient_accumulation_steps,
            },
            "checkpoint": {
                "checkpoint_dir": self.checkpoint.checkpoint_dir,
                "save_every_n_epochs": self.checkpoint.save_every_n_epochs,
                "keep_last_n": self.checkpoint.keep_last_n,
            },
            "progress": {
                "enable_agui_events": self.progress.enable_agui_events,
                "log_to_console": self.progress.log_to_console,
            },
            "num_workers": self.num_workers,
        }

    def to_yaml(self, path: str) -> None:
        """Save configuration to YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False)

    def print_summary(self) -> None:
        """Print configuration summary."""
        print("\n" + "=" * 60)
        print("SHML Training Configuration")
        print("=" * 60)

        print(f"\nExecution:")
        print(f"  Mode: {self.mode.value}")
        print(f"  Device: {self.device}")
        print(f"  GPUs: {self.num_gpus}")
        print(f"  Precision: {self.precision}")

        print(f"\nTraining:")
        print(f"  Epochs: {self.epochs}")
        print(f"  Batch Size: {self.batch_size}")
        print(f"  Gradient Accumulation: {self.memory.gradient_accumulation_steps}")
        print(
            f"  Effective Batch: {self.batch_size * self.memory.gradient_accumulation_steps}"
        )
        print(f"  Learning Rate: {self.learning_rate}")

        print(f"\nMemory Optimization:")
        print(f"  Chunked Loss: {self.memory.chunked_loss}")
        print(f"  Gradient Checkpointing: {self.memory.gradient_checkpointing}")
        print(
            f"  CPU Offload (checkpoints): {self.memory.gradient_checkpointing_offload_to_cpu}"
        )
        print(f"  CPU Offload (optimizer): {self.memory.cpu_offload_optimizer}")
        print(f"  CPU Offload (params): {self.memory.cpu_offload_params}")

        if self._memory_budget:
            print(f"\nMemory Budget:")
            print(f"  Required: {self._memory_budget.total_required_gb:.1f} GB")
            print(f"  Available GPU: {self._memory_budget.available_gpu_gb:.1f} GB")
            print(f"  Fits on GPU: {self._memory_budget.can_fit_on_gpu}")

        print("=" * 60 + "\n")
