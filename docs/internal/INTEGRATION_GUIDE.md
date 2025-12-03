# MLflow + Ray Integration Guide

**Last Updated:** 2025-11-22

---

## Overview

Unified ML platform combining MLflow experiment tracking with Ray distributed compute. Single Docker network (`ml-platform`) with Traefik gateway for all services.

---

## Architecture

```
Client → Traefik:80 → Path Router → Services
         |
         ├─ /mlflow/* → mlflow-nginx:80 → mlflow-server:5000
         ├─ /ray/* → ray-head:8265 (not deployed)
         ├─ /api/compute/* → ray-compute-api:8000 (not deployed)
         └─ Internal: ray-compute-api → mlflow-nginx:80 → MLflow
```

**Network:** `ml-platform` (172.30.0.0/16)  
**DNS:** Docker internal resolution  
**Shared:** Redis (DB 0: MLflow, DB 1: Ray)

---

## Network Configuration

### Docker Compose Integration

**ml-platform/mlflow-server/docker-compose.yml:**
```yaml
networks:
  ml-platform:
    name: ml-platform
    driver: bridge
    ipam:
      config:
        - subnet: 172.30.0.0/16
```

**ml-platform/ray_compute/docker-compose.yml:**
```yaml
networks:
  ml-platform:
    external: true  # Join existing network
```

### Service Names (Internal DNS)

| Service | Internal Name | Port | Status |
|---------|--------------|------|--------|
| MLflow API | mlflow-nginx | 80 | ✅ |
| MLflow Server | mlflow-server | 5000 | ✅ |
| Ray Dashboard | ray-head | 8265 | ⏸️ |
| Ray API | ray-compute-api | 8000 | ⏸️ |
| Redis | ml-platform-redis | 6379 | ✅ |
| MLflow DB | mlflow-postgres | 5432 | ✅ |
| Ray DB | ray-compute-db | 5433 | ⏸️ |

---

## Integration Points

### 1. Ray Job → MLflow Logging

**Use Case:** Ray distributed training logs to MLflow

```python
# Inside Ray task
import mlflow

# Use internal Docker DNS
mlflow.set_tracking_uri("http://mlflow-nginx:80")

with mlflow.start_run():
    mlflow.log_params({"n_estimators": 100})
    mlflow.log_metrics({"accuracy": 0.95})
```

**Docker Compose Config (ray-compute-api):**
```yaml
environment:
  MLFLOW_TRACKING_URI: http://mlflow-nginx:80
```

### 2. External Client → MLflow

**Use Case:** Training script on remote machine

```python
import mlflow

# Use LAN or VPN IP
mlflow.set_tracking_uri("http://localhost/mlflow/")
# or
mlflow.set_tracking_uri("http://${TAILSCALE_IP}/mlflow/")
```

**Note:** External clients use Traefik path `/mlflow/`, internal uses direct `mlflow-nginx:80`

### 3. External Client → Ray

**Use Case:** Submit job to Ray cluster (when deployed)

```python
import requests

# Submit job via Traefik
resp = requests.post(
    "http://localhost/api/compute/jobs",
    json={
        "name": "training-job",
        "script": "train.py",
        "gpu_fraction": 0.5
    },
    headers={"Authorization": f"Bearer {token}"}
)
```

---

## Access Patterns

### Local (on server)

```bash
# MLflow
curl http://localhost/mlflow/
mlflow.set_tracking_uri("http://localhost/mlflow/")

# Ray (when deployed)
curl http://localhost/ray/
curl http://localhost/api/compute/health
```

### LAN (${SERVER_IP})

```bash
# MLflow
curl http://localhost/mlflow/
mlflow.set_tracking_uri("http://localhost/mlflow/")

# Ray
curl http://localhost/ray/
curl http://localhost/api/compute/health
```

### VPN (Tailscale: ${TAILSCALE_IP})

