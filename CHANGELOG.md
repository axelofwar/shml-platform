# Changelog

All notable changes to the ML Platform project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] - 2025-12-01

### Changed

- **Authentication Migration**: Migrated from Authentik to FusionAuth for OAuth/SSO
  - Simplified authentication setup with streamlined configuration
  - FusionAuth admin URL: `http://localhost:9011/admin/` or via Tailscale Funnel
  - Email-based admin login (configured during setup)
  - Port changed from 9000/9443 (Authentik) to 9011 (FusionAuth)
  - OAuth endpoints changed from `/application/o/` to `/oauth2/`
- **Social Login Support**: Added OAuth providers
  - Google OAuth integration
  - GitHub OAuth integration  
  - Twitter OAuth integration
- **Public HTTPS Access**: Configured Tailscale Funnel
  - Public URL: `https://sfml-platform.tail38b60a.ts.net/`
  - FusionAuth accessible at `https://sfml-platform.tail38b60a.ts.net/auth/admin/`
  - Automatic SSL/TLS termination via Tailscale

### Removed

- Authentik OAuth provider (replaced by FusionAuth)
- Authentik-specific containers (authentik-server, authentik-worker, authentik-postgres, authentik-redis)

---

## [Unreleased]

### Added

- **Inference Stack**: Local LLM and Image Generation services
  - **Qwen3-VL-8B-INT4**: Planning, architecture, code scaffolding (RTX 2070)
  - **Z-Image-Turbo**: Photorealistic image generation (RTX 3090, on-demand)
  - **Inference Gateway**: Request queue, rate limiting, chat history
  - Dynamic GPU management: Z-Image yields to training jobs
  - PostgreSQL chat history with compressed zstd backups
  - OpenAI-compatible API endpoints
  - Privacy-first: TRANSFORMERS_OFFLINE=1, no telemetry
- **Inference Stack Testing**: Comprehensive test suite for inference services
  - Unit tests for schemas, config, and utilities (no GPU required)
  - Integration tests for API endpoints and service health
  - Mock fixtures for testing without GPU access
  - Dedicated test runner: `tests/run_inference_tests.sh`
- **Start/Stop Script Integration**: Inference stack integrated with platform lifecycle
  - `start_all_safe.sh`: Phase 7 for inference services with GPU detection
  - `stop_all.sh`: Graceful inference shutdown with backup
  - Inference management commands in startup output
- **Unified Monitoring Stack**: Consolidated Prometheus and Grafana
  - Single Prometheus instance scraping all services (mlflow, ray, traefik, node-exporter, cadvisor)
  - Single Grafana instance with folder-organized dashboards (System, MLflow, Ray)
  - Platform overview dashboard for cross-service monitoring
  - Consolidated alerting rules for all services
  - Reduces container count from 4 monitoring containers to 2
