# Ray Compute - Installation & Setup Summary

## ✅ What Has Been Created

Your complete GPU-accelerated ML job orchestration system with:

### 📁 Directory Structure

```
ray_compute/
├── README.md                    # Complete documentation
├── start_all.sh                 # Quick start script
├── stop_all.sh                  # Stop all services
├── ray-compute                  # CLI tool
│
├── scripts/                     # Installation & management
│   ├── install_nvidia_drivers.sh
│   ├── install_docker_nvidia.sh
│   ├── install_ray_cluster.sh
│   ├── install_systemd_services.sh
│   ├── start_ray_head.sh
│   ├── stop_ray.sh
│   └── check_status.sh
│
├── docker/                      # Container images
│   ├── Dockerfile.gpu           # PyTorch + CUDA + YOLO
│   ├── Dockerfile.cpu           # CPU-only processing
│   └── build_images.sh
│
├── api/                         # Job orchestration API
│   ├── server.py                # FastAPI REST API
│   ├── client.py                # Python SDK
│   └── start_api.sh
│
├── pipelines/                   # Example workflows
│   ├── yolo_training.py
│   ├── yolo_inference.py
│   ├── dataset_curation.py
│   └── auto_retraining_pipeline.py
│
├── config/                      # System configuration
│   ├── ray-head.service         # Systemd service
│   └── ray-compute-api.service  # API service
│
└── docs/                        # Additional documentation
```

---

## 🚀 Installation Steps

### Step 1: Install NVIDIA Drivers & Reboot

```bash
cd /home/$USER/Projects/mlflow-server/ray_compute
./scripts/install_nvidia_drivers.sh

# REBOOT REQUIRED
sudo reboot
```

### Step 2: Verify GPU & Install Docker

```bash
# After reboot, verify
nvidia-smi

# Install Docker + NVIDIA Container Toolkit
./scripts/install_docker_nvidia.sh

# Log out and back in (or run: newgrp docker)
```

### Step 3: Install Ray & ML Libraries

```bash
./scripts/install_ray_cluster.sh
```

### Step 4: Build Docker Images

```bash
cd docker
./build_images.sh
cd ..
```

### Step 5: Start Everything

```bash
./start_all.sh
```

---

## 🎯 System Capabilities

### Hardware Utilization

- **GPU**: NVIDIA RTX 2070 (8GB VRAM)
- **CPU**: AMD Ryzen 9 3900X (24 threads)
- **RAM**: 15GB available
- **Storage**: 1.7TB available

### Resource Allocation Strategy

```
Training Jobs (GPU):
  • 1x RTX 2070 GPU
  • 8 CPU cores
  • 8GB RAM
  • Max 1 concurrent

Inference Jobs (GPU):
  • 1x RTX 2070 GPU
  • 4 CPU cores
  • 4GB RAM
  • Can share GPU with training

Dataset Curation (CPU):
  • 0 GPU
  • 12 CPU cores
  • 6GB RAM
  • Runs alongside GPU jobs

System Reserved:
  • 4 CPU cores
  • 3GB RAM
```

---

## 📖 Usage Examples

### CLI Usage

```bash
# Submit GPU test job
./ray-compute submit \
  --name "gpu-test" \
  --code "import torch; print(torch.cuda.get_device_name(0))" \
  --gpu 1 \
  --wait --logs

# Submit training job from file
./ray-compute submit \
  --name "yolo-train" \
  --code-file my_training.py \
  --type training \
  --cpu 8 --memory 8 --gpu 1 \
  --experiment "yolo-experiments"

# List running jobs
./ray-compute list --status RUNNING

# Get job status
./ray-compute status <job-id>

# View logs
./ray-compute logs <job-id>

# Check resources
./ray-compute resources
```

### Python SDK Usage

```python
from api.client import RayComputeClient, submit_training_job

# Quick submit with defaults
job_id = submit_training_job(
    name="yolo-training",
    code=open('train.py').read(),
    mlflow_experiment="yolo"
)

# Advanced usage
client = RayComputeClient()

job_id = client.submit_job(
    name="custom-job",
    code="""
import torch
from ultralytics import YOLO
import mlflow

model = YOLO('yolov8n.pt')
results = model.train(data='coco128.yaml', epochs=10)
mlflow.log_metrics(results.results_dict)
""",
    job_type=JobType.TRAINING,
    cpu=8,
    memory_gb=8,
    gpu=1,
    mlflow_experiment="yolo-training"
)

# Wait and get results
result = client.wait_for_job(job_id)
print(f"Status: {result['status']}")
```

### REST API Usage

```bash
# Submit job
curl -X POST http://localhost:8266/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-job",
    "job_type": "training",
    "code": "import torch; print(torch.cuda.is_available())",
    "requirements": {"cpu": 4, "memory_gb": 8, "gpu": 1}
  }'

# Get job status
curl http://localhost:8266/jobs/<job-id>

# List jobs
curl http://localhost:8266/jobs

# Get resources
curl http://localhost:8266/resources
```

---

## 🌐 Access URLs

| Service       | URL                        | Purpose                       |
| ------------- | -------------------------- | ----------------------------- |
| Ray Dashboard | http://localhost:8265      | Monitor jobs, resources, logs |
| Compute API   | http://localhost:8266      | Job submission endpoint       |
| API Docs      | http://localhost:8266/docs | Interactive API documentation |
| MLflow UI     | http://localhost:8080      | Experiment tracking, models   |

