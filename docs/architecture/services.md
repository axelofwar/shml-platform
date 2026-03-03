# Service Inventory

Complete inventory of all services in the SHML Platform, grouped by function.

---

## Infrastructure

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **Traefik** | `shml-traefik` | `:80`, `:443`, `:8090` | `docker-compose.infra.yml` | API gateway, reverse proxy, TLS termination |
| **PostgreSQL** | `shml-postgres` | `:5432` (internal) | `docker-compose.infra.yml` | Shared database (MLflow, Ray, FusionAuth, Nessie) |
| **Redis** | `shml-redis` | `:6379` (internal) | `docker-compose.infra.yml` | Shared cache, session store, pub/sub |
| **Homer** | `homer` | `:8080` (internal) | `docker-compose.infra.yml` | Static landing page / service dashboard |
| **Code Server** | `shml-code-server` | `:8080` (internal) | `docker-compose.infra.yml` | VS Code in browser (admin only) |

---

## Authentication & Authorization

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **FusionAuth** | `fusionauth` | `:9011` | `docker-compose.infra.yml` | OAuth2/OIDC identity provider |
| **OAuth2-Proxy** | `oauth2-proxy` | `:4180` (internal) | `docker-compose.infra.yml` | Forward-auth proxy for protected services |
| **Role-Auth** | `shml-role-auth` | `:8080` (internal) | `docker-compose.infra.yml` | RBAC role checker (viewer/developer/admin) |

---

## ML Training & Compute

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **Ray Head** | `ray-head` | `:6379`, `:8265`, `:8080` | `ray_compute/docker-compose.yml` | Ray cluster head node with GPU access |
| **Ray Compute API** | `ray-compute-api` | `:8000` (internal) | `ray_compute/docker-compose.yml` | REST API for job submission and management |
| **Ray Compute UI** | `ray-compute-ui` | `:3000` (internal) | `ray_compute/docker-compose.yml` | Custom web UI for Ray job management |
| **Ray Prometheus** | `ray-prometheus` | `:9090` (internal) | `ray_compute/docker-compose.yml` | Service-specific metrics (7d retention) |

---

## Experiment Tracking

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **MLflow Server** | `mlflow-server` | `:5000` (internal) | `mlflow-server/docker-compose.yml` | Experiment tracking, model registry |
| **MLflow Nginx** | `mlflow-nginx` | `:80` (internal) | `mlflow-server/docker-compose.yml` | Reverse proxy for MLflow (static prefix) |
| **MLflow API** | `mlflow-api` | `:8000` (internal) | `mlflow-server/docker-compose.yml` | Custom REST API with enhanced endpoints |
| **MLflow Prometheus** | `mlflow-prometheus` | `:9090` (internal) | `mlflow-server/docker-compose.yml` | Service-specific metrics (30d retention) |

---

## Data & Catalog

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **Nessie** | `shml-nessie` | `:19120` (internal) | `docker-compose.infra.yml` | Apache Iceberg catalog with Git-like versioning |
| **FiftyOne** | `shml-fiftyone` | `:5151` (internal) | `docker-compose.infra.yml` | CV dataset curation and visualization |
| **FiftyOne MongoDB** | `shml-fiftyone-mongodb` | `:27017` (internal) | `docker-compose.infra.yml` | Metadata store for FiftyOne |

---

## Monitoring & Observability

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **Global Prometheus** | `global-prometheus` | `:9090` (internal) | `docker-compose.infra.yml` | Federated metrics (90d retention) |
| **Pushgateway** | `shml-pushgateway` | `:9091` (internal) | `docker-compose.infra.yml` | Batch job metrics (training jobs) |
| **Unified Grafana** | `unified-grafana` | `:3000` (internal) | `docker-compose.infra.yml` | Dashboards and alerting |
| **ML SLO Exporter** | `shml-ml-slo-exporter` | `:9092` (internal) | `docker-compose.infra.yml` | Custom MLflow/Ray SLO metrics |
| **Node Exporter** | `shml-node-exporter` | `:9100` (internal) | `docker-compose.infra.yml` | Host-level system metrics |
| **cAdvisor** | `shml-cadvisor` | `:8080` (internal) | `docker-compose.infra.yml` | Container-level resource metrics |
| **Dozzle** | `dozzle` | `:8080` (internal) | `docker-compose.infra.yml` | Real-time Docker log viewer |

---

## Logging & Tracing (Optional Stacks)

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **Loki** | `shml-loki` | `:3100` | `docker-compose.logging.yml` | Log aggregation (90d retention) |
| **Promtail** | `shml-promtail` | `:9080` | `docker-compose.logging.yml` | Log shipper for Loki |
| **Tempo** | `shml-tempo` | `:3200`, `:4317`, `:9411` | `docker-compose.tracing.yml` | Distributed trace storage |
| **OTEL Collector** | `shml-otel-collector` | `:4315`, `:4316`, `:13133` | `docker-compose.tracing.yml` | OpenTelemetry trace collector |

---

## Secrets & Deployment

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **Infisical** | `shml-infisical` | `:8080` (internal) | `docker-compose.secrets.yml` | Self-hosted secrets manager |
| **Infisical Postgres** | `shml-infisical-postgres` | `:5432` (internal) | `docker-compose.secrets.yml` | Infisical's dedicated database |
| **Infisical Redis** | `shml-infisical-redis` | `:6379` (internal) | `docker-compose.secrets.yml` | Infisical's dedicated cache |
| **Webhook Deployer** | `webhook-deployer` | `:9000` (internal) | `docker-compose.infra.yml` | GitHub push-to-deploy |
| **Postgres Backup** | `postgres-backup` | `:8080` (internal) | `docker-compose.infra.yml` | Automated database backups |

---

## Utility

| Service | Container | Port(s) | Compose File | Purpose |
|---------|-----------|---------|-------------|---------|
| **SBA Resource Portal** | `shml-sba-resource-portal` | `:80` (internal) | `docker-compose.infra.yml` | Gemini AI document Q&A |

---

## Access Tiers

All services behind Traefik use the platform's 4-tier RBAC:

| Tier | Services |
|------|----------|
| **viewer** | Homer, Grafana (dashboards only) |
| **developer** | MLflow, Ray Dashboard, Ray API, Dozzle, Chat API, FiftyOne, Nessie |
| **elevated-developer** | Agent tools, GitHub actions, model management |
| **admin** | Traefik dashboard, Prometheus, Code Server, Infisical, all others |

!!! tip "Public Endpoints"
    Webhook Deployer and health check endpoints are publicly accessible (authenticated via secret or no auth required).

---

## Network

All services share a single Docker bridge network:

- **Name:** `shml-platform`
- **Subnet:** `172.30.0.0/16`
- **Driver:** `bridge`
