# Ray Job Submission Guide

**Version**: 1.0  
**Last Updated**: November 23, 2025  
**Platform**: ML Platform Ray Compute

## Overview

This guide covers all methods for submitting jobs to the Ray Compute platform, from both local and remote machines, with full MLflow integration for experiment tracking. All jobs automatically log to MLflow when the tracking URI is configured.

## Prerequisites

- Ray Compute platform running (`./start_all.sh`)
- MLflow server accessible
- OAuth credentials (for remote submission)
- Python 3.8+ with ray[default]==2.9.0

## Job Submission Methods

### 1. Local Submission (Inside Ray Container)

**When to use**: Testing, debugging, direct access to Ray head node

```bash
# Enter the Ray container
docker exec -it ray-head bash

# Submit a job
ray job submit \
  --address="http://127.0.0.1:8265" \
  --runtime-env-json='{"env_vars":{"MLFLOW_TRACKING_URI":"http://mlflow-server:5000"}}' \
  -- python /opt/ray/my_script.py
```

**Example Job Script** (`/opt/ray/my_script.py`):
```python
import ray
import mlflow

@ray.remote
def train_model(param1):
    # Your training code
    return {"accuracy": 0.95}

# Initialize Ray
ray.init(address="auto")

# MLflow is pre-configured via environment
mlflow.set_experiment("my-experiment")

with mlflow.start_run():
    mlflow.log_param("param1", "value1")
    
    # Run distributed training
    results = ray.get([train_model.remote(i) for i in range(10)])
    
    mlflow.log_metric("accuracy", sum(r["accuracy"] for r in results) / len(results))

ray.shutdown()
```

### 2. Host Machine Submission (via Script)

**When to use**: Quick testing from host, CI/CD pipelines

```bash
# From ml-platform directory
cd /home/axelofwar/Desktop/Projects/ml-platform

# Run test jobs
./ray_compute/test_jobs.sh

# Submit custom job
docker exec ray-head ray job submit \
  --address="http://127.0.0.1:8265" \
  --working-dir /opt/ray/job_workspaces \
  --runtime-env-json='{"pip":["scikit-learn","pandas"],"env_vars":{"MLFLOW_TRACKING_URI":"http://mlflow-server:5000"}}' \
  -- python my_job.py
```

### 3. Remote Submission (Python Client)

**When to use**: Training machines, data scientists' laptops, automated workflows

#### Setup on Remote Machine

```bash
# Install Ray client
pip install ray[default]==2.9.0 mlflow==2.9.2

# Set connection details
export RAY_ADDRESS="http://localhost:8265"
export MLFLOW_TRACKING_URI="http://localhost/mlflow/"
```

#### Python Submission Script

```python
from ray.job_submission import JobSubmissionClient
import os

# Connect to Ray cluster
client = JobSubmissionClient("http://localhost:8265")

# Submit job with dependencies
job_id = client.submit_job(
    entrypoint="python train.py --epochs 10",
    runtime_env={
        "working_dir": "./my_project",  # Local directory to upload
        "pip": [
            "torch==2.1.0",
            "transformers==4.30.0",
            "mlflow==2.9.2",
            "scikit-learn"
        ],
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://mlflow-server:5000",
            "CUDA_VISIBLE_DEVICES": "0",
            "OMP_NUM_THREADS": "4"
        },
        "excludes": [
            "*.git",
            "__pycache__",
            "*.pyc",
            "data/"  # Exclude large directories
        ]
    },
    metadata={
        "submitter": "data-scientist",
        "project": "model-training",
        "version": "v1.0"
    }
)

print(f"Job submitted: {job_id}")

# Monitor job status
status = client.get_job_status(job_id)
print(f"Status: {status}")

# Get logs
logs = client.get_job_logs(job_id)
print(logs)

# Wait for completion (blocking)
client.wait_until_finish(job_id, timeout=3600)
final_status = client.get_job_status(job_id)
print(f"Final status: {final_status}")
```

### 4. Authenticated Remote Submission (via Ray Compute API)

**When to use**: Production environments with security requirements, multi-tenant setups

#### Get OAuth Token

