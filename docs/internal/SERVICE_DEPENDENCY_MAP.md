# Service Dependency Map

**Version:** 1.0.0  
**Last Updated:** 2025-12-05  
**Purpose:** Visual representation of service dependencies and startup order

---

## Complete Dependency Graph

```
                                    START
                                      │
                                      ├─ Phase 1: Network & Infrastructure
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
            ml-platform         shared-postgres    ml-platform-redis
              network               :5432              :6379
                    │                 │                 │
                    └─────────────────┼─────────────────┘
                                      │
                                      ├─ Phase 2: Authentication
                                      │
                                      ▼
                                 fusionauth
                                   :9011
                           (depends: shared-postgres)
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                                   │
                    ▼                                   ▼
              oauth2-proxy                         role-auth
                :4180                                :8080
          (depends: fusionauth)              (depends: fusionauth)
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      │
                                      ├─ Phase 3: Gateway & Monitoring
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │         │               │               │         │
            ▼         ▼               ▼               ▼         ▼
        traefik   homer          dozzle        Prometheus    Grafana
         :80,     :8080           :8080         Stack       :3000
         :8090  (depends:      (depends:         │           │
     (depends:   oauth2)        oauth2)          │           │
      oauth2                                     │           │
    middleware)                                  │           │
            │                                    │           │
            │    ┌───────────────────────────────┼───────────┤
            │    │               │               │           │
            │    ▼               ▼               ▼           │
            │  global-       mlflow-         ray-           │
            │  prometheus   prometheus    prometheus        │
            │   :9090         :9091          :9092          │
            │    │               │               │           │
            │    └───────────────┴───────────────┴───────────┘
            │                                                │
            │                                                │
            └────────────────────┬───────────────────────────┘
                                 │
                                 ├─ Phase 4: Core Services
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        │    MLflow Stack        │      Ray Stack        │
        │                        │                        │
        ▼                        │                        ▼
    mlflow-server               │                    ray-head
      :5000                     │                     :8265, :10001
(depends: shared-postgres,      │              (depends: shared-postgres,
 ml-platform-redis DB 0)        │               ml-platform-redis DB 1,
        │                       │                     GPUs)
        │                       │                        │
        ▼                       │                        │
    mlflow-api                  │                        │
      :8000                     │                        │
(depends: mlflow-server)        │                        │
        │                       │                        │
        ▼                       │                        ▼
    mlflow-nginx                │                   ray-compute-api
      :80                       │                      :8000
(depends: mlflow-server)        │              (depends: ray-head,
        │                       │               mlflow-nginx for logging)
        │                       │                        │
        └───────────────────────┼────────────────────────┘
                                │
                                ├─ Phase 5: Inference (Optional)
                                │
                                ▼
                        inference-gateway
                              :8000
                    (depends: shared-postgres)
                                │
                ┌───────────────┴───────────────┐
                │                               │
                ▼                               ▼
          qwen3-vl-api                    z-image-api
            :8000                           :8000
        (depends: RTX 2070)             (depends: RTX 3090)
        (always loaded)                 (on-demand, yields)
```

---

## Dependency Matrix

### Infrastructure Layer

| Service | Depends On | Provides To | Critical Path |
|---------|-----------|-------------|---------------|
| ml-platform network | - | All services | ✅ Yes |
| shared-postgres | network | MLflow, Ray, Inference, FusionAuth | ✅ Yes |
| ml-platform-redis | network | MLflow (DB 0), Ray (DB 1) | ✅ Yes |

### Authentication Layer

| Service | Depends On | Provides To | Critical Path |
|---------|-----------|-------------|---------------|
| fusionauth | shared-postgres | oauth2-proxy, role-auth | ✅ Yes |
| oauth2-proxy | fusionauth | All protected services (via Traefik middleware) | ✅ Yes |
| role-auth | fusionauth | All role-protected services (via Traefik middleware) | ✅ Yes |

### Gateway & Monitoring Layer

| Service | Depends On | Provides To | Critical Path |
|---------|-----------|-------------|---------------|
| traefik | oauth2-proxy (middleware) | External access to all services | ✅ Yes |
| global-prometheus | - | unified-grafana | No |
| mlflow-prometheus | - | unified-grafana | No |
| ray-prometheus | - | unified-grafana | No |
| unified-grafana | Prometheus instances | Dashboard access | No |
| homer | oauth2-proxy | Landing page | No |
| dozzle | oauth2-proxy | Log viewer | No |
| cadvisor | - | global-prometheus | No |
| node-exporter | - | global-prometheus | No |
| nvidia-mps | GPUs | global-prometheus | No |

### MLflow Stack

