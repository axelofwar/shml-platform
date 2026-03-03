# SHML Training Library

**Version:** 0.1.0  
**License:** Dual Licensed (Apache 2.0 + Commercial)  
**Status:** 🚧 Modularization in Progress

## Overview

Production-ready training library for state-of-the-art computer vision models. Open-core architecture with proprietary optimization techniques available under commercial license.

## Architecture

```
shml_training/
├── core/              # Open Source (Apache 2.0)
│   ├── trainer.py     # Base training loop
│   ├── config.py      # Configuration management
│   ├── callbacks.py   # Training callbacks
│   └── dataset.py     # Dataset loaders
│
├── techniques/        # Proprietary (Commercial License)
│   ├── curriculum.py  # 4-stage curriculum learning
│   ├── sapo.py        # SAPO soft gating optimizer
│   ├── advantage_filter.py  # Online advantage filtering
│   └── multiscale.py  # Enhanced multi-scale training
│
├── integrations/      # Open Source (Apache 2.0)
│   ├── mlflow.py      # MLflow tracking integration
│   ├── prometheus.py  # Prometheus metrics
│   └── ray.py         # Ray distributed training
│
└── sdk/              # Open Source (Apache 2.0)
    └── client.py      # Remote training API client
```

## Features

### Open Source (Apache 2.0)
- **Base Training Loop**: YOLO-optimized training pipeline
- **MLflow Integration**: Automatic experiment tracking
- **Prometheus Metrics**: Real-time observability
- **Ray Distribution**: Distributed training on Ray clusters
- **Configurable Callbacks**: Extensible training hooks
- **Dataset Loaders**: WIDER Face and custom datasets

### Proprietary (Commercial License Required)
- **Curriculum Learning**: 4-stage progressive difficulty training
- **SAPO Optimizer**: Soft gating with advantage-based selection
- **Online Advantage Filter**: Skip easy batches, focus on hard examples
- **Enhanced Multi-Scale**: Dynamic resolution scheduling

## Installation

### Open Source (Core Features Only)

```bash
cd /path/to/shml-platform
pip install -e libs/training

# Or from PyPI (future)
pip install shml-training
```

### Pro Features (Requires License)

```bash
pip install shml-training[pro]
export SHML_LICENSE_KEY="your-license-key"
    CheckpointManager,
    ProgressReporter,
)

# Auto-configure based on hardware
config = TrainingConfig.auto_configure(
    model_size_billions=7,
    target_batch_size=8,
)

# Setup components
memory_opt = MemoryOptimizer(config)
checkpoint_mgr = CheckpointManager("./checkpoints")
reporter = ProgressReporter(run_id="train-001", total_epochs=100)

# Start training
reporter.start_run(config={"model": "my-model", "epochs": 100})

for epoch in range(100):
    reporter.start_epoch(epoch)

    for step, batch in enumerate(dataloader):
        loss = train_step(batch)
        reporter.log_step(step, loss=loss)

    reporter.end_epoch(epoch, metrics={"loss": epoch_loss})
    checkpoint_mgr.save(epoch, model, optimizer)

reporter.end_run(metrics={"final_loss": final_loss})
```

### Memory Optimization

```python
from shml_training import MemoryOptimizer, chunked_cross_entropy_loss

# Create optimizer
memory_opt = MemoryOptimizer(config)

# Apply optimizations
memory_opt.optimize_for_hardware()

# Use chunked loss for large vocabularies (60% VRAM savings)
loss = chunked_cross_entropy_loss(
    logits,  # (batch, seq_len, vocab_size)
    labels,  # (batch, seq_len)
    chunk_size=8192,  # Process in chunks
)

# Enable gradient checkpointing
from shml_training import gradient_checkpoint_sequential
model.transformer = gradient_checkpoint_sequential(
    model.transformer,
    chunks=4,
)
```

### Distributed Training

```python
from shml_training import (
    DistributedConfig,
    DistributedWrapper,
    DistributedStrategy,
)

# Auto-select strategy
config = DistributedConfig.auto_select(
    model_params=7_000_000_000,  # 7B
    available_vram_gb=24,
    num_gpus=2,
)

# Wrap model and dataloader
wrapper = DistributedWrapper(config)
model = wrapper.wrap_model(model)
dataloader = wrapper.wrap_dataloader(train_loader)

# Training loop
for batch in dataloader:
    loss = model(batch)
    wrapper.backward(loss)
    wrapper.step(optimizer)

# Save checkpoint (only on main process)
wrapper.save_checkpoint(model, optimizer, "checkpoint.pt", epoch=epoch)
```

### Job Orchestration

```python
from shml_training import (
    JobOrchestrator,
    JobSpec,
    JobPriority,
    run_training_job,
)

# Simple submission
result = run_training_job(
    name="bert-finetuning",
    config=training_config,
    train_fn=my_train_function,
    user_role="admin",  # Full GPU access
)

# Advanced: Use orchestrator for preemption support
orchestrator = JobOrchestrator(ray_address="auto")

job = JobSpec(
    job_id="train-001",
    name="Large Model Training",
    config=training_config,
    user_id="alice",
    user_role="admin",
    priority=JobPriority.HIGH,
    min_gpu_memory_gb=20,
    preemptible=False,  # Admin jobs not preemptible
)

result = orchestrator.submit_and_wait(job, train_fn)
```

### Ray Integration

