# Archived Approaches - GPU Sharing Strategies

This folder contains design documents for approaches that were explored but **not implemented** due to technical limitations.

## Why These Approaches Were Abandoned

### 1. NVIDIA MPS (Multi-Process Service) - `DYNAMIC_MPS_DESIGN.md`

**What it was:** Use NVIDIA MPS daemon to allow concurrent GPU sharing between training and inference.

**Why it failed:**

| Problem | Impact |
|---------|--------|
| **Memory math doesn't work** | 32B model needs ~20GB, training needs ~6-12GB, RTX 3090 Ti only has 24GB |
| **MPS blocks Docker containers** | When MPS is at 100% thread allocation, Docker containers can't access GPUs |
| **OOM risk during training** | Training VRAM usage peaks during validation/mAP calculation - any additional load causes crashes |
| **Complexity vs benefit** | Checkpoint-based pausing is simpler and achieves same goal |

**Key insight from testing:**
```bash
# MPS daemon blocks Ray containers from accessing GPUs
# We added stop_mps_daemon() to start_all_safe.sh to handle this
systemctl stop nvidia-mps  # Required before starting Ray
```

### 2. GPU Native Architecture - `GPU_NATIVE_ARCHITECTURE_MIGRATION.md`

**What it was:** Run vLLM and training natively (outside Docker) with MPS for sharing.

**Why it failed:**

- **Environment conflicts:** PyTorch/CUDA versions for training vs inference differ
- **MPS still doesn't solve memory problem** (see above)
- **Loses Docker isolation benefits:** Harder to manage, no easy rollback
- **Security concerns:** Native processes harder to sandbox

## What Actually Works (Current Implementation)

### Health-Check Based Routing

```
┌─────────────────────────────────────────────────────────────────┐
│                     IMPLEMENTED ARCHITECTURE                     │
│                                                                  │
│  GPU 0 (3090 Ti) ──── Training OR Primary Model (mutually       │
│                       exclusive via YIELD_ON_TRAINING=true)      │
│                                                                  │
│  GPU 1 (2070) ─────── Fallback Model (always available)          │
│                                                                  │
│  Traefik routes based on container health checks:                │
│  - Primary healthy → route to primary (priority=210)             │
│  - Primary unhealthy → route to fallback (priority=200)          │
└─────────────────────────────────────────────────────────────────┘
```

**Key files:**
- `inference/coding-model/docker-compose.yml` - Dual model setup
- `start_all_safe.sh` - MPS stop logic (lines 280-340)
- `chat-ui/src/components/TrainingAwareModelSelector.tsx` - UI routing

### Why This Works

1. **Clean resource isolation:** GPU 0 for training OR primary, never both
2. **Automatic failover:** Traefik health checks handle routing
3. **Simple state machine:** Primary yields when Ray job detected
4. **No MPS complexity:** Docker GPU isolation "just works"

## Lessons Learned

1. **Don't fight physics:** 24GB VRAM cannot fit 20GB model + 12GB training
2. **Simpler is better:** Health-check routing beats complex MPS control
3. **MPS is problematic:** Blocks Docker GPU access, requires careful lifecycle management
4. **Dual GPU is the answer:** Dedicate each GPU to its role, no sharing needed

## Related Documentation

- `../ARCHITECTURE.md` - Current architecture (needs MPS section removed)
- `../../SETUP_COMPLETE.md` - Setup status (needs MPS claim removed)
- `../../inference/coding-model/docker-compose.yml` - Actual implementation