```bash
# Set credentials
export RAY_CLIENT_ID="your_client_id"
export RAY_CLIENT_SECRET="your_client_secret"

# Get token
TOKEN=$(curl -s -X POST "http://localhost:9000/application/o/token/" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$RAY_CLIENT_ID" \
  -d "client_secret=$RAY_CLIENT_SECRET" | jq -r '.access_token')

echo "Token: $TOKEN"
```

#### Submit Job via API

```bash
# Submit job with OAuth
curl -X POST "http://localhost/api/ray/jobs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "authenticated-training-job",
    "entrypoint": "python train.py",
    "runtime_env": {
      "pip": ["torch", "mlflow"],
      "env_vars": {"MLFLOW_TRACKING_URI": "http://mlflow-server:5000"}
    },
    "cpu": 4,
    "memory_gb": 8,
    "gpu": 0.5,
    "timeout_hours": 24,
    "metadata": {
      "project": "production-model",
      "version": "2.0"
    }
  }'
```

#### Python Client with OAuth

```python
import requests
from ray.job_submission import JobSubmissionClient

class AuthenticatedRayClient:
    def __init__(self, ray_address, client_id, client_secret, auth_url):
        self.ray_address = ray_address
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url
        self.token = None
        
    def get_token(self):
        """Get OAuth token from Authentik"""
        response = requests.post(
            self.auth_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret
            }
        )
        response.raise_for_status()
        self.token = response.json()["access_token"]
        return self.token
    
    def submit_job(self, entrypoint, runtime_env=None, metadata=None):
        """Submit job with OAuth authentication"""
        if not self.token:
            self.get_token()
        
        # Use Ray Compute API instead of direct Ray submission
        response = requests.post(
            f"{self.ray_address}/api/ray/jobs",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "name": metadata.get("name", "unnamed-job"),
                "entrypoint": entrypoint,
                "runtime_env": runtime_env or {},
                "metadata": metadata or {}
            }
        )
        response.raise_for_status()
        return response.json()

# Usage
client = AuthenticatedRayClient(
    ray_address="http://localhost",
    client_id="your_client_id",
    client_secret="your_client_secret",
    auth_url="http://localhost:9000/application/o/token/"
)

job_result = client.submit_job(
    entrypoint="python train.py",
    runtime_env={
        "pip": ["mlflow", "torch"],
        "env_vars": {"MLFLOW_TRACKING_URI": "http://localhost/mlflow/"}
    },
    metadata={"name": "my-training-job", "project": "ml-research"}
)
```

## MLflow Integration

### Automatic Experiment Tracking

MLflow is pre-installed in the Ray container with proper configuration. All jobs automatically have access to MLflow tracking.

#### Basic Usage

```python
import ray
import mlflow

ray.init(address="auto")

# MLflow tracking URI is pre-configured
mlflow.set_experiment("my-experiment")

with mlflow.start_run(run_name="distributed-training"):
    # Log parameters
    mlflow.log_param("learning_rate", 0.001)
    mlflow.log_param("num_workers", 10)
    
    # Distributed training
    @ray.remote
    def train_worker(worker_id):
        # Training logic
        return {"loss": 0.5, "accuracy": 0.95}
    
    results = ray.get([train_worker.remote(i) for i in range(10)])
    
    # Log metrics
    avg_loss = sum(r["loss"] for r in results) / len(results)
    avg_acc = sum(r["accuracy"] for r in results) / len(results)
    
    mlflow.log_metric("avg_loss", avg_loss)
    mlflow.log_metric("avg_accuracy", avg_acc)
    
    # Log artifacts
    mlflow.log_artifact("model.pkl")
    mlflow.log_artifact("training_plot.png")

ray.shutdown()
```

#### Autologging Support

```python
import mlflow
from sklearn.ensemble import RandomForestClassifier

# Enable autologging
mlflow.sklearn.autolog()

mlflow.set_experiment("sklearn-training")

with mlflow.start_run():
    model = RandomForestClassifier(n_estimators=100)
    model.fit(X_train, y_train)
    # Parameters, metrics, and model automatically logged
```

#### Distributed Training with MLflow

