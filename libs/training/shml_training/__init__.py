"""
SHML Training Library
Version: 0.1.0
License: Dual Licensed (Apache 2.0 + Commercial)

Open-core training library for state-of-the-art computer vision models.

Architecture:
    core/          - Base training components (Apache 2.0)
    techniques/    - Proprietary SOTA techniques (Commercial)
    integrations/  - MLflow, Prometheus, Ray (Apache 2.0)
    sdk/          - Remote training client (Apache 2.0)

Basic Usage (Open Source):
    from shml_training import (
        TrainingConfig,
        MemoryOptimizer,
        CheckpointManager,
        ProgressReporter,
        JobOrchestrator,
    )

    # Configure training with auto-optimization
    config = TrainingConfig.auto_configure(
        model_size_billions=7,
        target_batch_size=8,
    )

    # Use memory optimizer
    optimizer = MemoryOptimizer(config)
    optimizer.optimize_for_hardware()

    # Track progress with AG-UI events
    reporter = ProgressReporter(run_id="train-001", total_epochs=100)
    reporter.start_run(config=config.to_dict())

    # Checkpoint with preemption support
    checkpoint_mgr = CheckpointManager(checkpoint_dir="./checkpoints")

    for epoch in range(100):
        reporter.start_epoch(epoch)
        for step, loss in training_loop():
            reporter.log_step(step, loss=loss)
        reporter.end_epoch(epoch, metrics={'loss': loss})
        checkpoint_mgr.save(epoch, model, optimizer)

    reporter.end_run(metrics={'final_loss': loss})

Pro Usage (Requires License - SHML_LICENSE_KEY):
    from shml_training.techniques import CurriculumLearning, SAPO, AdvantageFilter

    # Proprietary SOTA techniques
    # See techniques/LICENSE-COMMERCIAL for pricing
    # Hobbyist: $29/mo, Professional: $99/mo, Business: $499/mo

See README.md for full documentation.
"""

# Hardware detection
from .core.hardware import (
    GPUInfo,
    GPUTier,
    SystemInfo,
    HardwareProfile,
    HardwareDetector,
)


# Convenience aliases
def detect_hardware(force_refresh: bool = False) -> HardwareProfile:
    """Detect hardware and return profile."""
    return HardwareDetector.detect(force_refresh)


def has_nvidia_gpu() -> bool:
    """Check if NVIDIA GPU is available."""
    profile = HardwareDetector.detect()
    return len(profile.gpus) > 0


def get_gpu_memory_info() -> dict:
    """Get GPU memory information."""
    profile = HardwareDetector.detect()
    return {
        "total_vram_gb": profile.total_vram_gb,
        "effective_vram_gb": profile.effective_vram_gb,
        "gpus": [{"name": g.name, "memory_gb": g.memory_gb} for g in profile.gpus],
    }


# For backward compatibility
HardwareInfo = HardwareProfile

# Configuration
from .core.config import (
    TrainingConfig,
    TrainingMode,
    OptimizationLevel,
    MemoryBudget,
    MemoryOptimizationConfig,
    CheckpointConfig,
    ProgressConfig,
)

# SOTA defaults - define here for convenience
SOTA_DEFAULTS = {
    "optimizer": "AdamW",
    "lr0": 0.01,
    "lrf": 0.01,
    "momentum": 0.937,
    "weight_decay": 0.0005,
    "warmup_epochs": 3.0,
    "warmup_momentum": 0.8,
    "warmup_bias_lr": 0.1,
    "cos_lr": True,
    "label_smoothing": 0.1,
    "close_mosaic": 10,
    "patience": 50,
    "amp": True,
}

MULTISCALE_PHASES = [
    {"name": "Phase 1", "imgsz": 640, "epochs_ratio": 0.33, "desc": "Basic patterns"},
    {"name": "Phase 2", "imgsz": 960, "epochs_ratio": 0.33, "desc": "Medium details"},
    {"name": "Phase 3", "imgsz": 1280, "epochs_ratio": 0.34, "desc": "Fine details"},
]

# Memory optimization
from .core.memory import (
    MemoryOptimizer,
    ChunkedLossWrapper,
    GradientCheckpointer,
    estimate_memory_usage,
)


# Convenience aliases for memory functions
def chunked_cross_entropy_loss(logits, labels, chunk_size=8192, ignore_index=-100):
    """Chunked cross-entropy loss wrapper."""
    wrapper = ChunkedLossWrapper(chunk_size=chunk_size, ignore_index=ignore_index)
    return wrapper.forward(logits, labels)


def gradient_checkpoint_sequential(module, chunks=1):
    """Apply gradient checkpointing to sequential module."""
    checkpointer = GradientCheckpointer(chunks=chunks)
    return checkpointer.wrap_module(module)


def clear_memory():
    """Clear GPU memory cache."""
    import torch
    import gc

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


# Checkpointing
from .core.checkpointing import CheckpointManager

# Progress reporting (AG-UI protocol)
from .integrations.progress import (
    ProgressReporter,
    AGUIEventEmitter,
    AGUIEventType,
    AGUIEvent,
    print_progress_bar,
)

# Distributed training
from .core.distributed import (
    DistributedConfig,
    DistributedStrategy,
    DistributedWrapper,
    init_distributed,
    cleanup_distributed,
    get_model_params,
    get_trainable_params,
    print_model_size,
)

# Job orchestration
from .integrations.orchestrator import (
    JobOrchestrator,
    JobSpec,
    JobResult,
    JobStatus,
    JobPriority,
    Backend,
    run_training_job,
)

# Training signals (for GPU yielding coordination)
from .core.signal import (
    training_context,
    requires_gpu,
    signal_training_start,
    signal_training_stop,
    signal_config,
    SignalConfig,
)

__version__ = "0.1.0"
__all__ = [
    # Hardware
    "HardwareInfo",
    "detect_hardware",
    "has_nvidia_gpu",
    "get_gpu_memory_info",
    # Config
    "TrainingConfig",
    "SOTA_DEFAULTS",
    "MULTISCALE_PHASES",
    # Memory
    "MemoryOptimizer",
    "chunked_cross_entropy_loss",
    "gradient_checkpoint_sequential",
    "clear_memory",
    # Checkpointing
    "CheckpointManager",
    # Progress
    "ProgressReporter",
    "AGUIEventEmitter",
    "AGUIEventType",
    "AGUIEvent",
    "print_progress_bar",
    # Distributed
    "DistributedConfig",
    "DistributedStrategy",
    "DistributedWrapper",
    "init_distributed",
    "cleanup_distributed",
    "get_model_params",
    "get_trainable_params",
    "print_model_size",
    # Orchestration
    "JobOrchestrator",
    "JobSpec",
    "JobResult",
    "JobStatus",
    "JobPriority",
    "Backend",
    "run_training_job",
    # Signals
    "training_context",
    "requires_gpu",
    "signal_training_start",
    "signal_training_stop",
    "signal_config",
    "SignalConfig",
]
