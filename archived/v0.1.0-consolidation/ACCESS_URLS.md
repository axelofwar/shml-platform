# Access URLs

Quick reference for all service endpoints and credentials.

## ✅ Deployment Status

**All services deployed and operational:**
- **MLflow Stack:** 8 services (server, postgres, nginx, grafana, prometheus, redis, adminer, backup)
- **Ray Stack:** 10 services (head, api, postgres, grafana, prometheus, redis, authentik-server, authentik-worker, authentik-postgres, authentik-redis)
- **Gateway:** Traefik (routing all services)

**Test all services:** `./test_all_services.sh`  
**Update passwords:** `./update_passwords.sh <new_password>`

**All passwords set to:** `AiSolutions2350!`
- MLflow Grafana: admin / AiSolutions2350!
- Ray Grafana: admin / AiSolutions2350!
- Authentik: akadmin / AiSolutions2350!

---

## 📚 Quick Links

- **Remote Client Usage:** [REMOTE_CLIENT_GUIDE.md](ml-platform/mlflow-server/docs/REMOTE_CLIENT_GUIDE.md) - How to upload experiments, artifacts, and register models from your machine
- **Model Registry Guide:** [MODEL_REGISTRY_GUIDE.md](ml-platform/mlflow-server/docs/MODEL_REGISTRY_GUIDE.md) - Native MLflow Model Registry documentation
- **Docker Compose Fix:** [DOCKER_COMPOSE_FIX.md](ml-platform/mlflow-server/docs/DOCKER_COMPOSE_FIX.md) - Troubleshooting ContainerConfig errors

---

## Quick Access Table

| Service | Local | LAN | VPN | Auth |
|---------|-------|-----|-----|------|
| **MLflow UI** | http://localhost/mlflow/ | http://localhost/mlflow/ | http://${TAILSCALE_IP}/mlflow/ | None |
| **Ray Dashboard** | http://localhost/ray/ | http://localhost/ray/ | http://${TAILSCALE_IP}/ray/ | None |
| **Traefik Dashboard** | http://localhost:8090 | http://localhost:8090 | http://${TAILSCALE_IP}:8090 | None |
| **MLflow Grafana** | http://localhost/grafana/ | http://localhost/grafana/ | http://${TAILSCALE_IP}/grafana/ | admin / see secrets |
| **Ray Grafana** | http://localhost/ray-grafana/ | http://localhost/ray-grafana/ | http://${TAILSCALE_IP}/ray-grafana/ | admin / see .env |
| **MLflow Prometheus** | http://localhost/prometheus/ | http://localhost/prometheus/ | http://${TAILSCALE_IP}/prometheus/ | None |
| **Ray Prometheus** | Internal only | Internal only | Internal only | None (not exposed) |
| **Adminer** | http://localhost/adminer/ | http://localhost/adminer/ | http://${TAILSCALE_IP}/adminer/ | See DB creds |
| **Authentik** | http://localhost:9000 | http://localhost:9000 | http://${TAILSCALE_IP}:9000 | See .env |

---

## MLflow Stack

### MLflow UI
- **URL:** /mlflow/
- **Tracking URI (remote clients):** `http://localhost/mlflow`
- **API:** /api/2.0/mlflow/ - See [API_REFERENCE.md](API_REFERENCE.md)
- **AJAX:** /ajax-api/2.0/mlflow/
- **Auth:** None (network-level protection only)
- **Status:** ✓ Working
- **Features:**
  - Native Model Registry (PostgreSQL-backed)
  - Artifact serving via HTTP (--serve-artifacts enabled)
  - Experiment tracking and comparison
  - Model versioning and stage transitions
- **Remote Usage:** See [REMOTE_CLIENT_GUIDE.md](ml-platform/mlflow-server/docs/REMOTE_CLIENT_GUIDE.md)

### MLflow Grafana
- **URL:** /grafana/
- **User:** admin
- **Password:** `AiSolutions2350!` (stored in `ml-platform/mlflow-server/secrets/grafana_password.txt`)
- **Status:** ✓ Working
- **Purpose:** MLflow server metrics, job queue, artifact storage

### MLflow Prometheus
- **URL:** /prometheus/
- **Auth:** None
- **Status:** ✓ Working
- **Purpose:** Metrics storage for Grafana
- **Targets:** mlflow-server:5000/metrics, postgres, redis

