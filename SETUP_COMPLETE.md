# ML Platform Setup Complete ✅

**Date:** 2025-11-24  
**Host:** axelofwar-server  
**Status:** Fully Operational

---

## 🎉 What's Installed & Running

### Core Infrastructure
- ✅ Docker Engine 29.0.3
- ✅ Docker Compose v2.40.3
- ✅ NVIDIA Container Toolkit 1.18.0
- ✅ Tailscale VPN 1.90.8
- ✅ NVIDIA Driver 580.95.05

### GPUs Detected
- ✅ NVIDIA GeForce RTX 3090 Ti (24GB VRAM)
- ✅ NVIDIA GeForce RTX 2070 (8GB VRAM)
- ✅ NVIDIA MPS enabled for GPU sharing

### Services Running (20 containers)
1. **Traefik** - API Gateway (v2.11)
2. **MLflow Server** - Experiment tracking
3. **MLflow Nginx** - MLflow reverse proxy
4. **MLflow API** - Custom API endpoints
5. **MLflow PostgreSQL** - Database
6. **MLflow Grafana** - Monitoring dashboard
7. **MLflow Prometheus** - Metrics collection
8. **MLflow Adminer** - Database admin
9. **Ray Head** - Distributed computing (2 GPUs)
10. **Ray Compute API** - Job submission API
11. **Ray PostgreSQL** - Job metadata
12. **Ray Grafana** - Ray monitoring
13. **Ray Prometheus** - Ray metrics
14. **FusionAuth** - OAuth provider with social logins
18. **Redis** - Shared cache
19. **Node Exporter** - System metrics
20. **cAdvisor** - Container metrics

---

## 🌐 Access Information

### Network
- **LAN IP:** 10.0.0.163
- **Tailscale IP:** <TAILSCALE_IP> (VPN)

### Quick Access URLs
```bash
# MLflow
http://<TAILSCALE_IP>/mlflow/          # UI
http://<TAILSCALE_IP>/api/2.0/mlflow/  # API

# Ray
http://<TAILSCALE_IP>/ray/             # Dashboard
http://<TAILSCALE_IP>:8265             # Direct access

# Monitoring
http://<TAILSCALE_IP>:8090/            # Traefik
http://<TAILSCALE_IP>:9011/admin/      # FusionAuth
```

---

## �� Important Passwords

All passwords preserved from original setup:
- **MLflow Grafana:** `<your-password-from-.env>`
- **Ray Grafana:** `oVkbwOk7AtELl2xz`
- **FusionAuth Admin:** Email-based login (configured during setup)
- **Databases:** See `.env` file

---

## 🚀 Getting Started

### From Your Remote Machine

1. **Install packages:**
   ```bash
   pip install mlflow==2.9.2 ray[default]==2.9.0
   ```

2. **Set environment:**
   ```bash
   export MLFLOW_TRACKING_URI="http://<TAILSCALE_IP>/mlflow"
   export RAY_ADDRESS="http://<TAILSCALE_IP>:8265"
   ```

3. **Test connection:**
   ```python
   import mlflow
   import requests

   # Test MLflow
   response = requests.get(f"{os.getenv('MLFLOW_TRACKING_URI')}/api/2.0/mlflow/experiments/search")
   print(f"MLflow OK: {response.status_code == 200}")

   # Test Ray
   from ray.job_submission import JobSubmissionClient
   client = JobSubmissionClient(os.getenv('RAY_ADDRESS'))
   print(f"Ray version: {client.get_version()}")
   ```

---

## 💻 System Resources

### CPU & Memory
- **CPU:** AMD Ryzen 9 3900X (24 threads)
- **RAM:** 16GB DDR4
- **Allocated to Ray:** 8 CPUs, 2 GPUs

### GPU Configuration
- **Total VRAM:** 32GB (24GB + 8GB)
- **Ray Object Store:** 512MB
- **GPU Sharing:** Enabled via NVIDIA MPS

### Resource Optimization
- Docker resource limits dynamically calculated
- Services optimized for 16GB RAM system
- ~10GB available for ML workloads

---

## ��️ Management

### Start Platform
```bash
cd /home/axelofwar/Projects/shml-platform
sudo bash ./start_all_safe.sh
```

### Stop Platform
```bash
cd /home/axelofwar/Projects/shml-platform
sudo docker compose down
```

