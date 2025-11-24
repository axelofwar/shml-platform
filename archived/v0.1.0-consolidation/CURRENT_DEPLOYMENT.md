# Current Deployment Status

**Last Updated:** 2025-11-22  
**Status:** ✅ Fully Operational

---

## Infrastructure Overview

**Network:** `ml-platform` (172.30.0.0/16)  
**Gateway:** Traefik v2.10 on port 80/8090  
**Total:** 14 containers (13 healthy)

---

## MLflow Stack (8 services)

**Status:** ✅ Operational  
**Version:** MLflow 2.17.2, PostgreSQL 15, Redis 7

| Service | Container | Port | Health |
|---------|-----------|------|--------|
| MLflow | mlflow-server | 5000→8080 | ✅ |
| PostgreSQL | mlflow-postgres | 5432 | ✅ |
| Nginx | mlflow-nginx | 80→8080 | ✅ |
| Redis | ml-platform-redis | 6379 (DB 0) | ✅ |
| Grafana | mlflow-grafana | 3000 | ✅ |
| Prometheus | mlflow-prometheus | 9090 | ✅ |
| Adminer | mlflow-adminer | 8080→8081 | ✅ |
| Backup | mlflow-backup | - | ✅ |

**Access URLs:**
- UI: http://localhost/mlflow/
- API: http://localhost/api/2.0/mlflow/
- Grafana: http://localhost/mlflow-grafana/ (admin/admin)
- Adminer: http://localhost/mlflow-adminer/

**Features:**
- ✅ 6 pre-configured experiments (prod/staging/dev/dataset/registry)
- ✅ Schema enforcement (required tags per experiment)
- ✅ Daily backups (2 AM, 90-day retention)
- ✅ REST API + Python SDK
- ✅ Tailscale VPN access (${TAILSCALE_IP})

**Database:**
- Host: mlflow-postgres:5432 (internal)
- Database: mlflow_db
- User: mlflow
- Password: secrets/db_password.txt

---

## Ray Compute Stack (5 services)

**Status:** ⚠️ Infrastructure Ready, App Development Pending  
**Version:** Ray 2.9.0-gpu, PostgreSQL 15, FastAPI

| Service | Container | Port | Health |
|---------|-----------|------|--------|
| Ray Head | ray-head | 8265 | ⏸️ Not deployed |
| API Server | ray-compute-api | 8000 | ⏸️ Not deployed |
| PostgreSQL | ray-compute-db | 5433 | ⏸️ Not deployed |
| Grafana | ray-grafana | 3001 | ⏸️ Not deployed |
| Prometheus | ray-prometheus | 9091 | ⏸️ Not deployed |

**OAuth (Authentik):**
- Status: ⏸️ Not deployed (infrastructure ready)
- Web UI: ⏸️ Production-ready, not deployed
- Client ID: ray-compute-api
- Groups: admins, premium, users

**Access URLs (when deployed):**
- Dashboard: http://localhost/ray/
- API: http://localhost/api/compute/
- Web UI: http://localhost/ray-ui/
- Grafana: http://localhost/ray-grafana/
- Authentik: http://localhost:9000

**Database (Schema Ready):**
- 8 tables: users, user_quotas, jobs, job_queue, artifact_versions, resource_usage_daily, audit_log, system_alerts
- Functions: calculate_fair_share, should_cleanup_artifact
- Triggers: log_audit_event

**GPU:**
- NVIDIA MPS enabled (fractional GPU sharing)
- GPU exporter: ⚠️ Restarting (nvidia-docker runtime config needed)

**Pending Development:**
- API server implementation (auth, scheduler, queue, notifications)
- Ray head node deployment
- Web UI deployment
- CLI tool (ray-compute)

---

## Shared Services

**Redis (ml-platform-redis):**
- DB 0: MLflow cache ✅
- DB 1: Ray Compute cache ⏸️
- Port: 6379 (internal)