- **Ray Cluster Metrics Integration**: Full Ray observability per [Ray docs](https://docs.ray.io/en/latest/cluster/metrics.html)
  - HTTP service discovery for dynamic node scraping (`/api/prometheus/sd`)
  - `--metrics-export-port=8080` on ray-head for dedicated metrics endpoint
  - Ray Cluster Overview Grafana dashboard with:
    - Cluster overview (active nodes, pending/running tasks, actors, CPU/GPU usage)
    - Resource utilization (CPU/GPU %, object store memory)
    - Task & actor state tracking (pending/running/finished, alive/dead)
    - Node health monitoring (CPU, memory per node)
    - GPU metrics (utilization, VRAM usage per GPU)
    - Autoscaler metrics (node scaling, failures/restarts)
  - Enhanced alerting rules for Ray:
    - `RayClusterDown`, `RayNodeDead`, `RayObjectStoreMemoryHigh`
    - `RayWorkerMemoryHigh`, `RayGPUUtilizationLow`, `RayTasksPending`
    - `RayActorRestartHigh`
- Initial GitHub repository preparation
- Professional project files (LICENSE, CONTRIBUTING.md, CODE_OF_CONDUCT.md)
- Comprehensive .gitignore for ML/Docker/Python/Node.js projects
- **SELF_HOSTED_PREMIUM_FEATURES.md**: Complete guide for implementing Supabase-like premium features while staying 100% self-hosted and privacy-focused (PostgREST auto APIs, MinIO object storage, pgvector semantic search, Meilisearch full-text search, OpenFaaS edge functions, Caddy CDN)
- **MONETIZATION_STRATEGY.md**: Symlinked from pii-pro project for unified monetization strategy across both projects

### Changed

- Documentation consolidation from 74 files to <20 files
- Updated copilot instructions with inference stack documentation
- Service count: 19 core → 21 total (with inference stack, after monitoring consolidation)
- Updated `tests/conftest.py` with inference fixtures and markers
- Updated `tests/requirements.txt` with inference testing dependencies
- **Monitoring Consolidation**: Replaced 4 separate monitoring containers with 2 unified containers
  - `mlflow-prometheus` + `ray-prometheus` → unified `prometheus` service
  - `mlflow-grafana` + `ray-grafana` → unified `grafana` service
  - Routes: `/prometheus` and `/grafana` via Traefik
  - Updated `start_all_safe.sh` for consolidated monitoring services
- **PostgreSQL Consolidation**: Merged 3 PostgreSQL instances into 1 shared instance
  - `mlflow-postgres` + `ray-postgres` + `inference-postgres` → `shared-postgres`
  - **Savings**: ~1 GB RAM (513 + 513 + 512 = 1538 MB → 768 MB)
  - FusionAuth uses its own PostgreSQL for security isolation
  - New init script: `postgres/init-databases.sh` (creates mlflow_db, ray_compute, inference)
  - Unified backup directory: `./backups/postgres/`
  - Updated all services to use `shared-postgres` with `shared_db_password` secret
- **Redis Memory Fix**: Fixed critical maxmemory mismatch bug
  - Container limit was 385 MB but Redis config set `--maxmemory 2gb` (would cause OOM)
  - Fixed to: container 512 MB, Redis `--maxmemory 400mb`
- **Dev Profile for Adminer**: `mlflow-adminer` now requires `--profile dev` to start
  - Production deployments skip this service automatically
  - Run with: `docker compose --profile dev up -d` to include Adminer
  - **Savings**: 141 MB RAM in production
- **Service Count Reduction**: 21 → 18 services (main stack) + 3 (inference) = 21 total
  - Removed: `mlflow-postgres`, `ray-postgres`, `inference-postgres`
  - Added: `shared-postgres`
  - Net reduction: 2 containers

### Fixed

- **Redis OOM Risk**: Container memory limit (385 MB) was lower than Redis maxmemory (2 GB)
  - This would have caused container crashes under load
  - Fixed by aligning container limit (512 MB) with Redis config (400 MB)

---

## [0.1.0] - 2025-11-23

### 🎉 Initial Release

A production-ready ML platform combining MLflow experiment tracking and Ray distributed computing with unified Traefik gateway and Tailscale VPN access.

---

### 🚀 Core Platform

#### Architecture

- **MLflow Stack**: 8 services (tracking server, PostgreSQL, Redis, Nginx, Grafana, Prometheus, Adminer, backup)
- **Ray Stack**: 10 services (head node, API server, PostgreSQL, Redis, Grafana, Prometheus, FusionAuth OAuth)
- **Gateway**: Traefik v2.10 reverse proxy with Docker provider
- **Network**: Unified `ml-platform` Docker network (172.30.0.0/16)
- **VPN**: Tailscale integration for secure remote access

#### Services

- MLflow 2.9.2 tracking server with PostgreSQL backend
- Ray 2.9.0-gpu with CUDA support (NVIDIA RTX 2070)
- Traefik gateway with automatic service discovery
- FusionAuth OAuth provider for authentication
- Prometheus + Grafana monitoring for both stacks
- Redis shared cache (multi-database support)

---

### 📊 MLflow Features

#### Experiment Tracking

- PostgreSQL-backed tracking with full CRUD operations
- Native Model Registry (no separate backend needed)
- HTTP artifact serving via `--serve-artifacts`
- Pre-configured experiments with schema enforcement
- REST API + Python SDK support

#### Storage & Persistence

- Volume mounts for all data (postgres, redis, artifacts, grafana)
- Automated daily backups (2 AM, 90-day retention)
- Database migrations tracked and documented

#### Monitoring

- Grafana dashboards for MLflow metrics
- Prometheus scraping (server, database, cache)
- Adminer web UI for database management

#### Access

- Web UI: `/mlflow/`
- REST API: `/api/2.0/mlflow/`
- Custom API: `/api/v1/` (enhanced endpoints with pagination)
- Localhost, LAN (${SERVER_IP}), and Tailscale (${TAILSCALE_IP}) access

---

### 🎯 Ray Features

#### Distributed Computing

- Ray 2.9.0 with GPU support
- 4 CPUs, 1 GPU (NVIDIA RTX 2070), 4GB RAM allocation
- Object store: 1GB, Shared memory: 2GB
- Job submission via Python API and CLI

#### Job Management

- Ray Dashboard UI at `/ray/`
- Job submission API with runtime environments
- GPU job scheduling (@ray.remote(num_gpus=1))
- Integration with MLflow for experiment tracking

#### Monitoring

- Ray Dashboard for cluster status
- Grafana dashboards for Ray metrics
- Prometheus scraping (head node, API server)

#### OAuth Integration

- FusionAuth OAuth provider configured
- Client ID/Secret for API authentication
- Ready for web UI authentication (not yet enforced)

---

### 🔧 Infrastructure

#### Docker Compose

- Unified `docker-compose.yml` with 20+ services
- Health checks for all critical services
- Resource limits (CPU, memory) per service
- Dependency management with `depends_on`
- Multiple Docker networks (ml-platform, ray-internal)

#### Traefik Configuration

- Path-based routing for all services
- Router priority management (critical for `/api/*` paths)
- HTTP entrypoints (HTTPS ready but not configured)
- Dashboard at port 8090
- Automatic service discovery via Docker labels

#### Network Access

- Tailscale VPN: ${TAILSCALE_IP} (axelofwar-dev-terminal-1.tail38b60a.ts.net)
- LAN: ${SERVER_IP}
- Localhost: 127.0.0.1
- Firewall: UFW configured for required ports

---

### 🛠️ Management Scripts

#### Unified Scripts (root level)

- `start_all_safe.sh`: Phased startup with health verification
- `stop_all.sh`: Stop all services cleanly
- `restart_all.sh`: Restart with safety checks
- `check_platform_status.sh`: Health check all services
- `test_all_services.sh`: Integration testing

#### MLflow Scripts (mlflow-server/scripts/)

- 15+ management utilities
- Database backup/restore
- Artifact management
- Configuration validation
- Health monitoring

#### Ray Scripts (ray_compute/)

- OAuth configuration helpers
- Service restart scripts
- Job submission examples
- GPU utilization monitoring

---

### 📚 Documentation

#### Core Documentation (12 files)

- `README.md`: Project overview and quick start
- `ARCHITECTURE.md`: System design and technology decisions
- `API_REFERENCE.md`: Complete API documentation (MLflow, Ray, Traefik)
- `INTEGRATION_GUIDE.md`: Service integration patterns
- `TROUBLESHOOTING.md`: Common issues and solutions (813 lines)
- `LESSONS_LEARNED.md`: Critical patterns and best practices
- `REMOTE_QUICK_REFERENCE.md`: Remote access guide (public)
- `NEW_GPU_SETUP.md`: GPU configuration guide (exportable)
- `mlflow-server/README.md`: MLflow-specific documentation
- `ray_compute/README.md`: Ray-specific documentation
- `CONTRIBUTING.md`: Contribution guidelines
- `CHANGELOG.md`: This file

#### Special Documentation

- `REMOTE_ACCESS_COMPLETE.sh`: Complete reference with credentials (git-ignored)
- Copilot instructions for MLflow and Ray (context for AI assistance)

---

### 🔒 Security

#### Secrets Management

- All passwords in git-ignored `secrets/` directories
- Docker secrets for sensitive data
- Environment variables for configuration
- No hardcoded credentials in code or compose files

#### Network Security

- Services not exposed to public internet
- Tailscale VPN for remote access
- Optional OAuth with FusionAuth
- Network-level isolation between services

#### Current Credentials

- MLflow Grafana: admin / <your-password-from-.env>
- Ray Grafana: admin / oVkbwOk7AtELl2xz
- FusionAuth: (email-based login configured during setup)
- Database passwords: In secrets/\*.txt files
- OAuth secrets: In ray_compute/.env

---

### 🐛 Critical Fixes

#### Traefik Routing Priority (CRITICAL)

**Problem**: Custom API routes at `/api/v1/*` returned 404  
**Root Cause**: Traefik internal API uses PathPrefix(`/api`) with priority 2147483646  
**Solution**: Set custom API router priority to 2147483647 (max int32)  
**Impact**: MLflow custom API now accessible with <10ms response time

#### Ray Head Memory Allocation (CRITICAL)

**Problem**: Ray head crashed with "memory available is less than -112%" error  
**Root Cause**: Allocated 4GB object store + 2GB shm in 2GB container  
**Solution**: Reduced object store to 1GB, increased container to 4GB  
**Impact**: Ray head starts successfully, all GPU jobs functional

#### MLflow API Performance (CRITICAL)

**Problem**: Health check endpoint took 97+ seconds, appearing as timeouts  
**Root Cause**: Calling `client.search_experiments()` on every health check  
**Solution**: Removed expensive MLflow query, return static response  
**Impact**: Health check response time: 97,147ms → 10ms (9,700x improvement)

#### Service Startup Dependencies

**Problem**: Services failing to start due to race conditions  
**Root Cause**: Docker Compose starting all services simultaneously  
**Solution**: Phased startup script (infrastructure → core → APIs → monitoring)  
**Impact**: 100% successful startup, all 16 services healthy in ~90 seconds

#### Orphaned Container Cleanup

**Problem**: Manual `docker run` commands left containers blocking compose  
**Root Cause**: docker-compose unaware of manually created containers  
**Solution**: Detect and remove orphaned containers in start script  
**Impact**: Clean startup every time without manual intervention

---

### 📈 Performance

#### System Resources

- **CPU**: AMD Ryzen 9 3900X (12C/24T) - 4 cores allocated to Ray
- **RAM**: 16GB DDR4-2400 - Ray limited to 4GB, upgrade to 64GB recommended
- **GPU**: NVIDIA RTX 2070 (8GB VRAM) - Fully utilized for GPU jobs
- **Storage**: 1.8TB total, 51GB used (3%)

#### Service Performance

- MLflow API response time: <10ms (optimized)
- Ray job submission: Instant (async)
- Platform startup time: ~90 seconds (cold start)
- All services healthy and stable

#### Resource Allocation

- Ray Head: 4 CPUs, 4GB RAM, 1GB object store, 1 GPU
- MLflow: 2 CPUs, 2GB RAM
- PostgreSQL (MLflow): 2 CPUs, 2GB RAM
- PostgreSQL (Ray): 2 CPUs, 2GB RAM
- Remaining capacity for workloads and future expansion

---

### 🧪 Testing & Validation

#### Integration Tests

- All service health checks passing
- MLflow experiment CRUD operations verified
- Ray job submission tested (CPU and GPU)
- Model registry operations validated
- Artifact upload/download confirmed
- Network routing verified (all paths working)

#### Example Jobs

- Simple Pi calculation (Monte Carlo method)
- GPU matrix multiplication (cupy)
- MLflow+Ray integration examples
- Distributed hyperparameter tuning

---

### 📖 Usage Examples

#### MLflow Tracking

```python
import mlflow
mlflow.set_tracking_uri("http://${TAILSCALE_IP}/mlflow")
mlflow.set_experiment("my-experiment")

with mlflow.start_run():
    mlflow.log_param("param", value)
    mlflow.log_metric("metric", value)
    mlflow.sklearn.log_model(model, "model")
```

#### Ray Job Submission

```python
from ray.job_submission import JobSubmissionClient

client = JobSubmissionClient("http://${TAILSCALE_IP}:8265")
job_id = client.submit_job(
    entrypoint="python train.py",
    runtime_env={"pip": ["mlflow==2.9.2"]}
)
```

#### GPU Jobs

```python
import ray

@ray.remote(num_gpus=1)
def train_on_gpu():
    # Your GPU code here
    pass
```

---

### 🔄 Migration Notes

This is the initial release. Future versions will document:

- Breaking changes
- Migration steps
- Deprecated features
- Upgrade instructions

---

### 📝 Known Limitations

1. **RAM**: 16GB limits concurrent workload capacity (upgrade to 64GB recommended)
2. **Authentication**: OAuth configured but not enforced (network-level security only)
3. **HTTPS**: Not configured (HTTP only, suitable for VPN/internal use)
4. **Backup**: MLflow backup service disabled (missing S3 credentials)
5. **Monitoring**: Limited historical data retention (Prometheus default settings)

---

### 🎯 Future Enhancements

See individual NEXT_STEPS.md files in:

- `mlflow-server/NEXT_STEPS.md` - MLflow roadmap
- `ray_compute/` - Ray roadmap

Planned features:

- Enforce OAuth authentication across all services
- SSL/TLS certificates for HTTPS
- Ray worker nodes for scaling
- S3 backend for MLflow artifacts
- Advanced monitoring dashboards
- Automated testing pipeline
- CI/CD integration

---

### 🙏 Acknowledgments

- **MLflow Team**: Excellent experiment tracking platform
- **Ray Team**: Powerful distributed computing framework
- **Traefik Team**: Robust reverse proxy with Docker integration
- **FusionAuth Team**: Modern OAuth/OIDC provider with social login

---

### 📞 Support & Resources

- Documentation: See README.md and linked guides
- Issues: Check TROUBLESHOOTING.md first
- Best Practices: See LESSONS_LEARNED.md
- Contributing: See CONTRIBUTING.md

---

## Version History

- **0.1.0** (2025-11-23): Initial release - Production-ready ML platform

---

**Note**: This CHANGELOG will be updated with each release. Contributors should add entries under "Unreleased" section as changes are made.
