# SHML Platform

> Self-Hosted ML Platform — GPU-optimized training, experiment tracking,
> model registry, and agentic development on your own hardware.

[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://shml-platform.github.io/docs)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Quick Start

### Prerequisites

- Docker Engine 24+ with Compose V2
- NVIDIA Container Toolkit (`nvidia-ctk`)
- NVIDIA GPU with 24GB+ VRAM (training)
- 16GB+ RAM, 100GB+ disk

### Install & Launch

```bash
git clone https://github.com/yourusername/shml-platform.git
cd shml-platform

# One-time setup: installs deps, creates network, generates secrets
sudo ./setup.sh

# Start all services (with health checks)
./start_all_safe.sh

# Install SDK
pip install -e sdk/

# Verify
shml platform status
```

### Externalized Runtime Storage

Large runtime artifact trees live outside the repo root at `/home/axelofwar/Projects/shml-platform-storage` and are exposed back into the repo through symlinks. Keep using the original repo paths in scripts and services; do not redownload models, checkpoints, or backups because those paths still resolve normally.

Current externalized paths:

- `data` -> `/home/axelofwar/Projects/shml-platform-storage/data`
- `backups` -> `/home/axelofwar/Projects/shml-platform-storage/backups`
- `runs` -> `/home/axelofwar/Projects/shml-platform-storage/runs`
- `logs` -> `/home/axelofwar/Projects/shml-platform-storage/logs`
- `site` -> `/home/axelofwar/Projects/shml-platform-storage/site`
- `.public-mirror` -> `/home/axelofwar/Projects/shml-platform-storage/.public-mirror`
- `ray_compute/data` -> `/home/axelofwar/Projects/shml-platform-storage/ray_compute/data`
- `mlflow-server/logs` -> `/home/axelofwar/Projects/shml-platform-storage/mlflow-server/logs`

Quick verification:

```bash
readlink -f data
readlink -f backups
readlink -f ray_compute/data
```

---

## SDK & CLI

The `shml` CLI is the primary interface for training, job management, and GPU control.

### Training

```bash
# List available training profiles
shml config list-profiles

# Dry-run to preview configuration
shml train --profile balanced --dry-run

# Launch training
shml train --profile balanced --epochs 10

# Monitor
shml status <job_id>
shml logs <job_id>
```

### Python SDK

```python
from shml import Client, TrainingConfig

with Client() as c:
    # Submit training from a built-in profile
    job = c.submit_training("balanced", epochs=10)

    # Wait for completion
    result = c.wait_for_job(job.job_id)
    print(f"mAP50: {result.metrics.get('mAP50')}")

    # Access integrations
    runs = c.mlflow.list_runs("face-detection")
    c.nessie.create_branch("experiment-v2")
```

### Training Profiles

| Profile | Epochs | Batch | ImgSz | Est. Duration |
|---------|--------|-------|-------|---------------|
| `quick-test` | 2 | 8 | 640 | ~10 min |
| `balanced` | 10 | 4 | 1280 | ~2.5 hr |
| `full-finetune` | 50 | 4 | 1280 | ~12 hr |
| `foundation` | 100 | 4 | 1280 | ~24 hr |

Profiles live in `config/profiles/*.yaml` — create custom ones following the same format.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│               Traefik API Gateway (:80)                  │
│           OAuth2-Proxy + FusionAuth RBAC                 │
└─────┬──────────┬──────────┬──────────┬───────────────────┘
      │          │          │          │
      ▼          ▼          ▼          ▼
┌──────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐
│  MLflow  │ │  Ray   │ │Grafana │ │  Data Stack  │
│ Tracking │ │Compute │ │  Prom  │ │ Nessie/FO/FS │
│ Registry │ │  Jobs  │ │  Loki  │ │ Spark/Iceberg│
│ Artifacts│ │  GPUs  │ │  SLOs  │ │              │
└──────────┘ └────────┘ └────────┘ └──────────────┘
      │          │          │          │
      └──────────┴──────────┴──────────┘
            PostgreSQL + Redis + MongoDB
```

**Compose Files:**

| File | Services |
|------|----------|
| `deploy/compose/docker-compose.infra.yml` | Traefik, PostgreSQL, Redis, FusionAuth, OAuth2-Proxy, Prometheus, Grafana, Homer |
| `mlflow-server/deploy/compose/docker-compose.yml` | MLflow server + Nginx proxy |
| `ray_compute/deploy/compose/docker-compose.yml` | Ray head + workers |
| `deploy/compose/docker-compose.secrets.yml` | Secrets manager overlay |
| `deploy/compose/docker-compose.tracing.yml` | Distributed tracing |
| `deploy/compose/docker-compose.logging.yml` | Loki log aggregation |
| `inference/*/deploy/compose/docker-compose.yml` | Coding models, Chat API, Chat UI |

> **Note:** Always use `./start_all_safe.sh` — never `docker compose up` directly.

---

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| MLflow | `http://localhost/mlflow/` | Experiment tracking & model registry |
| Ray Dashboard | `http://localhost/ray/` | Job monitoring & cluster status |
| Grafana | `http://localhost/grafana/` | Metrics dashboards & alerting |
| FusionAuth | `http://localhost:9011/` | User management & OAuth |
| Homer | `http://localhost/` | Service dashboard |
| Traefik | `http://localhost:8090/` | Routing dashboard |
| Pushgateway | `http://localhost:9091/` | Training metrics ingestion |
| Prometheus | `http://localhost:9090/` | Metrics store |

**Remote access** via Tailscale VPN — see [Remote Access Guide](docs/guides/remote-access.md).

---

## GPU Management

```bash
# Check GPU status (VRAM, utilization, temperature)
shml gpu status

# Yield GPU for other tasks (graceful)
shml gpu yield

# Reclaim GPU for training
shml gpu reclaim
```

**Hardware:** Ryzen 9 3900X · RTX 3090 Ti (24GB) · RTX 2070 (8GB)

---

## Monitoring

Grafana dashboards at `http://localhost/grafana/`:

- **Unified Training** — epoch progress, loss curves, mAP metrics
- **Platform Overview** — CPU, RAM, disk, network
- **GPU Metrics** — DCGM monitoring for both GPUs
- **ML SLOs** — availability, latency, error budget
- **Ray Cluster** — task throughput, node resources

Training jobs auto-report metrics to Prometheus via the SDK's Pushgateway integration.

---

## User Roles

| Role | Capabilities |
|------|-------------|
| `viewer` | Read dashboards, view experiments |
| `developer` | Submit jobs, manage own experiments |
| `elevated-developer` | GPU management, model registry |
| `admin` | Platform management, user admin |

Authentication: FusionAuth → OAuth2-Proxy → Traefik role-auth middleware.

---

## Service Management

The platform uses a **modular deploy library** (`scripts/deploy/`) under a single orchestrator (`start_all_safe.sh`). The preferred developer interface is [`Taskfile.yml`](Taskfile.yml) (requires [Task](https://taskfile.dev)):

```bash
# Install Task (once)
brew install go-task  # or: go install github.com/go-task/task/v3/cmd/task@latest

# Common operations
task                           # Show platform status (default)
task start                     # Start all services
task start:inference           # Start inference stack only
task restart:ray               # Restart Ray compute stack
task stop                      # Stop all services
task status                    # Detailed health status
task deploy                    # Pull from registry then start
task logs -- <service>         # Follow service logs
task gpu                       # GPU VRAM + utilization
task systemd:install           # Install systemd unit files
```

Lower-level access via the orchestrator script directly:

```bash
./start_all_safe.sh                  # Start everything (with health checks)
./start_all_safe.sh start mlflow     # Start specific service group
./start_all_safe.sh stop             # Stop all services
./start_all_safe.sh status           # Detailed health status
./check_platform_status.sh           # Quick health overview
```

### Deploy Library

Orchestration logic is split into focused, independently-sourceable modules in `scripts/deploy/`:

| Module | Purpose |
|--------|---------|
| `lib.sh` | Core env loading, colors, log helpers, timeouts, Tailscale |
| `networks.sh` | Network constants (`shml-platform`, `shml-core-net`), `ensure_networks()` |
| `docker.sh` | `dc_pull/up/stop/down/restart`, conflict cleanup, retry backoff |
| `health.sh` | `wait_for_health/http/middleware` with strict/warn modes |
| `gpu.sh` | MPS daemon management, VRAM verification |
| `backup.sh` | Backup discovery, DB restore, pre-restart snapshots |

Each module uses an idempotency guard (e.g. `_SHML_LIB_LOADED`) so it is safe to source from multiple entry-points without redefinition.

---

## Documentation

| Resource | Description |
|----------|-------------|
| [Full Documentation](docs/index.md) | Complete platform docs (MkDocs) |
| [SDK Reference](docs/sdk/index.md) | Client, Config, Training Runner |
| [CLI Reference](docs/cli/index.md) | All CLI commands |
| [Architecture](docs/architecture/index.md) | System design & service topology |
| [Training Guide](docs/guides/training-walkthrough.md) | End-to-end training walkthrough |
| [Remote Access](docs/guides/remote-access.md) | Tailscale VPN setup & remote jobs |
| [Monitoring](docs/guides/monitoring.md) | Grafana, Prometheus, SLOs |
| [MLflow Guide](docs/guides/mlflow.md) | Experiments, model registry, artifacts |
| [Troubleshooting](docs/guides/troubleshooting.md) | Common issues & solutions |

---

## Security

- Pre-commit secret scanning (ggshield + Gitleaks)
- No privileged containers — NVIDIA CDI mode
- OAuth/SSO via FusionAuth with 4-tier RBAC
- All credentials in gitignored `secrets/` directory
- Tailscale VPN for encrypted remote access

```bash
# Required developer setup
pip install pre-commit ggshield
pre-commit install
pre-commit install --hook-type pre-push
```

---

## Hardware Requirements

| Tier | CPU | RAM | GPU | Disk |
|------|-----|-----|-----|------|
| Minimum | 4C/8T | 8 GB | 8GB VRAM | 50 GB |
| Recommended | 8C/16T | 16 GB | 24GB VRAM | 100 GB |
| Current Setup | Ryzen 9 3900X | 64 GB | 3090 Ti + 2070 | 2 TB NVMe |

---

## License

[MIT](LICENSE)
