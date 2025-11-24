# Ray GPU Job Submission Examples

This directory contains working examples for submitting GPU jobs to the Ray cluster.

## Files

### Working Examples

1. **`test_simple_gpu.py`** - Simple GPU availability test
   - Tests basic GPU allocation
   - Verifies PyTorch can access GPU
   - Quick validation (< 30 seconds)

2. **`test_full_training.py`** - Full GPU training simulation
   - Simulates pii-pro WiderFace YOLOv8 training workflow
   - Multi-scale training (480px, 640px, 800px)
   - GPU-accelerated convolutions
   - Proper gradient computation
   - Memory-efficient training loop
   - Validation phase
   - Runs for ~30-60 seconds

3. **`training_script.py`** - Standalone training script
   - Can be executed directly or uploaded to Ray
   - Contains the full training loop logic
   - Used by `test_full_training.py`

## Usage

### From ray-compute-api Container

```bash
# Simple GPU test
sudo docker cp /home/axelofwar/Projects/sfml-platform/ray_compute/examples/test_simple_gpu.py ray-compute-api:/tmp/
sudo docker exec ray-compute-api python3 /tmp/test_simple_gpu.py

# Full training test
sudo docker cp /home/axelofwar/Projects/sfml-platform/ray_compute/examples/test_full_training.py ray-compute-api:/tmp/
sudo docker cp /home/axelofwar/Projects/sfml-platform/ray_compute/examples/training_script.py ray-compute-api:/tmp/
sudo docker exec ray-compute-api python3 /tmp/test_full_training.py
```

### From Remote Machine

If accessing via Tailscale (100.90.57.39):

```python
from ray.job_submission import JobSubmissionClient
import os

# Connect to Ray via Tailscale
client = JobSubmissionClient("http://100.90.57.39/ray/api")

# Upload local directory with training scripts
script_dir = "/path/to/local/scripts"

job_id = client.submit_job(
    entrypoint="python training_script.py",
    runtime_env={
        "working_dir": script_dir,
        "pip": ["torch"],
    },
    submission_id=f"remote_training_{int(time.time())}",
    entrypoint_num_gpus=1,
    entrypoint_num_cpus=2,
)

# Monitor job
print(f"Job ID: {job_id}")
print(f"Dashboard: http://100.90.57.39/ray/#/jobs/{job_id}")
```

## Important Notes

### Ray Job Submission API

**Correct parameter names:**
- Use `entrypoint_num_gpus=1` (NOT `resources={"GPU": 1}`)
- Use `entrypoint_num_cpus=2` (NOT `resources={"CPU": 2}`)

The old `resources={"GPU": 1, "CPU": 2}` syntax will cause:
```
Failed to start supervisor actor: 'Use the 'num_cpus' and 'num_gpus' keyword instead of 'CPU' and 'GPU' in 'resources' keyword'
```

### PyTorch Gradient Computation

**Always use `requires_grad=True` for model parameters:**

```python
# ✅ CORRECT
weights = torch.randn(64, 3, 3, 3, device=device, requires_grad=True)
output = torch.nn.functional.conv2d(batch, weights)
loss = output.mean()
loss.backward()  # Works!

# ❌ WRONG
weights = torch.randn(64, 3, 3, 3, device=device)  # No requires_grad=True
output = torch.nn.functional.conv2d(batch, weights)
loss = output.mean()
loss.backward()  # RuntimeError: element 0 of tensors does not require grad
```

### Runtime Environment

The `runtime_env` parameter handles:
- **`pip`**: Install Python packages (e.g., `["torch", "numpy"]`)
- **`working_dir`**: Upload local directory to Ray (zipped and uploaded to GCS)
- **`env_vars`**: Set environment variables

Example with dataset from MLflow:
```python
runtime_env={
    "pip": ["torch", "mlflow"],
    "working_dir": "/path/to/scripts",
    "env_vars": {
        "MLFLOW_TRACKING_URI": "http://mlflow-server:5000",
        "DATASET_NAME": "widerface",
    }
}
```

## Monitoring

### Ray Dashboard
- Local: http://localhost/ray/#/jobs
- Tailscale: http://100.90.57.39/ray/#/jobs
- View job status, logs, and resource usage

### Ray Grafana
- Local: http://localhost/ray-grafana/
- Tailscale: http://100.90.57.39/ray-grafana/
- Login: admin / AiSolutions2350!
- Monitor GPU usage, system metrics

### MLflow UI
- Local: http://localhost/mlflow/
- Tailscale: http://100.90.57.39/mlflow/
- Login: mlflow / AiSolutions2350!
- Track experiments, datasets, model registry

## Access URLs

| Service | Local | Tailscale (Remote) | Credentials |
|---------|-------|-------------------|-------------|
| Ray Dashboard | http://localhost/ray/ | http://100.90.57.39/ray/ | N/A |
| Ray Grafana | http://localhost/ray-grafana/ | http://100.90.57.39/ray-grafana/ | admin / AiSolutions2350! |
| MLflow | http://localhost/mlflow/ | http://100.90.57.39/mlflow/ | mlflow / AiSolutions2350! |
| Traefik | http://localhost/dashboard/ | http://100.90.57.39/dashboard/ | N/A |

## Troubleshooting

### Job Fails with "does not require grad"
- Make sure all tensors that need gradients have `requires_grad=True`
- Use the pattern shown in `training_script.py`

### Job Fails with "Use the 'num_cpus' and 'num_gpus' keyword"
- Update to correct parameter names: `entrypoint_num_gpus`, `entrypoint_num_cpus`
- See examples in this directory

### Job Stuck in PENDING
- Check GPU availability: `sudo docker exec ray-head ray status`
- Verify GPU not already in use by another job
- Check Ray dashboard for resource allocation

### "working_dir must be an existing directory"
- The path must exist on the machine running `submit_job()`
- Ray will zip and upload the directory to the cluster
- Alternatively, upload files to ray-head and reference them in entrypoint

## Example: Full pii-pro Integration

```python
#!/usr/bin/env python3
"""
Submit pii-pro training job to Ray with MLflow integration
"""

from ray.job_submission import JobSubmissionClient
import time

client = JobSubmissionClient("http://ray-head:8265")

job_id = client.submit_job(
    entrypoint="python train_yolov8_widerface.py",
    runtime_env={
        "working_dir": "/home/axelofwar/Projects/pii-pro/training",
        "pip": ["torch", "ultralytics", "mlflow", "boto3"],
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://mlflow-server:5000",
            "EXPERIMENT_NAME": "face-detection-training",
            "MODEL_NAME": "yolov8n-face",
            "DATASET_URI": "mlflow-artifacts:/datasets/widerface/v1",
        }
    },
    submission_id=f"pii_pro_training_{int(time.time())}",
    entrypoint_num_gpus=1,
    entrypoint_num_cpus=4,
    metadata={
        "project": "pii-pro",
        "model": "yolov8n",
        "dataset": "widerface",
        "version": "v7",
    }
)

print(f"✅ pii-pro training job submitted: {job_id}")
print(f"   Ray Dashboard: http://100.90.57.39/ray/#/jobs/{job_id}")
print(f"   MLflow: http://100.90.57.39/mlflow/#/experiments")
```

## System Info

- **Host:** axelofwar-server
- **GPUs:** RTX 3090 Ti (24GB), RTX 2070 (8GB)
- **Ray:** 2.9.0-gpu
- **PyTorch:** 2.1.0+cu118
- **CUDA:** 11.8