```bash
# MLflow
curl http://${TAILSCALE_IP}/mlflow/
mlflow.set_tracking_uri("http://${TAILSCALE_IP}/mlflow/")

# Ray
curl http://${TAILSCALE_IP}/ray/
curl http://${TAILSCALE_IP}/api/compute/health
```

### SSH Tunnel

```bash
ssh -L 8080:localhost:80 user@${SERVER_IP}

# Then access:
curl http://localhost:8080/mlflow/
curl http://localhost:8080/ray/
```

---

## Service Communication Examples

### Verify Network Connectivity

```bash
# Check DNS resolution
docker exec ray-compute-api nslookup mlflow-nginx
# Should return: 172.30.0.x

# Check network
docker exec ray-compute-api ping -c 2 mlflow-nginx

# Check HTTP
docker exec ray-compute-api curl http://mlflow-nginx:80/health
# Should return: {"status":"ok"}
```

### Test MLflow Integration

```bash
# From Ray container
docker exec ray-compute-api python -c "
import mlflow
mlflow.set_tracking_uri('http://mlflow-nginx:80')
print('MLflow version:', mlflow.__version__)
print('Experiments:', len(mlflow.search_experiments()))
"
```

### Test Redis Sharing

```bash
# MLflow cache (DB 0)
docker exec ml-platform-redis redis-cli -n 0 KEYS "*"

# Ray cache (DB 1)
docker exec ml-platform-redis redis-cli -n 1 KEYS "*"
```

---

## Common Workflows

### Workflow 1: Distributed Training with Tracking

```python
# Submit Ray job that logs to MLflow
import ray
import mlflow

@ray.remote
def train_model(data_chunk):
    mlflow.set_tracking_uri("http://mlflow-nginx:80")
    with mlflow.start_run():
        # Training code
        mlflow.log_metric("loss", 0.5)
    return model

# Submit from external client
ray.init(address="http://${TAILSCALE_IP}/ray/")
results = ray.get([train_model.remote(chunk) for chunk in data])
```

### Workflow 2: Artifact Storage

```python
# Ray job stores artifacts, logs metadata to MLflow
import mlflow

mlflow.set_tracking_uri("http://mlflow-nginx:80")

with mlflow.start_run():
    # Train model
    model.fit(X, y)

    # Log to MLflow artifacts
    mlflow.sklearn.log_model(model, "model")
    mlflow.log_artifact("output.csv")
```

### Workflow 3: Model Registry + Ray Serving

```python
# Load model from MLflow, serve via Ray (future)
import mlflow.pyfunc

model_uri = "models:/production-model/latest"
model = mlflow.pyfunc.load_model(model_uri)

# Serve with Ray Serve
from ray import serve
serve.run(model.predict, name="ml-model")
```

---

## Environment Variables

### MLflow Server

```bash
# ml-platform/mlflow-server/.env
POSTGRES_DB=mlflow_db
POSTGRES_USER=mlflow
POSTGRES_PASSWORD=<from secrets/db_password.txt>
MLFLOW_BACKEND_STORE_URI=postgresql://mlflow:${POSTGRES_PASSWORD}@mlflow-postgres:5432/mlflow_db
MLFLOW_DEFAULT_ARTIFACT_ROOT=/mlflow/artifacts
REDIS_HOST=ml-platform-redis
REDIS_PORT=6379
REDIS_DB=0
```

### Ray Compute (when deployed)

```bash
# ml-platform/ray_compute/.env
POSTGRES_DB=ray_compute
POSTGRES_USER=ray_compute
POSTGRES_PASSWORD=<password>
REDIS_HOST=ml-platform-redis
REDIS_PORT=6379
REDIS_DB=1
MLFLOW_TRACKING_URI=http://mlflow-nginx:80
FUSIONAUTH_URL=http://fusionauth:9011
```

---

## Firewall Configuration

### Required Ports (External)

