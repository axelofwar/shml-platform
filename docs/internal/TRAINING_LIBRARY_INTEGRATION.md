# SHML Training Library Integration Guide

This guide shows how to integrate the SHML Training Library into existing training scripts.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Memory Optimization](#memory-optimization)
3. [Progress Reporting (AG-UI)](#progress-reporting-ag-ui)
4. [Checkpointing](#checkpointing)
5. [Distributed Training](#distributed-training)
6. [Ray Integration](#ray-integration)
7. [Migration from ResourceManager](#migration-from-resourcemanager)
8. [Full Example](#full-example)

## Quick Start

### Installation

```bash
# Install from SHML platform
cd /path/to/shml-platform
pip install -e libs/training

# Or install with extras
pip install -e "libs/training[ray,distributed]"
```

### Basic Import

```python
from shml_training import (
    # Hardware detection
    detect_hardware,
    HardwareInfo,

    # Configuration
    TrainingConfig,
    SOTA_DEFAULTS,

    # Memory optimization
    MemoryOptimizer,
    chunked_cross_entropy_loss,

    # Checkpointing
    CheckpointManager,

    # Progress reporting
    ProgressReporter,
    AGUIEventEmitter,
)
```

## Memory Optimization

### Auto-Configuration Based on Hardware

```python
from shml_training import detect_hardware, TrainingConfig, MemoryOptimizer

# Detect hardware
hardware = detect_hardware()
print(f"Total VRAM: {hardware.total_vram_gb:.1f} GB")
print(f"Effective VRAM (with offload): {hardware.effective_vram_gb:.1f} GB")

# Create config with auto-optimization
config = TrainingConfig.auto_configure(
    model_size_billions=7,  # 7B parameter model
    target_batch_size=8,
)

# Apply memory optimizations
optimizer = MemoryOptimizer(config)
optimized = optimizer.optimize_for_hardware()

print(f"Recommended batch size: {optimized['batch_size']}")
print(f"Gradient accumulation: {optimized['gradient_accumulation_steps']}")
print(f"Use gradient checkpointing: {optimized['use_gradient_checkpointing']}")
```

### Chunked Cross-Entropy Loss

For large vocabulary models (LLMs), chunked loss reduces VRAM by 60%:

```python
from shml_training import chunked_cross_entropy_loss

# Instead of standard cross-entropy
# loss = F.cross_entropy(logits.view(-1, vocab_size), labels.view(-1))

# Use chunked version
loss = chunked_cross_entropy_loss(
    logits,  # (batch, seq_len, vocab_size)
    labels,  # (batch, seq_len)
    chunk_size=8192,  # Process in chunks
    ignore_index=-100,
)
```

### Gradient Checkpointing

```python
from shml_training import gradient_checkpoint_sequential

# Wrap sequential layers for memory savings
model.encoder = gradient_checkpoint_sequential(
    model.encoder,
    chunks=4,  # Number of checkpointed segments
)
```

## Progress Reporting (AG-UI)

### Basic Progress Reporting

```python
from shml_training import ProgressReporter

reporter = ProgressReporter(
    run_id="my-training-001",
    total_epochs=100,
    log_to_console=True,
)

reporter.start_run(config={
    'model': 'bert-base',
    'batch_size': 8,
    'learning_rate': 1e-4,
})

for epoch in range(100):
    reporter.start_epoch(epoch)

    for step, batch in enumerate(dataloader):
        loss = train_step(batch)
        lr = scheduler.get_last_lr()[0]

        reporter.log_step(
            step=step,
            loss=loss.item(),
            learning_rate=lr,
            throughput=batch_size / step_time,
            gpu_memory_gb=torch.cuda.memory_allocated() / 1e9,
        )

    reporter.end_epoch(epoch, metrics={
        'train_loss': epoch_loss,
        'val_loss': val_loss,
        'val_accuracy': val_acc,
    })

    reporter.log_checkpoint(
        path=f"checkpoints/epoch_{epoch}.pt",
        epoch=epoch,
        is_best=(val_loss < best_loss),
    )

reporter.end_run(metrics={
    'final_train_loss': final_train_loss,
    'final_val_loss': final_val_loss,
    'best_val_accuracy': best_accuracy,
})
```

### AG-UI Event Streaming to UI

```python
from shml_training import AGUIEventEmitter

# Stream events to HTTP endpoint
emitter = AGUIEventEmitter(
    run_id="train-001",
    endpoint="http://localhost:8080/api/events",  # Your UI backend
)

emitter.start()

# Events are automatically sent to endpoint
emitter.emit_run_started(config={'model': 'gpt2'})
emitter.emit_state_delta({'epoch': 1, 'loss': 0.5})
emitter.emit_checkpoint_saved('/path/to/ckpt', epoch=1)
emitter.emit_run_finished(metrics={'accuracy': 0.95})

emitter.stop()
```

### Notifications via ntfy.sh

```python
reporter = ProgressReporter(
    run_id="training-001",
    total_epochs=100,
    ntfy_topic="my-training-notifications",  # Sends to ntfy.sh
)

# Notifications sent on:
# - Training completion
# - Errors
# - Custom events via reporter.log_error()
```

## Checkpointing

### Basic Checkpointing

```python
from shml_training import CheckpointManager

checkpoint_mgr = CheckpointManager(
    checkpoint_dir="./checkpoints",
    max_checkpoints=5,  # Keep last 5
    enable_signal_handlers=True,  # Handle SIGTERM/SIGINT
)

for epoch in range(100):
    train_epoch(model, optimizer)

    # Save checkpoint
    checkpoint_mgr.save(
        epoch=epoch,
        model=model,
        optimizer=optimizer,
        extra_data={
            'scheduler': scheduler.state_dict(),
            'best_loss': best_loss,
        },
    )

    # Check for preemption signal
    if checkpoint_mgr.should_stop:
        print("Preemption signal received, saving and exiting...")
        break
```

### Resume from Checkpoint

```python
# Check for existing checkpoint
checkpoint = checkpoint_mgr.load_latest()

if checkpoint:
    start_epoch = checkpoint['epoch'] + 1
    model.load_state_dict(checkpoint['model_state_dict'])
    optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
    scheduler.load_state_dict(checkpoint['extra_data']['scheduler'])
    print(f"Resuming from epoch {start_epoch}")
else:
    start_epoch = 0
```

### Preemption Handling

The CheckpointManager registers signal handlers for graceful shutdown:

- `SIGTERM`: Container/job termination
- `SIGINT`: Ctrl+C interrupt
- `SIGUSR1`: User-defined checkpoint trigger

```python
# Signal handlers automatically save checkpoint on termination
checkpoint_mgr = CheckpointManager(
    checkpoint_dir="./checkpoints",
    enable_signal_handlers=True,
)

# Training loop
while not checkpoint_mgr.should_stop:
    train_batch()

# Checkpoint already saved by signal handler
```

## Distributed Training

### Auto-Select Strategy

```python
from shml_training import (
    DistributedConfig,
    DistributedWrapper,
    get_model_params,
)

# Auto-select based on model and hardware
config = DistributedConfig.auto_select(
    model_params=get_model_params(model),
    available_vram_gb=24,
    num_gpus=4,
)

print(f"Selected strategy: {config.strategy}")
# Will choose DDP, FSDP, or DeepSpeed based on requirements
```

### FSDP Training

```python
from shml_training import DistributedConfig, DistributedWrapper, DistributedStrategy

config = DistributedConfig(
    strategy=DistributedStrategy.FSDP,
    fsdp_sharding_strategy="FULL_SHARD",
    fsdp_cpu_offload=True,  # For very large models
)

wrapper = DistributedWrapper(config)

# Wrap model
model = wrapper.wrap_model(model)

# Wrap dataloader for distributed sampling
train_loader = wrapper.wrap_dataloader(train_loader)

# Training loop
for batch in train_loader:
    loss = model(batch)
    wrapper.backward(loss)
    wrapper.step(optimizer)

# Save checkpoint (only on rank 0)
wrapper.save_checkpoint(model, optimizer, "checkpoint.pt", epoch=epoch)
```

### DeepSpeed ZeRO

```python
config = DistributedConfig(
    strategy=DistributedStrategy.DEEPSPEED_ZERO3,
    deepspeed_offload_optimizer=True,
    deepspeed_offload_params=True,  # For huge models
)

wrapper = DistributedWrapper(config)
model = wrapper.wrap_model(model, optimizer)  # DeepSpeed needs optimizer at wrap time
```

## Ray Integration

### Submit Job to Ray Cluster

```python
from shml_training.ray_wrapper import RayTrainer, RayJobConfig

# Create trainer with role-based resource allocation
trainer = RayTrainer(
    config=training_config,
    ray_address="auto",
    user_role="admin",  # Gets full GPU access
)

def my_train_fn(config, **kwargs):
    """Training function executed on Ray."""
    model = load_model(config)

    # Use provided utilities
    progress_reporter = kwargs.get('progress_reporter')
    memory_optimizer = kwargs.get('memory_optimizer')

    for epoch in range(config.epochs):
        loss = train_epoch(model)
        if progress_reporter:
            progress_reporter.log_step(epoch, loss=loss)

    return {'final_loss': loss}

# Submit and wait
result = trainer.train(
    train_fn=my_train_fn,
    checkpoint_dir="./checkpoints",
)

print(f"Training completed: {result.status}")
print(f"Metrics: {result.metrics}")
```

### Distributed Ray Training

```python
result = trainer.train_distributed(
    train_fn=my_train_fn,
    num_workers=4,  # 4 distributed workers
    use_gpu=True,
)
```

## Migration from ResourceManager

### Before (ResourceManager)

```python
from scripts.utils.resource_manager import ResourceManager

mgr = ResourceManager.preflight_check(
    min_ram_gb=10.0,
    min_vram_gb=14.0,
    target_batch_size=batch_size,
    target_workers=workers,
)

batch_size = mgr.recommended_batch_size
workers = mgr.recommended_workers
```

### After (SHML MemoryOptimizer)

```python
from shml_training import TrainingConfig, MemoryOptimizer

config = TrainingConfig(
    batch_size=batch_size,
    # ... other config
)

optimizer = MemoryOptimizer(config)
optimized = optimizer.optimize_for_hardware()

batch_size = optimized['batch_size']
# Also get: gradient_accumulation_steps, use_gradient_checkpointing, etc.
```

### Backward Compatibility

The pii-pro training script automatically falls back to ResourceManager if SHML Training Library is not installed:

```python
# Auto-detected in train.py
if SHML_TRAINING_AVAILABLE:
    # Use SHML library
    optimizer = MemoryOptimizer(config)
    optimized = optimizer.optimize_for_hardware()
elif RESOURCE_MANAGER_AVAILABLE:
    # Legacy fallback
    mgr = ResourceManager.preflight_check(...)
```

## Full Example

Complete training script with all features:

```python
#!/usr/bin/env python3
"""Complete training example with SHML Training Library."""

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from shml_training import (
    detect_hardware,
    TrainingConfig,
    MemoryOptimizer,
    CheckpointManager,
    ProgressReporter,
    chunked_cross_entropy_loss,
)

def main():
    # ==========================================================================
    # Hardware Detection & Configuration
    # ==========================================================================
    hardware = detect_hardware()
    print(f"Detected: {len(hardware.gpu_info)} GPUs, {hardware.total_vram_gb:.1f}GB VRAM")

    config = TrainingConfig.auto_configure(
        model_size_billions=0.3,  # 300M params
        target_batch_size=32,
    )

    # ==========================================================================
    # Memory Optimization
    # ==========================================================================
    mem_opt = MemoryOptimizer(config)
    optimized = mem_opt.optimize_for_hardware()

    batch_size = optimized['batch_size']
    grad_accum = optimized['gradient_accumulation_steps']

    print(f"Optimized: batch={batch_size}, grad_accum={grad_accum}")

    # ==========================================================================
    # Initialize Components
    # ==========================================================================
    checkpoint_mgr = CheckpointManager(
        checkpoint_dir="./checkpoints",
        max_checkpoints=3,
        enable_signal_handlers=True,
    )

    reporter = ProgressReporter(
        run_id="training-001",
        total_epochs=config.epochs,
        agui_endpoint="http://localhost:8080/events",  # Optional
        ntfy_topic="my-training",  # Optional
    )

    # ==========================================================================
    # Model & Data
    # ==========================================================================
    model = YourModel().cuda()
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)
    train_loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # Resume if checkpoint exists
    checkpoint = checkpoint_mgr.load_latest()
    start_epoch = 0
    if checkpoint:
        start_epoch = checkpoint['epoch'] + 1
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        print(f"Resuming from epoch {start_epoch}")

    # ==========================================================================
    # Training Loop
    # ==========================================================================
    reporter.start_run(config=config.to_dict())

    for epoch in range(start_epoch, config.epochs):
        reporter.start_epoch(epoch)

        for step, batch in enumerate(train_loader):
            # Forward pass
            logits = model(batch['input'].cuda())

            # Use chunked loss for large vocab
            loss = chunked_cross_entropy_loss(
                logits,
                batch['labels'].cuda(),
                chunk_size=8192,
            ) / grad_accum

            # Backward
            loss.backward()

            # Update with gradient accumulation
            if (step + 1) % grad_accum == 0:
                optimizer.step()
                optimizer.zero_grad()

            # Report progress
            reporter.log_step(
                step=step,
                loss=loss.item() * grad_accum,
                learning_rate=optimizer.param_groups[0]['lr'],
                gpu_memory_gb=torch.cuda.memory_allocated() / 1e9,
            )

            # Check for preemption
            if checkpoint_mgr.should_stop:
                print("Preemption detected, saving checkpoint...")
                checkpoint_mgr.save(epoch, model, optimizer, force=True)
                reporter.end_run(status='preempted')
                return

        # End of epoch
        val_metrics = validate(model, val_loader)
        reporter.end_epoch(epoch, metrics=val_metrics)

        # Checkpoint
        is_best = val_metrics['loss'] < best_loss
        checkpoint_mgr.save(epoch, model, optimizer)
        reporter.log_checkpoint(
            path=checkpoint_mgr.get_latest_path(),
            epoch=epoch,
            is_best=is_best,
        )

    # Training complete
    reporter.end_run(metrics={'best_val_loss': best_loss})
    print("Training complete!")

if __name__ == '__main__':
    main()
```

## Environment Variables

The library respects these environment variables:

| Variable | Description |
|----------|-------------|
| `SHML_USER_ROLE` | User role for resource allocation (admin, elevated, developer) |
| `AGUI_ENDPOINT` | Default AG-UI HTTP endpoint |
| `NTFY_TOPIC` | Default ntfy.sh topic |
| `MLFLOW_TRACKING_URI` | MLflow server URI |
| `RAY_ADDRESS` | Ray cluster address |

## Troubleshooting

### Import Errors

```python
# Check if library is available
try:
    from shml_training import detect_hardware
    print("SHML Training Library available")
except ImportError:
    print("Install with: pip install -e libs/training")
```

### CUDA Out of Memory

```python
# Use more aggressive memory optimization
config = TrainingConfig(
    batch_size=1,  # Start small
    use_gradient_checkpointing=True,
    use_cpu_offload=True,
    mixed_precision='fp16',
)

optimizer = MemoryOptimizer(config)
optimizer.clear_memory()  # Clear CUDA cache
optimized = optimizer.optimize_for_hardware()
```

### Ray Connection Issues

```python
from shml_training.ray_wrapper import get_ray_cluster_info

info = get_ray_cluster_info("auto")
if 'error' in info:
    print(f"Ray error: {info['error']}")
else:
    print(f"Connected to {info['num_nodes']} nodes")
```

## See Also

- [SHML Training Library README](../libs/training/README.md)
- [SOTA Best Practices Summary](./research/SOTA_BEST_PRACTICES_SUMMARY.md)
- [GPU Native Architecture Migration](./internal/GPU_NATIVE_ARCHITECTURE_MIGRATION.md)
