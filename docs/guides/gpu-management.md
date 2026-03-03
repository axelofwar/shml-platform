# GPU Management

How the SHML Platform allocates, yields, and reclaims GPU resources
across training and inference workloads.

---

## Hardware

| GPU | VRAM | CUDA Cores | Primary Role |
|-----|------|------------|--------------|
| NVIDIA RTX 3090 Ti | 24 GB | 10 752 | Training (GPU 0) |
| NVIDIA RTX 2070 | 8 GB | 2 304 | Inference (GPU 1) |

Both GPUs are visible to the Ray cluster. The platform scheduler
assigns workloads based on VRAM requirements and current state.

---

## GPU Lifecycle

```
idle ──▶ training ──▶ cooldown ──▶ idle
                        │
                        ▼
                    inference
```

| State | Description |
|-------|-------------|
| **idle** | GPU available, no active workload |
| **training** | Occupied by a Ray training job |
| **cooldown** | Brief pause after training (thermal / VRAM cleanup) |
| **inference** | Serving real-time inference requests |

---

## Yield / Reclaim Workflow

Inference containers normally hold the GPU. Before a training job can
run, the GPU must be **yielded**; afterward it is **reclaimed**.

### 1. Yield

```bash
# SDK
with Client() as c:
    c.gpu_yield(gpu_ids=[0])

# CLI
shml gpu yield --ids 0

# API
curl -X POST http://localhost/api/ray/gpu/yield \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SHML_API_KEY" \
  -d '{"gpu_ids": [0]}'
```

!!! warning
    Yielding stops inference on the target GPU. Dependent services will
    return errors until the GPU is reclaimed.

### 2. Run Training

Submit and wait for the job to complete (see
[Training Walkthrough](training-walkthrough.md)).

### 3. Reclaim

```bash
# SDK
with Client() as c:
    c.gpu_reclaim()

# CLI
shml gpu reclaim

# API
curl -X POST http://localhost/api/ray/gpu/reclaim \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SHML_API_KEY" \
  -d '{}'
```

---

## Multi-GPU Considerations

- **Data-parallel training** splits batches across both GPUs. Set
  `gpu: 2.0` in the job payload to request all available GPUs.
- The RTX 2070 has only 8 GB VRAM, so large models or high-resolution
  images may OOM on it. Prefer the RTX 3090 Ti for heavy workloads.
- When both GPUs are used for training, **all inference is offline**.

!!! tip "Single-GPU safe mode"
    To keep inference running on GPU 1 while training on GPU 0:
    ```bash
    shml gpu yield --ids 0
    shml train submit --profile balanced --gpu-ids 0
    ```

---

## Memory Management

Batch size and image size are the two biggest levers for VRAM usage.

| Config | RTX 3090 Ti (24 GB) | RTX 2070 (8 GB) |
|--------|---------------------|-----------------|
| `batch=16, imgsz=640` | ~10 GB | OOM |
| `batch=8, imgsz=640` | ~6 GB | ~5 GB |
| `batch=4, imgsz=1280` | ~14 GB | OOM |
| `batch=2, imgsz=1280` | ~8 GB | ~7 GB |

!!! danger "Out-of-memory"
    If a job fails with `CUDA out of memory`, reduce batch size or image
    size and resubmit.

### Checking Current Usage

```bash
# Quick check
shml gpu status

# Detailed (nvidia-smi)
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu \
  --format=csv
```
