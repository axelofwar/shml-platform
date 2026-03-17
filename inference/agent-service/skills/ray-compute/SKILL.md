---
name: ray-compute
description: Submit and manage distributed training jobs on the Ray cluster. Use for GPU-accelerated training, face detection training with curriculum learning, and distributed computing tasks. Check job status, logs, and metrics.
license: MIT
compatibility: Requires Ray cluster running (ray-compute-api). Needs elevated-developer role for job submission.
metadata:
  author: shml-platform
  version: "1.0"
allowed-tools: Bash(curl:*) Bash(ray:*)
---

# Ray Compute Skill

## When to use this skill
Use this skill when the user asks to:
- Submit a training job
- Train a model (face detection, YOLO, etc.)
- Check job status or logs
- List running/completed jobs
- Cancel a job
- Use distributed computing

## API Endpoints

Base URL: `http://ray-compute-api:8000/api/v1`

### Jobs
- `GET /jobs` - List all jobs
- `POST /jobs` - Submit new job
- `GET /jobs/{job_id}` - Get job status
- `DELETE /jobs/{job_id}` - Cancel job
- `GET /jobs/{job_id}/logs` - Get job logs

### Resources
- `GET /resources` - Get cluster resources
- `GET /health` - Health check

## Face Detection Training

SHML Platform's flagship training capability:

```python
result = await execute("submit_face_detection", {
    "epochs": 100,
    "batch_size": 8,
    "imgsz": 1280,
    "curriculum_enabled": True,  # 4-stage curriculum learning
    "recall_focused": True       # Prioritize recall for privacy
})
```

### Curriculum Learning Stages
1. **Presence Detection (20%)** - Basic face vs non-face
2. **Localization (30%)** - Precise bounding boxes
3. **Occlusion Handling (25%)** - Partial faces, masks
4. **Multi-Scale (25%)** - Tiny + large faces

## GPU Allocation

- **RTX 3090 Ti**: Training priority (yield Z-Image first)
- **RTX 2070**: Vision model (Qwen3-VL)

Before training:
```bash
curl -X POST http://localhost/api/image/yield-to-training
```

## Common Operations

### List Jobs
```bash
curl http://ray-compute-api:8000/api/v1/jobs
```

### Submit Generic Job
```bash
curl -X POST http://ray-compute-api:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "entrypoint": "python train.py --epochs 10",
    "runtime_env": {"working_dir": "/app/jobs"},
    "entrypoint_num_gpus": 1
  }'
```

### Get Job Status
```bash
curl http://ray-compute-api:8000/api/v1/jobs/{job_id}
```

### Cancel Job
```bash
curl -X DELETE http://ray-compute-api:8000/api/v1/jobs/{job_id}
```

## Error Handling

| Code | Meaning | Action |
|------|---------|--------|
| 401 | Unauthorized | Check OAuth token |
| 403 | Forbidden | Need elevated-developer role |
| 503 | No GPUs | Yield Z-Image or wait |
| 507 | Out of memory | Reduce batch size |

## Fallback for GPU Status

If Ray API returns 401/503, use gpu-monitoring skill instead:
```bash
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv
```
