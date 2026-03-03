# GPU Management

Commands for monitoring and controlling GPU allocation between training and inference workloads.

---

## shml gpu status

Show GPU utilization, memory, and temperature.

```
shml gpu status
```

### Example

```bash
shml gpu status
```

Rich output:

```
          GPU Status
┌────┬────────────────┬─────────────┬───────────────┬──────┐
│ ID │ Name           │ Utilization │ Memory        │ Temp │
├────┼────────────────┼─────────────┼───────────────┼──────┤
│ 0  │ NVIDIA RTX 4090│ 78%         │ 14200/24564 MB│ 72°C │
└────┴────────────────┴─────────────┴───────────────┴──────┘
```

Without Rich, each GPU is printed as a JSON object.

!!! tip
    If no GPU data is returned from the platform API, the CLI suggests running `nvidia-smi` locally.

---

## shml gpu yield

Yield GPU resources for training by stopping inference containers.

```
shml gpu yield
```

### What it does

1. Signals the platform to **stop inference containers** that are occupying GPU memory.
2. Frees GPU resources so training jobs can use the full device.

### Example

```bash
shml gpu yield
```

```
✓ GPU yielded: inference containers stopped, 24564 MB available
```

!!! warning
    Yielding GPUs will **stop all running inference endpoints**. Make sure no production inference traffic depends on them before running this command.

---

## shml gpu reclaim

Reclaim GPU resources by restarting inference containers.

```
shml gpu reclaim
```

### What it does

1. Signals the platform to **restart inference containers**.
2. Returns GPU allocation to the normal shared state between training and inference.

### Example

```bash
shml gpu reclaim
```

```
✓ GPU reclaimed: inference containers restarted
```

---

## Typical Workflow

```bash
# 1. Check current GPU state
shml gpu status

# 2. Free GPUs for a large training run
shml gpu yield

# 3. Submit training
shml train --profile balanced --epochs 50

# 4. Once training completes, restore inference
shml gpu reclaim
```

!!! info "Platform status"
    Use `shml platform status` to check the health of all platform services, including GPU-dependent ones.
