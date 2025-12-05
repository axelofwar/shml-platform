# ML Platform Architecture
## Unified MLflow + Ray Compute

**Version:** 2.1 | **Updated:** 2025-12-05 | **Status:** Production

---

## Related Documentation

**Core Architecture:**
- **[SYSTEM_INTEGRATION.md](SYSTEM_INTEGRATION.md)** - Complete integration analysis (1000+ lines)
- **[SERVICE_DEPENDENCY_MAP.md](SERVICE_DEPENDENCY_MAP.md)** - Visual dependency graphs and startup order
- **[CONSOLIDATION_PLAN.md](CONSOLIDATION_PLAN.md)** - Repository consolidation strategy

**Integration Guides:**
- **[INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)** - Service integration patterns
- **[API_REFERENCE.md](API_REFERENCE.md)** - API documentation
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Common issues and solutions

---

## Executive Summary

**Architecture:** Unified Docker bridge network with Traefik gateway, 23 microservices  
**Key Principle:** Single network, DNS-based discovery, shared infrastructure  
**Access:** Port 80 (HTTP), Port 8090 (Traefik dashboard)

**For complete integration details, see [SYSTEM_INTEGRATION.md](SYSTEM_INTEGRATION.md)**

### Component Matrix

| Stack | Services | Database | Cache | Gateway |
|-------|----------|----------|-------|---------|
| **MLflow** | 8 containers | PostgreSQL 15 | Redis DB 0 | Traefik |
| **Ray** | 5 containers | PostgreSQL 15 | Redis DB 1 | Traefik |
| **Shared** | Redis, Traefik | - | - | - |

---

## Architecture Diagram

```
HOST (Ubuntu)
│
├─ ml-platform network (172.30.0.0/16)
│  │
│  ├─ traefik:80,8090 ◄── EXTERNAL ENTRY POINT
│  │  ├─ /mlflow/* → mlflow-nginx:80
│  │  ├─ /ray/* → ray-head:8265
│  │  └─ /api/* → ray-compute-api:8000
│  │
│  ├─ MLFLOW STACK
│  │  ├─ mlflow-nginx:80 → mlflow-server:5000
│  │  ├─ mlflow-postgres:5432
│  │  ├─ mlflow-prometheus:9090
│  │  ├─ mlflow-grafana:3000
│  │  ├─ mlflow-adminer:8080
│  │  └─ mlflow-backup
│  │
│  ├─ RAY STACK
│  │  ├─ ray-head:8265 (GPU)
│  │  ├─ ray-compute-api:8000
│  │  ├─ ray-postgres:5432
│  │  ├─ ray-prometheus:9090
│  │  └─ ray-grafana:3000
│  │
│  └─ SHARED
│     └─ ml-platform-redis:6379 (DB 0,1)
```

---

## Tool Selection & Rationale

### 1. Traefik API Gateway

**Selected:** Traefik v2.10

**Why:**
- Auto-discovery via Docker labels
- Path-based routing (/mlflow, /ray)
- No config reload needed
- Built-in metrics

**vs Nginx:** Manual config, no auto-discovery  
**vs HAProxy:** Complex setup, no Docker integration  
**vs Envoy:** Overkill, steep curve

**Enterprise Scale:**
- ✅ 10k req/sec with tuning
- ✅ K8s compatible
- ⚠️ Multi-host needs external LB

### 2. Docker Bridge Network

**Selected:** Single ml-platform network (172.30.0.0/16)

**Why:**
- DNS-based discovery (mlflow-server:5000)
- No hardcoded IPs
- Container isolation from host
- Easy service addition

**Config:**
```yaml
networks:
  ml-platform:
    driver: bridge
    ipam:
      config:
        - subnet: 172.30.0.0/16
```

**Enterprise Scale:**
- ✅ Single host: Works perfectly
- ⚠️ Multi-host: Switch to overlay network
- ⚠️ 100+ services: Consider service mesh

### 3. Redis (Shared Cache)

