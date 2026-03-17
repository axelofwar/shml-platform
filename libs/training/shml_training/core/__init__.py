"""
SHML Training - Core Module
License: Apache 2.0

Base training components for SHML Platform.

Modules:
    config          - Training configuration and auto-optimization
    hardware        - GPU detection and hardware profiling
    checkpointing   - Model checkpointing with preemption support
    memory          - Memory optimization (chunked loss, gradient checkpointing)
    distributed     - Multi-GPU training (FSDP/DeepSpeed)
    signal          - GPU yielding coordination signals
    callbacks       - Event-driven callback system
    trainer         - Base trainer class with extensibility

All core modules are open source under Apache 2.0.
"""

from .config import (
    TrainingConfig,
    TrainingMode,
    OptimizationLevel,
    MemoryBudget,
    MemoryOptimizationConfig,
    CheckpointConfig,
    ProgressConfig,
)

from .hardware import (
    GPUInfo,
    GPUTier,
    SystemInfo,
    HardwareProfile,
    HardwareDetector,
)

from .checkpointing import CheckpointManager

from .memory import (
    MemoryOptimizer,
    ChunkedLossWrapper,
    GradientCheckpointer,
    estimate_memory_usage,
)

from .distributed import (
    DistributedConfig,
    DistributedStrategy,
    DistributedWrapper,
    init_distributed,
    cleanup_distributed,
    get_model_params,
    get_trainable_params,
    print_model_size,
)

from .signal import (
    training_context,
    requires_gpu,
    signal_training_start,
    signal_training_stop,
    signal_config,
    SignalConfig,
)

from .callbacks import (
    TrainingCallback,
    CallbackList,
)

from .trainer import (
    Trainer,
    UltralyticsTrainer,
)

__all__ = [
    # Config
    "TrainingConfig",
    "TrainingMode",
    "OptimizationLevel",
    "MemoryBudget",
    "MemoryOptimizationConfig",
    "CheckpointConfig",
    "ProgressConfig",
    # Hardware
    "GPUInfo",
    "GPUTier",
    "SystemInfo",
    "HardwareProfile",
    "HardwareDetector",
    # Checkpointing
    "CheckpointManager",
    # Memory
    "MemoryOptimizer",
    "ChunkedLossWrapper",
    "GradientCheckpointer",
    "estimate_memory_usage",
    # Distributed
    "DistributedConfig",
    "DistributedStrategy",
    "DistributedWrapper",
    "init_distributed",
    "cleanup_distributed",
    "get_model_params",
    "get_trainable_params",
    "print_model_size",
    # Signals
    "training_context",
    "requires_gpu",
    "signal_training_start",
    "signal_training_stop",
    "signal_config",
    "SignalConfig",
    # Callbacks
    "TrainingCallback",
    "CallbackList",
    # Trainer
    "Trainer",
    "UltralyticsTrainer",
]