```bash
# Open Traefik gateway
sudo ufw allow 80/tcp comment "Traefik Gateway (MLflow, Ray)"
sudo ufw allow 8090/tcp comment "Traefik Dashboard"

# Optional: Direct FusionAuth (if not behind Traefik)
sudo ufw allow 9011/tcp comment "FusionAuth OAuth"
```

### Internal Only (No Firewall Needed)

- 5000 (mlflow-server) - Internal only
- 8265 (ray-head) - Internal only
- 8000 (ray-compute-api) - Internal only
- 5432 (mlflow-postgres) - Internal only
- 5433 (ray-compute-db) - Internal only
- 6379 (redis) - Internal only

---

## Traefik Configuration

### MLflow Routing

```yaml
# mlflow-nginx labels
traefik.http.routers.mlflow.rule: PathPrefix(`/mlflow`)
traefik.http.routers.mlflow.middlewares: mlflow-stripprefix
traefik.http.middlewares.mlflow-stripprefix.stripprefix.prefixes: /mlflow
traefik.http.routers.mlflow.priority: 100
```

**Result:** `http://localhost/mlflow/` → `mlflow-nginx:80/`

### Ray Routing (when deployed)

```yaml
# ray-head labels
traefik.http.routers.ray.rule: PathPrefix(`/ray`)
traefik.http.routers.ray.middlewares: ray-stripprefix
traefik.http.middlewares.ray-stripprefix.stripprefix.prefixes: /ray
traefik.http.routers.ray.priority: 90

# ray-compute-api labels
traefik.http.routers.ray-api.rule: PathPrefix(`/api/compute`)
traefik.http.routers.ray-api.priority: 110
```

**Result:**
- `http://localhost/ray/` → `ray-head:8265/`
- `http://localhost/api/compute/` → `ray-compute-api:8000/api/compute/`

---

## Monitoring Integration

### Grafana Dashboards

**MLflow Monitoring:**
- URL: http://localhost/mlflow-grafana/
- Datasource: mlflow-prometheus
- Dashboards: MLflow server metrics, job queue, artifact storage

**Ray Monitoring (when deployed):**
- URL: http://localhost/ray-grafana/
- Datasource: ray-prometheus
- Dashboards: Ray cluster metrics, GPU utilization, job queue

### Prometheus Targets

```yaml
# mlflow-prometheus scrape configs
- job_name: 'mlflow'
  static_configs:
    - targets: ['mlflow-server:5000']

# ray-prometheus scrape configs (when deployed)
- job_name: 'ray-cluster'
  static_configs:
    - targets: ['ray-head:8265']

- job_name: 'ray-api'
  static_configs:
    - targets: ['ray-compute-api:8000']
```

---

## Troubleshooting

### "Can't reach MLflow from Ray"

```bash
# 1. Check network
docker network inspect ml-platform | grep ray-compute-api
docker network inspect ml-platform | grep mlflow-nginx

# 2. Check DNS
docker exec ray-compute-api nslookup mlflow-nginx

# 3. Check connectivity
docker exec ray-compute-api curl http://mlflow-nginx:80/health

# 4. Check MLFLOW_TRACKING_URI
docker exec ray-compute-api env | grep MLFLOW
```

**Fix:** Ensure both services on `ml-platform` network

### "External clients can't connect"

```bash
# 1. Check Traefik
curl http://localhost:8090/api/http/routers

# 2. Check firewall
sudo ufw status | grep 80

# 3. Test path routing
curl -v http://localhost/mlflow/
curl -v http://localhost/ray/

# 4. Check logs
docker logs traefik --tail 50
```

### "Tailscale VPN not working"

```bash
# 1. Check Tailscale status
tailscale status

# 2. Check IP
ip addr show tailscale0

# 3. Test connectivity
curl http://${TAILSCALE_IP}/mlflow/

# 4. Restart Tailscale
sudo systemctl restart tailscaled
```

### "Services restarting"

