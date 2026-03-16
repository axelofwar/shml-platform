# Platform Operations

Day-to-day operational procedures for the SHML Platform.

---

## Starting Services

```bash
# Full restart (stop → cleanup → start all)
./start_all_safe.sh

# Start all (assumes clean state)
./start_all_safe.sh start

# Start specific group
./start_all_safe.sh start infra        # Traefik, Postgres, Redis
./start_all_safe.sh start auth         # FusionAuth + OAuth2-Proxy
./start_all_safe.sh start mlflow       # MLflow stack
./start_all_safe.sh start ray          # Ray compute cluster
./start_all_safe.sh start inference    # Coding models + Chat API
./start_all_safe.sh start monitoring   # Prometheus + Grafana
```

---

## Stopping Services

```bash
# Stop everything
./start_all_safe.sh stop

# Stop specific group
./start_all_safe.sh stop inference
./start_all_safe.sh stop ray
```

!!! warning "GPU Services"
    When stopping Ray, the NVIDIA MPS daemon is **not** restarted. If you need MPS for other workloads, start it manually: `sudo nvidia-cuda-mps-control -d`

---

## Health Checks

### Quick Status

```bash
./start_all_safe.sh status
```

### Manual Verification

```bash
# All containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | sort

# Specific service health
docker inspect shml-postgres --format='{{.State.Health.Status}}'

# Traefik middleware registration (critical for auth)
curl -s http://localhost:8090/api/http/middlewares | python3 -m json.tool | grep oauth2

# MLflow health
curl -s http://localhost/mlflow/health

# Ray cluster status
docker exec ray-head ray status
```

### Auth Diagnostics

```bash
# Full auth chain verification
./start_all_safe.sh diagnose

# Check OAuth2-Proxy is routing correctly
curl -s -o /dev/null -w "%{http_code}" http://localhost/mlflow/
# Expected: 302 (redirect to login) or 200 (if authenticated)
```

---

## Log Viewing

### Dozzle (Web UI)

Access at `/logs` — shows real-time logs from all running containers with filtering.

### Command Line

```bash
# Follow specific service logs
docker logs -f mlflow-server --tail 100
docker logs -f ray-head --tail 100

# All platform containers
docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml logs -f --tail 50

# Search for errors
docker logs ray-head 2>&1 | grep -i "error\|exception\|traceback" | tail -20
```

### Loki (if enabled)

Query logs in Grafana → Explore → Loki datasource:

```logql
{container_name="ray-head"} |= "error"
{container_name=~"mlflow.*"} | json | level="ERROR"
```

---

## Upgrading Services

### Single Service

```bash
# 1. Pull new image
docker pull grafana/grafana:10.3.0

# 2. Update version in compose file
# Edit deploy/compose/docker-compose.infra.yml: image: grafana/grafana:10.3.0

# 3. Recreate container
docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d unified-grafana

# 4. Verify health
docker inspect unified-grafana --format='{{.State.Health.Status}}'
```

### Full Platform Update

```bash
# 1. Create backup
./start_all_safe.sh stop
cp -r . ../shml-platform-backup-$(date +%Y%m%d)

# 2. Pull latest code
git pull

# 3. Rebuild custom images
docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml build
docker compose --env-file .env -f ray_compute/deploy/compose/docker-compose.yml build
docker compose --env-file .env -f mlflow-server/deploy/compose/docker-compose.yml build

# 4. Restart
./start_all_safe.sh
```

!!! tip "Zero-Downtime Updates"
    For services behind Traefik, you can update one service at a time. Traefik will stop routing to unhealthy containers and resume when the new one is healthy.

---

## Common Operations

### Clear Redis Cache

```bash
docker exec shml-redis redis-cli FLUSHALL
```

### PostgreSQL Shell

```bash
docker exec -it shml-postgres psql -U postgres
# \l          — list databases
# \c mlflow_db — connect to database
# \dt         — list tables
```

### Restart Single Container

```bash
docker restart shml-traefik
# Or recreate from compose
docker compose --env-file .env -f deploy/compose/docker-compose.infra.yml up -d traefik
```

### Disk Usage

```bash
# Docker volumes
docker system df -v | head -30

# MLflow artifacts
du -sh /mlflow/artifacts/

# PostgreSQL backups
du -sh backups/postgres/
```
