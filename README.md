# ML Platform - Production Ready

## Overview

A production-ready ML platform with MLflow experiment tracking, Ray distributed compute, and comprehensive monitoring. Designed for GPU workloads with security, observability, and remote access.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Traefik API Gateway                       │
│                         Port 80                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
       ┌───────────┴────────────┬─────────────┐
       │                        │             │
       ▼                        ▼             ▼
┌──────────────┐      ┌─────────────┐   ┌────────────┐
│   MLflow     │      │ Ray Compute │   │ Monitoring │
│              │      │             │   │            │
│ • Tracking   │      │ • Head Node │   │ • Grafana  │
│ • Registry   │      │ • API       │   │ • 3x Prom  │
│ • API        │      │ • Workers   │   │ • DCGM     │
│ • PostgreSQL │      │ • PostgreSQL│   │ • cAdvisor │
└──────────────┘      └─────────────┘   └────────────┘
       │                        │             │
       └────────────┬───────────┴─────────────┘
                    ▼
        ml-platform network (172.30.0.0/16)
```

## Quick Start

### Initial Setup (One-time)

```bash
# Clone and navigate to platform
cd /home/axelofwar/Projects/sfml-platform/sfml-platform

# Run unified setup script
sudo ./setup.sh
```

The setup script will:
1. ✓ Install dependencies (Docker, NVIDIA toolkit, etc.)
2. ✓ Create network and generate passwords
3. ✓ Build .env files and secrets
4. ✓ Provision Grafana dashboards
5. ✓ Start all services in correct order
6. ✓ Run health checks and validation

**Time:** ~5-10 minutes for fresh install

### Start/Stop Services

```bash
# Start all services (safe phased startup)
./start_all_safe.sh

# Stop all services (optional backup)
./stop_all.sh
./stop_all.sh --backup  # Create backup before stopping

# Check platform status
./check_platform_status.sh
```

## Service Access

All services accessible via Traefik routing:

| Service | URL | Credentials |
|---------|-----|-------------|
| **MLflow UI** | http://localhost/mlflow/ | None (open) |
| **Ray Dashboard** | http://localhost/ray/ | None (open) |
| **Grafana** | http://localhost/grafana/ | admin / (from secrets/) |
| **FusionAuth** | http://localhost:9011/admin/ | Email-based login |
| **Traefik** | http://localhost:8090/ | Dashboard |

### Remote Access (Tailscale)

```bash
# Get Tailscale IP
tailscale ip -4

# Access from any device on your tailnet
http://<tailscale-ip>/mlflow/
http://<tailscale-ip>/grafana/
```

## Python Client Usage

### MLflow Tracking

```python
import mlflow

# Local access
mlflow.set_tracking_uri("http://localhost/mlflow")

# Remote access (Tailscale)
mlflow.set_tracking_uri("http://<tailscale-ip>/mlflow")

# Log experiments
with mlflow.start_run():
    mlflow.log_param("learning_rate", 0.01)
    mlflow.log_metric("accuracy", 0.95)
```

### Ray Remote Jobs

```python
import ray

# Connect to Ray cluster
ray.init(address="ray://localhost:10001")

# Or remote via Tailscale
ray.init(address="ray://<tailscale-ip>:10001")

# Submit tasks
@ray.remote
def train_model(data):
    # Your training code
    return model

result = ray.get(train_model.remote(data))
```

## Monitoring Dashboards

Access via Grafana: `http://localhost/grafana/`

**Platform Dashboards:**
- **System Metrics**: CPU, RAM, disk, network
- **Container Metrics**: Resource usage by container with ID reference
- **GPU Metrics**: DCGM monitoring (5 panels, both GPUs)

**MLflow Dashboards:**
- Request rates, latency, error rates
- Database connections, experiment metrics

**Ray Dashboards:**
- Cluster overview, node resources
- Task/actor metrics, GPU utilization

## Platform Management

### Service Health

```bash
# Check all services
./check_platform_status.sh

# View specific service logs
sudo docker logs mlflow-server
sudo docker logs ray-head
sudo docker logs unified-grafana

# Follow logs in real-time
sudo docker logs -f <service-name>
```

### Update Dashboards

```bash
# Regenerate container ID reference table
cd scripts
sudo ./update_container_dashboard.sh
```

### Run Tests

```bash
# Test all services
cd tests
./test_all_services.sh

# Test Ray job submission
./test_job_submission.py

# Test remote compute
./test_remote_compute.py
```

### Fresh Install

```bash
# Complete cleanup and reinstall
sudo ./setup.sh --full-reset
```

## File Structure

```
sfml-platform/
├── setup.sh                        # 🔥 Main setup script (use this!)
├── start_all_safe.sh               # Safe startup with health checks
├── stop_all.sh                     # Safe shutdown
├── check_platform_status.sh        # Status checker
│
├── docker-compose.yml              # Main services (MLflow, Ray, FusionAuth)
├── docker-compose.infra.yml        # Infrastructure (Traefik, PostgreSQL, Redis)
│
├── monitoring/
│   ├── global-prometheus.yml       # Global metrics (15s scrape)
│   ├── grafana/
│   │   ├── datasources.yml         # 3 Prometheus sources
│   │   └── dashboards/
│   │       ├── platform/           # System, Container, GPU
│   │       ├── mlflow/             # MLflow metrics
│   │       └── ray/                # Ray cluster metrics
│
├── mlflow-server/
│   ├── docker-compose.mlflow.yml   # MLflow-specific config
│   ├── monitoring/                 # MLflow Prometheus
│   └── secrets/                    # Grafana passwords
│
├── ray_compute/
│   ├── docker-compose.ray.yml      # Ray-specific config
│   ├── monitoring/                 # Ray Prometheus
│   └── .env                        # Ray environment
│
├── fusionauth/                     # OAuth/SSO config
├── secrets/                        # Generated passwords
├── scripts/                        # Utility scripts
├── tests/                          # All test scripts (unit, integration)
└── archived/                       # Obsolete files
```

