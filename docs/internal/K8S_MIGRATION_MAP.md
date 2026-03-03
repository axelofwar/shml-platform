# Kubernetes Migration Map — SHML Platform

> **Purpose**: Document the exact mapping from current Docker Compose patterns to Kubernetes equivalents. This is a reference for when the platform migrates to K8s — NOT a migration plan. All compose files have been hardened with health checks, resource limits, and centralized config to make this mapping 1:1.

---

## Table of Contents

1. [Service Inventory](#service-inventory)
2. [Resource Limits Mapping](#resource-limits-mapping)
3. [Health Check → Probe Mapping](#health-check--probe-mapping)
4. [Volume Mapping](#volume-mapping)
5. [Service Discovery Mapping](#service-discovery-mapping)
6. [Configuration Mapping](#configuration-mapping)
7. [Secret Mapping](#secret-mapping)
8. [Network Mapping](#network-mapping)
9. [Ingress Mapping](#ingress-mapping)
10. [GPU / Device Mapping](#gpu--device-mapping)
11. [Deployment Strategy Notes](#deployment-strategy-notes)

---

## Service Inventory

| Compose File | Service | K8s Workload Type | K8s Namespace |
|---|---|---|---|
| `docker-compose.infra.yml` | traefik | Deployment (→ replaced by Ingress Controller) | `ingress-system` |
| `docker-compose.infra.yml` | postgres | StatefulSet | `shml-data` |
| `docker-compose.infra.yml` | redis | StatefulSet | `shml-data` |
| `docker-compose.infra.yml` | fusionauth | Deployment | `shml-auth` |
| `docker-compose.infra.yml` | oauth2-proxy | Deployment | `shml-auth` |
| `docker-compose.infra.yml` | role-auth | Deployment | `shml-auth` |
| `docker-compose.infra.yml` | node-exporter | DaemonSet | `shml-monitoring` |
| `docker-compose.infra.yml` | cadvisor | DaemonSet | `shml-monitoring` |
| `docker-compose.infra.yml` | global-prometheus | StatefulSet | `shml-monitoring` |
| `docker-compose.infra.yml` | pushgateway | Deployment | `shml-monitoring` |
| `docker-compose.infra.yml` | unified-grafana | Deployment | `shml-monitoring` |
| `docker-compose.infra.yml` | dozzle | Deployment | `shml-monitoring` |
| `docker-compose.infra.yml` | sba-resource-portal | Deployment | `shml-apps` |
| `docker-compose.infra.yml` | homer | Deployment | `shml-apps` |
| `docker-compose.infra.yml` | postgres-backup | CronJob | `shml-data` |
| `docker-compose.infra.yml` | webhook-deployer | Deployment | `shml-ci` |
| `docker-compose.infra.yml` | code-server | Deployment | `shml-dev` |
| `docker-compose.logging.yml` | loki | StatefulSet | `shml-monitoring` |
| `docker-compose.logging.yml` | promtail | DaemonSet | `shml-monitoring` |
| `docker-compose.tracing.yml` | tempo | StatefulSet | `shml-monitoring` |
| `docker-compose.tracing.yml` | otel-collector | DaemonSet / Deployment | `shml-monitoring` |
| `docker-compose.secrets.yml` | infisical | Deployment | `shml-secrets` |
| `docker-compose.secrets.yml` | infisical-postgres | StatefulSet | `shml-secrets` |
| `docker-compose.secrets.yml` | infisical-redis | StatefulSet | `shml-secrets` |
| `mlflow-server/docker-compose.yml` | mlflow-server | Deployment | `shml-ml` |
| `mlflow-server/docker-compose.yml` | mlflow-nginx | Deployment | `shml-ml` |
| `mlflow-server/docker-compose.yml` | mlflow-api | Deployment | `shml-ml` |
| `mlflow-server/docker-compose.yml` | mlflow-prometheus | StatefulSet | `shml-monitoring` |
| `ray_compute/docker-compose.yml` | ray-head | StatefulSet | `shml-compute` |
| `ray_compute/docker-compose.yml` | ray-compute-api | Deployment | `shml-compute` |
| `ray_compute/docker-compose.yml` | ray-prometheus | StatefulSet | `shml-monitoring` |
| `ray_compute/docker-compose.yml` | ray-compute-ui | Deployment | `shml-compute` |

---

## Resource Limits Mapping

Docker Compose `deploy.resources` maps directly to K8s `resources` in pod spec.

### Pattern

```yaml
# Docker Compose
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 768M
    reservations:
      cpus: '0.5'
      memory: 384M

# Kubernetes equivalent
resources:
  limits:
    cpu: "2000m"      # cpus × 1000
    memory: "768Mi"   # M → Mi (close enough)
  requests:
    cpu: "500m"       # reservations.cpus × 1000
    memory: "384Mi"   # reservations.memory
```

### Conversion Table

| Service | Compose CPU Limit | K8s CPU Limit | Compose Mem Limit | K8s Mem Limit |
|---|---|---|---|---|
| traefik | 1.49 | 1490m | 385M | 385Mi |
| postgres | 2.0 | 2000m | 768M | 768Mi |
| redis | 1.34 | 1340m | 512M | 512Mi |
| fusionauth | 1.0 | 1000m | 512M | 512Mi |
| oauth2-proxy | 0.5 | 500m | 128M | 128Mi |
| role-auth | 0.1 | 100m | 32M | 32Mi |
| node-exporter | 0.42 | 420m | 109M | 109Mi |
| cadvisor | 0.47 | 470m | 200M | 200Mi |
| global-prometheus | 1.0 | 1000m | 512M | 512Mi |
| pushgateway | 0.5 | 500m | 128M | 128Mi |
| unified-grafana | 1.0 | 1000m | 512M | 512Mi |
| dozzle | 0.25 | 250m | 128M | 128Mi |
| homer | 0.1 | 100m | 32M | 32Mi |
| code-server | 4.0 | 4000m | 4G | 4Gi |
| loki | 2.0 | 2000m | 2G | 2Gi |
| promtail | 2.0 | 2000m | 2G | 2Gi |
| tempo | 2.0 | 2000m | 2G | 2Gi |
| otel-collector | 2.0 | 2000m | 2G | 2Gi |
| infisical | 1.0 | 1000m | 1G | 1Gi |
| mlflow-server | 2.0 | 2000m | 2560M | 2560Mi |
| mlflow-nginx | 0.72 | 720m | 192M | 192Mi |
| mlflow-api | 0.87 | 870m | 384M | 384Mi |
| ray-head | 8.0 | 8000m | 48G | 48Gi |
| ray-compute-api | 0.87 | 870m | 640M | 640Mi |
| ray-compute-ui | 1.0 | 1000m | 512M | 512Mi |

---

## Health Check → Probe Mapping

Docker Compose `healthcheck` maps to K8s `livenessProbe` and `readinessProbe`.

### Pattern

```yaml
# Docker Compose
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s

# Kubernetes equivalent
livenessProbe:
  httpGet:
    path: /health
    port: 5000
  initialDelaySeconds: 40    # start_period
  periodSeconds: 30          # interval
  timeoutSeconds: 10         # timeout
  failureThreshold: 3        # retries
readinessProbe:
  httpGet:
    path: /health
    port: 5000
  initialDelaySeconds: 10
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

### Service Probe Map

| Service | Health Check Method | K8s Probe Type | Path/Command |
|---|---|---|---|
| traefik | `traefik healthcheck --ping` | `exec` / httpGet `/ping` | Replaced by Ingress Controller probes |
| postgres | `pg_isready -U postgres` | `exec` | `pg_isready -U postgres` |
| redis | `redis-cli ping` | `exec` | `redis-cli ping` |
| fusionauth | HTTP GET `/api/status:9011` | `httpGet` | `/api/status` port 9011 |
| oauth2-proxy | disabled (distroless) | `tcpSocket` | port 4180 |
| role-auth | HTTP GET `/health:8080` | `httpGet` | `/health` port 8080 |
| node-exporter | HTTP GET `/:9100` | `httpGet` | `/` port 9100 |
| cadvisor | HTTP GET `/healthz:8080` | `httpGet` | `/healthz` port 8080 |
| global-prometheus | HTTP GET `/-/healthy:9090` | `httpGet` | `/-/healthy` port 9090 |
| pushgateway | HTTP GET `/-/healthy:9091` | `httpGet` | `/-/healthy` port 9091 |
| unified-grafana | HTTP GET `/api/health:3000` | `httpGet` | `/api/health` port 3000 |
| dozzle | disabled (distroless) | `tcpSocket` | port 8080 |
| homer | HTTP GET `/:8080` | `httpGet` | `/` port 8080 |
| postgres-backup | HTTP GET `/:8080` | `httpGet` | `/` port 8080 |
| webhook-deployer | `kill -0 1` | `exec` | process liveness |
| code-server | HTTP GET `/healthz:8080` | `httpGet` | `/healthz` port 8080 |
| loki | HTTP GET `/ready:3100` | `httpGet` | `/ready` port 3100 |
| promtail | HTTP GET `/ready:9080` | `httpGet` | `/ready` port 9080 |
| tempo | HTTP GET `/ready:3200` | `httpGet` | `/ready` port 3200 |
| otel-collector | HTTP GET `/:13133` | `httpGet` | `/` port 13133 |
| infisical | HTTP GET `/api/status:8080` | `httpGet` | `/api/status` port 8080 |
| mlflow-server | HTTP GET `/health:5000` | `httpGet` | `/health` port 5000 |
| mlflow-nginx | HTTP GET `/health:80` | `httpGet` | `/health` port 80 |
| mlflow-api | HTTP GET `/health:8000` | `httpGet` | `/health` port 8000 |
| ray-head | `ray status` | `exec` | `ray status` |
| ray-compute-api | HTTP GET `/health:8000` | `httpGet` | `/health` port 8000 |
| ray-compute-ui | HTTP GET `/ray/ui:3000` | `httpGet` | `/ray/ui` port 3000 |

---

## Volume Mapping

Docker Compose named volumes → K8s PersistentVolumeClaims (PVCs).

### Named Volumes → PVCs

| Docker Volume | K8s PVC Name | Access Mode | Storage Class | Size Estimate |
|---|---|---|---|---|
| `shml-postgres-data` | `postgres-data-pvc` | ReadWriteOnce | local-path / longhorn | 50Gi |
| `shml-redis-data` | `redis-data-pvc` | ReadWriteOnce | local-path | 5Gi |
| `shml-fusionauth-config` | `fusionauth-config-pvc` | ReadWriteOnce | local-path | 1Gi |
| `shml-global-prometheus-data` | `global-prometheus-data-pvc` | ReadWriteOnce | local-path | 100Gi |
| `shml-unified-grafana-data` | `grafana-data-pvc` | ReadWriteOnce | local-path | 5Gi |
| `shml-mlflow-mlruns` | `mlflow-mlruns-pvc` | ReadWriteOnce | local-path | 50Gi |
| `shml-mlflow-prometheus-data` | `mlflow-prometheus-data-pvc` | ReadWriteOnce | local-path | 20Gi |
| `shml-ray-prometheus-data` | `ray-prometheus-data-pvc` | ReadWriteOnce | local-path | 20Gi |
| `shml-infisical-postgres-data` | `infisical-postgres-data-pvc` | ReadWriteOnce | local-path | 5Gi |
| `shml-infisical-redis-data` | `infisical-redis-data-pvc` | ReadWriteOnce | local-path | 1Gi |
| `mlflow-artifacts` (external) | `mlflow-artifacts-pvc` | ReadWriteMany | NFS / longhorn | 500Gi |

### Bind Mounts → ConfigMaps / HostPath

| Bind Mount | K8s Equivalent | Notes |
|---|---|---|
| `./monitoring/traefik/dynamic.yml` | ConfigMap `traefik-dynamic-config` | Replaced by Ingress resources |
| `./monitoring/loki/*.yml` | ConfigMap `loki-config` | Mount as volume from ConfigMap |
| `./monitoring/tempo/*.yaml` | ConfigMap `tempo-config` | Mount as volume from ConfigMap |
| `./monitoring/grafana/dashboards/` | ConfigMap `grafana-dashboards` | Use Grafana sidecar provisioner |
| `./monitoring/grafana/datasources.yml` | ConfigMap `grafana-datasources` | Mount as volume |
| `./monitoring/homer/` | ConfigMap `homer-assets` | Static config |
| `./docker/nginx/nginx.conf` | ConfigMap `mlflow-nginx-config` | Mount as volume |
| `/var/run/docker.sock` | Not applicable | Use K8s API / kubelet instead |
| `/proc`, `/sys`, `/` (node-exporter) | `hostPath` | DaemonSet with hostPath mounts |
| `./logs/*` | `emptyDir` or Loki direct | Prefer stdout/stderr → Loki |
| `./postgres/init-databases.sh` | ConfigMap `postgres-init` | Init container or ConfigMap mount |
| `/mlflow/artifacts` (host path) | PVC `mlflow-artifacts-pvc` | Shared via ReadWriteMany |

---

## Service Discovery Mapping

Docker Compose service names resolve via Docker DNS. In K8s, these become ClusterIP Services.

```yaml
# Docker Compose (DNS resolution)
POSTGRES_HOST=postgres          # resolves to container IP

# Kubernetes (ClusterIP Service)
apiVersion: v1
kind: Service
metadata:
  name: postgres               # Same name = same DNS
  namespace: shml-data
spec:
  selector:
    app: postgres
  ports:
    - port: 5432
      targetPort: 5432
```

### DNS Name Mapping

| Docker DNS Name | K8s Service Name | Namespace | Port(s) |
|---|---|---|---|
| `postgres` | `postgres` | `shml-data` | 5432 |
| `redis` | `redis` | `shml-data` | 6379 |
| `fusionauth` | `fusionauth` | `shml-auth` | 9011 |
| `oauth2-proxy` | `oauth2-proxy` | `shml-auth` | 4180 |
| `role-auth` | `role-auth` | `shml-auth` | 8080 |
| `ray-head` | `ray-head` | `shml-compute` | 6379, 8265, 8080, 10001 |
| `ray-compute-api` | `ray-compute-api` | `shml-compute` | 8000 |
| `mlflow-server` | `mlflow-server` | `shml-ml` | 5000 |
| `mlflow-nginx` | `mlflow-nginx` | `shml-ml` | 80 |
| `mlflow-api` | `mlflow-api` | `shml-ml` | 8000 |
| `global-prometheus` | `global-prometheus` | `shml-monitoring` | 9090 |
| `unified-grafana` | `unified-grafana` | `shml-monitoring` | 3000 |
| `loki` | `loki` | `shml-monitoring` | 3100 |
| `tempo` | `tempo` | `shml-monitoring` | 3200, 4317, 4318 |
| `otel-collector` | `otel-collector` | `shml-monitoring` | 4317, 4318, 13133 |
| `infisical` | `infisical` | `shml-secrets` | 8080 |

> **Cross-namespace resolution**: Use FQDN format: `postgres.shml-data.svc.cluster.local`

---

## Configuration Mapping

### .env Files → ConfigMaps

| Docker Compose | K8s ConfigMap | Contents |
|---|---|---|
| `config/platform.env` | `platform-config` | Service discovery, platform metadata |
| Service-specific `environment:` | Per-service ConfigMaps | App-specific non-secret config |
| `${PLATFORM_PREFIX}` vars | Namespace labels / annotations | Platform prefix becomes namespace |

```yaml
# config/platform.env → K8s ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: platform-config
  namespace: shml-platform
data:
  POSTGRES_HOST: "postgres.shml-data.svc.cluster.local"
  POSTGRES_PORT: "5432"
  REDIS_HOST: "redis.shml-data.svc.cluster.local"
  REDIS_PORT: "6379"
  MLFLOW_TRACKING_URI: "http://mlflow-nginx.shml-ml.svc.cluster.local:80"
  RAY_HEAD_ADDRESS: "ray-head.shml-compute.svc.cluster.local:6379"
  PLATFORM_VERSION: "2.0"
  PLATFORM_ENV: "production"
```

---

## Secret Mapping

### Docker Secrets → K8s Secrets

| Docker Secret File | K8s Secret Name | Namespace | Type |
|---|---|---|---|
| `secrets/shared_db_password.txt` | `shared-db-credentials` | `shml-data` | Opaque |
| `secrets/grafana_password.txt` | `grafana-credentials` | `shml-monitoring` | Opaque |
| `secrets/fusionauth_db_password.txt` | `fusionauth-db-credentials` | `shml-auth` | Opaque |
| `secrets/oauth2_proxy_cookie_secret.txt` | `oauth2-proxy-credentials` | `shml-auth` | Opaque |
| `.env` (FUSIONAUTH_PROXY_CLIENT_*) | `fusionauth-oidc-config` | `shml-auth` | Opaque |
| `.env` (OAUTH2_PROXY_COOKIE_SECRET) | `oauth2-proxy-config` | `shml-auth` | Opaque |
| `.env` (RAY_API_SECRET_KEY) | `ray-api-credentials` | `shml-compute` | Opaque |
| `.env` (CICD_*_KEY) | `cicd-api-keys` | `shml-compute` | Opaque |

```yaml
# Docker secret file mount → K8s Secret
apiVersion: v1
kind: Secret
metadata:
  name: shared-db-credentials
  namespace: shml-data
type: Opaque
data:
  password: <base64-encoded>

# Usage in pod spec (replaces POSTGRES_PASSWORD_FILE pattern)
env:
  - name: POSTGRES_PASSWORD
    valueFrom:
      secretKeyRef:
        name: shared-db-credentials
        key: password
```

> **Migration note**: Current Docker pattern uses `_FILE` suffix (e.g., `POSTGRES_PASSWORD_FILE=/run/secrets/shared_db_password`). K8s injects secrets directly as env vars or volume mounts — the `_FILE` pattern is not needed.

---

## Network Mapping

### Docker Bridge Network → K8s NetworkPolicy

Current: Single `shml-platform` bridge network (172.30.0.0/16) connecting all services.

K8s equivalent: Default pod-to-pod connectivity with NetworkPolicies for isolation.

```yaml
# Docker Compose
networks:
  platform:
    name: shml-platform
    driver: bridge
    ipam:
      config:
        - subnet: 172.30.0.0/16

# K8s NetworkPolicy equivalent (restrict monitoring namespace)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-monitoring-ingress
  namespace: shml-monitoring
spec:
  podSelector: {}
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: shml-monitoring
        - namespaceSelector:
            matchLabels:
              name: shml-ml
        - namespaceSelector:
            matchLabels:
              name: shml-compute
```

### Recommended Namespace Isolation

| Namespace | Allowed Ingress From | Allowed Egress To |
|---|---|---|
| `shml-data` | `shml-ml`, `shml-compute`, `shml-auth`, `shml-secrets` | (none external) |
| `shml-auth` | `ingress-system`, `shml-data` | `shml-data` |
| `shml-ml` | `ingress-system`, `shml-compute` | `shml-data`, `shml-monitoring` |
| `shml-compute` | `ingress-system` | `shml-data`, `shml-ml`, `shml-monitoring` |
| `shml-monitoring` | `shml-ml`, `shml-compute`, `shml-data` | (scrape targets) |

---

## Ingress Mapping

### Traefik Labels → K8s Ingress Resources

Traefik reverse proxy with Docker labels → K8s Ingress resources (with any Ingress Controller).

```yaml
# Docker Compose (Traefik labels)
labels:
  - "traefik.http.routers.mlflow-ui.rule=PathPrefix(`/mlflow`)"
  - "traefik.http.routers.mlflow-ui.middlewares=oauth2-errors,oauth2-auth,role-auth-developer"
  - "traefik.http.services.mlflow.loadbalancer.server.port=80"

# K8s Ingress equivalent
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mlflow-ingress
  namespace: shml-ml
  annotations:
    nginx.ingress.kubernetes.io/auth-url: "http://oauth2-proxy.shml-auth.svc.cluster.local:4180/oauth2-proxy/auth"
    nginx.ingress.kubernetes.io/auth-signin: "https://$host/oauth2-proxy/sign_in?rd=$escaped_request_uri"
spec:
  rules:
    - host: shml-platform.tail38b60a.ts.net
      http:
        paths:
          - path: /mlflow
            pathType: Prefix
            backend:
              service:
                name: mlflow-nginx
                port:
                  number: 80
```

### Route Table

| Traefik Path | K8s Ingress Path | Backend Service | Auth Middleware → Annotation |
|---|---|---|---|
| `/` | `/` | homer:8080 | oauth2-auth → `auth-url` |
| `/mlflow` | `/mlflow` | mlflow-nginx:80 | role-auth-developer |
| `/ray` | `/ray` | ray-head:8265 | role-auth-developer |
| `/ray/ui` | `/ray/ui` | ray-compute-ui:3000 | role-auth-developer |
| `/api/ray`, `/api/compute` | `/api/ray` | ray-compute-api:8000 | role-auth-developer |
| `/api/v1` | `/api/v1` | mlflow-api:8000 | role-auth-developer |
| `/grafana` | `/grafana` | unified-grafana:3000 | oauth2-auth |
| `/logs` | `/logs` | dozzle:8080 | role-auth-developer |
| `/auth` | `/auth` | fusionauth:9011 | (none) |
| `/oauth2-proxy` | `/oauth2-proxy` | oauth2-proxy:4180 | (none) |
| `/prometheus` | `/prometheus` | global-prometheus:9090 | role-auth-admin |
| `/secrets` | `/secrets` | infisical:8080 | role-auth-admin |
| `/ide` | `/ide` | code-server:8080 | role-auth-admin |
| `/webhook` | `/webhook` | webhook-deployer:9000 | (none — secret-based) |
| `/sba-portal` | `/sba-portal` | sba-resource-portal:80 | role-auth-developer |

---

## GPU / Device Mapping

### Docker GPU Runtime → K8s device plugins

```yaml
# Docker Compose
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          device_ids: ['0', '1']
          capabilities: [gpu]

# K8s equivalent (nvidia-device-plugin required)
resources:
  limits:
    nvidia.com/gpu: 2
# Plus node selector or toleration for GPU nodes
nodeSelector:
  nvidia.com/gpu.present: "true"
```

### SHML GPU Inventory

| Device | Docker device_ids | K8s Resource | VRAM |
|---|---|---|---|
| RTX 3090 Ti | `0` | `nvidia.com/gpu: 1` | 24GB |
| RTX 2070 | `1` | `nvidia.com/gpu: 1` | 8GB |

> **Note**: K8s `nvidia-device-plugin` treats all GPUs as fungible `nvidia.com/gpu` resources. For heterogeneous GPU scheduling (3090 Ti vs 2070), use node labels + nodeSelector or MIG profiles.

### Ray-specific considerations

- `shm_size: 2gb` → Pod `spec.volumes` with `emptyDir.medium: Memory` and `sizeLimit: 2Gi`
- `CUDA_VISIBLE_DEVICES` → Managed by nvidia-device-plugin, do not set manually
- Ray cluster should use KubeRay operator instead of manual StatefulSet

---

## Deployment Strategy Notes

### Migration Order (recommended)

1. **Monitoring namespace** first (Prometheus, Grafana, Loki, Tempo) — independent, no auth deps
2. **Data namespace** (Postgres, Redis) — StatefulSets with PVC migration
3. **Auth namespace** (FusionAuth, OAuth2-Proxy) — needs data layer
4. **ML namespace** (MLflow) — needs data + auth
5. **Compute namespace** (Ray via KubeRay) — needs data + ML + auth
6. **Apps namespace** (Homer, SBA portal) — last, least critical

### Key Differences to Handle

| Docker Compose Pattern | K8s Equivalent | Action Required |
|---|---|---|
| `restart: unless-stopped` | Pod `restartPolicy: Always` (default) | None |
| `container_name: fixed` | Pod metadata, not guaranteed | Update any hardcoded references |
| `depends_on: condition` | Init containers / readiness probes | Convert to init containers |
| `extra_hosts` | Pod `hostAliases` | Direct mapping |
| `privileged: true` (cadvisor) | `securityContext.privileged` | Needs PSP/PSA exception |
| `pid: host` (node-exporter) | `hostPID: true` | Needs PSP/PSA exception |
| Docker socket mount | K8s API / kubelet metrics | Redesign for Dozzle, cAdvisor |
| `env_file` | `envFrom: configMapRef` | Direct mapping |

### Tools for Migration

- **Kompose**: `kompose convert -f docker-compose.infra.yml` for initial manifests
- **KubeRay**: Operator for Ray cluster management (replaces manual ray-head setup)
- **Helm Charts**: Available for Grafana, Prometheus, Loki, Tempo (use official charts)
- **External Secrets Operator**: Bridge Infisical → K8s Secrets
