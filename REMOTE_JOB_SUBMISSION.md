# Remote Job Submission Guide

## Quick Start: Submit Jobs from Remote Machine

This guide shows how to submit GPU training jobs to your sfml-platform from any remote machine with Tailscale access.

## Prerequisites

1. **Tailscale VPN** installed and connected
2. **Python 3.8+** with pip
3. **Git** (to clone the repository)

## Setup on Remote Machine

### 1. Clone the Repository

```bash
git clone https://github.com/axelofwar/sfml-platform.git
cd sfml-platform
```

### 2. Install Ray Python Client

```bash
pip install ray[default]==2.9.0
```

### 3. Verify Tailscale Connection

```bash
# Check you can reach the server
ping 100.90.57.39

# Test Ray API endpoint
curl http://100.90.57.39/ray/api/version
```

## Submit Jobs

### Simple GPU Test (30 seconds)

```bash
cd sfml-platform/ray_compute/examples

# Edit test_simple_gpu.py to use Tailscale IP
sed -i 's/ray-head:8265/100.90.57.39\/ray\/api/g' test_simple_gpu.py

# Run test
python3 test_simple_gpu.py
```

### Full GPU Training Test

```bash
cd sfml-platform/ray_compute/examples

# Edit test_full_training.py
sed -i 's/ray-head:8265/100.90.57.39\/ray\/api/g' test_full_training.py

# Run training job
python3 test_full_training.py
```

### Custom Job Submission

```python
#!/usr/bin/env python3
"""
Submit custom job to Ray cluster via Tailscale
"""

from ray.job_submission import JobSubmissionClient
import time

# Connect to Ray via Tailscale
client = JobSubmissionClient("http://100.90.57.39/ray/api")

# Submit job
job_id = client.submit_job(
    entrypoint="python my_training_script.py",
    runtime_env={
        "working_dir": "/path/to/local/training/scripts",
        "pip": ["torch", "numpy", "pandas"],
        "env_vars": {
            "DATASET_PATH": "/data/my_dataset",
        }
    },
    submission_id=f"my_training_{int(time.time())}",
    entrypoint_num_gpus=1,
    entrypoint_num_cpus=4,
    metadata={
        "project": "my-project",
        "experiment": "my-experiment",
    }
)

print(f"Job ID: {job_id}")
print(f"Dashboard: http://100.90.57.39/ray/#/jobs/{job_id}")

# Monitor job status
while True:
    status = client.get_job_status(job_id)
    print(f"Status: {status}")
    
    if status in ["SUCCEEDED", "FAILED", "STOPPED"]:
        break
    
    time.sleep(5)

# Get job logs
logs = client.get_job_logs(job_id)
print("\nJob Logs:")
print(logs)
```

## Monitoring

### Ray Dashboard
```bash
# Open in browser
xdg-open http://100.90.57.39/ray/#/jobs
# or
open http://100.90.57.39/ray/#/jobs  # macOS
```

View:
- Job status and progress
- GPU utilization
- Resource allocation
- Job logs in real-time

### Ray Grafana
```bash
xdg-open http://100.90.57.39/ray-grafana/
```

Login: `admin` / `AiSolutions2350!`

Dashboards:
- GPU usage over time
- System metrics (CPU, memory, network)
- Job execution timelines

### MLflow UI
```bash
xdg-open http://100.90.57.39/mlflow/
```

Login: `mlflow` / `AiSolutions2350!`

Access:
- Experiment tracking
- Model registry
- Dataset registry (WiderFace already registered)

## CLI Job Submission

### Using Ray CLI

```bash
# Install Ray CLI
pip install ray[default]==2.9.0

# Submit job
ray job submit \
  --address http://100.90.57.39/ray/api \
  --working-dir /path/to/local/scripts \
  --runtime-env-json '{"pip": ["torch"]}' \
  --num-gpus 1 \
  --num-cpus 2 \
  -- python training_script.py

# List jobs
ray job list --address http://100.90.57.39/ray/api

# Get job status
ray job status <job-id> --address http://100.90.57.39/ray/api

# Get job logs
ray job logs <job-id> --address http://100.90.57.39/ray/api
```

## Using with MLflow Integration

```python
#!/usr/bin/env python3
"""
Submit training job with MLflow integration
"""

from ray.job_submission import JobSubmissionClient
import time

client = JobSubmissionClient("http://100.90.57.39/ray/api")

# Training script that logs to MLflow
training_code = """
import mlflow
import torch
import time

# Connect to MLflow
mlflow.set_tracking_uri("http://100.90.57.39/mlflow")
mlflow.set_experiment("face-detection-training")

with mlflow.start_run(run_name="remote_training"):
    # Log parameters
    mlflow.log_param("model", "yolov8n")
    mlflow.log_param("epochs", 10)
    mlflow.log_param("batch_size", 16)
    
    # Train model
    device = torch.device("cuda:0")
    # ... your training code ...
    
    # Log metrics
    mlflow.log_metric("accuracy", 0.95)
    mlflow.log_metric("loss", 0.05)
    
    # Log model
    # mlflow.pytorch.log_model(model, "model")

print("Training complete and logged to MLflow!")
"""

job_id = client.submit_job(
    entrypoint=f"python -c '{training_code}'",
    runtime_env={"pip": ["torch", "mlflow"]},
    submission_id=f"mlflow_training_{int(time.time())}",
    entrypoint_num_gpus=1,
    entrypoint_num_cpus=2,
)

print(f"Job: {job_id}")
print(f"Ray: http://100.90.57.39/ray/#/jobs/{job_id}")
print(f"MLflow: http://100.90.57.39/mlflow/#/experiments/1")
```