### Adminer (Database UI)
- **URL:** /adminer/
- **System:** PostgreSQL
- **Server:** mlflow-postgres
- **User:** mlflow
- **Password:** `cat ml-platform/mlflow-server/secrets/db_password.txt`
- **Database:** mlflow_db
- **Status:** ✓ Working

### PostgreSQL (MLflow)
**No UI - Access via:**

**CLI:**
```bash
# From host
PGPASSWORD=$(cat ml-platform/mlflow-server/secrets/db_password.txt) \
  psql -h localhost -p 5432 -U mlflow -d mlflow_db

# From container
docker exec -it mlflow-postgres psql -U mlflow -d mlflow_db
```

**Adminer (Web UI):** See above

**Monitoring logs:**
```bash
# Real-time logs
docker logs -f mlflow-postgres

# Last 100 lines
docker logs mlflow-postgres --tail 100

# Search for errors
docker logs mlflow-postgres 2>&1 | grep -i error

# Via Grafana: mlflow-grafana dashboard → PostgreSQL panel
```

### Redis (Shared Cache)
**No UI - Access via:**

**CLI:**
```bash
# From host (DB 0 = MLflow)
docker exec -it ml-platform-redis redis-cli -n 0

# From container
docker exec -it ml-platform-redis redis-cli -n 0 KEYS "*"
docker exec -it ml-platform-redis redis-cli -n 0 INFO
```

**Monitoring logs:**
```bash
# Real-time logs
docker logs -f ml-platform-redis

# Memory stats
docker exec ml-platform-redis redis-cli INFO memory

# Via Prometheus: query `redis_memory_used_bytes`
```

### Nginx (MLflow Proxy)
**No UI - Access via:**

**Monitoring logs:**
```bash
# Access logs (requests)
docker logs mlflow-nginx 2>&1 | grep -v "GET /health"

# Error logs only
docker logs mlflow-nginx 2>&1 | grep -i error

# Real-time access log
docker logs -f mlflow-nginx

# Via file (if mounted)
tail -f ml-platform/mlflow-server/logs/nginx/access.log
```

---

## Ray Stack

### Ray Dashboard
- **URL:** /ray/
- **Auth:** None
- **Status:** ✓ Working
- **Purpose:** Cluster monitoring, job submission

### Ray Grafana
- **URL:** /ray-grafana/
- **User:** admin
- **Password:** `AiSolutions2350!`
- **Status:** ✓ Working
- **Purpose:** Ray cluster metrics, GPU utilization, job queue

### Ray Prometheus
- **URL:** Internal only (not exposed externally)
- **Auth:** None
- **Status:** ✓ Running (accessible only within Docker network)
- **Purpose:** Metrics storage for Ray Grafana
- **Targets:** ray-head:8265/metrics, ray-compute-api:8000/metrics
- **Note:** Access via Ray Grafana UI or internal DNS: http://ray-prometheus:9090

### Authentik (OAuth)
- **URL:** http://localhost:9000 (not behind Traefik)
- **User:** admin (bootstrap password in `.env`)
- **Password:** `grep AUTHENTIK_BOOTSTRAP_PASSWORD ml-platform/ray_compute/.env | cut -d= -f2`
- **Status:** ✓ Working
- **Recovery Token:** `docker exec authentik-worker ak create_recovery_key 1 akadmin`
- **Purpose:** OAuth2 provider for Ray Web UI

### PostgreSQL (Ray)
**No UI - Access via:**

**Status:** ✓ Running (healthy)

**CLI:**
```bash
# From host
PGPASSWORD=$(grep POSTGRES_PASSWORD ml-platform/ray_compute/.env | cut -d= -f2) \
  psql -h localhost -p 5433 -U ray_compute -d ray_compute

# From container
docker exec -it ray-compute-db psql -U ray_compute -d ray_compute
```

**Monitoring logs:**
```bash
# Real-time logs
docker logs -f ray-compute-db

# Schema info
docker exec ray-compute-db psql -U ray_compute -d ray_compute -c "\dt"
```

---

## Shared Services

### Traefik Dashboard
- **URL:** http://localhost:8090
- **Auth:** None (internal network only)
- **API:** http://localhost:8090/api
- **Features:**
  - View all routers: /api/http/routers
  - View all services: /api/http/services
  - View all middlewares: /api/http/middlewares
  - Health: /ping

**Monitoring logs:**
```bash
# Real-time logs (all requests)
docker logs -f traefik

# Access logs only
docker logs traefik 2>&1 | grep "entryPointName=web"

# Errors only
docker logs traefik 2>&1 | grep -i error

# Via dashboard: http://localhost:8090 → click service
```

