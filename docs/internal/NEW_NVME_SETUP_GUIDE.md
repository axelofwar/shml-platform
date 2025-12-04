# SFML Platform Setup Guide - New NVMe Drive & Dual GPU Configuration

**Date:** November 30, 2025  
**Hardware:** New Samsung 990 PRO 2TB NVMe Drive  
**GPUs:** NVIDIA RTX 3090 Ti (24GB) + RTX 2070 (8GB)  
**System:** AMD Ryzen 9 3900X, 16GB RAM, Ubuntu 24.04

---

## 📋 Overview

This guide walks you through setting up the SFML ML Platform on your new NVMe drive with full dual-GPU support. The platform includes:

- **MLflow** - Experiment tracking and model registry
- **Ray Compute** - Distributed computing with GPU scheduling
- **Traefik** - API gateway for unified access
- **Monitoring** - Grafana, Prometheus, and system metrics
- **Authentication** - FusionAuth OAuth provider

---

## 🔍 Current System Status

### ✅ Hardware Detected
- **Storage:** Samsung 990 PRO 2TB mounted at `/` (1.8TB)
- **GPU 0:** NVIDIA GeForce RTX 3090 Ti (24GB VRAM, Compute 8.6)
- **GPU 1:** NVIDIA GeForce RTX 2070 (8GB VRAM, Compute 7.5)
- **CPU:** AMD Ryzen 9 3900X (24 threads)
- **Memory:** 16GB RAM (11GB available)
- **NVIDIA Driver:** 570.195.03

### ⚠️ Missing Components
- Docker Engine (not installed)
- Docker Compose (not installed)
- NVIDIA Container Toolkit (not installed)
- Platform containers (not running)

---

## 🎯 Setup Strategy

