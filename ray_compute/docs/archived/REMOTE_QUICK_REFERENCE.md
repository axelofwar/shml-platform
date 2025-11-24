# Remote Compute - Quick Reference

## Server Setup (One-Time)

```bash
cd /home/axelofwar/Projects/mlflow-server/ray_compute

# 1. Install system dependencies (reboot required)
sudo bash scripts/install_nvidia_drivers.sh
# After reboot:
sudo bash scripts/install_docker_nvidia.sh
sudo bash scripts/install_ray_cluster.sh

# 2. Build Docker images
cd docker && bash build_images.sh

# 3. Start services
cd .. && bash start_all_remote.sh
```

## Daily Operations

### Start/Stop Services

```bash
cd /home/axelofwar/Projects/mlflow-server/ray_compute

# Start
bash start_all_remote.sh

# Stop
bash stop_all_remote.sh

# Check status
bash scripts/check_status.sh
```

### Validation

```bash
# Run full test suite
python3 test_remote_compute.py http://100.69.227.36:8266
```

## Remote Client (Training Machine)

### Install Client

```bash
# Copy from server
scp user@100.69.227.36:/path/to/ray_compute/api/client_remote.py .
```

### Basic Usage

```python
from client_remote import RemoteComputeClient

# Connect
client = RemoteComputeClient("http://100.69.227.36:8266")

# Submit job
job_id = client.submit_job(
    name="my_job",
    code="""
import torch
import os
from pathlib import Path

# Your code here
print(f"CUDA: {torch.cuda.is_available()}")

# Save outputs
output_dir = Path(os.environ['JOB_OUTPUT_DIR'])
with open(output_dir / 'result.txt', 'w') as f:
    f.write("Done!")
""",
    gpu=1,
    cpu=4,
    memory_gb=4
)

# Wait and download
job = client.wait_for_job(job_id)
artifacts = client.download_artifacts(job_id, output_dir="./results")
```

### Convenience Functions

```python
from client_remote import submit_training_job, submit_inference_job

# Training (8 CPU, 8GB RAM, 1 GPU, 240 min timeout)
result = submit_training_job(
    server_url="http://100.69.227.36:8266",
    name="yolo_train",
    code="...",
    mlflow_experiment="yolo-training"
)

# Inference (4 CPU, 4GB RAM, 1 GPU, 60 min timeout)
result = submit_inference_job(
    server_url="http://100.69.227.36:8266",
    name="yolo_infer",
    code="..."
)
```

## API Endpoints

```bash
SERVER="http://100.69.227.36:8266"

# Health check
curl $SERVER/health

# Resources
curl $SERVER/resources

# Submit job
curl -X POST $SERVER/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test",
    "job_type": "custom",
    "code": "print(\"Hello\")",
    "requirements": {"cpu": 2, "memory_gb": 2, "gpu": 0}
  }'

# List jobs
curl $SERVER/jobs

# Get job
curl $SERVER/jobs/{job_id}

# Get logs
curl $SERVER/jobs/{job_id}/logs

# Download artifacts
curl $SERVER/jobs/{job_id}/artifacts/download -o artifacts.zip

# Cancel job
curl -X POST $SERVER/jobs/{job_id}/cancel

# Delete job
curl -X DELETE $SERVER/jobs/{job_id}
```

## Key Features

### Ephemeral Storage

- Jobs execute in isolated workspaces
- Artifacts collected in `outputs/` directory
- **Auto-cleanup after download** (configurable)
- 24-hour retention for unclaimed artifacts

### Resource Profiles

**GPU Job (Training)**

- CPU: 8 cores
- Memory: 8GB
- GPU: 1x RTX 2070 (8GB VRAM)
- Timeout: 240 minutes

**CPU Job (Data Processing)**

- CPU: 12 cores
- Memory: 6GB
- GPU: 0
- Timeout: 120 minutes

**Custom**

- CPU: 1-20 cores
- Memory: 1-12 GB
- GPU: 0 or 1
- Timeout: 1-1440 minutes

### MLflow Integration

```python
# All jobs automatically tracked in MLflow
# View at: http://100.69.227.36:8080

import mlflow
mlflow.set_tracking_uri("http://100.69.227.36:8080")

# Access run data
run = mlflow.get_run(job['mlflow_run_id'])
print(run.data.metrics)
```

## Services

| Service       | Local URL             | Remote URL (Tailscale)    |
| ------------- | --------------------- | ------------------------- |
| Compute API   | http://localhost:8266 | http://100.69.227.36:8266 |
| Ray Dashboard | http://localhost:8265 | http://100.69.227.36:8265 |
| MLflow Server | http://localhost:8080 | http://100.69.227.36:8080 |

## Logs

```bash
# API logs
tail -f /home/axelofwar/Projects/mlflow-server/ray_compute/logs/api_remote.log

# Ray logs
tail -f /home/axelofwar/Projects/mlflow-server/ray_compute/logs/ray_head.log

# Job logs (on server)
ls -la /opt/ray/logs/jobs/
```

## Monitoring

```bash
# GPU usage
watch -n 1 nvidia-smi

# System resources
htop

# Ray cluster status
ray status

# API resources
curl http://localhost:8266/resources | jq
```

## Troubleshooting

```bash
# Check services
bash scripts/check_status.sh

# Restart everything
bash stop_all_remote.sh && bash start_all_remote.sh

# Verify Tailscale
tailscale status
tailscale ping 100.69.227.36

# Test connectivity
curl http://localhost:8266/health
curl http://100.69.227.36:8266/health  # From remote machine
```

## Production Deployment

```bash
# Install systemd services
sudo bash scripts/install_systemd_services.sh

# Manage services
sudo systemctl start ray-compute-api-remote
sudo systemctl enable ray-compute-api-remote
sudo systemctl status ray-compute-api-remote
sudo journalctl -u ray-compute-api-remote -f
```

## Example: YOLO Training

```python
from client_remote import submit_training_job

result = submit_training_job(
    server_url="http://100.69.227.36:8266",
    name="yolo_v8_training",
    code="""
from ultralytics import YOLO
from pathlib import Path
import os

output_dir = Path(os.environ['JOB_OUTPUT_DIR'])

# Train
model = YOLO('yolov8n.pt')
results = model.train(
    data='coco128.yaml',
    epochs=50,
    imgsz=640
)

# Save
model.save(output_dir / 'trained_model.pt')

# Metrics
import json
metrics = {
    'mAP50': float(results.results_dict['metrics/mAP50(B)']),
    'loss': float(results.results_dict['train/box_loss'])
}
with open(output_dir / 'metrics.json', 'w') as f:
    json.dump(metrics, f)
""",
    mlflow_experiment="yolo-production",
    mlflow_tags={"model": "yolov8n", "dataset": "coco128"}
)

print(f"✓ Training complete!")
print(f"  MLflow: {result['mlflow_run_id']}")
print(f"  Artifacts: {result['artifact_path']}")
```

## Next Steps

1. ✅ Install system dependencies
2. ✅ Build Docker images
3. ✅ Start services
4. ✅ Run validation tests
5. ✅ Set up remote client
6. ✅ Submit first job
7. ✅ Verify artifact cleanup

## Documentation

- Full guide: `REMOTE_SETUP_GUIDE.md`
- Architecture: `docs/ARCHITECTURE.md`
- API reference: http://localhost:8266/docs (when running)