```python
import ray
from ray import train
import mlflow

@ray.remote
class Trainer:
    def __init__(self, model_params):
        self.params = model_params
        mlflow.set_tracking_uri("http://mlflow-server:5000")
        
    def train(self, data):
        mlflow.set_experiment("distributed-training")
        
        with mlflow.start_run():
            # Log parameters
            for key, value in self.params.items():
                mlflow.log_param(key, value)
            
            # Training code
            model = self._build_model()
            history = model.fit(data)
            
            # Log metrics per epoch
            for epoch, metrics in enumerate(history):
                mlflow.log_metrics(metrics, step=epoch)
            
            # Log model
            mlflow.pytorch.log_model(model, "model")
            
        return model

# Initialize Ray
ray.init(address="auto")

# Create trainers
trainers = [Trainer.remote({"lr": 0.001}) for _ in range(4)]

# Run training
models = ray.get([t.train.remote(data) for t in trainers])

ray.shutdown()
```

## Job Monitoring

### Method 1: Ray Dashboard (Web UI)

Access: `http://localhost/ray/`

**Features**:
- Real-time job status and logs
- Resource utilization (CPU, GPU, memory)
- Task timeline and profiling
- Node health and cluster status
- Interactive log streaming

**Navigation**:
1. Click "Jobs" tab
2. Select your job from the list
3. View logs, status, and resource usage
4. Download logs for offline analysis

### Method 2: Ray CLI

```bash
# List all jobs
docker exec ray-head ray job list --address="http://127.0.0.1:8265"

# Get job status
docker exec ray-head ray job status <job-id> --address="http://127.0.0.1:8265"

# Stream job logs
docker exec ray-head ray job logs <job-id> --address="http://127.0.0.1:8265" --follow

# Stop a running job
docker exec ray-head ray job stop <job-id> --address="http://127.0.0.1:8265"

# Delete a finished job
docker exec ray-head ray job delete <job-id> --address="http://127.0.0.1:8265"
```

### Method 3: Python API

```python
from ray.job_submission import JobSubmissionClient

client = JobSubmissionClient("http://localhost:8265")

# Get job status
status = client.get_job_status(job_id)
print(f"Status: {status}")  # PENDING, RUNNING, SUCCEEDED, FAILED, STOPPED

# Get job info
info = client.get_job_info(job_id)
print(f"Start time: {info.start_time}")
print(f"End time: {info.end_time}")
print(f"Runtime: {info.runtime_ms / 1000} seconds")

# Get logs
logs = client.get_job_logs(job_id)
print(logs)

# Tail logs (last N lines)
logs = client.tail_job_logs(job_id, num_lines=50)

# List all jobs
jobs = client.list_jobs()
for job in jobs:
    print(f"{job.job_id}: {job.status} - {job.entrypoint}")
```

### Method 4: MLflow UI

Access: `http://localhost/mlflow/`

**Features**:
- View all experiments and runs
- Compare metrics across runs
- Visualize training curves
- Download artifacts and models
- Search and filter runs

**Usage**:
1. Navigate to "Experiments" tab
2. Select experiment (e.g., "ray-compute-jobs")
3. View all runs with metrics, parameters
4. Compare runs side-by-side
5. Download models and artifacts

### Method 5: Grafana Dashboards

Access: `http://localhost/ray-grafana/`

**Dashboards**:
- **Ray Cluster Metrics**: CPU/GPU utilization, memory usage, task execution
- **System Metrics**: Host-level resource monitoring
- **Container Metrics**: Per-container resource usage

**Key Metrics**:
```promql
# Active tasks
ray_tasks_running

# Task completion rate
rate(ray_tasks_finished_total[5m])

# GPU utilization
ray_node_gpu_utilization

# Object store memory
ray_object_store_memory / ray_object_store_available_memory
```

## Runtime Environment Configuration

### Dependency Management

#### Option 1: Pip Requirements

```python
runtime_env = {
    "pip": [
        "pandas==2.0.3",
        "scikit-learn>=1.3.0",
        "torch==2.1.0"
    ]
}
```

#### Option 2: Requirements File

```python
runtime_env = {
    "pip": "requirements.txt",  # Relative to working_dir
}
```