### View Logs
```bash
# All services
sudo docker compose logs -f

# Specific service
sudo docker compose logs -f mlflow-server
sudo docker compose logs -f ray-head
```

### Check Status
```bash
# Container status
sudo docker compose ps

# GPU status
sudo docker exec ray-head nvidia-smi

# Ray cluster status
sudo docker exec ray-head ray status
```

---

## 📊 Verified Working

### MLflow
- ✅ Experiment tracking
- ✅ Model registry
- ✅ Artifact storage
- ✅ REST API
- ✅ Web UI

### Ray
- ✅ Job submission
- ✅ GPU scheduling (2 GPUs)
- ✅ Dashboard
- ✅ Distributed computing
- ✅ Python API

### Infrastructure
- ✅ Traefik routing
- ✅ Database persistence
- ✅ Monitoring (Grafana/Prometheus)
- ✅ OAuth ready (FusionAuth with Google, GitHub, Twitter)
- ✅ VPN access (Tailscale)

---

## 📁 Configuration Files

- **Environment:** `.env` (credentials & IPs)
- **Docker Compose:** `docker-compose.yml` (services)
- **Secrets:** `secrets/`, `mlflow-server/secrets/`, `ray_compute/secrets/`
- **Remote Access:** `REMOTE_ACCESS_NEW.md` (complete guide)

---

## 🔄 What Changed from Old Setup

1. **New IPs:**
   - Old Tailscale: `axelofwar-dev-terminal-1`
   - New Tailscale: `<TAILSCALE_IP>` (axelofwar-server)

2. **GPU Upgrade:**
   - Added: RTX 3090 Ti (24GB)
   - Kept: RTX 2070 (8GB)
   - Total: 2 GPUs available to Ray

3. **Configuration Updates:**
   - Removed unsupported MLflow options
   - Fixed Ray GPU device enumeration
   - Updated Traefik to v2.11 for Docker API compatibility
   - Optimized memory allocation for 16GB RAM

4. **Secrets:**
   - All original passwords preserved
   - Stored in `.env` and `secrets/` directories

---

## 📚 Documentation

- **Remote Access:** `REMOTE_ACCESS_NEW.md` - Complete remote usage guide
- **Architecture:** `ARCHITECTURE.md` - System design & components
- **GPU Setup:** `NEW_GPU_SETUP.md` - Dual GPU installation reference
- **API Reference:** `API_REFERENCE.md` - API endpoints & examples
- **Troubleshooting:** `TROUBLESHOOTING.md` - Common issues & solutions

---

## 🎯 Next Steps

1. **Test from remote machine:**
   - Install client packages
   - Run example MLflow experiment
   - Submit test Ray job

2. **Configure OAuth (optional):**
   - FusionAuth is running with social login support
   - Access admin at http://localhost:9011/admin/
   - See `configure_oauth.sh` to enable for services

3. **Monitor performance:**
   - Grafana dashboards at `/grafana/` and `/ray-grafana/`
   - Watch GPU usage: `watch -n 1 nvidia-smi`

4. **Start building:**
   - Create experiments in MLflow
   - Submit distributed jobs to Ray
   - Leverage dual GPUs for parallel training

---

## ✅ Setup Verification

Run this from the host to verify everything:

```bash
cd /home/axelofwar/Projects/shml-platform
echo "=== Platform Status ===" && \
sudo docker compose ps && \
echo -e "\n=== GPU Status ===" && \
sudo docker exec ray-head nvidia-smi --query-gpu=index,name,memory.total --format=csv && \
echo -e "\n=== Ray Cluster ===" && \
sudo docker exec ray-head ray status && \
echo -e "\n=== Endpoints ===" && \
curl -s -o /dev/null -w "MLflow UI: %{http_code}\n" http://localhost/mlflow/ && \
curl -s -o /dev/null -w "Ray Dashboard: %{http_code}\n" http://localhost/ray/ && \
echo -e "\n✅ All systems operational!"
```

---

**Platform is ready for remote ML workloads! 🚀**

After startup, access:

Traefik Dashboard: http://100.66.26.115:8090/
MLflow UI: http://100.66.26.115/mlflow/
Ray Dashboard: http://100.66.26.115/ray/
Grafana: http://100.66.26.115/grafana/ (admin / your-password)