**Selected:** Single Redis 7, separate DBs

**Why:**
- No port conflicts (prev had 2 instances)
- DB isolation (DB 0: MLflow, DB 1: Ray)
- Less memory overhead
- Central cache mgmt

**Config:**
```yaml
REDIS_HOST: ml-platform-redis
REDIS_DB: 0  # MLflow
REDIS_DB: 1  # Ray
```

**Enterprise Scale:**
- ✅ Redis Sentinel: HA failover
- ✅ Redis Cluster: >50GB data
- ⚠️ Massive scale: Memcached/Hazelcast

### 4. PostgreSQL (Separate DBs)

**Selected:** 2 PostgreSQL 15 instances

**Why:**
- Data isolation (MLflow ≠ Ray metadata)
- Independent backup/restore
- Fault isolation
- Different tuning per workload

**Enterprise Scale:**
- ✅ Replication: Primary + replicas
- ✅ Patroni + etcd: Auto-failover
- ✅ Citus: Distributed PostgreSQL
- ⚠️ Consider managed (RDS/CloudSQL)

### 5. NVIDIA MPS (GPU Sharing)

**Selected:** MPS for concurrent GPU access

**Why:**
- Multiple services use GPU simultaneously
- Better utilization
- No code changes
- Transparent to apps

**Config:**
```yaml
environment:
  CUDA_MPS_PIPE_DIRECTORY: /tmp/nvidia-mps
volumes:
  - nvidia-mps:/tmp/nvidia-mps
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
```

**Alternatives:**
- **MIG:** A100/H100 only, hard isolation
- **Time-slicing:** K8s round-robin
- **vGPU:** VM-level sharing

---

## Network Integration Details

### Service Communication Patterns

**External → Internal:**
```
Browser → http://localhost/mlflow/
  ↓
Traefik (PathPrefix=/mlflow, strip prefix)
  ↓
mlflow-nginx:80/
  ↓
mlflow-server:5000/
```

**Internal (Container-to-Container):**
```
ray-compute-api → mlflow-nginx:80          # Log experiments
ray-compute-api → ray-head:8265            # Submit jobs
mlflow-server → mlflow-postgres:5432       # Metadata
ray-compute-api → ml-platform-redis:6379   # Cache
```

### Critical Config Requirements

**1. Use Docker Service Names**
```python
# ✅ CORRECT
MLFLOW_TRACKING_URI = "http://mlflow-nginx:80"
RAY_ADDRESS = "http://ray-head:8265"

# ❌ WRONG
MLFLOW_TRACKING_URI = "http://localhost:8080"
RAY_ADDRESS = "http://localhost:8265"
```

**2. Path Stripping**
```yaml
# Request: /mlflow/experiments
# Traefik strips /mlflow
# Forwards: /experiments to mlflow-nginx:80
- "traefik.http.middlewares.mlflow-strip.stripprefix.prefixes=/mlflow"
```

**3. Router Priority**
```yaml
mlflow-api: PathPrefix(`/api/2.0/mlflow`) priority=400
mlflow-ajax: PathPrefix(`/ajax-api`) priority=350
mlflow-ui: PathPrefix(`/mlflow`) priority=10
```

### Network Troubleshooting

```bash
# Test DNS
docker exec ray-compute-api nslookup mlflow-nginx
# Should return: 172.30.0.x

# Test connectivity
docker exec ray-compute-api ping mlflow-nginx
docker exec ray-compute-api curl http://mlflow-nginx:80/health
```

---

## Scaling Strategy

### Current (Single Host)

**Capacity:**
- Users: <10
- Experiments: <1000/month
- GPU: 1 shared via MPS
- Storage: Local filesystem

**Limitations:**
- Single point of failure
- Vertical scaling only
- Shared GPU overhead
- No geo-distribution

### Team Scale (10-50 users)

**Changes:**

1. **PostgreSQL Replication**
```yaml
mlflow-postgres-replica:
  environment:
    POSTGRES_REPLICATION_MODE: replica
```