#### Option 3: Conda Environment

```python
runtime_env = {
    "conda": {
        "dependencies": [
            "python=3.9",
            "pytorch::pytorch=2.0.1",
            "conda-forge::xgboost"
        ],
        "pip": ["mlflow==2.9.2"]
    }
}
```

### Environment Variables

```python
runtime_env = {
    "env_vars": {
        "MLFLOW_TRACKING_URI": "http://mlflow-server:5000",
        "AWS_ACCESS_KEY_ID": "your-key",
        "AWS_SECRET_ACCESS_KEY": "your-secret",
        "CUDA_VISIBLE_DEVICES": "0",
        "OMP_NUM_THREADS": "8",
        "PYTHONPATH": "/opt/ray/custom_modules"
    }
}
```

### Working Directory

```python
runtime_env = {
    "working_dir": "./my_project",  # Upload local directory
    "excludes": [
        "*.git",
        "__pycache__",
        "*.pyc",
        "data/",
        "*.log"
    ]
}
```

### Container Image (Advanced)

```python
runtime_env = {
    "container": {
        "image": "custom-ray-image:latest",
        "worker_path": "/opt/ray/bin/ray"
    }
}
```

## Resource Specification

### CPU and Memory

```python
# Via Python API
@ray.remote(num_cpus=2, memory=4*1024*1024*1024)  # 4GB
def cpu_task():
    pass

# Via job submission
runtime_env = {
    "resources": {
        "CPU": 4,
        "memory": 8589934592  # 8GB in bytes
    }
}
```

### GPU Allocation

```python
# Request 0.5 GPU (shared)
@ray.remote(num_gpus=0.5)
def gpu_task():
    import torch
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # Your GPU code

# Request full GPU
@ray.remote(num_gpus=1)
def full_gpu_task():
    pass

# Request specific GPU
runtime_env = {
    "env_vars": {
        "CUDA_VISIBLE_DEVICES": "0"  # Use first GPU
    }
}
```

### Custom Resources

```python
# Define custom resource
@ray.remote(resources={"special_hardware": 1})
def special_task():
    pass
```

## Best Practices

### 1. Always Use MLflow Tracking

```python
# Set experiment name consistently
mlflow.set_experiment("project-name")

# Use descriptive run names
with mlflow.start_run(run_name=f"experiment-{timestamp}"):
    mlflow.log_params(config)
    # Training code
    mlflow.log_metrics(metrics)
```

### 2. Handle Errors Gracefully

```python
@ray.remote(max_retries=3, retry_exceptions=[ConnectionError])
def fault_tolerant_task():
    try:
        # Task code
        pass
    except Exception as e:
        mlflow.log_param("error", str(e))
        raise
```

### 3. Optimize Object Store Usage

```python
# Put large objects in object store
data_ref = ray.put(large_data)

# Pass reference to tasks
results = ray.get([process.remote(data_ref) for _ in range(100)])
```

### 4. Use Appropriate Task Granularity

```python
# Too fine-grained (overhead > computation)
❌ results = [process.remote(x) for x in range(1000000)]

# Better (batch processing)
✅ batches = np.array_split(data, 100)
✅ results = [process_batch.remote(batch) for batch in batches]
```

### 5. Clean Up Resources

```python
# Always shutdown Ray
try:
    # Your code
    pass
finally:
    ray.shutdown()
```

### 6. Monitor Resource Usage

```python
# Check cluster resources before submission
import ray
ray.init(address="auto")
resources = ray.cluster_resources()
print(f"Available CPUs: {resources.get('CPU', 0)}")
print(f"Available GPUs: {resources.get('GPU', 0)}")
```

## Troubleshooting

### Job Fails to Submit

```bash
# Check Ray cluster status
docker exec ray-head ray status

# Check logs
docker logs ray-head --tail 100

# Verify connectivity
curl http://localhost:8265/api/version
```

### MLflow Tracking Not Working

```bash
# Verify MLflow is installed in Ray container
docker exec ray-head python -c "import mlflow; print(mlflow.__version__)"

# Check MLflow server
curl http://localhost/mlflow/api/2.0/mlflow/experiments/list?max_results=1

# Test connection from Ray container
docker exec ray-head curl http://mlflow-server:5000/health
```

