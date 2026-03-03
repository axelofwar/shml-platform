# Docker Volumes

Named volumes and bind mounts used by the SHML Platform.

---

## Named Volumes

Managed by Docker. Data persists across container restarts and rebuilds.

### Shared Data

| Volume | Container(s) | Purpose |
|--------|-------------|---------|
| `shml-postgres-data` | `shml-postgres` | PostgreSQL databases (MLflow, Ray, FusionAuth, Nessie) |
| `shml-redis-data` | `shml-redis` | Redis AOF persistence and RDB snapshots |

### Monitoring

| Volume | Container(s) | Purpose |
|--------|-------------|---------|
| `shml-global-prometheus-data` | `global-prometheus` | Prometheus TSDB (90-day retention) |
| `shml-unified-grafana-data` | `unified-grafana` | Grafana state (user preferences, annotations) |

### Auth

| Volume | Container(s) | Purpose |
|--------|-------------|---------|
| `shml-fusionauth-config` | `fusionauth` | FusionAuth runtime configuration |

### Ray Compute

| Volume | Container(s) | Purpose |
|--------|-------------|---------|
| `ray-data` | `ray-head` | Ray temp data, checkpoints, datasets |
| `job-workspaces` | `ray-head`, `ray-compute-api` | Ray job working directories |
| `ray-api-logs` | `ray-compute-api` | API server logs |
| `ray-artifacts` | `ray-compute-api` | Job output artifacts |

### MLflow

| Volume | Container(s) | Purpose |
|--------|-------------|---------|
| `shml-mlflow-mlruns` | `mlflow-server` | MLflow local run data |
| `mlflow-prometheus-data` | `mlflow-prometheus` | MLflow-specific metrics (30d retention) |

### Data & Catalog

| Volume | Container(s) | Purpose |
|--------|-------------|---------|
| `shml-fiftyone-data` | `shml-fiftyone` | FiftyOne application data |
| `shml-fiftyone-datasets` | `shml-fiftyone` | CV dataset files |
| `shml-fiftyone-mongodb-data` | `shml-fiftyone-mongodb` | FiftyOne metadata store |

---

## Bind Mounts

Host filesystem paths mounted directly into containers.

| Host Path | Container Path | Service | Purpose |
|-----------|----------------|---------|---------|
| `/mlflow/artifacts` | `/mlflow/artifacts` | `mlflow-server`, `mlflow-api`, `ray-head` | Shared artifact storage |
| `./backups/postgres` | `/backups` | `shml-postgres`, `postgres-backup` | Database backup output |
| `./logs/traefik` | `/var/log/traefik` | `shml-traefik` | Traefik access logs |
| `./logs/mlflow` | `/mlflow/logs` | `mlflow-server` | MLflow server logs |
| `./logs/nginx` | `/var/log/nginx` | `mlflow-nginx` | Nginx access/error logs |
| `./monitoring/grafana/dashboards/` | `/var/lib/grafana/dashboards/` | `unified-grafana` | Provisioned dashboards (read-only) |
| `./monitoring/grafana/datasources.yml` | Grafana provisioning | `unified-grafana` | Data source definitions |
| `./secrets/*.txt` | `/run/secrets/*` | Various | Docker secrets |
| `/var/run/docker.sock` | `/var/run/docker.sock` | `shml-traefik`, `dozzle`, `shml-cadvisor` | Docker API access |

---

## Data Lifecycle

| Category | Persistence | Backup Strategy |
|----------|:-----------:|-----------------|
| **PostgreSQL data** | Persistent | Automated every 6 hours (7 daily, 4 weekly, 6 monthly) |
| **MLflow artifacts** | Persistent | Manual (bind mount on host at `/mlflow/artifacts`) |
| **Ray checkpoints** | Persistent | Synced to MLflow asynchronously |
| **Grafana dashboards** | Provisioned | Source-controlled in `monitoring/grafana/dashboards/` |
| **Grafana state** | Persistent | Not backed up (recreatable) |
| **Prometheus TSDB** | Persistent | Not backed up (re-scrapeable) |
| **Redis data** | Persistent | AOF + RDB, not externally backed up |
| **Training datasets** | Persistent | Not backed up (re-downloadable) |
| **Container logs** | Ephemeral | Aggregated by Loki (if enabled) |

!!! tip "Disaster Recovery"
    The only data that **must** be backed up is PostgreSQL (automated) and MLflow artifacts (manual). Everything else can be regenerated or re-scraped.
