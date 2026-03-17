---
name: gpu-monitoring
description: Monitor GPU status, VRAM usage, temperature, and utilization using nvidia-smi directly. Use when the user asks about GPU status, VRAM, CUDA, GPU memory, GPU utilization, or GPU temperature. Preferred over Ray API for direct GPU metrics.
license: MIT
compatibility: Requires nvidia-smi installed on host or accessible via Docker
metadata:
  author: shml-platform
  version: "1.0"
allowed-tools: Bash(nvidia-smi:*) Bash(docker:*)
---

# GPU Monitoring Skill

## When to use this skill
Use this skill when the user asks about:
- GPU status or health
- VRAM/memory usage
- GPU utilization percentage
- GPU temperature
- CUDA availability
- Which GPUs are available
- GPU allocation for training

## Primary Method: nvidia-smi

The most reliable way to get GPU information is via `nvidia-smi` directly:

```bash
# Full GPU status
nvidia-smi

# Concise query format
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv,noheader

# Just memory usage
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader

# Process list (what's using the GPU)
nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader
```

## Fallback Methods

If nvidia-smi is not available on host, try:

1. **Docker container with GPU access:**
   ```bash
   docker exec <container-with-gpu> nvidia-smi
   ```

2. **Grafana Dashboard:**
   - URL: http://localhost:3000/d/gpu-monitoring
   - Provides historical metrics and trends

3. **Ray Dashboard:**
   - URL: http://localhost:8265
   - Shows GPU allocation per Ray job

## Expected Output Format

Return GPU information in this structured format:

```json
{
  "gpus": [
    {
      "index": 0,
      "name": "NVIDIA GeForce RTX 3090 Ti",
      "memory_total": "24576 MiB",
      "memory_used": "1234 MiB",
      "memory_free": "23342 MiB",
      "utilization": "45%",
      "temperature": "52C"
    }
  ],
  "total_gpus": 2,
  "healthy": true
}
```

## Error Handling

If nvidia-smi fails:
1. Check if NVIDIA drivers are installed: `which nvidia-smi`
2. If not found, PROMPT USER: "nvidia-smi not found. Would you like me to help install NVIDIA drivers?"
3. Check docker access: `docker exec nemotron-coding nvidia-smi`
4. If container doesn't have GPU: suggest container with `--gpus all`

## Platform-Specific GPU Allocation

SHML Platform GPU strategy:
- **RTX 3090 Ti (cuda:0, 24GB)**: Training priority, Nemotron coding model
- **RTX 2070 (cuda:1, 8GB)**: Qwen3-VL vision, fallback coding

Before training, yield RTX 3090:
```bash
curl -X POST http://localhost/api/image/yield-to-training
```
