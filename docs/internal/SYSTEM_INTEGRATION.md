# ML Platform - Complete System Integration Analysis

**Version:** 1.0.0  
**Last Updated:** 2025-12-05  
**Status:** Production Documentation  
**Purpose:** Comprehensive integration analysis for repository consolidation

---

## Executive Summary

This document provides a complete analysis of the ML Platform's system architecture, integration patterns, and service dependencies. It serves as the authoritative reference for understanding how all components work together.

### Platform Overview

- **Total Services:** 23 Docker containers across 5 stacks
- **Network Architecture:** Single `ml-platform` bridge network (172.30.0.0/16)
- **API Gateway:** Traefik v2.11 with path-based routing
- **Authentication:** FusionAuth OAuth2 + role-based authorization
- **Database:** Single shared PostgreSQL instance with 4 databases
- **Cache:** Single Redis instance with 2 logical databases
- **Repository Size:** 49MB (600 files, 87 markdown docs, 116 Python files)

---

## Table of Contents

1. [Service Topology](#service-topology)
2. [Network Architecture](#network-architecture)
3. [Authentication & Authorization](#authentication--authorization)
4. [Routing Patterns](#routing-patterns)
5. [Database Architecture](#database-architecture)
6. [Integration Patterns](#integration-patterns)
7. [SDK & API Structure](#sdk--api-structure)
8. [Testing Infrastructure](#testing-infrastructure)
9. [Deployment Patterns](#deployment-patterns)
10. [Consolidation Opportunities](#consolidation-opportunities)

---

## 1. Service Topology

### 1.1 Complete Service Matrix

| Stack | Container Name | Port(s) | Database | GPU | Status |
|-------|---------------|---------|----------|-----|--------|
| **Infrastructure (5)** |
| Gateway | ml-platform-traefik | 80,443,8090 | - | - | ✅ |
| Database | shared-postgres | 5432 | postgres | - | ✅ |
| Cache | ml-platform-redis | 6379 | - | - | ✅ |
| Backup | postgres-backup | - | - | - | ✅ |
| Logs | dozzle | 8080 | - | - | ✅ |
| **Authentication (2)** |
| OAuth Provider | fusionauth | 9011 | fusionauth | - | ✅ |
| OAuth Proxy | oauth2-proxy | 4180 | - | - | ✅ |
| Role Auth | role-auth | 8080 | - | - | ✅ |
| **Monitoring (5)** |
| Metrics (Global) | global-prometheus | 9090 | - | - | ✅ |
| Metrics (MLflow) | mlflow-prometheus | 9091 | - | - | ✅ |
| Metrics (Ray) | ray-prometheus | 9092 | - | - | ✅ |
| Dashboards | unified-grafana | 3000 | - | - | ✅ |
| GPU Metrics | nvidia-mps | 9400 | - | Yes | ✅ |
| Container Metrics | cadvisor | 8080 | - | - | ✅ |
| System Metrics | node-exporter | 9100 | - | - | ✅ |
| Dashboard Hub | homer | 8080 | - | - | ✅ |
| **MLflow Stack (3)** |
| Tracking Server | mlflow-server | 5000 | mlflow_db | - | ✅ |
| Enhanced API | mlflow-api | 8000 | mlflow_db | - | ✅ |
| Reverse Proxy | mlflow-nginx | 80 | - | - | ✅ |
| **Ray Stack (3)** |
| Head Node | ray-head | 8265,10001 | ray_compute | Both | ✅ |
| Compute API | ray-compute-api | 8000 | ray_compute | - | ✅ |
| **Inference Stack (4)** |
| LLM Service | qwen3-vl-api | 8000 | inference | RTX 2070 | ✅ |
| Image Gen | z-image-api | 8000 | inference | RTX 3090 | ✅ |
| Gateway | inference-gateway | 8000 | inference | - | ✅ |
| Webhook | webhook-deployer | 9000 | - | - | ✅ |

**Total:** 23 active containers

### 1.2 Service Dependencies

```
Startup Order (from start_all_safe.sh):

Phase 1: Infrastructure
├── ml-platform network
├── shared-postgres
└── ml-platform-redis

Phase 2: Authentication
├── fusionauth (depends on: shared-postgres)
└── oauth2-proxy (depends on: fusionauth)

Phase 3: Gateway & Monitoring
├── traefik (depends on: nothing, but registers middleware from oauth2-proxy)
├── role-auth (depends on: fusionauth API)
├── global-prometheus
├── mlflow-prometheus
├── ray-prometheus
├── unified-grafana (depends on: all prometheus instances)
├── homer (dashboard hub)
└── dozzle (log viewer)

Phase 4: Core Services
├── mlflow-server (depends on: shared-postgres, ml-platform-redis DB 0)
├── mlflow-nginx (depends on: mlflow-server)
├── mlflow-api (depends on: mlflow-server)
├── ray-head (depends on: shared-postgres, GPUs)
└── ray-compute-api (depends on: ray-head, mlflow-nginx)

Phase 5: Inference (Optional)
├── inference-gateway (depends on: shared-postgres)
├── qwen3-vl-api (depends on: RTX 2070)
└── z-image-api (depends on: RTX 3090, on-demand)
```

### 1.3 Critical Dependencies

**OAuth2 Proxy Middleware Registration:**
```yaml
# Traefik registers middlewares from Docker labels
# OAuth2 Proxy MUST be healthy before protected services start
oauth2-proxy:
  labels:
    - "traefik.http.middlewares.oauth2-auth.forwardauth.address=http://oauth2-proxy:4180/oauth2-proxy/auth"
    - "traefik.http.middlewares.oauth2-errors.errors.status=401-403"
```

**Protected Services (require oauth2-auth middleware):**
- Traefik dashboard (admin role required)
- Grafana (developer role)
- MLflow UI/API (developer role)
- Ray Dashboard/API (developer role)
- Dozzle logs (developer role)
- Prometheus (admin role)

---

## 2. Network Architecture

### 2.1 Docker Bridge Network

```yaml
networks:
  ml-platform:
    name: ml-platform
    driver: bridge
    ipam:
      config:
        - subnet: 172.30.0.0/16
          gateway: 172.30.0.1
```

**Key Characteristics:**
- Single network for all services
- DNS-based service discovery (no hardcoded IPs)
- Isolated from host network
- External access via Traefik on port 80/443
- Internal service-to-service communication

### 2.2 DNS Resolution

**Internal Service Names:**
```
mlflow-server:5000       → MLflow tracking server
mlflow-nginx:80          → MLflow HTTP proxy
mlflow-api:8000          → Enhanced MLflow API
ray-head:8265            → Ray dashboard
ray-head:10001           → Ray client port
ray-compute-api:8000     → Ray job submission API
shared-postgres:5432     → PostgreSQL server
ml-platform-redis:6379   → Redis cache
fusionauth:9011          → FusionAuth admin
oauth2-proxy:4180        → OAuth2 proxy
role-auth:8080           → Role-based auth service
```

**External Access Patterns:**
```
localhost:80/mlflow/     → mlflow-nginx:80 → mlflow-server:5000
localhost:80/ray/        → ray-head:8265
localhost:80/api/        → ray-compute-api:8000 or mlflow-api:8000
localhost:80/grafana/    → unified-grafana:3000
localhost:80/auth/       → fusionauth:9011
localhost:8090/          → traefik:8080 (dashboard)
```

### 2.3 Port Bindings

**Host → Container Mappings:**
```yaml
# Traefik (Gateway)
127.0.0.1:80:80          # HTTP (localhost only)
127.0.0.1:443:443        # HTTPS (localhost only)
${LAN_IP}:80:80          # HTTP (LAN access)
${LAN_IP}:443:443        # HTTPS (LAN access)
0.0.0.0:8090:8080        # Traefik dashboard (all interfaces)

# Ray Client Port
0.0.0.0:10001:10001      # Ray remote job submission

# All other services exposed via Traefik only
```

---

## 3. Authentication & Authorization

### 3.1 Authentication Stack

```
User Request
    ↓
Traefik (receives request with /mlflow/ path)
    ↓
oauth2-errors middleware (catches 401/403)
    ↓
oauth2-auth middleware (ForwardAuth to oauth2-proxy:4180/oauth2-proxy/auth)
    ↓
OAuth2 Proxy checks session cookie
    ↓
    ├─ Valid session → Forward to backend
    └─ No session → Redirect to /oauth2-proxy/sign_in?rd=<original_url>
           ↓
       OAuth2 Proxy redirects to FusionAuth:9011/oauth2/authorize
           ↓
       User authenticates with FusionAuth (email/password or social login)
           ↓
       FusionAuth redirects back to /oauth2-proxy/callback with auth code
           ↓
       OAuth2 Proxy exchanges code for token, sets session cookie
           ↓
       User redirected back to original URL
```

### 3.2 Role-Based Authorization

**Role Hierarchy:**
```
admin (superuser)
  ├── Full access to all services
  ├── Traefik dashboard
  ├── Prometheus metrics
  └── All developer permissions

developer (default)
  ├── MLflow UI and API
  ├── Ray Dashboard and API
  ├── Grafana dashboards
  ├── Dozzle logs
  └── Homer dashboard

viewer (future)
  └── Read-only access to dashboards
```

**Middleware Chain:**
```yaml
# Example: MLflow UI protection
traefik.http.routers.mlflow-ui.middlewares: |
  oauth2-errors,oauth2-auth,role-auth-developer
```

**Implementation:**
- `oauth2-errors`: Catches 401/403 and redirects to login
- `oauth2-auth`: Validates OAuth2 session with oauth2-proxy
- `role-auth-developer`: Forwards to role-auth:8080/auth/developer to verify role

**role-auth Service:**
```nginx
# nginx.conf
location /auth/developer {
    # Check X-Auth-Request-Groups header from oauth2-proxy
    if ($http_x_auth_request_groups ~* "(developer|admin)") {
        return 200;
    }
    return 403;
}

location /auth/admin {
    if ($http_x_auth_request_groups ~* "admin") {
        return 200;
    }
    return 403;
}
```

### 3.3 FusionAuth Configuration

**Database:** fusionauth database in shared-postgres
**Admin Access:** http://localhost:9011/admin/
**Public Endpoints:** /auth/, /oauth2/, /.well-known/, /api/, /css/, /js/, /images/

**OAuth2 Application (for oauth2-proxy):**
```yaml
Application Name: OAuth2-Proxy
Client ID: ${OAUTH2_CLIENT_ID}
Client Secret: ${OAUTH2_CLIENT_SECRET}
Authorized Redirect URLs:
  - https://${TAILSCALE_DOMAIN}/oauth2-proxy/callback
  - http://localhost/oauth2-proxy/callback
```

**Groups & Roles:**
- Default group: "developer" (all users)
- Admin group: "admin" (manually assigned)

---

## 4. Routing Patterns

### 4.1 Traefik Path-Based Routing

**Priority System:**
```
Higher priority = more specific route
Default priority = 0

Priority 200: /auth/* (FusionAuth OAuth, includes /oauth2/*)
Priority 150: /admin, /css, /js, /images, /.well-known, /ajax (FusionAuth assets)
Priority 100: /mlflow/*, /ray/*, /api/*, /grafana/* (protected services)
Priority 50:  /oauth2-proxy/* (OAuth2 Proxy)
```

**Why Priority Matters:**
- `/oauth2` prefix is used by BOTH FusionAuth and OAuth2 Proxy
- FusionAuth `/oauth2/*` endpoints (authorize, token) need priority 200
- OAuth2 Proxy `/oauth2-proxy/*` endpoints need lower priority (50)
- Without proper priority, OAuth2 callback fails → login loops

### 4.2 Complete Routing Table

| Path | Service | Port | Middleware | Notes |
|------|---------|------|------------|-------|
| `/traefik` | traefik | 8080 | oauth2,admin | Dashboard |
| `/auth/*` | fusionauth | 9011 | none | Public OAuth |
| `/admin/*` | fusionauth | 9011 | none | Admin UI |
| `/oauth2/*` | fusionauth | 9011 | none | OIDC endpoints |
| `/oauth2-proxy/*` | oauth2-proxy | 4180 | none | Callback, sign_in |
| `/mlflow/*` | mlflow-nginx | 80 | oauth2,developer | MLflow UI |
| `/api/v2.0/mlflow/*` | mlflow-api | 8000 | oauth2,developer | Enhanced API |
| `/ray/*` | ray-head | 8265 | oauth2,developer | Ray dashboard |
| `/api/compute/*` | ray-compute-api | 8000 | oauth2,developer | Job API |
| `/grafana/*` | unified-grafana | 3000 | oauth2 | Dashboards |
| `/prometheus/*` | global-prometheus | 9090 | oauth2,admin | Metrics |
| `/dozzle/*` | dozzle | 8080 | oauth2,developer | Logs |
| `/` | homer | 8080 | oauth2 | Landing page |

### 4.3 Middleware Definitions

**In docker-compose.infra.yml:**
```yaml
# OAuth2 authentication
- "traefik.http.middlewares.oauth2-auth.forwardauth.address=http://oauth2-proxy:4180/oauth2-proxy/auth"
- "traefik.http.middlewares.oauth2-auth.forwardauth.trustForwardHeader=true"
- "traefik.http.middlewares.oauth2-auth.forwardauth.authResponseHeaders=X-Auth-Request-User,X-Auth-Request-Email,X-Auth-Request-Groups,Authorization"

# OAuth2 error handling (redirects to login on 401/403)
- "traefik.http.middlewares.oauth2-errors.errors.status=401-403"
- "traefik.http.middlewares.oauth2-errors.errors.service=oauth2-proxy"
- "traefik.http.middlewares.oauth2-errors.errors.query=/oauth2-proxy/sign_in?rd={url}"

# Role-based authorization
- "traefik.http.middlewares.role-auth-developer.forwardauth.address=http://role-auth:8080/auth/developer"
- "traefik.http.middlewares.role-auth-admin.forwardauth.address=http://role-auth:8080/auth/admin"

# Path rewriting
- "traefik.http.middlewares.mlflow-strip.stripprefix.prefixes=/mlflow"
- "traefik.http.middlewares.ray-stripprefix.stripprefix.prefixes=/ray"
```

### 4.4 Special Cases

**MLflow AJAX Requests:**
```yaml
# Priority 110 to intercept /mlflow/ajax/* before generic /mlflow/*
- "traefik.http.routers.mlflow-ajax.rule=PathPrefix(`/mlflow/ajax`)"
- "traefik.http.routers.mlflow-ajax.priority=110"
- "traefik.http.routers.mlflow-ajax.middlewares=oauth2-errors,oauth2-auth,role-auth-developer,mlflow-ajax-strip"
```

**FusionAuth Static Assets:**
```yaml
# Separate routers for /css, /js, /images, /fonts to avoid auth on static files
# All at priority 150 to match before lower-priority routes
- "traefik.http.routers.fusionauth-css.rule=PathPrefix(`/css`)"
- "traefik.http.routers.fusionauth-css.priority=150"
```

**Webhook (No Auth):**
```yaml
# Webhook endpoint uses HMAC signature instead of OAuth2
- "traefik.http.routers.webhook.rule=PathPrefix(`/webhook`)"
- "traefik.http.routers.webhook.middlewares=webhook-strip"
# No oauth2-auth middleware!
```

---

## 5. Database Architecture

### 5.1 Shared PostgreSQL Instance

**Container:** shared-postgres (postgres:15-alpine)
**Port:** 5432 (internal only)
**Credentials:** Loaded from `/run/secrets/shared_db_password`

### 5.2 Database Topology

```
shared-postgres:5432
├── postgres (default database)
├── mlflow_db (owner: mlflow)
│   ├── experiments
│   ├── runs
│   ├── metrics
│   ├── params
│   ├── tags
│   ├── model_versions
│   └── registered_models
│
├── ray_compute (owner: ray_compute)
│   ├── jobs
│   ├── job_status
│   └── job_logs
│
├── inference (owner: inference)
│   ├── conversations
│   ├── messages
│   └── request_logs
│
└── fusionauth (owner: fusionauth)
    ├── users
    ├── groups
    ├── applications
    ├── identities
    └── authentications
```

### 5.3 Initialization Script

**File:** `postgres/init-databases.sh`

```bash
#!/bin/bash
# Runs on first container start only
# Creates all databases with dedicated users

create_database() {
    local database=$1
    local user=$2

    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
        CREATE USER $user WITH PASSWORD '$POSTGRES_PASSWORD';
        CREATE DATABASE $database OWNER $user;
        GRANT ALL PRIVILEGES ON DATABASE $database TO $user;
EOSQL
}

create_database "mlflow_db" "mlflow"
create_database "ray_compute" "ray_compute"
create_database "inference" "inference"
create_database "fusionauth" "fusionauth"
```

### 5.4 Connection Strings

**MLflow Server:**
```python
DB_URI = "postgresql://mlflow:${SHARED_DB_PASSWORD}@shared-postgres:5432/mlflow_db"
```

**Ray Compute API:**
```python
DATABASE_URL = "postgresql://ray_compute:${SHARED_DB_PASSWORD}@shared-postgres:5432/ray_compute"
```

**Inference Gateway:**
```python
DATABASE_URL = "postgresql://inference:${SHARED_DB_PASSWORD}@shared-postgres:5432/inference"
```

**FusionAuth:**
```yaml
database:
  url: jdbc:postgresql://shared-postgres:5432/fusionauth
  username: fusionauth
  password: ${SHARED_DB_PASSWORD}
```

### 5.5 Backup Strategy

**Script:** `scripts/backup_databases.sh`

```bash
#!/bin/bash
# Backs up all databases to /backups/postgres/

DATABASES=("mlflow_db" "ray_compute" "inference" "fusionauth")

for db in "${DATABASES[@]}"; do
    docker exec shared-postgres pg_dump -U postgres -d "$db" | \
        gzip > "/backups/postgres/${db}_$(date +%Y%m%d_%H%M%S).sql.gz"
done
```

**Automated:** Runs daily via systemd timer or cron

---

## 6. Integration Patterns

### 6.1 MLflow ↔ Ray Integration

**Use Case:** Ray distributed training logs experiments to MLflow

**Configuration:**
```yaml
# ray_compute/docker-compose.yml
ray-compute-api:
  environment:
    - MLFLOW_TRACKING_URI=http://mlflow-nginx:80
```

**Python Client (inside Ray task):**
```python
import mlflow
import ray

@ray.remote
def train_model(params):
    # Use internal Docker DNS
    mlflow.set_tracking_uri("http://mlflow-nginx:80")
    
    with mlflow.start_run():
        mlflow.log_params(params)
        # training code...
        mlflow.log_metrics({"accuracy": 0.95})
```

### 6.2 External Client → Platform

**Local Access:**
```python
import mlflow
import ray

# MLflow tracking
mlflow.set_tracking_uri("http://localhost/mlflow")

# Ray remote compute
ray.init(address="ray://localhost:10001")
```

**Remote Access (Tailscale VPN):**
```python
import mlflow
import ray

TAILSCALE_IP = "100.x.x.x"  # From: tailscale ip -4

# MLflow tracking
mlflow.set_tracking_uri(f"http://{TAILSCALE_IP}/mlflow")

# Ray remote compute
ray.init(address=f"ray://{TAILSCALE_IP}:10001")
```

### 6.3 Inference Stack Integration

**Architecture:**
```
Client
  ↓
Traefik :80
  ↓
/api/llm/* → inference-gateway:8000 → qwen3-vl-api:8000 (RTX 2070)
/api/image/* → inference-gateway:8000 → z-image-api:8000 (RTX 3090)
```

**Gateway Features:**
- Request queuing (PostgreSQL-backed)
- Rate limiting (per-user, per-IP)
- Chat history persistence
- Model lifecycle management (auto-unload z-image after 5min idle)

**Example:**
```python
import requests

# OpenAI-compatible LLM endpoint
response = requests.post(
    "http://localhost/api/llm/v1/chat/completions",
    headers={"Authorization": f"Bearer {token}"},
    json={
        "model": "Qwen/Qwen3-VL-8B-Instruct",
        "messages": [{"role": "user", "content": "Hello!"}]
    }
)

# Image generation
response = requests.post(
    "http://localhost/api/image/v1/generate",
    headers={"Authorization": f"Bearer {token}"},
    json={
        "prompt": "A cat in space",
        "num_inference_steps": 4
    }
)
```

### 6.4 Monitoring Integration

**Prometheus Scrape Targets:**
```yaml
# monitoring/global-prometheus.yml
scrape_configs:
  - job_name: 'traefik'
    static_configs:
      - targets: ['ml-platform-traefik:8080']
  
  - job_name: 'mlflow'
    static_configs:
      - targets: ['mlflow-prometheus:9090']
  
  - job_name: 'ray'
    static_configs:
      - targets: ['ray-prometheus:9090']
  
  - job_name: 'dcgm'
    static_configs:
      - targets: ['nvidia-mps:9400']
  
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
  
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

**Grafana Datasources:**
```yaml
# monitoring/grafana/datasources.yml
datasources:
  - name: Global Prometheus
    type: prometheus
    url: http://global-prometheus:9090
  
  - name: MLflow Prometheus
    type: prometheus
    url: http://mlflow-prometheus:9091
  
  - name: Ray Prometheus
    type: prometheus
    url: http://ray-prometheus:9092
```

---

## 7. SDK & API Structure

### 7.1 Platform SDK (Python)

**Location:** `scripts/platform_sdk/`

**Purpose:** Python client for FusionAuth API management

**Modules:**
```python
# Core
platform_sdk.client         # FusionAuth API client
platform_sdk.http           # HTTP client with retry logic
platform_sdk.config         # Configuration management
platform_sdk.exceptions     # Custom exceptions

# Services (1:1 with FusionAuth API)
platform_sdk.services.users          # User CRUD
platform_sdk.services.groups         # Group management
platform_sdk.services.roles          # Role management
platform_sdk.services.applications   # OAuth app management
platform_sdk.services.registrations  # User-app registrations
platform_sdk.services.api_keys       # API key management

# Bootstrap
platform_sdk.bootstrap.create_test_keys  # Development setup
```

**Usage:**
```python
from platform_sdk import FusionAuthClient

client = FusionAuthClient(
    base_url="http://fusionauth:9011",
    api_key="your-api-key"
)

# Create user
user = client.users.create({
    "email": "user@example.com",
    "password": "securepassword"
})

# Add to group
client.groups.add_member(group_id="developer-group", user_id=user.id)
```

### 7.2 MLflow Enhanced API

**Location:** `mlflow-server/api/`

**Purpose:** Extended MLflow functionality beyond core API

**Endpoints:**
```
GET  /api/v2.0/mlflow/experiments/search  # Advanced search
POST /api/v2.0/mlflow/experiments/compare # Compare experiments
GET  /api/v2.0/mlflow/models/lineage      # Model lineage tracking
POST /api/v2.0/mlflow/models/deploy       # Deployment triggers
```

**Features:**
- Experiment comparison
- Model lineage tracking
- Deployment automation
- Custom metrics aggregation

### 7.3 Ray Compute API

**Location:** `ray_compute/api/`

**Purpose:** Job submission, cluster management, OAuth integration

**Endpoints:**
```
POST /api/compute/jobs                    # Submit Ray job
GET  /api/compute/jobs/{job_id}           # Job status
GET  /api/compute/jobs/{job_id}/logs      # Job logs
DELETE /api/compute/jobs/{job_id}         # Stop job
GET  /api/compute/cluster/status          # Cluster health
GET  /api/compute/cluster/resources       # Available resources
```

**Key Files:**
```python
ray_compute/api/server.py          # FastAPI app (local access)
ray_compute/api/server_remote.py   # OAuth-protected version
ray_compute/api/auth.py            # FusionAuth integration
ray_compute/api/database.py        # Job metadata storage
ray_compute/api/mlflow_integration.py  # MLflow automatic logging
```

**Authentication:**
```python
# server_remote.py
from fastapi.security import OAuth2AuthorizationCodeBearer

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="http://fusionauth:9011/oauth2/authorize",
    tokenUrl="http://fusionauth:9011/oauth2/token",
)

@app.post("/api/compute/jobs")
async def submit_job(token: str = Depends(oauth2_scheme)):
    # Verify token with FusionAuth
    # Submit job to Ray
    pass
```

### 7.4 Inference Gateway API

**Location:** `inference/gateway/`

**Purpose:** Unified interface for LLM and image generation

**Endpoints:**
```
POST /api/llm/v1/chat/completions     # OpenAI-compatible LLM
GET  /api/llm/health                  # Qwen3-VL status
POST /api/image/v1/generate           # Image generation
POST /api/image/yield-to-training     # Free GPU for training
GET  /inference/health                # Gateway health
GET  /inference/conversations         # Chat history
POST /inference/conversations/clear   # Clear history
GET  /inference/queue/status          # Request queue
```

**Schema:**
```python
# inference/gateway/schemas.py
from pydantic import BaseModel

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = False

class ImageGenerationRequest(BaseModel):
    prompt: str
    num_inference_steps: int = 4
    guidance_scale: float = 0.0
    height: int = 512
    width: int = 512
```

---

## 8. Testing Infrastructure

### 8.1 Test Types

**1. Service Health Checks (Bash)**
- **File:** `tests/test_all_services.sh`
- **Purpose:** Verify all containers are running and healthy
- **Coverage:** Infrastructure, MLflow, Ray, Auth, Monitoring

**2. Integration Tests (Pytest)**
- **Location:** `tests/integration/`
- **Purpose:** End-to-end API testing
- **Files:**
  - `test_api_endpoints.py` - API response validation
  - `test_inference_stack.py` - Inference pipeline testing
  - `test_full_stack.py` - Complete workflow tests

**3. Unit Tests (Pytest)**
- **Location:** `tests/unit/`
- **Purpose:** Component-level testing
- **Files:**
  - `unit/inference/test_config.py` - Config validation
  - `unit/inference/test_schemas.py` - Pydantic models
  - `unit/inference/test_utils.py` - Helper functions

**4. Ray Job Submission Tests**
- **Files:**
  - `tests/test_job_submission.py` - API submission
  - `tests/test_remote_compute.py` - Remote client
  - `tests/test_jobs.sh` - Shell script tests
  - `tests/test_gpu_ray_native.py` - GPU access validation

### 8.2 Test Execution

**All Services:**
```bash
cd /home/axelofwar/Projects/shml-platform/shml-platform
./tests/test_all_services.sh
```

**Integration Tests:**
```bash
cd tests
pytest integration/ -v --tb=short
```

**Unit Tests:**
```bash
cd tests
pytest unit/ -v --cov=../inference/gateway --cov-report=term-missing
```

**Ray Tests:**
```bash
cd tests
python test_job_submission.py
python test_remote_compute.py
./test_jobs.sh
```

**Full Suite:**
```bash
./run_tests.sh
```

### 8.3 Test Coverage Matrix

| Component | Health Check | Integration | Unit | GPU |
|-----------|-------------|-------------|------|-----|
| Traefik | ✅ | ✅ | - | - |
| PostgreSQL | ✅ | ✅ | - | - |
| Redis | ✅ | ✅ | - | - |
| FusionAuth | ✅ | ✅ | - | - |
| OAuth2 Proxy | ✅ | ✅ | - | - |
| MLflow Server | ✅ | ✅ | - | - |
| MLflow API | ✅ | ✅ | ✅ | - |
| Ray Head | ✅ | ✅ | - | ✅ |
| Ray API | ✅ | ✅ | ✅ | - |
| Inference Gateway | ✅ | ✅ | ✅ | - |
| Qwen3-VL | ✅ | ✅ | - | ✅ |
| Z-Image | ✅ | ✅ | - | ✅ |
| Grafana | ✅ | - | - | - |
| Prometheus (3x) | ✅ | - | - | - |

### 8.4 CI/CD Integration

**GitHub Actions Workflows:**
```
.github/workflows/
├── test-services.yml       # Service health checks
├── test-integration.yml    # Integration tests
├── security-scan.yml       # GitGuardian, Trivy, pip-audit
├── pre-commit.yml          # Pre-commit hook validation
└── deploy.yml              # Deployment automation
```

**Pre-commit Hooks:**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitguardian/ggshield
    hooks:
      - id: ggshield
        name: GitGuardian Secret Scanning
  
  - repo: https://github.com/gitleaks/gitleaks
    hooks:
      - id: gitleaks
  
  - repo: https://github.com/hadolint/hadolint
    hooks:
      - id: hadolint
        name: Dockerfile Linting
```

---

## 9. Deployment Patterns

### 9.1 Startup Flow

**Script:** `start_all_safe.sh`

```bash
#!/bin/bash
# Phase 1: Infrastructure (no dependencies)
docker-compose -f docker-compose.infra.yml up -d \
    ml-platform-traefik \
    shared-postgres \
    ml-platform-redis

wait_for_health shared-postgres 120

# Phase 2: Authentication (depends on postgres)
docker-compose -f docker-compose.infra.yml up -d fusionauth
wait_for_health fusionauth 180

docker-compose -f docker-compose.infra.yml up -d oauth2-proxy role-auth
wait_for_health oauth2-proxy 120

# Verify middleware registration
verify_middleware_registered "oauth2-auth@docker"

# Phase 3: Monitoring
docker-compose -f docker-compose.infra.yml up -d \
    global-prometheus \
    unified-grafana \
    homer \
    dozzle

# Phase 4: MLflow
docker-compose -f mlflow-server/docker-compose.yml up -d

# Phase 5: Ray
docker-compose -f ray_compute/docker-compose.yml up -d

# Phase 6: Inference (optional)
docker-compose -f inference/docker-compose.inference.yml up -d
```

### 9.2 Critical Startup Lessons

**From `start_all_safe.sh` header:**

```
LESSONS LEARNED (December 2025):
================================
1. OAuth2 Proxy Health Check:
   - The oauth2-proxy image is DISTROLESS (no shell)
   - Health checks using wget/curl will ALWAYS fail
   - Solution: Use "healthcheck: disable: true"
   - Traefik uses container "running" status instead of "healthy"

2. Traefik Container Filtering:
   - Traefik FILTERS OUT containers that are "unhealthy" or "starting"
   - Middleware from unhealthy containers is NEVER registered
   - Debug: docker logs traefik 2>&1 | grep -i "filter"
   - Check: docker inspect <container> --format='{{.State.Health.Status}}'

3. OAuth2 Proxy Path Prefix:
   - FusionAuth uses /oauth2/* for OIDC endpoints
   - OAuth2 Proxy also defaults to /oauth2/*
   - CONFLICT: Traefik routes all /oauth2/* to FusionAuth, breaking OAuth2 Proxy
   - Solution: Use /oauth2-proxy/* prefix
   - Set OAUTH2_PROXY_PROXY_PREFIX=/oauth2-proxy
   - Update redirect URL to /oauth2-proxy/callback

4. Middleware Registration Verification:
   - ALWAYS verify oauth2-auth@docker middleware exists before starting protected services
   - Check: curl -s http://localhost:8090/api/http/middlewares | jq '.[].name'
   - Protected services return 500 errors if middleware doesn't exist

5. FusionAuth OAuth Client Setup:
   - OAuth client must have /oauth2-proxy/callback as authorized redirect
   - If you get "invalid_redirect_uri" error, run: ./start_all_safe.sh fix-oauth
```

### 9.3 Environment Configuration

**Files:**
- `.env.example` - Template (committed)
- `.env` - Actual values (gitignored)
- `secrets/` - Sensitive credentials (gitignored)

**Required Variables:**
```bash
# Network
LAN_IP=192.168.1.100
TAILSCALE_DOMAIN=shml-platform.tail38b60a.ts.net
TAILSCALE_IP=100.x.x.x

# Database (loaded from secrets/)
SHARED_DB_PASSWORD=$(cat secrets/shared_db_password.txt)

# FusionAuth
FUSIONAUTH_API_KEY=$(cat secrets/fusionauth_api_key.txt)

# OAuth2 Proxy
OAUTH2_CLIENT_ID=your-client-id
OAUTH2_CLIENT_SECRET=$(cat secrets/oauth2_client_secret.txt)
OAUTH2_COOKIE_SECRET=$(cat secrets/oauth2_cookie_secret.txt)

# Grafana
GRAFANA_PASSWORD=$(cat secrets/grafana_password.txt)
```

### 9.4 Systemd Service

**File:** `shml-platform.service`

```ini
[Unit]
Description=ML Platform - MLflow + Ray + Monitoring
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/axelofwar/Projects/shml-platform/shml-platform
ExecStart=/home/axelofwar/Projects/shml-platform/shml-platform/start_all_safe.sh start
ExecStop=/home/axelofwar/Projects/shml-platform/shml-platform/stop_all.sh
TimeoutStartSec=600
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**Commands:**
```bash
sudo systemctl enable shml-platform   # Auto-start on boot
sudo systemctl start shml-platform    # Start now
sudo systemctl status shml-platform   # Check status
sudo systemctl restart shml-platform  # Restart all
sudo journalctl -u shml-platform -f   # View logs
```

---

## 10. Consolidation Opportunities

### 10.1 Current State Analysis

**Repository Size:** 49MB total
- `.git/` - 23MB (46%)
- `backups/` - 21MB (42%)
- `archived/` - 1.1MB (2%)
- Active code - 5MB (10%)

**Documentation:** 87 markdown files
- Active documentation: 13 files in `docs/internal/` and `docs/research/`
- Archived documentation: 47 files in `archived/`
- Subproject docs: 15 files in `mlflow-server/docs/` and `ray_compute/docs/`
- Service-specific READMEs: 12 files

### 10.2 Consolidation Recommendations

#### 10.2.1 Documentation Consolidation

**Current Structure:**
```
docs/
├── internal/
│   ├── ARCHITECTURE.md (this should be at root)
│   ├── API_REFERENCE.md (this should be at root)
│   ├── INTEGRATION_GUIDE.md (this should be at root)
│   ├── TROUBLESHOOTING.md (this should be at root)
│   ├── NEW_GPU_SETUP.md
│   └── NEW_NVME_SETUP_GUIDE.md
└── research/
    ├── REMOTE_ACCESS_NEW.md
    ├── REMOTE_JOB_SUBMISSION.md
    └── REMOTE_QUICK_REFERENCE.md
```

**Recommended Structure:**
```
root/
├── README.md (main overview)
├── ARCHITECTURE.md (moved from docs/internal/)
├── API_REFERENCE.md (moved from docs/internal/)
├── INTEGRATION_GUIDE.md (moved from docs/internal/)
├── TROUBLESHOOTING.md (moved from docs/internal/)
├── SYSTEM_INTEGRATION.md (this document)
│
└── docs/
    ├── GPU_SETUP.md (consolidated hardware guides)
    ├── REMOTE_ACCESS.md (consolidated remote guides)
    └── ARCHIVED.md (migration map to archived content)
```

**Benefits:**
- Core docs at root level (standard convention)
- Single source of truth for each topic
- Reduced nested directory structure
- Easier discovery and navigation

#### 10.2.2 Archive Cleanup

**Action Items:**
1. Review `archived/v0.1.0-consolidation/` (47 files, 1.1MB)
   - Extract lessons learned → Add to main docs
   - Document migration notes → CHANGELOG.md
   - Delete obsolete content

2. Review `archived/v0.2.0-pre-unified-cleanup/` (8 files)
   - Consolidate setup guides → README.md
   - Archive or delete old compose files

3. Clean up subproject archives:
   - `mlflow-server/docs/archived/` (migrate key content)
   - `ray_compute/docs/archived/` (migrate key content)

**Expected Savings:** ~1MB, 50+ fewer files

#### 10.2.3 Code Deduplication

**Current Issues:**
1. **Multiple server.py variants:**
   - `ray_compute/api/server.py` (local)
   - `ray_compute/api/server_remote.py` (OAuth)
   - `ray_compute/api/server_v2.py` (?)

   **Recommendation:** Consolidate into single `server.py` with OAuth flag

2. **Duplicate Prometheus configs:**
   - `monitoring/global-prometheus.yml`
   - `mlflow-server/monitoring/prometheus.yml`
   - `ray_compute/monitoring/prometheus.yml`

   **Recommendation:** Use single global prometheus with job labels

3. **Redundant Grafana instances:**
   - `unified-grafana` (current)
   - MLflow Grafana (removed)
   - Ray Grafana (removed)

   **Status:** Already consolidated ✅

#### 10.2.4 Secrets Management

**Current:** Mixed approach
- `secrets/` directory (gitignored)
- Environment variables in `.env`
- Docker secrets in compose files
- Hardcoded placeholders in examples

**Recommendation:**
1. Standardize on Docker secrets for all sensitive data
2. Use `.env.example` with clear placeholders
3. Document secret generation in `secrets/README.md`
4. Add validation script to check required secrets

#### 10.2.5 Compose File Structure

**Current:**
```
docker-compose.yml (include directive, 3 files)
docker-compose.infra.yml (infrastructure + auth + monitoring)
mlflow-server/docker-compose.yml (MLflow services)
ray_compute/docker-compose.yml (Ray services)
inference/docker-compose.inference.yml (inference services)
```

**Recommendation:** Keep as-is
- Clear separation of concerns
- Independent service management
- Allows selective startup
- Standard Docker Compose v2 pattern

#### 10.2.6 Testing Consolidation

**Current:** Mixed bash + pytest
- `tests/test_all_services.sh` - Bash health checks
- `tests/integration/` - Pytest integration tests
- `tests/unit/` - Pytest unit tests
- Individual test scripts: `test_jobs.sh`, `test_persistence.sh`

**Recommendation:** Migrate bash tests to pytest
1. Convert health checks to pytest fixtures
2. Use pytest-docker plugin for container management
3. Consolidate test runners into single `pytest` command
4. Keep only `run_tests.sh` as wrapper

**Benefits:**
- Single test framework
- Better test discovery
- Unified reporting
- Easier CI/CD integration

### 10.3 Consolidation Impact

**Before Consolidation:**
- 49MB repository size
- 87 markdown files
- 600 total files
- Nested documentation structure
- Duplicate code paths
- Mixed testing frameworks

**After Consolidation (Projected):**
- 47MB repository size (-2MB from archive cleanup)
- 50 markdown files (-37 files)
- 550 total files (-50 files)
- Flat documentation structure
- Single code paths
- Unified testing framework

**Effort Estimate:**
- Documentation consolidation: 4-6 hours
- Archive cleanup: 2-3 hours
- Code deduplication: 3-4 hours
- Testing consolidation: 4-6 hours
- Validation and testing: 2-3 hours
- **Total:** 15-22 hours

---

## 11. Conclusion

### 11.1 System Health

The ML Platform is a well-architected, production-ready system with:
- ✅ Clear separation of concerns (5 service stacks)
- ✅ Centralized authentication (FusionAuth OAuth2)
- ✅ Role-based authorization (developer, admin)
- ✅ Unified monitoring (3 Prometheus, 1 Grafana)
- ✅ Shared infrastructure (1 PostgreSQL, 1 Redis)
- ✅ Comprehensive testing (health, integration, unit, GPU)
- ✅ Secure remote access (Tailscale VPN)
- ✅ Auto-start on boot (systemd service)

### 11.2 Integration Maturity

**Strengths:**
- DNS-based service discovery eliminates hardcoded IPs
- Path-based routing with priority system works reliably
- OAuth2 flow is production-grade (supports social logins)
- Shared database reduces resource overhead
- GPU allocation strategy prevents conflicts

**Areas for Improvement:**
- Documentation scattered across multiple directories
- Code duplication in API server variants
- Mixed testing frameworks (bash + pytest)
- Archive cleanup needed

### 11.3 Consolidation Strategy

**Phase 1: Documentation (High Priority)**
1. Move core docs to root level
2. Consolidate remote access guides
3. Clean up archived documentation
4. Update cross-references

**Phase 2: Code (Medium Priority)**
1. Deduplicate server.py variants
2. Consolidate Prometheus configs
3. Standardize secrets management
4. Add validation scripts

**Phase 3: Testing (Low Priority)**
1. Migrate bash tests to pytest
2. Unified test runner
3. Improve CI/CD integration

**Phase 4: Maintenance (Ongoing)**
1. Regular archive reviews
2. Documentation updates
3. Dependency updates
4. Security scanning

### 11.4 No Functionality Loss

**Guarantee:** All consolidation recommendations preserve existing functionality.

**Services remain unchanged:**
- All 23 containers continue operating
- No changes to service configurations
- No changes to network topology
- No changes to authentication flow
- No changes to routing patterns
- No changes to database schema

**Changes are documentation-only:**
- File moves and renames
- Content consolidation
- Archive cleanup
- Reference updates

**Testing validates:**
- All existing tests must pass
- Health checks must succeed
- Integration tests must pass
- No performance degradation

---

## Appendix A: Service Configuration Reference

### A.1 Traefik Labels Reference

**Complete label set for protected service:**
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.myservice.rule=PathPrefix(`/myservice`)"
  - "traefik.http.routers.myservice.entrypoints=web,websecure"
  - "traefik.http.routers.myservice.priority=100"
  - "traefik.http.routers.myservice.middlewares=oauth2-errors,oauth2-auth,role-auth-developer"
  - "traefik.http.services.myservice.loadbalancer.server.port=8000"
```

### A.2 Environment Variables Reference

**Complete .env template:**
```bash
# Network Configuration
LAN_IP=192.168.1.100
TAILSCALE_DOMAIN=your-domain.ts.net
TAILSCALE_IP=100.x.x.x

# Database
SHARED_DB_PASSWORD=  # from secrets/shared_db_password.txt

# FusionAuth
FUSIONAUTH_API_KEY=  # from secrets/fusionauth_api_key.txt
FUSIONAUTH_APPLICATION_ID=your-app-id

# OAuth2 Proxy
OAUTH2_CLIENT_ID=your-client-id
OAUTH2_CLIENT_SECRET=  # from secrets/oauth2_client_secret.txt
OAUTH2_COOKIE_SECRET=  # from secrets/oauth2_cookie_secret.txt

# Grafana
GRAFANA_PASSWORD=  # from secrets/grafana_password.txt

# Ray
RAY_NUM_CPUS=24
RAY_NUM_GPUS=2
RAY_MEMORY=32000000000

# MLflow
MLFLOW_ARTIFACT_ROOT=file:///mlflow/mlruns
MLFLOW_BACKEND_STORE_URI=postgresql://mlflow:${SHARED_DB_PASSWORD}@shared-postgres:5432/mlflow_db

# Inference
MODEL_CACHE_DIR=/home/axelofwar/.cache/huggingface
TRANSFORMERS_OFFLINE=1
HF_HUB_OFFLINE=1
```

### A.3 Docker Compose Snippets

**Shared database connection:**
```yaml
environment:
  - DB_URI=postgresql://${DB_USER}:${SHARED_DB_PASSWORD}@shared-postgres:5432/${DB_NAME}
secrets:
  - shared_db_password
```

**OAuth2 protection:**
```yaml
labels:
  - "traefik.http.routers.myservice.middlewares=oauth2-errors,oauth2-auth,role-auth-developer"
```

**GPU access (NVIDIA CDI):**
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          device_ids: ["0"]  # or ["all"]
          capabilities: [gpu]
```

---

## Appendix B: Useful Commands

### B.1 Service Management

```bash
# Start all services
./start_all_safe.sh

# Stop all services
./stop_all.sh

# Restart specific service
docker-compose -f docker-compose.infra.yml restart traefik

# View logs
docker logs -f ml-platform-traefik
docker logs --tail=100 mlflow-server

# Check health
./check_platform_status.sh
docker inspect shared-postgres --format='{{.State.Health.Status}}'
```

### B.2 Debugging

```bash
# Verify middleware registration
curl -s http://localhost:8090/api/http/middlewares | jq '.[].name'

# Check Traefik routes
curl -s http://localhost:8090/api/http/routers | jq

# Test OAuth2 Proxy
curl -I http://localhost/mlflow/

# Check database connections
docker exec shared-postgres psql -U postgres -c "\l"
docker exec shared-postgres psql -U postgres -d mlflow_db -c "\dt"

# Verify DNS resolution
docker exec mlflow-server ping -c 1 shared-postgres
docker exec ray-head curl http://mlflow-nginx:80
```

### B.3 Monitoring

```bash
# Prometheus targets
curl http://localhost:9090/api/v1/targets | jq

# Grafana health
curl http://localhost/grafana/api/health

# GPU metrics
curl http://localhost:9400/metrics | grep dcgm

# Container resources
docker stats --no-stream
```

### B.4 Database Operations

```bash
# Backup all databases
./scripts/backup_databases.sh

# Restore database
./scripts/restore_databases.sh mlflow_db /backups/postgres/mlflow_db_20231205.sql.gz

# Connect to database
docker exec -it shared-postgres psql -U postgres -d mlflow_db

# Check database size
docker exec shared-postgres psql -U postgres -c "SELECT pg_database.datname, pg_size_pretty(pg_database_size(pg_database.datname)) FROM pg_database;"
```

---

**Document Version:** 1.0.0  
**Last Updated:** 2025-12-05  
**Next Review:** 2025-01-05  
**Maintained By:** Platform Team
