# Environment Variables

All non-sensitive platform configuration lives in `config/platform.env`. Secrets (passwords, tokens) belong in the `secrets/` directory.

---

## Platform Metadata

| Variable | Default | Description |
|----------|---------|-------------|
| `PLATFORM_VERSION` | `2.0` | Platform version number |
| `PLATFORM_ENV` | `production` | Environment (`production`, `development`) |
| `PLATFORM_PREFIX` | `shml` | Prefix for container and volume names |

---

## Service Discovery

Used by services to locate each other via Docker DNS.

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `postgres` | PostgreSQL hostname |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `REDIS_HOST` | `redis` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |

---

## MLflow

| Variable | Default | Description |
|----------|---------|-------------|
| `MLFLOW_TRACKING_URI` | `http://mlflow-nginx:80` | MLflow tracking server URL (via Nginx proxy) |
| `MLFLOW_REGISTRY_MODEL_NAME` | `face-detection-yolov8l-p2` | Default model name in the registry |
| `MLFLOW_ARTIFACT_ROOT` | `/mlflow/artifacts` | Root path for artifact storage |

!!! note
    MLflow uses the Nginx proxy internally to handle the `--static-prefix /mlflow` routing that MLflow 3.x requires.

---

## Ray Compute

| Variable | Default | Description |
|----------|---------|-------------|
| `RAY_HEAD_ADDRESS` | `ray-head:6379` | Ray GCS address for worker connections |
| `RAY_DASHBOARD_HOST` | `ray-head` | Ray Dashboard hostname |
| `RAY_DASHBOARD_PORT` | `8265` | Ray Dashboard port |
| `RAY_ADDRESS` | `http://ray-head:8265` | Ray Dashboard HTTP URL |

---

## Monitoring

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMETHEUS_HOST` | `global-prometheus` | Prometheus hostname |
| `PROMETHEUS_PORT` | `9090` | Prometheus HTTP port |
| `GRAFANA_HOST` | `unified-grafana` | Grafana hostname |
| `GRAFANA_PORT` | `3000` | Grafana HTTP port |
| `PUSHGATEWAY_HOST` | `pushgateway` | Pushgateway hostname |
| `PUSHGATEWAY_PORT` | `9091` | Pushgateway port |

---

## Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOKI_HOST` | `loki` | Loki log aggregation hostname |
| `LOKI_PORT` | `3100` | Loki HTTP port |

---

## Tracing

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPO_HOST` | `tempo` | Tempo trace storage hostname |
| `TEMPO_PORT` | `3200` | Tempo HTTP port |
| `OTEL_COLLECTOR_HOST` | `otel-collector` | OpenTelemetry Collector hostname |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTLP gRPC endpoint |

---

## Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `FUSIONAUTH_HOST` | `fusionauth` | FusionAuth hostname |
| `FUSIONAUTH_PORT` | `9011` | FusionAuth HTTP port |
| `OAUTH2_PROXY_HOST` | `oauth2-proxy` | OAuth2-Proxy hostname |
| `OAUTH2_PROXY_PORT` | `4180` | OAuth2-Proxy HTTP port |

---

## Secrets Management

| Variable | Default | Description |
|----------|---------|-------------|
| `INFISICAL_HOST` | `infisical` | Infisical secrets manager hostname |
| `INFISICAL_PORT` | `8080` | Infisical HTTP port |

---

## Variables in `.env` (Not in platform.env)

The `.env` file at the project root contains deployment-specific values that differ per installation. These are **not** in `platform.env` because they are either sensitive or host-specific.

| Variable | Description |
|----------|-------------|
| `PUBLIC_DOMAIN` | Tailscale Funnel domain (e.g., `shml-platform.tail38b60a.ts.net`) |
| `LAN_IP` | LAN IP for Traefik binding |
| `TAILSCALE_IP` | Tailscale IP for OAuth2-Proxy extra_hosts |
| `SHARED_DB_PASSWORD` | PostgreSQL shared password (also in `secrets/`) |
| `FUSIONAUTH_PROXY_CLIENT_ID` | OAuth2-Proxy client ID in FusionAuth |
| `FUSIONAUTH_PROXY_CLIENT_SECRET` | OAuth2-Proxy client secret |
| `OAUTH2_PROXY_COOKIE_SECRET` | Cookie encryption secret |
| `FUSIONAUTH_RUNTIME_MODE` | FusionAuth mode (`development` or `production`) |
| `GITHUB_WEBHOOK_SECRET` | Webhook deployer secret |
| `CICD_ADMIN_KEY` | API key for admin-level CI/CD access |
| `CICD_DEVELOPER_KEY` | API key for developer-level CI/CD access |
| `RAY_API_SECRET_KEY` | Ray Compute API session secret |

!!! warning "Never commit `.env`"
    The `.env` file is in `.gitignore`. Use `setup.sh` to generate it on a fresh installation.

---

## Kubernetes Migration

`config/platform.env` maps 1:1 to a Kubernetes ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: shml-platform-config
data:
  POSTGRES_HOST: postgres
  POSTGRES_PORT: "5432"
  MLFLOW_TRACKING_URI: http://mlflow-nginx:80
  # ... all platform.env values
```

Secrets map to Kubernetes Secrets objects. This design ensures a clean migration path when moving from Docker Compose to Kubernetes.