| Service | Depends On | Provides To | Critical Path |
|---------|-----------|-------------|---------------|
| mlflow-server | shared-postgres, redis DB 0 | mlflow-nginx, mlflow-api, Ray jobs | ✅ Yes |
| mlflow-api | mlflow-server | Enhanced API clients | No |
| mlflow-nginx | mlflow-server | Traefik routing, Ray integration | ✅ Yes |

### Ray Stack

| Service | Depends On | Provides To | Critical Path |
|---------|-----------|-------------|---------------|
| ray-head | shared-postgres, redis DB 1, GPUs | ray-compute-api, Ray clients | ✅ Yes |
| ray-compute-api | ray-head, mlflow-nginx | Job submission clients | ✅ Yes |

### Inference Stack

| Service | Depends On | Provides To | Critical Path |
|---------|-----------|-------------|---------------|
| inference-gateway | shared-postgres | Traefik routing, clients | No |
| qwen3-vl-api | RTX 2070, model cache | inference-gateway | No |
| z-image-api | RTX 3090, model cache | inference-gateway | No |

---

## Critical Path Analysis

### Minimum Services for Platform Operation

```
ml-platform network
    ↓
shared-postgres
    ↓
ml-platform-redis
    ↓
fusionauth
    ↓
oauth2-proxy + role-auth
    ↓
traefik
    ↓
mlflow-server → mlflow-nginx
    ↓
ray-head → ray-compute-api
```

**Total:** 10 containers (44% of full platform)

### Startup Time Estimates

| Phase | Services | Time | Cumulative |
|-------|----------|------|------------|
| Phase 1 | Network, Postgres, Redis | 120s | 120s |
| Phase 2 | FusionAuth, OAuth2, Role-Auth | 180s | 300s |
| Phase 3 | Traefik, Monitoring | 90s | 390s |
| Phase 4 | MLflow, Ray | 180s | 570s |
| Phase 5 | Inference | 120s | 690s |
| **Total** | **23 containers** | **~12 minutes** | |

**Note:** Times are maximum estimates with health check validation.

---

## Failure Impact Analysis

### Single Point of Failure (SPOF)

| Service | Impact if Down | Affected Services | Mitigation |
|---------|----------------|-------------------|------------|
| **shared-postgres** | ❌ Critical - Platform inoperable | All (MLflow, Ray, Inference, Auth) | Backup/restore, replication |
| **fusionauth** | ❌ Critical - No authentication | All protected services | Cache tokens, backup/restore |
| **oauth2-proxy** | ❌ Critical - Auth loop | All protected services | Disable auth for debugging |
| **traefik** | ❌ Critical - No external access | All services | Direct container port access |
| **ml-platform-redis** | ⚠️ High - Performance degradation | MLflow, Ray (cache layer) | Redis persistence, backup |
| mlflow-server | ⚠️ High - No experiment tracking | Ray (optional MLflow logging) | Not SPOF for Ray jobs |
| ray-head | ⚠️ High - No distributed compute | Ray jobs only | Not SPOF for MLflow |
| unified-grafana | ℹ️ Low - No dashboards | Monitoring only | Direct Prometheus access |
| inference-gateway | ℹ️ Low - No LLM/image gen | Inference only | Optional feature |

### Cascading Failure Scenarios

**Scenario 1: PostgreSQL Failure**
```
shared-postgres down
    ↓
fusionauth can't authenticate → All protected services inaccessible
    ↓
mlflow-server can't write experiments → Experiment tracking fails
    ↓
ray-head can't persist jobs → Job history lost
    ↓
inference-gateway can't store conversations → Chat history lost
```

**Mitigation:**
- PostgreSQL replication (primary + replica)
- Automated backups every 6 hours
- Health monitoring with alerting

**Scenario 2: FusionAuth Failure**
```
fusionauth down
    ↓
oauth2-proxy can't validate tokens → All logins fail
    ↓
All protected services return 502 → Platform inaccessible
```

**Mitigation:**
- Token caching in oauth2-proxy (valid until expiry)
- Emergency auth bypass flag (for debugging only)
- FusionAuth backup/restore procedures

**Scenario 3: Traefik Failure**
```
traefik down
    ↓
No external routing → All services inaccessible from outside
    │
    └─ Internal services still work (mlflow-nginx:80, ray-head:8265)
```

**Mitigation:**
- Direct port access for debugging
- Traefik health checks and auto-restart
- Backup reverse proxy (Nginx) configuration

---

## Dependency Chains by Feature

### Feature: MLflow Experiment Tracking (External Client)

```
Client
  ↓
Internet/LAN
  ↓
Traefik :80 (/mlflow/*)
  ↓
OAuth2 middleware (oauth2-proxy)
  ↓
Role Auth middleware (role-auth → developer)
  ↓
mlflow-nginx :80
  ↓
mlflow-server :5000
  ↓
shared-postgres :5432 (mlflow_db)
```