2. **Object Storage**
```yaml
MLFLOW_ARTIFACT_ROOT: s3://bucket
```

3. **Redis Sentinel** (HA)

4. **Multiple MLflow Servers** (LB)

**Capacity:**
- 5k-10k experiments/month
- 99.9% uptime
- 50+ concurrent users

### Enterprise (100+ users)

**Architecture:**

1. **Kubernetes** (Helm charts)
2. **Service Mesh** (Istio)
3. **Managed DBs** (RDS/CloudSQL)
4. **Multi-Region** (geo-distributed)
5. **Auto-Scaling** (HPA)

**Capacity:**
- 100k+ experiments/month
- 99.99% uptime
- 1000+ users
- <100ms multi-region latency

**Cost:**
| Scale | Setup | Monthly (AWS) |
|-------|-------|---------------|
| Current | Single host | $500-1k |
| Team | Multi-host | $2k-5k |
| Enterprise | K8s + Multi-region | $15k-50k+ |

---

## Implementation Specifics

### Startup Sequence

**Order (dependency-based):**

```
1. Network: ml-platform
2. Infrastructure: traefik, redis (parallel)
3. Databases: mlflow-postgres, ray-postgres (wait healthy)
4. Core: mlflow-server, ray-head (wait healthy)
5. Frontend: mlflow-nginx, ray-compute-api (wait healthy)
6. Monitoring: prometheus, grafana (parallel)
7. Utils: adminer, backup (parallel)
```

**Why:** Downstream services need upstream healthy first.

### Health Check Strategy

**Critical Services (aggressive):**
```yaml
healthcheck:
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 40s
```

**Monitoring (relaxed):**
```yaml
healthcheck:
  interval: 30s
  timeout: 10s
  retries: 3
```

### Volume Management

**Named Volumes (Docker-managed):**
- mlflow-postgres-data
- mlflow-artifacts
- ray-postgres-data
- redis-data

**Bind Mounts (host filesystem):**
- ./ml-platform/mlflow-server/logs → /mlflow/logs
- ./ml-platform/ray_compute/data → /app/data

**Why Both:**
- Named: Better performance, managed backups
- Bind: Easy host access, version control

### Secret Management

```yaml
secrets:
  mlflow_db_password:
    file: ./ml-platform/mlflow-server/secrets/db_password.txt

mlflow-server:
  secrets:
    - mlflow_db_password
  environment:
    POSTGRES_PASSWORD_FILE: /run/secrets/mlflow_db_password
```

**Security:**
- Not in env vars (visible in docker inspect)
- Not in compose (version controlled)
- Filesystem-based, restricted perms

---

## Security Architecture

### Current Posture

**✅ Implemented:**
- Network isolation (containers)
- Minimal port exposure (80, 8090)
- Database password secrets
- Tailscale VPN for remote
- **OAuth2 Authentication (FusionAuth + OAuth2-Proxy)**
- **Role-Based Access Control (RBAC)**
- **HTTPS via Tailscale Funnel**

**⚠️ Missing:**
- Encryption at rest
- Audit logging

---

## Authentication & Authorization

### OAuth2 Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AUTHENTICATION FLOW                               │
│                                                                      │
│  User Request → Traefik → OAuth2-Proxy ←→ FusionAuth                │
│                    │                           ↑                     │
│                    ↓                    Google/GitHub/Twitter        │
│               Protected Service                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Components:**
- **FusionAuth:** Identity Provider (OAuth2/OIDC)
- **OAuth2-Proxy:** Forward authentication for Traefik
- **role-auth:** Role-based access checker (OpenResty/Lua)

### Role-Based Access Control (RBAC)

**Access Tiers:**

| Role | Default | Services Accessible |
|------|---------|---------------------|
| `viewer` | ✅ Yes | Homer dashboard, Grafana |
| `developer` | No | + MLflow, Ray Dashboard/API, Dozzle logs |
| `admin` | No | + Traefik dashboard, Prometheus, System admin |