## Upload Training Data

### Option 1: Include in working_dir

```python
# Your local directory structure:
# my_training/
#   ├── train.py
#   ├── data/
#   │   ├── train.csv
#   │   └── val.csv
#   └── models/
#       └── config.yaml

job_id = client.submit_job(
    entrypoint="python train.py",
    runtime_env={
        "working_dir": "/path/to/my_training",  # Entire directory uploaded
    },
    entrypoint_num_gpus=1,
)
```

### Option 2: Use MLflow Dataset Registry

```python
# Register dataset in MLflow (one time)
import mlflow

mlflow.set_tracking_uri("http://100.90.57.39/mlflow")

dataset = mlflow.data.from_pandas(
    df,
    source="s3://my-bucket/dataset.parquet",
    name="my-training-dataset",
)

mlflow.log_input(dataset, context="training")

# In training script, load from MLflow
"""
import mlflow

mlflow.set_tracking_uri("http://100.90.57.39/mlflow")
client = mlflow.tracking.MlflowClient()

# Get dataset
dataset_info = client.search_datasets(filter_string="name='my-training-dataset'")
# Load and use dataset
"""
```

### Option 3: Direct File Transfer (for large datasets)

```bash
# Copy dataset to server via SSH/SCP
scp -r ./my_dataset/ axelofwar@100.90.57.39:/path/to/shared/storage/

# In job, reference the path
job_id = client.submit_job(
    entrypoint="python train.py --data /path/to/shared/storage/my_dataset",
    runtime_env={
        "working_dir": "/path/to/scripts",
    },
    entrypoint_num_gpus=1,
)
```

## Troubleshooting

### Connection Issues

```bash
# Check Tailscale status
tailscale status

# Check you can reach server
ping 100.90.57.39

# Test Ray API
curl -v http://100.90.57.39/ray/api/version
```

### Job Submission Failures

```python
# Check Ray cluster status
from ray.job_submission import JobSubmissionClient

client = JobSubmissionClient("http://100.90.57.39/ray/api")
print("Connected to Ray cluster!")

# List recent jobs
# (Ray Python SDK doesn't have list_jobs, use CLI)
```

```bash
ray job list --address http://100.90.57.39/ray/api
```

### GPU Not Available

- Check GPU allocation in Ray dashboard
- Verify `entrypoint_num_gpus=1` is set correctly
- Ensure no other jobs are using all GPUs

### Runtime Environment Issues

- Make sure all dependencies are listed in `runtime_env["pip"]`
- Check job logs for import errors
- Verify PyTorch/CUDA compatibility

## Example: pii-pro Integration

```python
#!/usr/bin/env python3
"""
Submit pii-pro YOLOv8 training to remote cluster
"""

from ray.job_submission import JobSubmissionClient
import time

client = JobSubmissionClient("http://100.90.57.39/ray/api")

job_id = client.submit_job(
    entrypoint="python train_yolo.py --config yolov8n.yaml",
    runtime_env={
        "working_dir": "/path/to/pii-pro/training",
        "pip": [
            "torch==2.1.0",
            "torchvision==0.16.0",
            "ultralytics==8.0.0",
            "mlflow==2.9.2",
        ],
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://100.90.57.39/mlflow",
            "EXPERIMENT_NAME": "face-detection-training",
            "DATASET_PATH": "mlflow-artifacts:/datasets/widerface/v1",
        }
    },
    submission_id=f"pii_pro_training_{int(time.time())}",
    entrypoint_num_gpus=1,
    entrypoint_num_cpus=4,
    metadata={
        "project": "pii-pro",
        "model": "yolov8n",
        "dataset": "widerface",
    }
)

print(f"✅ pii-pro training submitted!")
print(f"   Job ID: {job_id}")
print(f"   Ray Dashboard: http://100.90.57.39/ray/#/jobs/{job_id}")
print(f"   MLflow Experiments: http://100.90.57.39/mlflow/#/experiments")
print(f"   Grafana Monitoring: http://100.90.57.39/ray-grafana/")
```

## Access URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Ray Dashboard | http://100.90.57.39/ray/ | N/A |
| Ray API | http://100.90.57.39/ray/api | N/A |
| Ray Grafana | http://100.90.57.39/ray-grafana/ | admin / AiSolutions2350! |
| MLflow | http://100.90.57.39/mlflow/ | mlflow / AiSolutions2350! |
| Traefik Dashboard | http://100.90.57.39/dashboard/ | N/A |

## Resources

- **Ray Documentation:** https://docs.ray.io/
- **Ray Job Submission:** https://docs.ray.io/en/latest/cluster/running-applications/job-submission/index.html
- **MLflow Documentation:** https://mlflow.org/docs/latest/index.html
- **Platform Repo:** https://github.com/axelofwar/sfml-platform

## Support

For issues:
1. Check `RAY_GPU_TESTING_SUMMARY.md` for common problems
2. View `ray_compute/examples/README.md` for detailed examples
3. Check job logs in Ray dashboard
4. Review Grafana for system metrics

---

**Last Updated:** November 24, 2025  
**Platform Version:** 0.2.0  
**Ray Version:** 2.9.0-gpu  
**Server:** axelofwar-server (100.90.57.39)