**Dependencies:** 7 services
**SPOFs:** traefik, oauth2-proxy, shared-postgres

### Feature: Ray Job Submission (Remote Client)

```
Client
  ↓
Internet/LAN
  ↓
Ray Client Protocol :10001 (no Traefik!)
  ↓
ray-head :10001
  ↓
shared-postgres :5432 (ray_compute)
  │
  └─ Optional: MLflow logging
        ↓
      mlflow-nginx :80 (internal DNS)
        ↓
      mlflow-server :5000
```

**Dependencies:** 3 services (5 with MLflow logging)
**SPOFs:** ray-head, shared-postgres

### Feature: Ray Job via API (Browser)

```
Client
  ↓
Internet/LAN
  ↓
Traefik :80 (/api/compute/*)
  ↓
OAuth2 middleware (oauth2-proxy)
  ↓
Role Auth middleware (role-auth → developer)
  ↓
ray-compute-api :8000
  ↓
ray-head :8265 (internal)
  ↓
shared-postgres :5432 (ray_compute)
```

**Dependencies:** 7 services
**SPOFs:** traefik, oauth2-proxy, ray-head, shared-postgres

### Feature: Inference (LLM Chat)

```
Client
  ↓
Internet/LAN
  ↓
Traefik :80 (/api/llm/*)
  ↓
OAuth2 middleware (oauth2-proxy)
  ↓
inference-gateway :8000
  ↓
qwen3-vl-api :8000 (internal)
  ↓
RTX 2070 (cuda:0)
  │
  └─ Chat history
        ↓
      shared-postgres :5432 (inference)
```

**Dependencies:** 6 services
**SPOFs:** traefik, oauth2-proxy, qwen3-vl-api, RTX 2070

### Feature: Monitoring Dashboards

```
Client
  ↓
Internet/LAN
  ↓
Traefik :80 (/grafana/*)
  ↓
OAuth2 middleware (oauth2-proxy)
  ↓
unified-grafana :3000
  ↓
┌────────┬────────────┬────────────┐
│        │            │            │
▼        ▼            ▼            ▼
global   mlflow       ray          Other
-prom    -prom        -prom        exporters
:9090    :9091        :9092        (cadvisor,
│        │            │            node-exp,
└────────┴────────────┴────────────┘ dcgm)
         │
         ▼
    Service metrics (scraped every 15s)
```

**Dependencies:** 5 services + all monitored services
**SPOFs:** traefik, oauth2-proxy, unified-grafana

---

## Startup Order Rationale

### Why This Order?

**Phase 1 First:**
- Network must exist before any container can join
- PostgreSQL is database for 4 services (blocks all)
- Redis is cache for MLflow + Ray (performance-critical)