**Traefik (API Gateway):**
- Version: v2.10
- Dashboard: http://localhost:8090 ✅
- Path routing: /mlflow/*, /ray/*, /api/*
- Auto-discovery via Docker labels

---

## Network Architecture

```
Client → Traefik:80 → Path Router → Backend
         |
         ├─ /mlflow/* → mlflow-nginx:80 → mlflow-server:5000 ✅
         ├─ /ray/* → ray-head:8265 ⏸️
         ├─ /api/compute/* → ray-compute-api:8000 ⏸️
         ├─ /mlflow-grafana/* → mlflow-grafana:3000 ✅
         └─ /ray-grafana/* → ray-grafana:3001 ⏸️
```

**DNS:** Docker internal resolution (no hardcoded IPs)  
**Isolation:** Services only expose to ml-platform network  
**External:** Only Traefik binds to host ports (80, 8090)

---

## Data Persistence

**MLflow:**
```
./ml-platform/mlflow-server/data/
├── postgres/          # Database files
├── mlflow/artifacts/  # Model artifacts
├── redis/             # Cache
├── prometheus/        # Metrics
└── grafana/           # Dashboards
```

**Ray:**
```
./ml-platform/ray_compute/data/
├── postgres/          # Database files (schema ready)
├── ray/               # Logs, artifacts
├── redis/             # Cache
└── grafana/           # Dashboards
```

**Backups:**
```
./ml-platform/mlflow-server/backups/
├── postgres/          # Daily at 2 AM, 90-day retention
└── artifacts/
```

---

## Monitoring & Logs

**MLflow Monitoring:**
- Grafana: ✅ http://localhost/mlflow-grafana/
- Prometheus: ✅ http://localhost/mlflow-prometheus/
- Logs: `docker compose logs -f mlflow`

**Ray Monitoring:**
- Grafana: ⏸️ Not deployed
- Prometheus: ⏸️ Not deployed
- Loki: ⏸️ Not deployed (log aggregation ready)

**Notifications:**
- ntfy.sh topics generated for Ray (unused):
  - ray-compute-admin-a4fc45c810daa224
  - ray-compute-jobs-a4fc45c810daa224
  - ray-compute-system-a4fc45c810daa224

---

## Access Methods

**Local (on server):**
- http://localhost/mlflow/
- http://localhost/ray/ (when deployed)

**LAN (${SERVER_IP}):**
- http://localhost/mlflow/ ✅
- http://localhost/ray/ ⏸️
- http://localhost:8090 (Traefik) ✅

**VPN (Tailscale: ${TAILSCALE_IP}):**
- http://${TAILSCALE_IP}/mlflow/ ✅
- http://${TAILSCALE_IP}/ray/ ⏸️

**SSH Tunnel:**
```bash
ssh -L 8080:localhost:80 user@${SERVER_IP}
# Then: http://localhost:8080/mlflow/
```

---

## Security

**Implemented:**
- ✅ Network isolation (Docker bridge)
- ✅ HTTP-only cookies (MLflow sessions)
- ✅ Environment-based secrets (no hardcoded)
- ✅ Tailscale VPN for remote access
- ✅ Schema enforcement (MLflow experiments)
- ⏸️ OAuth2 + JWT (Ray, when deployed)

**Credentials:**
- MLflow DB: secrets/db_password.txt
- MLflow Grafana: secrets/grafana_password.txt
- Ray DB: ml-platform/ray_compute/.env
- Ray OAuth: ml-platform/ray_compute/.env
- Traefik: No auth (internal network only)

---

## CI/CD

**MLflow:** Manual deployment via docker-compose  
**Ray Web UI:** GitHub Actions pipeline ready:
- ESLint → Jest (70% coverage) → Build → E2E (Playwright) → Security (Trivy)
- Triggers: push/PR to main/develop

---

## Testing

**MLflow:**
```bash
curl http://localhost/mlflow/ | grep MLflow
curl http://localhost/api/2.0/mlflow/experiments/list
```

**Ray (when deployed):**
```bash
curl http://localhost/ray/
curl http://localhost/api/compute/health
```

**Traefik:**
```bash
curl http://localhost:8090/ping  # Should return "OK"
```

---

## Known Issues

**MLflow:**
- None - fully operational

**Ray:**
- GPU exporter restarting (needs nvidia-container-toolkit config)
- cAdvisor disabled (mount propagation issues, non-critical)
- Services not deployed (infrastructure only)

---

## Documentation

**Core:**
- ARCHITECTURE.md - Tool selection, scaling, implementation
- API_REFERENCE.md - OpenAPI specs for all APIs
- ACCESS_URLS.md - Quick URL reference
- INTEGRATION_GUIDE.md - MLflow+Ray integration (pending)
- TROUBLESHOOTING.md - Common issues (pending)

**Stack-Specific:**
- ml-platform/mlflow-server/README.md - Comprehensive MLflow guide
- ml-platform/ray_compute/README.md - OAuth-focused Ray guide
- ml-platform/ray_compute/LESSONS_LEARNED.md - Debugging insights
- ml-platform/ray_compute/docs/OAUTH_SETUP_GUIDE.md - Step-by-step OAuth

**Operational:**
- ml-platform/mlflow-server/scripts/ - 15 management scripts
- Unified scripts: start_all.sh, stop_all.sh (pending restart_all.sh)

---

## Next Steps

**Ray Deployment:**
1. Configure nvidia-container-toolkit for GPU
2. Implement API server (auth, scheduler, queue)
3. Deploy Ray head node
4. Deploy Web UI
5. Create CLI tool (ray-compute)
6. Enable monitoring stack

**Documentation:**
1. Create INTEGRATION_GUIDE.md
2. Create TROUBLESHOOTING.md
3. Rebuild ml-platform/mlflow-server/README.md
4. Create NEXT_STEPS.md (both stacks)
5. Create operational scripts
6. Create systemd service

**Cleanup:**
- Consolidate/remove 52 old .md files per MD_AUDIT.md

---

**MLflow:** ✅ Production Ready  
**Ray:** ⏸️ Infrastructure Ready, App Development Pending  
**Documentation:** 🔄 Consolidation In Progress