---

## Credentials Summary

**MLflow Stack:**
```bash
# Database
cat ml-platform/mlflow-server/secrets/db_password.txt

# Grafana
cat ml-platform/mlflow-server/secrets/grafana_password.txt
```

**Ray Stack:**
```bash
# All credentials
cat ml-platform/ray_compute/.env | grep -E "(PASSWORD|SECRET|CLIENT_SECRET)"

# Individual
grep POSTGRES_PASSWORD ml-platform/ray_compute/.env
grep GRAFANA_ADMIN_PASSWORD ml-platform/ray_compute/.env
grep AUTHENTIK_SECRET_KEY ml-platform/ray_compute/.env
grep AUTHENTIK_CLIENT_SECRET ml-platform/ray_compute/.env
```

**Security Note:** All credential files are git-ignored (.gitignore covers `secrets/`, `.env`, `*password*.txt`)

---

## Testing Access

```bash
# MLflow
curl http://localhost/mlflow/ | grep MLflow

# MLflow API
curl http://localhost/api/2.0/mlflow/experiments/list

# Ray (when deployed)
curl http://localhost/ray/

# Traefik
curl http://localhost:8090/ping  # Should return "OK"

# MLflow Prometheus
curl http://localhost/prometheus/api/v1/query?query=up

# Grafana (with auth)
curl -u admin:$(cat ml-platform/mlflow-server/secrets/grafana_password.txt) \
  http://localhost/grafana/api/health
```

---

## Log Monitoring Commands

### Quick Log Checks
```bash
# All containers status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# All logs (last 50 lines each)
docker compose -f ml-platform/mlflow-server/docker-compose.yml logs --tail 50

# Specific service
docker logs mlflow-server --tail 100 -f

# Search all for errors
docker compose logs 2>&1 | grep -i "error\|fail\|fatal"

# Follow multiple services
docker logs -f mlflow-server &
docker logs -f mlflow-postgres &
docker logs -f traefik
```

### Service-Specific Log Locations

**MLflow Server:**
```bash
docker logs mlflow-server | grep -E "error|warning"
# Or: ml-platform/mlflow-server/logs/mlflow.log (if mounted)
```

**PostgreSQL:**
```bash
docker logs mlflow-postgres | grep -E "ERROR|FATAL"
# Or: docker exec mlflow-postgres tail -f /var/log/postgresql/postgresql.log
```

**Redis:**
```bash
docker logs ml-platform-redis | grep -E "error|warning"
# Or: docker exec ml-platform-redis redis-cli INFO errorstats
```

**Nginx:**
```bash
# Access log
docker logs mlflow-nginx | grep -v "GET /health"

# Error log
docker logs mlflow-nginx 2>&1 | grep error
```

**Traefik:**
```bash
# All routing
docker logs traefik | grep -E "router|middleware"

# Errors
docker logs traefik 2>&1 | grep -i error
```

### Grafana Monitoring

**MLflow Grafana (when logged in):**
1. Go to http://localhost/grafana/
2. Login: admin / `cat ml-platform/mlflow-server/secrets/grafana_password.txt`
3. Dashboards show:
   - MLflow server metrics
   - PostgreSQL connections
   - Redis memory usage
   - Traefik request rates

**Create log alerts:**
- Explore → Loki (if configured) → Query: `{container_name="mlflow-server"} |= "error"`

---

## Troubleshooting Quick Reference

**Can't access service:**
```bash
# Check if running
docker ps | grep <service>

# Check logs
docker logs <service> --tail 50

# Check network
docker network inspect ml-platform | grep <service>

# Check health
docker inspect <service> | grep -A 10 Health
```

**Database connection issues:**
```bash
# Test from host
PGPASSWORD=$(cat ml-platform/mlflow-server/secrets/db_password.txt) \
  psql -h localhost -U mlflow -d mlflow_db -c "SELECT 1"

# Test from container
docker exec mlflow-server curl http://mlflow-postgres:5432
```

**Redis issues:**
```bash
# Check if responding
docker exec ml-platform-redis redis-cli PING

# Check memory
docker exec ml-platform-redis redis-cli INFO memory | grep used_memory_human

# Check connections
docker exec ml-platform-redis redis-cli CLIENT LIST
```

---

**For API details:** See [API_REFERENCE.md](API_REFERENCE.md)  
**For integration:** See [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)  
**For issues:** See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

**Updated:** 2025-11-22