```bash
# 1. Check health
docker ps

# 2. Check logs
docker logs <container> --tail 100

# 3. Check dependencies
docker compose ps

# 4. Restart in order
docker compose down
docker compose up -d traefik
docker compose up -d ml-platform-redis
docker compose up -d mlflow-postgres ray-compute-db
docker compose up -d mlflow-server ray-head
docker compose up -d mlflow-nginx ray-compute-api
```

---

## Security Considerations

### Network Isolation

- ✅ Docker bridge network (no external access to containers)
- ✅ Only Traefik exposes port 80 to host
- ✅ Internal services use container names (no IPs)
- ✅ Tailscale VPN for secure remote access

### Authentication

**MLflow:**
- No built-in auth (network isolation only)
- Access via Traefik (can add middleware)

**Ray Compute (when deployed):**
- OAuth2 via FusionAuth
- JWT tokens for API
- Session cookies (HTTP-only)
- Role-based access (admin, premium, user)

### Secrets Management

```bash
# MLflow
ml-platform/mlflow-server/secrets/db_password.txt
ml-platform/mlflow-server/secrets/grafana_password.txt

# Ray (FusionAuth OAuth credentials)
ml-platform/ray_compute/.env (FUSIONAUTH_RAY_CLIENT_SECRET, etc.)

# Never commit secrets to git
echo "secrets/" >> .gitignore
echo ".env" >> .gitignore
```

---

## Startup Sequence

**Correct order for integration:**

```bash
# 1. Network (auto-created)
docker network create ml-platform

# 2. Gateway
docker compose up -d traefik

# 3. Shared services
docker compose up -d ml-platform-redis

# 4. Databases
docker compose up -d mlflow-postgres ray-compute-db

# 5. Core services
docker compose up -d mlflow-server ray-head

# 6. Frontend/APIs
docker compose up -d mlflow-nginx ray-compute-api

# 7. Monitoring
docker compose up -d mlflow-grafana ray-grafana

# Or use unified script:
./start_all.sh
```

---

## Development Tips

### Test Internal Communication

```bash
# Enter Ray container
docker exec -it ray-compute-api bash

# Test MLflow from inside
python3 << 'EOF'
import mlflow
mlflow.set_tracking_uri("http://mlflow-nginx:80")
print(f"MLflow version: {mlflow.__version__}")
experiments = mlflow.search_experiments()
print(f"Found {len(experiments)} experiments")
EOF
```

### Local Development with Host

```bash
# Add to /etc/hosts
127.0.0.1 mlflow.local
127.0.0.1 ray.local

# Access via custom domains
curl http://mlflow.local/mlflow/
curl http://ray.local/ray/
```

### Debug Traefik Routing

```bash
# Check routers
curl http://localhost:8090/api/http/routers | jq

# Check services
curl http://localhost:8090/api/http/services | jq

# Check middlewares
curl http://localhost:8090/api/http/middlewares | jq
```

---

## Future Enhancements

### Planned Integrations

- [ ] Ray Serve + MLflow model registry
- [ ] Unified authentication (FusionAuth for MLflow too)
- [ ] Shared Loki logs (both stacks)
- [ ] Cross-stack alerts (Prometheus federation)
- [ ] Unified backup strategy

### Scaling Considerations

**Single-host (current):**
- 1 Redis, shared DBs
- Good for <100 concurrent users

**Team scale (10-50 users):**
- Separate Redis per stack
- Load balancer for MLflow
- Ray auto-scaling workers

**Enterprise (100+ users):**
- Kubernetes migration
- Separate clusters per stack
- External Redis/PostgreSQL (managed)
- S3 for artifacts

---

**See Also:**
- [ARCHITECTURE.md](ARCHITECTURE.md) - Tool decisions & scaling
- [API_REFERENCE.md](API_REFERENCE.md) - API specs & examples
- [CURRENT_DEPLOYMENT.md](CURRENT_DEPLOYMENT.md) - Deployment status
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues

**Updated:** 2025-11-22
