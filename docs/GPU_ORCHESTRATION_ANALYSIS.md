# GPU Yield & Model Orchestration Analysis

## Current State Analysis

### GPU Allocation (Current)

| GPU | VRAM | Current Services | Status |
|-----|------|-----------------|--------|
| **RTX 3090 Ti (cuda:0)** | 24GB | Nemotron-3 Nano 30B (~23GB) | 93% utilized |
| **RTX 2070 (cuda:1)** | 8GB | Qwen3-VL INT4 (~6.2GB) + coding-model-fallback (~1.5GB) | 95% utilized |

### GPU Yielding Analysis

**Current Yield Mechanisms:**

1. **Z-Image (on RTX 3090)** ✅ **WORKS**
   - Implements `YIELD_TO_TRAINING=true` in config
   - Auto-unloads after 300s (5min) idle
   - Endpoint: `POST /yield-to-training`
   - Training jobs can request via `/api/image/yield-to-training`

2. **Nemotron-3 (on RTX 3090)** ⚠️ **MANUAL ONLY**
   - Script: `inference/scripts/yield_to_training.sh`
   - Uses `docker stop nemotron-coding`
   - **NO API ENDPOINT** - llama.cpp doesn't have dynamic unload
   - Ray jobs look for `/training/start` endpoint (from old coding-model-primary)

3. **Qwen3-VL (on RTX 2070)** ✅ **HIGH AVAILABILITY**
   - Always loaded, never yields
   - INT4 quantization keeps it at ~6.2GB
   - Perfect for vision tasks during training

### Critical Gap: Nemotron Has No Yield API

**Problem:** Ray training jobs call `_request_gpu_yield()` which tries:
- `http://coding-model-primary:8000/training/start`
- `http://shml-coding-model-primary:8000/training/start`
- `http://localhost:8000/training/start`