---

## 📊 Example Workflows

### 1. YOLO Training Pipeline

```bash
cd pipelines
python3 yolo_training.py
```

- Loads YOLOv8n model
- Trains on your dataset
- Logs metrics to MLflow
- Registers model in Model Registry

### 2. Batch Inference

```bash
python3 yolo_inference.py
```

- Loads trained model from MLflow
- Runs detection on image directory
- Saves results and logs metrics

### 3. Dataset Curation

```bash
python3 dataset_curation.py
```

- Analyzes inference failures
- Clusters failure patterns (HDBSCAN)
- Curates hard examples for retraining

### 4. Automated Retraining

```bash
python3 auto_retraining_pipeline.py
```

- Full 4-stage pipeline
- Inference → Analysis → Curation → Retraining
- Automatic model versioning

---

## 🔧 Management Commands

### Start/Stop Services

```bash
# Start everything
./start_all.sh

# Stop everything
./stop_all.sh

# Check status
./scripts/check_status.sh
```

### View Logs

```bash
# Ray logs
tail -f /opt/ray/logs/ray_*.log

# API logs (if using start_all.sh)
tail -f /opt/ray/logs/api_server.log

# Systemd logs (if using systemd services)
sudo journalctl -u ray-head -f
sudo journalctl -u ray-compute-api -f
```

### Production Deployment (Optional)

```bash
# Install as systemd services
./scripts/install_systemd_services.sh

# Manage services
sudo systemctl start ray-head ray-compute-api
sudo systemctl stop ray-compute-api ray-head
sudo systemctl status ray-head ray-compute-api
```

---

## 🔐 Security Notes

### Current Setup (Single User)

- ✅ Tailscale VPN only (no public access)
- ✅ Docker container isolation
- ✅ Resource limits enforced
- ✅ Jobs run in isolated containers

### Future: Multi-User Setup

To enable multi-user access:

1. **Add Authentication**

   - Implement JWT tokens in `api/server.py`
   - Add user management database

2. **Resource Quotas**

   - Per-user CPU/GPU/memory limits
   - Job queue priorities

3. **Namespace Isolation**
   - Separate artifact directories per user
   - MLflow experiment isolation

---

## 🐛 Troubleshooting

### GPU Not Detected

```bash
# Check drivers
nvidia-smi

# Test in Docker
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi

# Reinstall if needed
./scripts/install_nvidia_drivers.sh
```

### Ray Not Starting

```bash
# Check logs
cat /opt/ray/logs/ray_*.log

# Restart
./scripts/stop_ray.sh
./scripts/start_ray_head.sh
```

### Job Stuck in PENDING

```bash
# Check resources
./scripts/check_status.sh
./ray-compute resources

# View Ray dashboard
firefox http://localhost:8265
```

### Docker Permission Issues

```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in
# Or: newgrp docker
```

---

## 📈 Performance Expectations

### Training (YOLO on RTX 2070)

- YOLOv8n: ~200 images/sec
- YOLOv8s: ~150 images/sec
- YOLOv8m: ~100 images/sec

### Inference (Batch)

- YOLOv8n: ~300 images/sec
- Single image: <10ms

### Dataset Curation

- 10,000 images: ~5-10 minutes (CPU)
- Clustering 1M samples: ~15-30 minutes

---

## 🎓 Next Steps

1. **Install & Test**

   ```bash
   ./scripts/install_nvidia_drivers.sh  # Reboot after
   ./scripts/install_docker_nvidia.sh
   ./scripts/install_ray_cluster.sh
   cd docker && ./build_images.sh
   cd .. && ./start_all.sh
   ```

2. **Run First Job**

   ```bash
   ./ray-compute submit \
     --name "gpu-test" \
     --code "import torch; print(f'GPU: {torch.cuda.get_device_name(0)}')" \
     --gpu 1 --wait --logs
   ```

3. **Adapt YOLO Training**

   - Edit `pipelines/yolo_training.py`
   - Update dataset config
   - Run: `python3 pipelines/yolo_training.py`

4. **Setup Automated Retraining**

   - Schedule `auto_retraining_pipeline.py`
   - Use cron or systemd timers

5. **Build Web UI** (Optional)
   - React dashboard for job management
   - Real-time logs and metrics
   - Resource graphs

---

## 📞 Support Resources

- **Ray Documentation**: https://docs.ray.io
- **MLflow Docs**: https://mlflow.org/docs/latest
- **YOLO Docs**: https://docs.ultralytics.com
- **PyTorch Docs**: https://pytorch.org/docs

---

## ✨ Key Features Summary

✅ **GPU-Accelerated** - RTX 2070 for training/inference  
✅ **Auto-Scaling** - Dynamic worker management  
✅ **Docker Isolated** - Secure containerized jobs  
✅ **MLflow Integrated** - Automatic experiment tracking  
✅ **Multi-Interface** - CLI, Python SDK, REST API  
✅ **YOLO Optimized** - Pre-configured for object detection  
✅ **Pipeline Ready** - Multi-stage workflow support  
✅ **Production Ready** - Systemd services, monitoring, logging

---

**Status**: Ready for Installation ✅  
**Next**: Run `./scripts/install_nvidia_drivers.sh` and reboot

Enjoy your GPU-accelerated ML compute cluster! 🚀