Your setup has two versions:
1. **shml-platform-original/** - Old configuration from previous drive
2. **shml-platform/shml-platform/** - New version to set up (recommended)

**We'll use:** The new version at `/home/axelofwar/Projects/shml-platform/shml-platform/`

---

## 📦 Phase 1: System Prerequisites (30-45 minutes)

### Step 1.1: Update System
```bash
# Update package lists
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y curl wget git vim nano htop build-essential \
    ca-certificates gnupg lsb-release postgresql-client
```

### Step 1.2: Install Docker Engine
```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform/ray_compute/scripts

# Run the Docker + NVIDIA Container Toolkit installer
chmod +x install_docker_nvidia.sh
./install_docker_nvidia.sh
```

**What this script does:**
- Removes old Docker versions
- Installs Docker CE from official repository
- Installs NVIDIA Container Toolkit
- Configures Docker to use NVIDIA runtime
- Adds your user to docker group
- Tests GPU access in Docker

**Expected output:**
```
✓ Docker installed successfully
✓ NVIDIA Container Toolkit installed
✓ SUCCESS! GPU is accessible in Docker
```

### Step 1.3: Apply Docker Group (REQUIRED)
```bash
# Log out and back in OR run:
newgrp docker

# Verify docker works without sudo
docker --version
docker compose version

# Verify GPU access
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi
```

You should see both GPUs listed in the Docker container output.

---

## 🎮 Phase 2: GPU Configuration (10 minutes)

### Step 2.1: Verify GPU PCIe Configuration

Your motherboard (ASUS ROG Crosshair VIII Hero) runs both GPUs optimally:
- **PCIEX16_1:** RTX 3090 Ti at PCIe 4.0 x8 (~16 GB/s bandwidth)
- **PCIEX16_2:** RTX 2070 at PCIe 4.0 x8 (~16 GB/s bandwidth)

This is more than sufficient for ML workloads (even PCIe 3.0 x8 is adequate).

```bash
# Verify PCIe configuration
lspci | grep -i nvidia

# Check detailed GPU info
nvidia-smi --query-gpu=index,name,pci.bus_id,memory.total,compute_cap --format=csv
```

### Step 2.2: Enable NVIDIA MPS (Multi-Process Service)

MPS allows multiple processes to share GPUs efficiently:

```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform/scripts

# Setup GPU sharing
chmod +x setup-gpu-sharing.sh
sudo ./setup-gpu-sharing.sh
```

**What this does:**
- Enables NVIDIA Persistence Mode (keeps driver loaded)
- Starts NVIDIA MPS daemon
- Configures compute mode for optimal sharing
- Creates systemd service for automatic startup

### Step 2.3: Verify GPU Status
```bash
# Check MPS status
nvidia-smi -q | grep -i "compute mode"
# Should show: "Default" or "Exclusive Process"

# Check driver persistence
nvidia-smi -q | grep -i "persistence mode"
# Should show: "Enabled"
```

---

## 🚀 Phase 3: Platform Deployment (20-30 minutes)

### Step 3.1: Navigate to Platform Directory
```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform
```

### Step 3.2: Review Configuration Files

The platform uses three main Docker Compose files:

1. **docker-compose.yml** - Main services (Traefik, Redis, Node Exporter, cAdvisor)
2. **ray_compute/docker-compose.yml** - Ray cluster with GPU support
3. **mlflow-server/docker-compose.yml** - MLflow tracking server

### Step 3.3: Configure Environment Variables

Check and update environment files:

```bash
# Ray Compute environment
cat ray_compute/.env
# Verify TAILSCALE_IP or set to your LAN IP (10.0.0.163)

# MLflow environment
cat mlflow-server/.env
# Verify database passwords and settings
```

### Step 3.4: Create Docker Network
```bash
# Create the shared ml-platform network
docker network create ml-platform --driver bridge --subnet 172.30.0.0/16
```

### Step 3.5: Start Platform Services

**Option A: Automated Start (Recommended)**
```bash
# Use the safe startup script
chmod +x start_all_safe.sh
sudo ./start_all_safe.sh
```

This script:
- Checks system resources
- Starts services in correct order
- Monitors health checks
- Provides status updates
- Handles resource constraints intelligently

**Option B: Manual Start (for debugging)**
```bash
# Start core infrastructure
docker compose up -d

# Start Ray Compute (includes GPU containers)
cd ray_compute
docker compose up -d

# Start MLflow
cd ../mlflow-server
docker compose up -d
```

### Step 3.6: Monitor Startup
```bash
# Watch all containers start
watch -n 2 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'

# Check logs for any service
docker logs -f ml-platform-traefik
docker logs -f ray-head
docker logs -f mlflow-server
```

**Expected startup time:** 3-5 minutes for all services to be healthy

---

## 🔍 Phase 4: Verification & Testing (15 minutes)

### Step 4.1: Check All Containers
```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform

# Run comprehensive test
chmod +x test_all_services.sh
./test_all_services.sh
```

### Step 4.2: Access Web Interfaces

Open your browser and test these URLs:

| Service | URL | Credentials |
|---------|-----|-------------|
| **Traefik Dashboard** | http://localhost:8090/ | None (public) |
| **MLflow UI** | http://localhost/mlflow/ | None |
| **Ray Dashboard** | http://localhost/ray/ | None |
| **MLflow Grafana** | http://localhost/grafana/ | admin / (see .env) |
| **Ray Grafana** | http://localhost/ray-grafana/ | admin / oVkbwOk7AtELl2xz |
| **Adminer (DB)** | http://localhost/adminer/ | See .env |

### Step 4.3: Test GPU Access in Ray

```bash
cd ray_compute/examples

# Quick GPU test (30 seconds)
python test_simple_gpu.py

# Full training test (1 minute)
python test_full_training.py
```

**Expected output:**
```
✅ GPU Training Job Completed Successfully!
GPU 0: NVIDIA GeForce RTX 3090 Ti
GPU 1: NVIDIA GeForce RTX 2070
```

### Step 4.4: Test MLflow Tracking

```python
import mlflow
import os

# Set tracking URI
mlflow.set_tracking_uri("http://localhost/mlflow")

# Create test experiment
mlflow.set_experiment("setup-verification")

# Log test run
with mlflow.start_run(run_name="gpu-test"):
    mlflow.log_param("gpu_count", 2)
    mlflow.log_param("gpu_0", "RTX 3090 Ti")
    mlflow.log_param("gpu_1", "RTX 2070")
    mlflow.log_metric("test_metric", 1.0)
    print("✅ MLflow tracking working!")
```

---

## 📊 Phase 5: Resource Optimization (Optional)

### Current Resource Allocation

With 16GB RAM, the platform dynamically allocates:
- **Docker Services:** ~6-8GB
- **Ray Workers:** 8GB allocated
- **GPU Memory:** 32GB total (24GB + 8GB)
- **Available for ML:** ~8-10GB system RAM

### Optimization Tips

**For memory-constrained systems:**

1. **Reduce Ray object store:**
```bash
# Edit ray_compute/docker-compose.yml
# Change RAY_OBJECT_STORE_MEMORY from 512MB to 256MB
```

2. **Limit concurrent jobs:**
```yaml
# Ray can run multiple jobs but schedule based on GPU availability
# Single GPU jobs: Can run 2 simultaneously (one per GPU)
# Dual GPU jobs: Only 1 at a time
```

3. **Monitor resource usage:**
```bash
# Real-time monitoring
htop

# Docker stats
docker stats --no-stream

# GPU utilization
watch -n 1 nvidia-smi
```

---

## 🌐 Phase 6: Remote Access Setup (Optional, 30 minutes)

### Option A: Tailscale VPN (Recommended)

```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform/mlflow-server/scripts

# Install and configure Tailscale
chmod +x setup_tailscale_vpn.sh
sudo ./setup_tailscale_vpn.sh
```

After setup:
1. Install Tailscale on your remote machine
2. Connect to the same Tailnet
3. Access services via Tailscale IP

### Option B: SSH Tunneling

```bash
# From remote machine
ssh -L 8080:localhost:80 \
    -L 8090:localhost:8090 \
    -L 8265:localhost:8265 \
    axelofwar@10.0.0.163

# Access services on remote machine:
# http://localhost:8080/mlflow/
# http://localhost:8090/ (Traefik)
# http://localhost:8265/ (Ray)
```

---

## 🔧 Phase 7: System Integration (Optional)

### Enable Automatic Startup

```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform/ray_compute/scripts

# Install systemd service
chmod +x install_systemd_services.sh
sudo ./install_systemd_services.sh
```

This creates a service that:
- Starts platform on boot
- Restarts on failure
- Logs to journalctl

### Daily Backups

```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform/scripts

# Setup automated backups
chmod +x setup_daily_backup.sh
sudo ./setup_daily_backup.sh
```

Backs up:
- MLflow experiments and models
- Ray job history
- PostgreSQL databases
- Configuration files

---

## 📝 Platform Architecture Summary

### Service Routing (via Traefik)

```
Internet/LAN (Port 80)
    │
    ├─ /mlflow/          → MLflow UI
    ├─ /ray/             → Ray Dashboard  
    ├─ /grafana/         → MLflow Grafana
    ├─ /ray-grafana/     → Ray Grafana
    ├─ /adminer/         → Database Admin
    └─ /api/             → Ray API
```

### GPU Resource Distribution

The platform automatically distributes GPU resources:

**Ray Cluster Configuration:**
- **CPUs:** 8 cores allocated (out of 24 available)
- **GPUs:** 2 GPUs (full access to both)
- **Memory:** 8GB system RAM
- **Object Store:** 512MB

**GPU Scheduling:**
- Jobs request GPUs via `entrypoint_num_gpus=1` or `2`
- Ray scheduler assigns available GPUs automatically
- Multiple single-GPU jobs can run concurrently
- NVIDIA MPS allows process-level sharing

### Data Persistence

All data persists in Docker volumes:
```bash
# List volumes
docker volume ls | grep ml-platform

# Backup location
/home/axelofwar/Projects/shml-platform/shml-platform/backups/
```

---

## 🎓 Common Operations

### Starting the Platform
```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform
sudo ./start_all_safe.sh
```

### Stopping the Platform
```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform
sudo ./stop_all.sh

# Or manually
docker compose down
cd ray_compute && docker compose down
cd ../mlflow-server && docker compose down
```

### Viewing Logs
```bash
# All services
docker compose logs -f

# Specific service
docker logs -f ray-head
docker logs -f mlflow-server

# Last 100 lines
docker logs --tail 100 ml-platform-traefik
```

### Restarting a Service
```bash
# Restart individual service
docker restart ray-head

# Rebuild and restart
docker compose up -d --force-recreate ray-head
```

### Checking GPU Usage
```bash
# Real-time GPU monitoring
watch -n 1 nvidia-smi

# GPU usage in Ray
curl http://localhost:8265/api/cluster_status | jq '.node_stats'
```

### Database Access
```bash
# MLflow database
docker exec -it mlflow-postgres psql -U mlflow -d mlflow_db

# Ray database
docker exec -it ray-postgres psql -U ray_compute -d ray_compute
```

---

## 🐛 Troubleshooting

### Issue: Docker containers won't start
```bash
# Check Docker daemon
sudo systemctl status docker

# Restart Docker
sudo systemctl restart docker

# Check disk space
df -h /
```

### Issue: GPUs not detected in Docker
```bash
# Verify NVIDIA runtime
docker info | grep -i nvidia

# Reconfigure toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Test GPU access
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi
```

### Issue: Port conflicts
```bash
# Check what's using port 80
sudo lsof -i :80

# Kill process if needed
sudo kill -9 <PID>

# Or change Traefik port in docker-compose.yml
```

### Issue: Out of memory
```bash
# Check memory usage
free -h
docker stats --no-stream

# Reduce Ray object store or restart services
```

### Issue: Service unhealthy
```bash
# Check health status
docker ps --format "table {{.Names}}\t{{.Status}}"

# View container logs
docker logs <container-name>

# Check resource limits
docker inspect <container-name> | jq '.[0].HostConfig.Resources'
```

---

## 📚 Additional Resources

### Documentation Files
- **README.md** - Platform overview and quick start
- **ARCHITECTURE.md** - Detailed architecture and design decisions
- **API_REFERENCE.md** - API endpoints and usage
- **SETUP_COMPLETE.md** - Previous setup summary
- **RAY_GPU_TESTING_SUMMARY.md** - GPU testing examples
- **TROUBLESHOOTING.md** - Common issues and solutions
- **NEW_GPU_SETUP.md** - Hardware installation guide

### Key Scripts
```
shml-platform/shml-platform/
├── start_all_safe.sh              # Safe startup
├── stop_all.sh                    # Shutdown all services
├── test_all_services.sh           # Verification tests
├── check_platform_status.sh       # Status check
├── scripts/
│   ├── backup_platform.sh         # Manual backup
│   ├── restore_platform.sh        # Restore from backup
│   └── monitor_resources.sh       # Resource monitoring
└── ray_compute/
    ├── examples/
    │   ├── test_simple_gpu.py     # Quick GPU test
    │   └── test_full_training.py  # Full training test
    └── scripts/
        └── install_docker_nvidia.sh  # Docker installer
```

---

## ✅ Post-Setup Checklist

- [ ] Docker and NVIDIA Container Toolkit installed
- [ ] Both GPUs accessible in Docker containers
- [ ] NVIDIA MPS enabled for GPU sharing
- [ ] All platform services started (20 containers)
- [ ] Traefik dashboard accessible (http://localhost:8090)
- [ ] MLflow UI accessible (http://localhost/mlflow)
- [ ] Ray Dashboard accessible (http://localhost/ray)
- [ ] Test GPU job completed successfully
- [ ] MLflow tracking working from Python
- [ ] Remote access configured (Tailscale or SSH)
- [ ] Automated backups configured (optional)
- [ ] Systemd service installed (optional)

---

## 🎉 Next Steps

Once setup is complete:

1. **Run example ML workloads:**
   ```bash
   cd ray_compute/examples
   python test_full_training.py
   ```

2. **Submit your own GPU jobs:**
   ```python
   from ray.job_submission import JobSubmissionClient
   client = JobSubmissionClient("http://localhost:8265")
   ```

3. **Track experiments in MLflow:**
   ```python
   import mlflow
   mlflow.set_tracking_uri("http://localhost/mlflow")
   ```

4. **Monitor GPU utilization:**
   - Ray Dashboard: http://localhost/ray
   - Ray Grafana: http://localhost/ray-grafana
   - NVIDIA-SMI: `watch -n 1 nvidia-smi`

5. **Explore advanced features:**
   - Multi-GPU training with Ray
   - Model registry in MLflow
   - Distributed hyperparameter tuning
   - Custom metrics and monitoring

---

## 💬 Support

For issues or questions:
1. Check TROUBLESHOOTING.md
2. View service logs: `docker logs -f <service-name>`
3. Check platform status: `./check_platform_status.sh`
4. Review documentation in the repo

---

**Setup Time Estimate:** 1.5 - 2 hours total  
**Difficulty:** Intermediate  
**Prerequisites:** Basic Docker knowledge, command line experience