**Service Middleware Chains:**

| Access Level | Middleware Chain | Services |
|--------------|------------------|----------|
| **Viewer** | `oauth2-errors,oauth2-auth` | Homer, Grafana |
| **Developer** | `oauth2-errors,oauth2-auth,role-auth-developer` | MLflow, Ray, Dozzle |
| **Admin** | `oauth2-errors,oauth2-auth,role-auth-admin` | Traefik, Prometheus |

### Identity Providers

| Provider | Auto-Registration | Default Role |
|----------|-------------------|--------------|
| **Google** | ✅ OAuth2-Proxy | `viewer` |
| **GitHub** | ✅ OAuth2-Proxy | `viewer` |
| **Twitter** | ❌ Requires admin | - |

### User Management Workflow

**New User (Social Login):**
1. User visits platform → Redirected to FusionAuth login
2. User signs in with Google/GitHub
3. FusionAuth creates user + auto-registers to OAuth2-Proxy with `viewer` role
4. User can access Homer dashboard and Grafana immediately

**Granting Developer Access:**
1. Admin logs into FusionAuth Admin UI (http://localhost:9011 or via Tailscale)
2. Navigate to Users → Find user → Registrations tab
3. Edit OAuth2-Proxy registration → Change role to `developer`
4. User can now access MLflow, Ray, and Dozzle

**Granting Admin Access:**
1. Same as above, but select `admin` role
2. Admin can access all services including Traefik and Prometheus

### Security Architecture

```yaml
# Role-auth service (scripts/role-auth/)
# Validates X-Auth-Request-Groups header from OAuth2-Proxy
Endpoints:
  /auth/viewer:     # Requires viewer, developer, or admin
  /auth/developer:  # Requires developer or admin
  /auth/admin:      # Requires admin only
```

---

### Production Hardening

**1. Enable HTTPS:**
```yaml
traefik:
  command:
    - "--entrypoints.websecure.address=:443"
    - "--certificatesresolvers.le.acme.email=admin@example.com"
```

**2. Basic Auth:**
```yaml
- "traefik.http.middlewares.auth.basicauth.users=user:$$apr1$$..."
```

**3. API Keys:**
```yaml
ray-compute-api:
  environment:
    API_KEY_ENABLED: "true"
```

**4. Firewall:**
```bash
ufw allow from 10.0.0.0/24 to any port 80
ufw allow from 100.64.0.0/10 to any port 80
ufw deny 80
```

---

## Monitoring & Observability

### Metrics

**Prometheus Targets:**
- mlflow-server:5000/metrics
- ray-head:8265/metrics
- traefik:8080/metrics

**Key Metrics:**
- `mlflow_experiments_total`
- `ray_tasks_running`
- `traefik_service_request_duration_seconds`

### Alerting

```yaml
- alert: MLflowDown
  expr: up{job="mlflow"} == 0
  for: 2m

- alert: RayHighMemory
  expr: ray_object_store_memory > 0.9
  for: 5m
```

---

## Backup & DR

### Automated Backups

**Schedule:** Daily 2 AM  
**Retention:** 90 days  
**Includes:** PostgreSQL, artifacts, configs

```bash
./backups/
├── postgres/mlflow_db_20251122.sql.gz
├── postgres/ray_compute_20251122.sql.gz
└── artifacts/mlflow_artifacts_20251122.tar.gz
```

### Recovery

**RTO:** 1 hour  
**RPO:** 24 hours

**Steps:**
1. Restore host (15 min)
2. Restore volumes (15 min)
3. Restore DBs (15 min)
4. Start services (10 min)
5. Verify (5 min)

---

## References

- [Traefik Docs](https://doc.traefik.io)
- [MLflow Docs](https://mlflow.org/docs)
- [Ray Docs](https://docs.ray.io)
- [12-Factor App](https://12factor.net)

---

**Version:** 2.0  
**Next Review:** 2025-12-22
