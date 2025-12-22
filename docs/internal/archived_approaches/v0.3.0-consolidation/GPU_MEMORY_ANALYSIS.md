# GPU Memory Analysis & Fallback Model Upgrade Guide

## Current GPU Configuration

### GPU 0: NVIDIA RTX 3090 Ti (24GB)
- **Role**: Primary inference model OR training
- **Display**: Disabled
- **Current usage during training**: ~18-21GB

### GPU 1: NVIDIA RTX 2070 (8GB)  
- **Role**: Fallback inference model (always available)
- **Display**: **ENABLED** (3 monitors connected via DP-4, HDMI-A-2, HDMI-A-3)
- **Display overhead**: ~1.2GB

## GPU 1 Memory Breakdown

| Component | Memory (MiB) |
|-----------|-------------|
| Total VRAM | 8192 |
| Display overhead (3 monitors) | ~1184 |
| **Available for compute** | **~7008** |

### Current Fallback Model (Qwen2.5-Coder-3B-AWQ)
| Component | Memory (MiB) |
|-----------|-------------|
| vLLM Engine | 6080 |
| Python process | 96 |
| **Total compute** | **6176** |
| **Headroom** | **~832** |

## Display Overhead Options

### Option 1: Keep Current Setup (Recommended during training)
- Accept ~1.2GB overhead from display
- Available: ~6.8GB for inference
- Pros: No physical changes, training unaffected
- Cons: Limited model size options

### Option 2: Move Displays to GPU 0
- Physically reconnect monitors to RTX 3090 Ti ports
- Frees ~1.2GB on GPU 1
- **NOT recommended** - could interfere with training

### Option 3: Go Headless
- Disable display manager: `sudo systemctl disable gdm`
- Use SSH/remote access only
- Frees ~1.2GB on GPU 1
- Requires reboot

## Fallback Model Upgrade Options

### Candidate Models (AWQ quantized, 4-bit)

| Model | Disk Size | VRAM (estimate) | Quality | Fits in 6.8GB? |
|-------|-----------|-----------------|---------|----------------|
| Qwen2.5-Coder-3B-AWQ (current) | 2.0GB | ~4GB + 2GB KV | ~75% | ✅ Yes |
| DeepSeek-Coder-6.7B-AWQ | 3.6GB | ~4GB + 1.5GB KV | ~82% | ⚠️ Tight |
| Qwen2.5-Coder-7B-AWQ | 4.2GB | ~4.5GB + KV | ~80% | ⚠️ Reduce context |
| CodeLlama-7B-Instruct-AWQ | 3.8GB | ~4GB + KV | ~78% | ⚠️ Tight |

### Recommended Upgrade Path

**DeepSeek-Coder-6.7B-Instruct-AWQ** with reduced context:
- Model ID: `TheBloke/deepseek-coder-6.7B-instruct-AWQ`
- Max context: 4096 (down from 8192)
- Expected VRAM: ~5.5GB
- Quality improvement: ~75% → ~82%

## Testing Procedure

### Safe Fallback Model Test (No Training Interruption)

```bash
cd /home/axelofwar/Projects/shml-platform/inference/coding-model

# Test DeepSeek-Coder-6.7B with 4K context
./test_fallback_model.sh "TheBloke/deepseek-coder-6.7B-instruct-AWQ" 4096

# Or test Qwen 7B with reduced context
./test_fallback_model.sh "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ" 2048
```

### What the Test Script Does

1. ✅ Verifies training is still running (won't be affected)
2. ✅ Verifies primary model won't be touched
3. ✅ Stops ONLY the fallback container
4. ✅ Starts fallback with new model configuration
5. ✅ Waits for model to load and health check
6. ✅ Runs inference test
7. ✅ Reports final GPU memory usage

### Reverting to Original Model

```bash
cd /home/axelofwar/Projects/shml-platform/inference/coding-model
docker compose up -d coding-model-fallback
```

## Making Changes Permanent

After successful testing, update `docker-compose.yml`:

```yaml
coding-model-fallback:
  environment:
    - MODEL_ID=TheBloke/deepseek-coder-6.7B-instruct-AWQ  # Changed
    - MAX_MODEL_LEN=4096  # Reduced from 8192
    - GPU_MEMORY_UTILIZATION=0.85  # Increased slightly
```

## Future Improvements

### If You Upgrade GPU 1
- RTX 3060 12GB would allow 13B models
- RTX 3070 8GB has same constraints but faster
- RTX 3080 10GB would allow 7B with full context

### If You Move to Headless
- Gain ~1.2GB on GPU 1
- Could run 7B model with 8K context
- Or run 6.7B with larger KV cache

## Monitoring Commands

```bash
# GPU memory usage
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv

# Check display status
nvidia-smi --query-gpu=index,display_active --format=csv

# Check fallback model health
docker exec coding-model-fallback curl -s http://localhost:8000/health

# Check fallback model logs
docker logs -f coding-model-fallback
```