**Phase 2 Second:**
- FusionAuth needs PostgreSQL (can't start without DB)
- OAuth2 Proxy needs FusionAuth (can't authenticate without OIDC provider)
- Role-Auth needs FusionAuth (can't verify roles without groups API)

**Phase 3 Third:**
- Traefik needs OAuth2 Proxy middleware registered (else 500 errors)
- Prometheus can start anytime (scrapes are tolerant of missing targets)
- Grafana needs Prometheus datasources (but dashboards work if late)

**Phase 4 Fourth:**
- MLflow needs PostgreSQL + Redis (dependencies met in Phase 1)
- Ray needs PostgreSQL + Redis + GPUs (dependencies met)
- Ray API needs mlflow-nginx for logging (must wait for MLflow)

**Phase 5 Last:**
- Inference is optional (platform works without it)
- GPU contention: Z-Image on RTX 3090 can be delayed
- Gateway can start before model APIs (queues requests)

### What If Order Changes?

**Starting Traefik before OAuth2 Proxy:**
- ❌ Middleware `oauth2-auth@docker` not registered
- ❌ Protected services return 500 "middleware not found"
- ✅ Fix: Wait for oauth2-proxy health + middleware verification

**Starting MLflow before PostgreSQL:**
- ❌ MLflow server fails to connect to database
- ❌ Container crashes and restarts in loop
- ✅ Fix: Health checks + depends_on (docker-compose v2.20+)

**Starting Ray API before MLflow:**
- ⚠️ Ray API starts but can't log to MLflow
- ✅ Ray jobs still work (logging is optional)
- ℹ️ Experiments won't be tracked until MLflow available

**Starting Grafana before Prometheus:**
- ⚠️ Grafana dashboards show "No data"
- ✅ Grafana works fine (datasource check fails gracefully)
- ℹ️ Dashboards populate once Prometheus catches up

---

## Service Groups by Function

### Core Platform (10 services)
```
ml-platform network
shared-postgres
ml-platform-redis
fusionauth
oauth2-proxy
role-auth
traefik
mlflow-server
mlflow-nginx
ray-head
```

### Extended Platform (+3 services)
```
Core Platform
+ ray-compute-api (job submission API)
+ mlflow-api (enhanced API)
+ unified-grafana (monitoring)
```

### Full Platform (+10 services)
```
Extended Platform
+ global-prometheus
+ mlflow-prometheus
+ ray-prometheus
+ homer (landing page)
+ dozzle (logs)
+ cadvisor (container metrics)
+ node-exporter (system metrics)
+ nvidia-mps (GPU metrics)
+ postgres-backup (automated backups)
+ inference-gateway (optional)
```

### Optional Services (not counted in 23)
```
qwen3-vl-api (LLM)
z-image-api (image generation)
webhook-deployer (CD automation)
```

---

## Recovery Procedures

### Graceful Restart Order

**Restart Infrastructure:**
```bash
docker-compose -f docker-compose.infra.yml restart shared-postgres
# Wait 30s
docker-compose -f docker-compose.infra.yml restart ml-platform-redis
```

**Restart Authentication:**
```bash
docker-compose -f docker-compose.infra.yml restart fusionauth
# Wait 60s
docker-compose -f docker-compose.infra.yml restart oauth2-proxy role-auth
# Wait 30s
# Verify middleware: curl http://localhost:8090/api/http/middlewares | grep oauth2-auth
```

**Restart Gateway:**
```bash
docker-compose -f docker-compose.infra.yml restart traefik
# Wait 10s
```

**Restart Core Services:**
```bash
docker-compose -f mlflow-server/docker-compose.yml restart
# Wait 30s
docker-compose -f ray_compute/docker-compose.yml restart
# Wait 60s
```

### Emergency Debugging Order

**Problem: Can't access any service**
1. Check Traefik: `docker logs ml-platform-traefik`
2. Check OAuth: `docker logs oauth2-proxy`
3. Check FusionAuth: `docker logs fusionauth`
4. Test directly: `curl http://mlflow-nginx:80` (from inside network)

**Problem: MLflow not working**
1. Check mlflow-server: `docker logs mlflow-server`
2. Check PostgreSQL: `docker exec shared-postgres psql -U postgres -d mlflow_db -c "\dt"`
3. Check Redis: `docker exec ml-platform-redis redis-cli -n 0 ping`
4. Test internally: `curl http://mlflow-server:5000/health`

**Problem: Ray jobs failing**
1. Check ray-head: `docker logs ray-head`
2. Check PostgreSQL: `docker exec shared-postgres psql -U postgres -d ray_compute -c "\dt"`
3. Check GPUs: `nvidia-smi`
4. Test internally: `curl http://ray-head:8265/api/workers`

---

## Appendix: Docker Compose Dependencies

### Infrastructure (docker-compose.infra.yml)

```yaml
services:
  shared-postgres:
    # No dependencies

  ml-platform-redis:
    # No dependencies

  fusionauth:
    depends_on:
      shared-postgres:
        condition: service_healthy

  oauth2-proxy:
    depends_on:
      fusionauth:
        condition: service_healthy

  role-auth:
    depends_on:
      fusionauth:
        condition: service_healthy

  traefik:
    depends_on:
      oauth2-proxy:
        condition: service_started  # No healthcheck (distroless image)

  unified-grafana:
    depends_on:
      - global-prometheus
      - mlflow-prometheus
      - ray-prometheus
```

### MLflow (mlflow-server/docker-compose.yml)

```yaml
services:
  mlflow-server:
    depends_on:
      shared-postgres:
        condition: service_healthy
      ml-platform-redis:
        condition: service_healthy

  mlflow-nginx:
    depends_on:
      mlflow-server:
        condition: service_healthy

  mlflow-api:
    depends_on:
      mlflow-server:
        condition: service_healthy
```

### Ray (ray_compute/docker-compose.yml)

```yaml
services:
  ray-head:
    depends_on:
      shared-postgres:
        condition: service_healthy
      ml-platform-redis:
        condition: service_healthy

  ray-compute-api:
    depends_on:
      ray-head:
        condition: service_started  # Ray has no healthcheck
      mlflow-nginx:
        condition: service_healthy  # For experiment logging
```

### Inference (inference/docker-compose.inference.yml)

```yaml
services:
  inference-gateway:
    depends_on:
      shared-postgres:
        condition: service_healthy

  qwen3-vl-api:
    # No dependencies (uses model cache)

  z-image-api:
    # No dependencies (uses model cache)
```

---

**Document Version:** 1.0.0  
**Last Updated:** 2025-12-05  
**Maintained By:** Platform Team