But Nemotron (llama.cpp's llama-server) doesn't have a `/training/start` endpoint!

**Current Workaround:** Manual script execution before training:
```bash
./inference/scripts/yield_to_training.sh
```

---

## Recommendations

### 1. Create Nemotron Yield Wrapper Service

Add a lightweight sidecar service that manages Nemotron lifecycle:

```yaml
# inference/nemotron/docker-compose.yml - add service
nemotron-manager:
  image: python:3.11-slim
  container_name: nemotron-manager
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
  environment:
    - NEMOTRON_CONTAINER=nemotron-coding
  command: python /app/manager.py
  ports:
    - "8011:8000"
```

**Manager endpoints:**
- `POST /training/start` - Stop Nemotron, return when GPU free
- `POST /training/end` - Restart Nemotron
- `GET /status` - Container status

### 2. Add Meta-Orchestrator for Model Selection

**YES - High Value!** Add a high-level orchestrator that:

```
┌─────────────────────────────────────────────────────────────────┐
│                    META-ORCHESTRATOR                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │Task Classifier│→ │Model Selector │→ │Execution Planner     │  │
│  │(keyword+ML)   │  │(capability)   │  │(sequential/parallel) │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                   │                      │
         ▼                   ▼                      ▼
┌─────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Nemotron-3 │    │   Qwen3-VL      │    │    Z-Image      │
│  (Agentic)  │    │   (Vision)      │    │   (ImageGen)    │
│  RTX 3090   │    │   RTX 2070      │    │   RTX 3090      │
│  temp=0.6   │    │   Always ON     │    │   On-Demand     │
└─────────────┘    └─────────────────┘    └─────────────────┘
```

**Benefits:**
- Single API for all model types
- Automatic task detection & routing
- Chain models for multi-modal tasks
- Training-aware scheduling

### 3. RTX 2070 High-Availability Strategy

**Current 2070 Usage:**
- Qwen3-VL (~6.2GB) - Vision, always loaded ✅
- coding-model-fallback (~1.5GB) - Small coder ✅

**Total:** ~7.7GB / 8GB = **Perfect allocation!**

**Recommendation:** Keep current setup but add failover logic:

```python
# When RTX 3090 busy with training:
if gpu_0_training_active:
    use model:
      - coding-model-fallback (7B, on RTX 2070)
      - Qwen3-VL for vision tasks
else:
    use model:
      - Nemotron-3 (30B, on RTX 3090) for coding
      - Z-Image for image gen
```

### 4. Permanent RTX 2070 Services

**Recommended always-on services:**

| Service | Model | VRAM | Purpose |
|---------|-------|------|---------|
| **Qwen3-VL** | 8B INT4 | ~6.2GB | Vision, OCR, screenshot analysis |
| **coding-model-fallback** | 7B | ~1.5GB | Fallback coder during training |
| **Total** | - | **~7.7GB** | 97% utilized |

**Do NOT add more to 2070** - it's optimally loaded.

### 5. Improved Model Router Config

Update `model_router.py` to include:

```python
class ModelConfig:
    MODELS = {
        # Primary coding (RTX 3090, yields to training)
        "nemotron-3": {
            "gpu": "cuda:0",
            "vram_gb": 23,
            "yields_to_training": True,
            "capabilities": ["coding", "agentic", "tool_calling"],
            "endpoint": "http://nemotron-coding:8000",
        },
        # Vision (RTX 2070, always available)
        "qwen3-vl": {
            "gpu": "cuda:1",
            "vram_gb": 6.2,
            "yields_to_training": False,  # Always available
            "capabilities": ["vision", "ocr", "multimodal"],
            "endpoint": "http://qwen3-vl-api:8000",
        },
        # Fallback coder (RTX 2070, always available)
        "coder-7b": {
            "gpu": "cuda:1",
            "vram_gb": 1.5,
            "yields_to_training": False,  # Always available
            "capabilities": ["coding", "simple_tasks"],
            "endpoint": "http://coding-model-fallback:8000",
        },
        # Image gen (RTX 3090, on-demand)
        "z-image": {
            "gpu": "cuda:0",
            "vram_gb": 8,
            "yields_to_training": True,
            "capabilities": ["image_generation"],
            "endpoint": "http://z-image-api:8000",
        },
    }
```

---

## Implementation Priority

| Priority | Task | Effort | Value |
|----------|------|--------|-------|
| **P0** | Create nemotron-manager sidecar for yield API | 2h | High - enables automatic GPU yield |
| **P1** | Update Ray jobs to call nemotron-manager | 1h | High - seamless training |
| **P2** | Add training-aware routing to model_router.py | 2h | High - auto-fallback during training |
| **P3** | Meta-orchestrator service | 4h | Medium - unified API |
| **P4** | MCP tool for model selection | 1h | Medium - agentic awareness |

---

## Quick Implementation: Nemotron Manager

```python
# inference/nemotron/manager/app.py
"""Nemotron lifecycle manager - provides yield API for training."""

import docker
from fastapi import FastAPI
import asyncio

app = FastAPI()
client = docker.from_env()
CONTAINER_NAME = "nemotron-coding"

@app.post("/training/start")
async def start_training(job_id: str = "unknown"):
    """Stop Nemotron to free GPU for training."""
    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status == "running":
            container.stop(timeout=30)
            # Wait for GPU memory to be freed
            await asyncio.sleep(3)
            return {"status": "ready", "model_yielded": True, "job_id": job_id}
        return {"status": "ready", "model_yielded": False, "message": "Already stopped"}
    except docker.errors.NotFound:
        return {"status": "ready", "model_yielded": False, "message": "Not running"}

@app.post("/training/end")
async def end_training(job_id: str = "unknown"):
    """Restart Nemotron after training completes."""
    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status != "running":
            container.start()
            return {"status": "started", "job_id": job_id}
        return {"status": "running", "message": "Already running"}
    except docker.errors.NotFound:
        return {"status": "error", "message": "Container not found"}

@app.get("/health")
async def health():
    """Health check with Nemotron status."""
    try:
        container = client.containers.get(CONTAINER_NAME)
        return {"status": "healthy", "nemotron_status": container.status}
    except:
        return {"status": "healthy", "nemotron_status": "unknown"}
```

---

## Summary

1. **GPU Yielding:** Z-Image works, but **Nemotron needs a manager service** for automatic yield
2. **Meta-Orchestrator:** **YES, valuable!** Add to unify model selection and handle multi-modal routing
3. **RTX 2070 High Availability:** Already optimal with Qwen3-VL + coding-fallback (~7.7GB/8GB)
4. **During Training:** System should automatically route to RTX 2070 models (Qwen3-VL, coder-7b)

**Immediate Action:** Create `nemotron-manager` sidecar to enable API-based GPU yielding.
