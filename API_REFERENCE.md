# API Reference
## ML Platform - Complete API Documentation

**Version:** 2.0 | **Updated:** 2025-11-22

All APIs accessible via unified Traefik gateway at `http://localhost` or `http://${TAILSCALE_IP}` (Tailscale)

---

## Table of Contents

1. [MLflow Tracking API](#mlflow-tracking-api)
2. [Ray Jobs API](#ray-jobs-api)
3. [Ray Compute API](#ray-compute-api)
4. [Traefik API](#traefik-api)
5. [Network Integration](#network-integration)

---

## MLflow Tracking API

**Base URL:** `http://localhost/api/2.0/mlflow`  
**Docs:** [MLflow REST API](https://mlflow.org/docs/latest/rest-api.html)  
**Auth:** None (add in production)

### OpenAPI Schema

```yaml
openapi: 3.0.0
info:
  title: MLflow Tracking API
  version: 2.17.2
servers:
  - url: http://localhost/api/2.0/mlflow
  - url: http://${TAILSCALE_IP}/api/2.0/mlflow
```

### Experiments

#### Create Experiment
```http
POST /experiments/create
Content-Type: application/json

{
  "name": "my-experiment",
  "artifact_location": "/mlflow/artifacts/1",
  "tags": [
    {"key": "project", "value": "ml-platform"},
    {"key": "team", "value": "data-science"}
  ]
}
```

**Response:**
```json
{
  "experiment_id": "1"
}
```

#### Search Experiments
```http
POST /experiments/search
Content-Type: application/json

{
  "max_results": 100,
  "filter": "name LIKE '%experiment%'",
  "order_by": ["creation_time DESC"]
}
```

**Response:**
```json
{
  "experiments": [
    {
      "experiment_id": "1",
      "name": "my-experiment",
      "artifact_location": "/mlflow/artifacts/1",
      "lifecycle_stage": "active",
      "tags": [...]
    }
  ]
}
```

#### Get Experiment
```http
GET /experiments/get?experiment_id=1
```

### Runs

#### Create Run
```http
POST /runs/create
Content-Type: application/json

{
  "experiment_id": "1",
  "start_time": 1700000000000,
  "tags": [
    {"key": "mlflow.user", "value": "user@example.com"},
    {"key": "mlflow.source.type", "value": "LOCAL"}
  ]
}
```

**Response:**
```json
{
  "run": {
    "info": {
      "run_id": "abc123...",
      "experiment_id": "1",
      "status": "RUNNING",
      "start_time": 1700000000000
    },
    "data": {
      "metrics": [],
      "params": [],
      "tags": [...]
    }
  }
}
```

#### Log Metric
```http
POST /runs/log-metric
Content-Type: application/json

{
  "run_id": "abc123",
  "key": "accuracy",
  "value": 0.95,
  "timestamp": 1700000000000,
  "step": 100
}
```

#### Log Parameter
```http
POST /runs/log-parameter
Content-Type: application/json

{
  "run_id": "abc123",
  "key": "learning_rate",
  "value": "0.001"
}
```

#### Search Runs
```http
POST /runs/search
Content-Type: application/json

{
  "experiment_ids": ["1"],
  "filter": "metrics.accuracy > 0.9",
  "max_results": 50,
  "order_by": ["metrics.accuracy DESC"]
}
```

### Models

#### Register Model
```http
POST /registered-models/create
Content-Type: application/json

{
  "name": "my-model",
  "tags": [
    {"key": "task", "value": "classification"}
  ],
  "description": "Production model for classification"
}
```

#### Create Model Version
```http
POST /model-versions/create
Content-Type: application/json

{
  "name": "my-model",
  "source": "runs:/abc123/model",
  "run_id": "abc123"
}
```

#### Transition Model Stage
```http
POST /model-versions/transition-stage
Content-Type: application/json

{
  "name": "my-model",
  "version": "1",
  "stage": "Production",
  "archive_existing_versions": true
}
```

**Stages:** `None`, `Staging`, `Production`, `Archived`

### Python Client

```python
import mlflow

# Configure client
mlflow.set_tracking_uri("http://localhost/api/2.0/mlflow")

# Create experiment
exp_id = mlflow.create_experiment("my-experiment", tags={"team": "ds"})

# Log run
with mlflow.start_run(experiment_id=exp_id):
    mlflow.log_param("alpha", 0.5)
    mlflow.log_metric("rmse", 0.89)
    mlflow.log_artifact("model.pkl")

# Register model
mlflow.register_model("runs:/abc123/model", "my-model")
```

---

## Ray Jobs API

**Base URL:** `http://localhost/ray` (Dashboard)  
**Jobs API:** Built into Ray Dashboard  
**Docs:** [Ray Jobs API](https://docs.ray.io/en/latest/cluster/running-applications/job-submission/index.html)

### Submit Job

```http
POST /api/jobs/
Content-Type: application/json

{
  "entrypoint": "python train.py",
  "runtime_env": {
    "working_dir": "./",
    "pip": ["scikit-learn", "pandas", "mlflow"]
  },
  "metadata": {
    "job_name": "training-job",
    "user": "data-scientist"
  }
}
```

**Response:**
```json
{
  "job_id": "raysubmit_123abc",
  "status": "PENDING"
}
```

### Get Job Status

```http
GET /api/jobs/{job_id}
```

**Response:**
```json
{
  "job_id": "raysubmit_123abc",
  "status": "RUNNING",
  "message": "Job is running",
  "start_time": 1700000000,
  "end_time": null
}
```

**Status Values:** `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `STOPPED`

### Get Job Logs

```http
GET /api/jobs/{job_id}/logs
```

### Stop Job

```http
POST /api/jobs/{job_id}/stop
```

### List Jobs

```http
GET /api/jobs/
```

### Python Client

```python
from ray.job_submission import JobSubmissionClient

# Connect to Ray
client = JobSubmissionClient("http://localhost/ray")

# Submit job
job_id = client.submit_job(
    entrypoint="python train.py",
    runtime_env={
        "working_dir": "./",
        "pip": ["torch", "mlflow"]
    }
)

# Monitor
status = client.get_job_status(job_id)
logs = client.get_job_logs(job_id)

# Stop
client.stop_job(job_id)
```

---

## Ray Compute API

**Base URL:** `http://localhost/api/compute`  
**Custom API:** Ray Compute Platform wrapper  
**Auth:** API Key (if enabled)

### OpenAPI Schema

```yaml
openapi: 3.0.0
info:
  title: Ray Compute API
  version: 1.0.0
servers:
  - url: http://localhost/api/compute
security:
  - ApiKeyAuth: []
```

### Health Check

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "ray_connected": true,
  "mlflow_connected": true,
  "timestamp": "2025-11-22T10:30:00Z"
}
```

### Submit Job

```http
POST /jobs/submit
Content-Type: application/json
X-API-Key: your-api-key

{
  "script": "train.py",
  "args": ["--epochs", "100"],
  "runtime_env": {
    "pip": ["torch", "mlflow"]
  },
  "resources": {
    "num_cpus": 4,
    "num_gpus": 1
  },
  "mlflow_experiment": "my-experiment"
}
```

**Response:**
```json
{
  "job_id": "compute_abc123",
  "ray_job_id": "raysubmit_xyz789",
  "status": "submitted",
  "mlflow_run_id": "def456"
}
```

### Get Job

```http
GET /jobs/{job_id}
X-API-Key: your-api-key
```

**Response:**
```json
{
  "job_id": "compute_abc123",
  "status": "running",
  "ray_job_id": "raysubmit_xyz789",
  "mlflow_run_id": "def456",
  "created_at": "2025-11-22T10:00:00Z",
  "updated_at": "2025-11-22T10:05:00Z",
  "resources": {
    "num_cpus": 4,
    "num_gpus": 1
  }
}
```

### List Jobs

```http
GET /jobs?status=running&limit=50
X-API-Key: your-api-key
```

### Cancel Job

```http
POST /jobs/{job_id}/cancel
X-API-Key: your-api-key
```

### Cluster Status

```http
GET /cluster/status
X-API-Key: your-api-key
```

**Response:**
```json
{
  "nodes": 1,
  "cpus_total": 24,
  "cpus_available": 20,
  "gpus_total": 1,
  "gpus_available": 0,
  "memory_total_gb": 64,
  "memory_available_gb": 32
}
```

### Python Client

```python
import requests

BASE_URL = "http://localhost/api/compute"
API_KEY = "your-api-key"
headers = {"X-API-Key": API_KEY}

# Submit job
resp = requests.post(f"{BASE_URL}/jobs/submit", headers=headers, json={
    "script": "train.py",
    "resources": {"num_gpus": 1},
    "mlflow_experiment": "my-exp"
})
job_id = resp.json()["job_id"]

# Check status
resp = requests.get(f"{BASE_URL}/jobs/{job_id}", headers=headers)
print(resp.json()["status"])

# Cancel
requests.post(f"{BASE_URL}/jobs/{job_id}/cancel", headers=headers)
```

---

## Traefik API

**Base URL:** `http://localhost:8090/api`  
**Dashboard:** `http://localhost:8090`  
**Docs:** [Traefik API](https://doc.traefik.io/traefik/operations/api/)

### List Routers

```http
GET /http/routers
```

**Response:**
```json
[
  {
    "name": "mlflow-api@docker",
    "rule": "PathPrefix(`/api/2.0/mlflow`)",
    "service": "mlflow",
    "priority": 400,
    "status": "enabled"
  },
  {
    "name": "ray-dashboard@docker",
    "rule": "PathPrefix(`/ray`)",
    "service": "ray-dashboard",
    "priority": 100,
    "status": "enabled"
  }
]
```

### List Services

```http
GET /http/services
```

### Health Check

```http
GET /ping
```

**Response:** `OK`

---

## Network Integration

### How Services Communicate

**1. External Client → MLflow**
```
Client → Traefik:80 (/api/2.0/mlflow/*)
  ↓
Traefik routes to mlflow-nginx:80
  ↓
mlflow-nginx proxies to mlflow-server:5000
```

**2. Ray Job → MLflow (Internal)**
```python
# Inside Ray job
import mlflow
mlflow.set_tracking_uri("http://mlflow-nginx:80")  # Docker DNS

with mlflow.start_run():
    mlflow.log_metric("accuracy", 0.95)
```

**3. Ray Compute API → Ray Head**
```python
# ray-compute-api container
RAY_ADDRESS = os.getenv("RAY_ADDRESS")  # http://ray-head:8265

from ray.job_submission import JobSubmissionClient
client = JobSubmissionClient(RAY_ADDRESS)
```

### Configuration Requirements

**ml-platform/ray_compute/.env:**
```bash
# Use Docker service names, not localhost
RAY_ADDRESS=http://ray-head:8265
MLFLOW_TRACKING_URI=http://mlflow-nginx:80
REDIS_HOST=ml-platform-redis
POSTGRES_HOST=ray-compute-db
```

**ml-platform/mlflow-server/docker-compose.yml:**
```yaml
mlflow-server:
  environment:
    MLFLOW_BACKEND_STORE_URI: postgresql://mlflow:${DB_PASSWORD}@mlflow-postgres:5432/mlflow_db
    REDIS_HOST: ml-platform-redis
  networks:
    - ml-platform  # REQUIRED
```

### Troubleshooting API Access

**Test DNS Resolution:**
```bash
docker exec ray-compute-api nslookup mlflow-nginx
# Should return: 172.30.0.x
```

**Test HTTP Connectivity:**
```bash
docker exec ray-compute-api curl http://mlflow-nginx:80/health
# Should return: OK
```

**Test MLflow API:**
```bash
docker exec ray-compute-api curl http://mlflow-nginx:80/api/2.0/mlflow/experiments/search -X POST -H "Content-Type: application/json" -d '{"max_results":1}'
```

### Common Errors

**❌ Connection Refused**
- Service not started
- Wrong port
- Service not on ml-platform network

**❌ Name Resolution Failed**
- Wrong service name
- Not on same network
- Docker DNS issue

**❌ 404 Not Found**
- Wrong path
- Traefik prefix stripping issue
- Check router priorities

---

## Request Examples

### MLflow + Ray Integration

**Complete Workflow:**

```python
import mlflow
import ray
from ray.job_submission import JobSubmissionClient

# Configure
mlflow.set_tracking_uri("http://localhost/api/2.0/mlflow")
ray_client = JobSubmissionClient("http://localhost/ray")

# Create experiment
exp_id = mlflow.create_experiment("distributed-training")

# Submit Ray job that logs to MLflow
job_script = f"""
import mlflow
mlflow.set_tracking_uri("http://mlflow-nginx:80")

with mlflow.start_run(experiment_id="{exp_id}"):
    mlflow.log_param("distributed", True)
    # ... training code ...
    mlflow.log_metric("accuracy", 0.95)
"""

job_id = ray_client.submit_job(
    entrypoint=f"python -c '{job_script}'",
    runtime_env={"pip": ["mlflow"]}
)

# Monitor
status = ray_client.get_job_status(job_id)
logs = ray_client.get_job_logs(job_id)
```

### cURL Examples

**MLflow - Create Experiment:**
```bash
curl -X POST http://localhost/api/2.0/mlflow/experiments/create \
  -H "Content-Type: application/json" \
  -d '{"name":"my-exp","tags":[{"key":"team","value":"ds"}]}'
```

**Ray - Submit Job:**
```bash
curl -X POST http://localhost/ray/api/jobs/ \
  -H "Content-Type: application/json" \
  -d '{
    "entrypoint":"python train.py",
    "runtime_env":{"pip":["torch"]}
  }'
```

**Ray Compute - Health Check:**
```bash
curl http://localhost/api/compute/health
```

---

## Rate Limiting & Quotas

**Current:** No limits (add in production)

**Recommended:**
```yaml
# Traefik rate limiting
- "traefik.http.middlewares.rate-limit.ratelimit.average=100"
- "traefik.http.middlewares.rate-limit.ratelimit.burst=50"
```

---

## Authentication

**Current:** None  
**Production:** Enable API keys

**Ray Compute API:**
```yaml
ray-compute-api:
  environment:
    API_KEY_ENABLED: "true"
    API_SECRET_KEY: "your-secret-key"
```

**Usage:**
```bash
curl -H "X-API-Key: your-secret-key" http://localhost/api/compute/jobs
```

---

## Versioning

| Service | API Version | Stability |
|---------|-------------|-----------|
| MLflow | 2.0 | Stable |
| Ray Jobs | Latest | Stable |
| Ray Compute | 1.0 | Beta |
| Traefik | 2.10 | Stable |

---

**Next:** See [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) for service integration patterns

**Updated:** 2025-11-22
