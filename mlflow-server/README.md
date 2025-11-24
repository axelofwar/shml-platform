# MLflow Tracking Server

Production MLflow deployment with PostgreSQL, Traefik gateway, automated backups, VPN access.

---

## Quick Start

### Prerequisites

```bash
# Docker 24.0+, Compose 2.20+
docker --version
docker compose version

# User in docker group
groups | grep docker
```

### Deploy (5 minutes)

```bash
cd mlflow-server

# Deploy all services
./scripts/deploy.sh

# Check status
./scripts/check_status.sh
```

**Access:** http://localhost/mlflow/ or http://localhost/mlflow/

---

## What's Included

**Services:**
- MLflow 2.17.2 (tracking server + model registry)
- PostgreSQL 15 (metadata backend)
- Nginx (reverse proxy, 2.5GB upload limit)
- Redis (shared cache, DB 0)
- Grafana + Prometheus (monitoring)
- Adminer (database UI)
- Automated backups (daily 2 AM, 90-day retention)

**Network:**
- Traefik gateway on port 80/8090
- Path routing: /mlflow/* → mlflow-nginx:80
- Internal: ml-platform network (172.30.0.0/16)

**Pre-configured Experiments:**
- production-models (ID 1) - Schema: requires approval
- staging-models (ID 2) - Schema: requires testing
- development-models (ID 3) - Schema: requires validation
- dataset-registry (ID 4) - Schema: requires schema validation
- model-registry-experiments (ID 5)

---

## Access

### Local (on server)

```bash
curl http://localhost/mlflow/
```

```python
import mlflow
mlflow.set_tracking_uri("http://localhost/mlflow/")
```

### LAN (${SERVER_IP})

```bash
curl http://localhost/mlflow/
```

```python
mlflow.set_tracking_uri("http://localhost/mlflow/")
```

### VPN (Tailscale: ${TAILSCALE_IP})

```bash
curl http://${TAILSCALE_IP}/mlflow/
```

```python
mlflow.set_tracking_uri("http://${TAILSCALE_IP}/mlflow/")
```

---

## Usage Examples

### Log Experiment

```python
import mlflow

mlflow.set_tracking_uri("http://localhost/mlflow/")

with mlflow.start_run(experiment_id="3"):
    mlflow.set_tags({
        "developer": "your_name",
        "model_type": "classification",
        "algorithm": "random_forest",
        "requires_validation": "true"
    })
    mlflow.log_params({"n_estimators": 100})
    mlflow.log_metrics({"accuracy": 0.95})
```

### Register Model

```python
# Train and log model
with mlflow.start_run():
    model = train_model(X, y)
    mlflow.sklearn.log_model(model, "model")
    run_id = mlflow.active_run().info.run_id

# Register
result = mlflow.register_model(
    f"runs:/{run_id}/model",
    "my-model"
)

# Promote to production
client = mlflow.MlflowClient()
client.transition_model_version_stage(
    name="my-model",
    version=1,
    stage="Production"
)
```

### Log Dataset

```python
import pandas as pd

df = pd.read_csv("data.csv")
dataset = mlflow.data.from_pandas(df, source="data.csv", name="training_v1")

with mlflow.start_run(experiment_id="4"):
    mlflow.log_input(dataset, context="training")
    mlflow.set_tags({
        "dataset_name": "user_activity",
        "dataset_version": "v1.0",
        "requires_schema": "true",
        "schema_validated": "true",
        "schema_hash": hashlib.sha256(df.dtypes.to_json().encode()).hexdigest()
    })
```

---

## REST API

**Base URL:** http://localhost/api/2.0/mlflow/

### Experiments

```bash
# Create
curl -X POST http://localhost/api/2.0/mlflow/experiments/create \
  -H "Content-Type: application/json" \
  -d '{"name": "my-experiment"}'

# List
curl -X POST http://localhost/api/2.0/mlflow/experiments/search \
  -H "Content-Type: application/json" \
  -d '{"max_results": 10}'
```

### Runs

```bash
# Create run
curl -X POST http://localhost/api/2.0/mlflow/runs/create \
  -H "Content-Type: application/json" \
  -d '{"experiment_id": "1"}'

# Log metric
curl -X POST http://localhost/api/2.0/mlflow/runs/log-metric \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "<run_id>",
    "key": "accuracy",
    "value": 0.95,
    "timestamp": 1700000000000
  }'
```

**Full API:** See [/Projects/API_REFERENCE.md](/Projects/API_REFERENCE.md)

---

## Management

### Service Control

```bash
# Status
docker compose ps

# Restart service
docker compose restart mlflow

# Restart all
docker compose restart

# Stop all
docker compose down

# View logs
docker compose logs -f mlflow
docker compose logs -f nginx
```

### Database

```bash
# Show credentials
./scripts/show_credentials.sh

# Database info
./scripts/db_info.sh

# Adminer web UI
open http://localhost/mlflow-adminer/
# System: PostgreSQL
# Server: mlflow-postgres
# User: mlflow
# Password: secrets/db_password.txt
# Database: mlflow_db

# CLI access
PGPASSWORD=$(cat secrets/db_password.txt) \
  psql -h localhost -U mlflow -d mlflow_db
```

### Backups

```bash
# Manual backup
docker compose exec mlflow-backup /backup.sh

# List backups
ls -lh backups/postgres/
ls -lh backups/artifacts/

# Restore database
gunzip -c backups/postgres/mlflow_backup_20251122.sql.gz | \
  docker exec -i mlflow-postgres psql -U mlflow -d mlflow_db

# Restore artifacts
cp -r backups/artifacts/20251122/* data/mlflow/artifacts/
```

**Schedule:** Daily 2 AM, 90-day retention

### Monitoring

```bash
# Grafana
open http://localhost/mlflow-grafana/
# Username: admin
# Password: secrets/grafana_password.txt

# Prometheus
open http://localhost/mlflow-prometheus/

# Metrics endpoint
curl http://mlflow-server:5000/metrics
```

---

## Data Persistence

```
./data/
├── postgres/        # Database files
├── mlflow/
│   ├── artifacts/   # Model artifacts, datasets
│   └── mlruns/      # Legacy run data
├── redis/           # Cache
├── prometheus/      # Metrics history
└── grafana/         # Dashboards

./backups/
├── postgres/        # Daily DB dumps (2 AM)
└── artifacts/       # Artifact snapshots

./logs/
├── mlflow/          # Server logs
└── nginx/           # Access & error logs

./secrets/
├── db_password.txt       # PostgreSQL password
└── grafana_password.txt  # Grafana admin password
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check ports
sudo netstat -tulpn | grep -E ':(80|5000|5432)'

# Stop conflicts
sudo systemctl stop nginx apache2 postgresql

# Restart
docker compose down
docker compose up -d
```

### Database Connection Failed

```bash
# Check PostgreSQL
docker exec mlflow-postgres pg_isready

# Test connection
PGPASSWORD=$(cat secrets/db_password.txt) \
  psql -h localhost -U mlflow -d mlflow_db -c '\dt'

# Check logs
docker logs mlflow-postgres --tail 50
```

### Can't Access UI

```bash
# Check Traefik
curl http://localhost:8090/ping

# Check routing
curl -v http://localhost/mlflow/

# Check firewall
sudo ufw status | grep 80

# Restart
docker restart traefik mlflow-nginx mlflow-server
```

### Large Upload Fails

```bash
# Check Nginx limit (should be 2.5GB)
docker exec mlflow-nginx grep client_max_body_size /etc/nginx/conf.d/mlflow.conf

# Increase if needed (docker-compose.yml):
# nginx:
#   environment:
#     CLIENT_MAX_BODY_SIZE: 5G
```

**Full Guide:** [/Projects/TROUBLESHOOTING.md](/Projects/TROUBLESHOOTING.md)

---

## Scripts

```bash
./scripts/
├── deploy.sh                # Full deployment
├── check_status.sh          # Health check
├── show_credentials.sh      # Display passwords
├── access_info.sh           # Show all URLs
├── db_info.sh               # Database info
├── mlflow-admin.sh          # Interactive admin menu (15 ops)
├── rebuild_and_start.sh     # Rebuild containers
├── ensure_tailscale.sh      # VPN check
├── test_persistence.sh      # Data persistence test
└── README.md                # Script documentation
```

---

## Configuration

### Environment Variables (.env)

```bash
# Database
POSTGRES_DB=mlflow_db
POSTGRES_USER=mlflow
POSTGRES_PASSWORD=<from secrets/db_password.txt>

# MLflow
MLFLOW_BACKEND_STORE_URI=postgresql://mlflow:${POSTGRES_PASSWORD}@mlflow-postgres:5432/mlflow_db
MLFLOW_DEFAULT_ARTIFACT_ROOT=/mlflow/artifacts

# Redis (shared with Ray)
REDIS_HOST=ml-platform-redis
REDIS_PORT=6379
REDIS_DB=0

# Backups
BACKUP_RETENTION_DAYS=90
```

### Nginx (2.5GB uploads)

```nginx
# docker/nginx/mlflow.conf
client_max_body_size 2560M;
proxy_read_timeout 3600s;
proxy_connect_timeout 3600s;
```

### Traefik Labels

```yaml
labels:
  traefik.http.routers.mlflow.rule: PathPrefix(`/mlflow`)
  traefik.http.routers.mlflow.priority: 100
  traefik.http.middlewares.mlflow-stripprefix.stripprefix.prefixes: /mlflow
```

---

## Security

**Implemented:**
- Network isolation (Docker bridge)
- Environment-based secrets (no hardcoded)
- Tailscale VPN for remote access
- HTTP-only cookies (session management)
- Schema enforcement (experiment validation)

**Credentials:**
- Database: secrets/db_password.txt
- Grafana: secrets/grafana_password.txt
- Adminer: Use database credentials
- Traefik: No auth (internal network only)

**Checklist:**
- [ ] Change default passwords
- [ ] Configure firewall (ufw allow 80/tcp)
- [ ] Enable HTTPS (Traefik + Let's Encrypt)
- [ ] Rotate secrets regularly
- [ ] Monitor access logs
- [ ] Set up rate limiting

---

## Integration

### With Ray Compute

```python
# In Ray task
import mlflow

# Use internal Docker DNS
mlflow.set_tracking_uri("http://mlflow-nginx:80")

@ray.remote
def train_model(data):
    with mlflow.start_run():
        model = train(data)
        mlflow.log_metric("accuracy", 0.95)
    return model
```

**Full Guide:** [/Projects/INTEGRATION_GUIDE.md](/Projects/INTEGRATION_GUIDE.md)

---

## Documentation

**Core Docs:**
- [/Projects/ARCHITECTURE.md](/Projects/ARCHITECTURE.md) - Tool decisions & scaling
- [/Projects/API_REFERENCE.md](/Projects/API_REFERENCE.md) - Complete API specs
- [/Projects/INTEGRATION_GUIDE.md](/Projects/INTEGRATION_GUIDE.md) - MLflow+Ray integration
- [/Projects/CURRENT_DEPLOYMENT.md](/Projects/CURRENT_DEPLOYMENT.md) - Deployment status
- [/Projects/TROUBLESHOOTING.md](/Projects/TROUBLESHOOTING.md) - Common issues

**MLflow Docs:**
- docs/API_USAGE_GUIDE.md - Python client examples
- docs/REMOTE_CLIENT_SETUP.md - Client machine setup
- docs/SECURITY.md - Security best practices
- scripts/README.md - Management script guide

---

## Status

**Version:** MLflow 2.17.2  
**Database:** PostgreSQL 15  
**Network:** ml-platform (shared with Ray)  
**Gateway:** Traefik v2.10  
**Deployment:** ✅ Production Ready  
**Last Updated:** 2025-11-22

**See:** [/Projects/CURRENT_DEPLOYMENT.md](/Projects/CURRENT_DEPLOYMENT.md) for current state