```python
from shml_training.ray_wrapper import RayTrainer, submit_ray_job

# Quick submission
result = submit_ray_job(
    train_fn=my_train_function,
    config=training_config,
    ray_config=RayJobConfig(num_gpus=1, num_cpus=4),
)

# Using RayTrainer for role-based resource allocation
trainer = RayTrainer(
    config=training_config,
    ray_address="auto",
    user_role="admin",  # Gets full GPU access
)

result = trainer.train(
    train_fn=my_train_function,
    checkpoint_dir="./checkpoints",
)

# Distributed training with Ray Train
result = trainer.train_distributed(
    train_fn=my_train_function,
    num_workers=4,
    use_gpu=True,
)
```

### AG-UI Progress Events

The library implements the [AG-UI Protocol](https://github.com/ag-ui/ag-ui) for real-time streaming to UIs:

```python
from shml_training import AGUIEventEmitter, AGUIEventType

# Create emitter with HTTP endpoint
emitter = AGUIEventEmitter(
    run_id="train-001",
    endpoint="http://localhost:8080/events",
)

emitter.start()

# Emit events
emitter.emit_run_started(config={"model": "bert"})
emitter.emit_state_delta({"epoch": 1, "loss": 0.5})
emitter.emit_checkpoint_saved("/path/to/ckpt", epoch=1, is_best=True)
emitter.emit_run_finished(metrics={"accuracy": 0.95})

emitter.stop()
```

Event types include:
- `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`
- `EPOCH_START`, `EPOCH_END`
- `STEP_UPDATE`, `METRIC_UPDATE`
- `CHECKPOINT_SAVED`
- `STATE_DELTA`, `STATE_SNAPSHOT`

## Hardware Detection

```python
from shml_training import detect_hardware, HardwareInfo

hardware = detect_hardware()
print(f"GPUs: {len(hardware.gpu_info)}")
print(f"Total VRAM: {hardware.total_vram_gb:.1f} GB")
print(f"RAM: {hardware.ram_gb:.1f} GB")
print(f"Effective VRAM (with offload): {hardware.effective_vram_gb:.1f} GB")

for gpu in hardware.gpu_info:
    print(f"  {gpu['name']}: {gpu['memory_total_gb']:.1f} GB")
```

## Configuration

### TrainingConfig

```python
from shml_training import TrainingConfig

config = TrainingConfig(
    # Basic
    epochs=100,
    batch_size=8,
    learning_rate=1e-4,

    # Memory optimization
    gradient_accumulation_steps=4,
    use_gradient_checkpointing=True,
    use_cpu_offload=True,
    mixed_precision="fp16",

    # Hardware limits
    gpu_memory_limit_gb=20,

    # Multi-scale training (for vision)
    multiscale_phases=[
        {"epochs": 30, "imgsz": 640, "batch": 16},
        {"epochs": 30, "imgsz": 960, "batch": 8},
        {"epochs": 30, "imgsz": 1280, "batch": 4},
    ],
)

# Or auto-configure
config = TrainingConfig.auto_configure(
    model_size_billions=7,
    target_batch_size=8,
    prefer_speed=False,  # Optimize for memory
)
```

### SOTA Defaults

```python
from shml_training import SOTA_DEFAULTS

print(SOTA_DEFAULTS)
# {
#     "optimizer": "adamw",
#     "warmup_ratio": 0.1,
#     "weight_decay": 0.01,
#     "lr_scheduler": "cosine",
#     "grad_clip_norm": 1.0,
#     "mixed_precision": "bf16",
#     ...
# }
```

## Role-Based Resource Allocation

The library supports role-based GPU access control:

| Role | GPU Access | CPU Cores | Preemption |
|------|-----------|-----------|------------|
| `developer` | MPS slice (2GB 3090, 0.5GB 2070) | 4 | Can be preempted |
| `elevated` | Up to 16GB via MPS/time-slice | 8 | Can be preempted |
| `admin` | Full GPU (no limits) | Unlimited | Cannot be preempted, can preempt others |
| `super_admin` | Full GPU + cluster-wide | Unlimited | Cannot be preempted, can preempt all |

## API Reference

### Core Classes

- `TrainingConfig` - Training configuration dataclass
- `MemoryOptimizer` - Memory optimization utilities
- `CheckpointManager` - Robust checkpointing with preemption support
- `ProgressReporter` - High-level progress tracking
- `AGUIEventEmitter` - AG-UI protocol event emission
- `DistributedWrapper` - Distributed training wrapper (DDP/FSDP/DeepSpeed)
- `JobOrchestrator` - Job routing and preemption
- `RayTrainer` - Ray cluster integration

### Key Functions

- `detect_hardware()` - Get hardware information
- `chunked_cross_entropy_loss()` - Memory-efficient loss computation
- `gradient_checkpoint_sequential()` - Gradient checkpointing wrapper
- `run_training_job()` - Quick job submission
- `submit_ray_job()` - Submit to Ray cluster

## Research Sources

This library incorporates best practices from:

- [Unsloth](https://github.com/unslothai/unsloth) - Chunked loss, 2x faster training
- [AG-UI Protocol](https://github.com/ag-ui/ag-ui) - Agent-User Interaction standard
- [ToolOrchestra](https://arxiv.org/abs/2505.11032) - Small model orchestration pattern
- [CUDA Tile](https://github.com/cuda-tile) - Tiled MLP for memory efficiency
- [PretrainZero](https://arxiv.org/abs/2501.08435) - ZeRO-style pretraining optimizations

## License

MIT License - Part of the SHML Platform

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for guidelines.
