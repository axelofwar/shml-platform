# Remote Compute Server - Setup and Validation Guide

## Overview

This guide helps you set up the Ray Compute server for remote job submission and validate that remote machines can send work and retrieve results.

## Architecture

```
Remote Machine                    Compute Server (100.69.227.36)
(Training/Dev)

┌──────────────────┐              ┌──────────────────────────────┐
│                  │   Tailscale  │                              │
│  Python Client   │─────VPN──────▶  Remote API (port 8266)     │
│  - Submit Jobs   │              │  - Job Orchestration         │
│  - Get Status    │              │  - Resource Management       │
│  - Download      │◀─────────────│  - Artifact Cleanup          │
│    Artifacts     │   Results    │                              │
└──────────────────┘              │  Ray Cluster (port 8265)     │
                                  │  - GPU Scheduling            │
                                  │  - Docker Execution          │
                                  │  - MLflow Integration        │
                                  │                              │
                                  │  MLflow Server (port 8080)   │
                                  │  - Experiment Tracking       │
                                  │  - Model Registry            │
                                  └──────────────────────────────┘
```

## Key Features

### Ephemeral Artifact Storage

- Jobs execute in isolated workspaces: `/opt/ray/job_workspaces/{job_id}/`
- Artifacts are collected in `outputs/` directory during execution
- After job completion, artifacts are packaged and available for download
- **Automatic cleanup**: Artifacts are deleted after download (configurable)
- **Retention policy**: Unclaimed artifacts auto-delete after 24 hours

### Remote Access

- **Tailscale VPN**: Secure remote access without exposing public ports
- **CORS enabled**: Remote clients can submit jobs from any machine
- **REST API**: Language-agnostic (Python SDK provided for convenience)
- **Real-time monitoring**: Job logs and status available during execution

### Resource Management

- GPU jobs: 1x RTX 2070 (8GB VRAM), 8 CPU cores, 8GB RAM
- CPU jobs: 12 cores, 6GB RAM
- Resource validation before submission
- Queue management with priority scheduling

## Server Setup (One-Time)

### 1. Install System Dependencies

```bash
cd /home/$USER/Projects/mlflow-server/ray_compute

# Install NVIDIA drivers for GPU support
sudo bash scripts/install_nvidia_drivers.sh
# ⚠️ System will reboot after driver installation

# After reboot, verify GPU
nvidia-smi

# Install Docker + NVIDIA Container Toolkit
sudo bash scripts/install_docker_nvidia.sh

# Install Ray and ML libraries
sudo bash scripts/install_ray_cluster.sh
```

### 2. Build Docker Images

```bash
cd docker
bash build_images.sh
```

This creates:

- `mlflow-compute-gpu`: PyTorch + CUDA 11.8 + YOLO + MLflow
- `mlflow-compute-cpu`: sklearn + XGBoost + MLflow

### 3. Start Services

```bash
cd /home/$USER/Projects/mlflow-server/ray_compute
bash start_all_remote.sh
```

This starts:

- Ray head node (Dashboard: http://localhost:8265)
- Remote API server (API: http://localhost:8266)
- Verifies MLflow server connectivity (http://localhost:8080)

Expected output:

```
==================================================
Ray Compute - Remote Edition Started
==================================================

Services:
  - Ray Dashboard:  http://localhost:8265
  - MLflow Server:  http://localhost:8080
  - Compute API:    http://localhost:8266
  - Remote API:     http://100.69.227.36:8266

Check status:       bash scripts/check_status.sh
Run validation:     python3 test_remote_compute.py http://100.69.227.36:8266
```

### 4. Verify Services

```bash
# Check service status
bash scripts/check_status.sh

# Verify Tailscale VPN
tailscale status
tailscale ip -4  # Should show: 100.69.227.36

# Test local API access
curl http://localhost:8266/health

# Test remote API access (from another Tailscale machine)
curl http://100.69.227.36:8266/health
```

## Remote Client Setup

### 1. Install Client Library (on remote machine)

```bash
# Copy client library to your remote machine
scp username@100.69.227.36:/home/$USER/Projects/mlflow-server/ray_compute/api/client_remote.py .

# Or clone this repository on remote machine
git clone <repo_url>
cd ray_compute/api
```

### 2. Basic Usage Example

```python
from client_remote import RemoteComputeClient

# Connect to server
client = RemoteComputeClient("http://100.69.227.36:8266")

# Check health
health = client.health_check()
print(f"Server status: {health['status']}")

# Check available resources
resources = client.get_resources()
print(f"Available GPU: {resources['available']['gpu']}")

# Submit a simple job
code = """
import torch
print(f"CUDA available: {torch.cuda.is_available()}")

# Save output
import os
from pathlib import Path
output_dir = Path(os.environ['JOB_OUTPUT_DIR'])

with open(output_dir / 'result.txt', 'w') as f:
    f.write("Hello from remote job!\\n")
"""

job_id = client.submit_job(
    name="test_job",
    code=code,
    gpu=1,
    cpu=4,
    memory_gb=4
)

# Wait for completion
job = client.wait_for_job(job_id)
print(f"Job status: {job['status']}")

# Download results
if job['status'] == 'SUCCEEDED':
    artifacts = client.download_artifacts(job_id, output_dir="./results")
    print(f"Artifacts: {artifacts}")

    # Artifacts are automatically deleted from server after download!
```

### 3. Convenience Functions

```python
from client_remote import submit_training_job, submit_inference_job

# Submit training job with defaults (8 CPU, 8GB RAM, 1 GPU)
result = submit_training_job(
    server_url="http://100.69.227.36:8266",
    name="yolo_training",
    code="""
from ultralytics import YOLO
import mlflow

# Train YOLO model
model = YOLO('yolov8n.pt')
results = model.train(
    data='coco128.yaml',
    epochs=10,
    imgsz=640
)

# Save model
import os
output_dir = Path(os.environ['JOB_OUTPUT_DIR'])
model.save(output_dir / 'yolo_model.pt')
""",
    mlflow_experiment="remote-yolo-training"
)

print(f"Training completed!")
print(f"MLflow run: {result['mlflow_run_id']}")
print(f"Artifacts: {result['artifact_path']}")
```

## Validation Tests

### Run Full Test Suite (from remote machine)

```bash
# Copy test script to remote machine
scp username@100.69.227.36:/home/$USER/Projects/mlflow-server/ray_compute/test_remote_compute.py .

# Run validation
python3 test_remote_compute.py http://100.69.227.36:8266
```

This tests:

1. ✓ Connection to server
2. ✓ Resource availability check
3. ✓ CPU job submission and artifact retrieval
4. ✓ GPU job submission and artifact retrieval

Expected output:

```
==================================================
Remote Ray Compute Server Validation
==================================================

Server: http://100.69.227.36:8266

============================================================
1. Testing Connection
============================================================
✓ Server health: healthy
  - Ray: healthy
  - MLflow: healthy

============================================================
2. Checking Available Resources
============================================================

Cluster Resources:
  - CPU: 24.0 cores total, 16.0 available
  - Memory: 62.6 GB total, 52.3 GB available
  - GPU: 1 total, 1 available

GPU Details:
  [0] NVIDIA GeForce RTX 2070
      Memory: 1024/8192 MB
      Utilization: 12.5%

============================================================
3. Testing CPU Job Submission
============================================================
✓ Job submitted: job_20240115_143022_a3f9
  Waiting for job to complete...
✓ Job completed with status: SUCCEEDED
  MLflow Run ID: abc123def456

Job Logs (last 500 chars):
------------------------------------------------------------
Starting CPU test job...
Computation result: 499999500000
Output saved to /opt/ray/job_workspaces/job_20240115_143022_a3f9/outputs/cpu_result.txt
CPU test job completed!

  Downloading artifacts...
✓ Artifacts downloaded to: ./test_results/job_20240115_143022_a3f9_artifacts

  Artifact contents:
------------------------------------------------------------
Result: 499999500000
Test completed successfully!

============================================================
4. Testing GPU Job Submission
============================================================
✓ Job submitted: job_20240115_143105_b7d2
  Waiting for job to complete...
✓ Job completed with status: SUCCEEDED
  MLflow Run ID: def789ghi012

Job Logs (last 500 chars):
------------------------------------------------------------
Starting GPU test job...
PyTorch version: 2.1.0+cu118
CUDA available: True
CUDA version: 11.8
GPU device: NVIDIA GeForce RTX 2070
GPU memory: 8.19 GB
GPU computation result: -1234.5678
Output saved to /opt/ray/job_workspaces/job_20240115_143105_b7d2/outputs/gpu_result.txt
GPU test job completed!

  Downloading artifacts...
✓ Artifacts downloaded to: ./test_results/job_20240115_143105_b7d2_artifacts

  Artifact contents:
------------------------------------------------------------
PyTorch version: 2.1.0+cu118
CUDA version: 11.8
GPU: NVIDIA GeForce RTX 2070
Computation result: -1234.5678

============================================================
Test Summary
============================================================
✓ PASS: Connection
✓ PASS: Resources
✓ PASS: CPU Job
✓ PASS: GPU Job

============================================================
🎉 ALL TESTS PASSED!
Remote compute server is ready for production use.
============================================================
```

## API Endpoints

### Health & Resources

- `GET /health` - Health check
- `GET /resources` - Available cluster resources

### Job Management

- `POST /jobs/submit` - Submit new job
- `GET /jobs` - List all jobs (with filtering)
- `GET /jobs/{job_id}` - Get job details
- `GET /jobs/{job_id}/logs` - Get job logs
- `POST /jobs/{job_id}/cancel` - Cancel running job
- `DELETE /jobs/{job_id}` - Delete job and artifacts

### Artifact Management

- `GET /jobs/{job_id}/artifacts/download` - Download job artifacts as zip
  - Automatically packages all files from `outputs/` directory
  - Triggers cleanup after download (if `cleanup_after=true`)

## Artifact Management

### How Artifacts Work

1. **Job Submission**: Each job gets isolated workspace

   ```
   /opt/ray/job_workspaces/{job_id}/
   ├── outputs/          # User saves artifacts here
   ├── mlflow_run_id.txt # MLflow tracking
   └── job_metadata.json # Job info
   ```

2. **During Execution**: User code saves to `$JOB_OUTPUT_DIR`

   ```python
   import os
   from pathlib import Path

   output_dir = Path(os.environ['JOB_OUTPUT_DIR'])
   model.save(output_dir / 'model.pt')
   results.to_csv(output_dir / 'metrics.csv')
   ```

3. **After Completion**: Artifacts ready for download

   - Server creates zip: `{job_id}_artifacts.zip`
   - Client downloads: `GET /jobs/{job_id}/artifacts/download`
   - Server cleanup: Deletes workspace after download

4. **Automatic Cleanup**:
   - Downloaded artifacts: Deleted immediately after download
   - Unclaimed artifacts: Deleted after 24 hours
   - Failed jobs: Workspace retained for 24 hours for debugging

### Cleanup Configuration

```python
# Keep artifacts on server (no cleanup)
job_id = client.submit_job(
    name="important_job",
    code=code,
    cleanup_after=False  # Artifacts persist indefinitely
)

# Automatic cleanup (default)
job_id = client.submit_job(
    name="ephemeral_job",
    code=code,
    cleanup_after=True  # Deleted after download
)
```

## MLflow Integration

All jobs automatically log to MLflow:

```python
# On server, experiments appear in MLflow UI
# http://localhost:8080  (or http://100.69.227.36:8080)

# View from remote client
import mlflow
mlflow.set_tracking_uri("http://100.69.227.36:8080")

# Get run info
run = mlflow.get_run(job['mlflow_run_id'])
print(f"Metrics: {run.data.metrics}")
print(f"Params: {run.data.params}")

# Download artifacts from MLflow
mlflow.artifacts.download_artifacts(
    run_id=job['mlflow_run_id'],
    dst_path="./mlflow_artifacts"
)
```

## Troubleshooting

### Server Issues

```bash
# Check service status
bash scripts/check_status.sh

# View logs
tail -f logs/ray_head.log
tail -f logs/api_remote.log

# Restart services
bash stop_all_remote.sh
bash start_all_remote.sh

# Check Ray cluster
ray status

# Test local connectivity
curl http://localhost:8266/health
curl http://localhost:8265  # Ray Dashboard
curl http://localhost:8080/health  # MLflow
```

### Remote Access Issues

```bash
# Verify Tailscale
tailscale status
tailscale ping 100.69.227.36

# Test from remote machine
curl http://100.69.227.36:8266/health

# Check firewall (if needed)
sudo ufw status
sudo ufw allow 8266/tcp  # Only needed if firewall blocks Tailscale
```

### Job Failures

```python
# Get detailed error
job = client.get_job(job_id)
print(f"Error: {job['error']}")

# Get full logs
logs = client.get_logs(job_id)
print(logs)

# Check Ray logs on server
# /opt/ray/logs/jobs/{ray_job_id}/
```

### Artifact Issues

```python
# Check if artifacts are ready
job = client.get_job(job_id)
print(f"Artifacts ready: {job['artifacts_ready']}")

# List workspace contents (on server)
# ls -la /opt/ray/job_workspaces/{job_id}/outputs/

# Manual artifact download (if automatic cleanup failed)
client.download_artifacts(job_id, output_dir="./manual_download")
```

## Production Deployment

### Systemd Services

For production, install systemd services:

```bash
sudo bash scripts/install_systemd_services.sh
```

This creates:

- `ray-head.service` - Ray cluster
- `ray-compute-api-remote.service` - Remote API server

Manage services:

```bash
sudo systemctl start ray-compute-api-remote
sudo systemctl enable ray-compute-api-remote
sudo systemctl status ray-compute-api-remote
sudo journalctl -u ray-compute-api-remote -f
```

### Security Considerations

1. **Tailscale VPN**: All traffic encrypted, no public exposure
2. **Authentication**: Consider adding API keys for multi-user
3. **Rate Limiting**: Implement in production (not included in MVP)
4. **Resource Quotas**: Add per-user limits if needed
5. **Audit Logging**: Enable for production tracking

### Monitoring

```bash
# Resource monitoring
watch -n 1 nvidia-smi
htop

# Ray Dashboard
# http://100.69.227.36:8265

# MLflow UI
# http://100.69.227.36:8080

# API metrics
curl http://100.69.227.36:8266/resources
```

## Next Steps

1. **Run validation tests** to ensure everything works
2. **Set up remote client** on training machine
3. **Submit test job** from remote machine
4. **Verify artifact cleanup** works correctly
5. **Integrate with your training scripts**

## Example Integration

```python
# training_script.py (on remote machine)
from client_remote import submit_training_job

result = submit_training_job(
    server_url="http://100.69.227.36:8266",
    name="production_yolo_training",
    code="""
from ultralytics import YOLO
import mlflow
from pathlib import Path
import os

# Get output directory
output_dir = Path(os.environ['JOB_OUTPUT_DIR'])

# Train model
model = YOLO('yolov8n.pt')
results = model.train(
    data='/data/my_dataset.yaml',
    epochs=100,
    imgsz=640,
    batch=16
)

# Save trained model
model.save(output_dir / 'best_model.pt')

# Save metrics
import json
metrics = {
    'mAP50': float(results.results_dict['metrics/mAP50(B)']),
    'mAP50-95': float(results.results_dict['metrics/mAP50-95(B)'])
}
with open(output_dir / 'metrics.json', 'w') as f:
    json.dump(metrics, f)

print(f"Training complete! Metrics: {metrics}")
""",
    mlflow_experiment="production-yolo",
    mlflow_tags={"team": "ml-research", "priority": "high"}
)

print(f"Training job completed!")
print(f"Download results from: {result['artifact_path']}")
print(f"MLflow run: {result['mlflow_run_id']}")
```

## Support

For issues or questions:

1. Check logs: `logs/api_remote.log`, `logs/ray_head.log`
2. Review troubleshooting section above
3. Check Ray documentation: https://docs.ray.io/
4. MLflow docs: https://mlflow.org/docs/latest/