## Hardware Requirements

**Minimum:**
- 8GB RAM
- 50GB disk space
- NVIDIA GPU (for GPU workloads)

**Recommended (current setup):**
- 16GB+ RAM
- RTX 3090 Ti (24GB) + RTX 2070 (8GB)
- Ryzen 9 3900X (12C/24T)
- 100GB+ disk space

## Troubleshooting

### Services not starting

```bash
# Check Docker status
sudo systemctl status docker

# Check logs
./check_platform_status.sh
sudo docker logs <service-name>

# Restart specific service
sudo docker-compose restart <service-name>
```

### Dashboards showing "No Data"

```bash
# Check Prometheus is scraping
curl http://localhost:9090/api/v1/targets

# Wait ~90 seconds for metrics (15s scrape interval)
# Dashboards auto-refresh every 5 seconds
```

### GPU not detected

```bash
# Verify NVIDIA runtime
sudo docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi

# Check DCGM exporter
sudo docker logs dcgm-exporter
```

### Network issues

```bash
# Verify ml-platform network exists
sudo docker network inspect ml-platform

# Recreate if needed (services must be stopped)
sudo docker network rm ml-platform
sudo docker network create --subnet=172.30.0.0/16 ml-platform
```

## Documentation

- `ARCHITECTURE.md` - Detailed architecture overview
- `INTEGRATION_GUIDE.md` - Integration examples
- `TROUBLESHOOTING.md` - Common issues and solutions
- `API_REFERENCE.md` - API documentation
- `REMOTE_ACCESS_NEW.md` - Remote access guide
- `REMOTE_JOB_SUBMISSION.md` - Ray job submission
- `RAY_GPU_TESTING_SUMMARY.md` - GPU testing results

## Security

### Security Features

- ✅ **Pre-commit secret scanning** - ggshield + Gitleaks block secrets before commit
- ✅ **CI/CD security scanning** - GitGuardian, Trivy, pip-audit on all PRs
- ✅ **No privileged containers** - NVIDIA CDI mode for GPU access
- ✅ **Scoped device access** - Only required devices mounted
- ✅ **OAuth/SSO ready** - FusionAuth with social logins (Google, GitHub, Twitter)
- ✅ **Secrets management** - All credentials in gitignored `secrets/` directory
- ✅ **Secure remote access** - Tailscale VPN for encrypted connections
- ✅ **No hardcoded secrets** - All credentials loaded from environment
- ✅ **Git history cleaned** - BFG Repo-Cleaner removes any leaked secrets

### Developer Setup (REQUIRED)

**Install pre-commit hooks to prevent accidental secret commits:**

```bash
# Install tools
pip install pre-commit ggshield

# Install hooks
pre-commit install
pre-commit install --hook-type pre-push

# Authenticate GitGuardian (one-time)
ggshield auth login

# Verify setup
pre-commit run --all-files
```

> ⚠️ **All developers must run this setup.** Commits with secrets will be blocked.

### Secrets Management

All sensitive credentials are stored in `secrets/` (gitignored):

```bash
secrets/
├── shared_db_password.txt     # PostgreSQL password
├── grafana_password.txt       # Grafana admin password
├── fusionauth_api_key.txt     # FusionAuth API key
├── authentik_db_password.txt  # Authentik database password
└── authentik_bootstrap_password.txt  # Initial admin password
```

**Generate secrets:**
```bash
# Automatic (via setup)
sudo ./setup.sh

# Manual generation
openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32 > secrets/shared_db_password.txt
chmod 600 secrets/*.txt
```

**View credentials:**
```bash
cat secrets/grafana_password.txt  # Grafana login
cat secrets/authentik_bootstrap_password.txt  # Authentik login
```

See `secrets/README.md` for complete documentation.

### Environment Configuration

Copy the example environment file and customize:

```bash
cp .env.example .env
# Edit .env with your values (or let setup.sh generate them)
```

**Important:** Never commit `.env` files - they are gitignored by default.

### Security Checklist

Before deploying to production:

- [ ] Pre-commit hooks installed (`pre-commit install`)
- [ ] All secrets generated with `openssl rand`
- [ ] `.env` and `secrets/` not in version control
- [ ] Tailscale or VPN configured for remote access
- [ ] OAuth enabled if exposing to network
- [ ] Regular secret rotation scheduled
- [ ] Backup encryption configured

## Support

**Issues?** Check these in order:
1. `./check_platform_status.sh` - Service health
2. `sudo docker logs <service>` - Service logs
3. `TROUBLESHOOTING.md` - Common issues
4. Grafana dashboards - Metrics and monitoring
5. Traefik dashboard (`http://localhost:8090`) - Routing

**Need to re-run setup?**
```bash
sudo ./setup.sh --full-reset
```