### Out of Memory Errors

```python
# Enable object spilling
ray.init(address="auto", _system_config={
    "automatic_object_spilling_enabled": True,
    "object_spilling_config": json.dumps({
        "type": "filesystem",
        "params": {"directory_path": "/tmp/ray_spill"}
    })
})
```

### GPU Not Available

```bash
# Check GPU visibility in Ray container
docker exec ray-head nvidia-smi

# Check Ray GPU resources
docker exec ray-head ray status | grep GPU
```

### Slow Job Execution

1. Profile with Ray timeline:
   ```python
   ray.timeline(filename="timeline.json")
   # Open chrome://tracing and load file
   ```

2. Check resource bottlenecks in Grafana

3. Optimize task granularity

4. Use Ray Data for large datasets

## Example Workflows

### 1. Hyperparameter Tuning with Ray Tune + MLflow

```python
from ray import tune
from ray.tune.integration.mlflow import mlflow_mixin
import mlflow

@mlflow_mixin
def train_model(config):
    mlflow.log_params(config)
    
    # Training code
    accuracy = train(config)
    
    mlflow.log_metric("accuracy", accuracy)
    tune.report(accuracy=accuracy)

analysis = tune.run(
    train_model,
    config={
        "lr": tune.loguniform(1e-4, 1e-1),
        "batch_size": tune.choice([32, 64, 128])
    },
    num_samples=10
)
```

### 2. Distributed Data Processing

```python
import ray
import mlflow

ray.init(address="auto")

mlflow.set_experiment("data-processing")

@ray.remote
def process_batch(batch_id, data):
    # Process data
    processed_count = len(data)
    return batch_id, processed_count

with mlflow.start_run():
    # Load data
    data = load_large_dataset()
    batches = np.array_split(data, 100)
    
    # Process in parallel
    futures = [process_batch.remote(i, batch) for i, batch in enumerate(batches)]
    results = ray.get(futures)
    
    # Log results
    total_processed = sum(r[1] for r in results)
    mlflow.log_metric("total_processed", total_processed)
    mlflow.log_param("num_batches", len(batches))

ray.shutdown()
```

### 3. Model Training with Automatic Checkpointing

```python
import ray
from ray import train
import mlflow
import torch

def train_func(config):
    mlflow.set_tracking_uri("http://mlflow-server:5000")
    mlflow.set_experiment("distributed-training")
    
    with mlflow.start_run():
        model = build_model(config)
        
        for epoch in range(config["epochs"]):
            metrics = train_epoch(model)
            
            # Log to MLflow
            mlflow.log_metrics(metrics, step=epoch)
            
            # Ray Train checkpoint
            train.report(metrics=metrics, checkpoint=train.Checkpoint.from_dict({
                "model_state": model.state_dict(),
                "epoch": epoch
            }))
            
        # Log final model to MLflow
        mlflow.pytorch.log_model(model, "model")

# Run distributed training
trainer = train.Trainer(
    train_func,
    scaling_config=train.ScalingConfig(num_workers=4, use_gpu=True)
)
result = trainer.fit()
```

## Summary

This guide covered:
- ✅ 4 methods for job submission (local, host, remote, authenticated)
- ✅ Complete MLflow integration patterns
- ✅ 5 monitoring approaches (Dashboard, CLI, API, MLflow, Grafana)
- ✅ Runtime environment configuration
- ✅ Resource specification (CPU, GPU, memory)
- ✅ Best practices and troubleshooting
- ✅ Real-world example workflows

**Key Takeaways**:
1. MLflow is pre-installed and configured in Ray containers
2. All jobs can automatically track experiments
3. Multiple submission methods for different use cases
4. Comprehensive monitoring through multiple interfaces
5. OAuth authentication available for production use

**Next Steps**:
- Try example workflows in `ray_compute/examples/`
- Review MLflow experiments at `http://localhost/mlflow/`
- Monitor jobs in Ray Dashboard at `http://localhost/ray/`
- Check resource usage in Grafana at `http://localhost/ray-grafana/`
