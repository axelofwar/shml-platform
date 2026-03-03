# Monitoring — Grafana, Prometheus & Alerting

The SHML platform ships a full observability stack: **Grafana** for dashboards,
a **federated Prometheus** trio for metrics at different retention horizons,
**Pushgateway** for batch/training job metrics, and an **ML SLO exporter** that
turns MLflow + Ray metadata into actionable SLO gauges.

---

## Architecture Overview

```
Training Job / SDK ──push──▶ Pushgateway :9091
                                  │
                            scrape 15 s
                                  ▼
Ray Prometheus ◀─federate─▶ Global Prometheus ◀─federate─▶ MLflow Prometheus
   (7 d retention)           (90 d retention)               (30 d retention)
                                  ▲
                            scrape 60 s
                                  │
                          ML SLO Exporter :9092
                          cAdvisor · Node Exporter
                          DCGM Exporter · Traefik
                                  │
                                  ▼
                            Unified Grafana :3000
```

!!! info "Federated design"
    Each service-level Prometheus (MLflow, Ray) keeps fine-grained metrics at
    short retention. **Global Prometheus** federates the important series and
    adds platform-wide scrape targets (pushgateway, node-exporter, cAdvisor,
    DCGM, Traefik, SLO exporter) with 90-day retention.

---

## Datasources

Grafana is provisioned with three Prometheus datasources
(see `monitoring/grafana/datasources.yml`):

| Name | UID | URL | Retention | Default |
|------|-----|-----|-----------|---------|
| Global Metrics | `global-metrics` | `http://global-prometheus:9090` | 90 d | **Yes** |
| MLflow Metrics | `mlflow-metrics` | `http://mlflow-prometheus:9090` | 30 d | No |
| Ray Metrics | `ray-metrics` | `http://ray-prometheus:9090` | 7 d | No |

!!! warning "Dashboard datasource UIDs"
    All dashboards should reference `global-metrics` (or use the `${datasource}`
    template variable). A previous misconfiguration used `unified-prometheus` —
    this UID does not exist and will cause "Data source not found" errors.

---

## Dashboard Inventory

Dashboards are provisioned from JSON files under `monitoring/grafana/dashboards/`.

### Training & Evaluation

| Dashboard | File | UID | Description |
|-----------|------|-----|-------------|
| **Face Detection — Unified** | `ray/face-detection-unified.json` | `face-detection-unified` | Combined training + evaluation view (31 panels). Real-time gauges, loss curves, KPI gap analysis, model comparison, artifact locations. |
| Training Cost Tracking | `training/training-cost-tracking.json` | — | GPU-hour and cost estimates per training run. |
| Training Resource Heatmaps | `training/training-resource-heatmaps.json` | — | GPU / memory heatmaps during training. |

### Platform & System

| Dashboard | File | UID | Description |
|-----------|------|-----|-------------|
| Platform Overview | `system/platform-overview.json` | — | High-level service health, container up/down status. |
| Container Metrics | `platform/container-metrics.json` | — | Per-container CPU, memory, network I/O via cAdvisor. |
| GPU Monitoring | `platform/gpu-monitoring.json` | — | NVIDIA DCGM metrics — utilization, temperature, memory. |
| System Metrics | `platform/system-metrics.json` | — | Host-level CPU, memory, disk, network (node-exporter). |

### ML SLOs

| Dashboard | File | UID | Description |
|-----------|------|-----|-------------|
| ML SLO Overview | `ml-slos/ml-slo-overview.json` | — | Model freshness, training success rate, error budget burn, eval completeness. |

### Ray Cluster

| Dashboard | File | Description |
|-----------|------|-------------|
| Ray Default | `ray/ray-default-dashboard.json` | Cluster-wide resource usage. |
| Ray Data | `ray/ray-data-dashboard.json` | Ray Data read/write throughput. |
| Ray Serve | `ray/ray-serve-dashboard.json` | Serve replica metrics. |
| Ray Serve Deployment | `ray/ray-serve-deployment-dashboard.json` | Per-deployment latency & QPS. |

### Other

| Dashboard | File | Description |
|-----------|------|-------------|
| Agent Usage Analytics | `agent-usage-analytics.json` | LLM agent token/cost analytics. |

---

## Unified Training Dashboard — Deep Dive

The **Face Detection — Unified** dashboard (`face-detection-unified`) replaces
two earlier dashboards and provides end-to-end coverage of the training
lifecycle.

### Sections

1. **Training Status & Artifacts** — active/inactive indicator, current epoch,
   progress gauge, curriculum stage, and a reference panel with all artifact
   storage paths (Ray checkpoints, MLflow artifacts, job links).
2. **Real-Time Training Metrics** — mAP@0.50, recall, precision gauges with
   KPI target thresholds; loss curves (total, box, cls, DFL); learning rate
   and GPU memory over time. Refreshes every **5 s**.
3. **Model Evaluation & KPI Comparison** — post-training evaluation gauges,
   F1 score, gap-to-target visualisation, multi-model selector (`$model`
   variable), "meets targets" boolean indicator.

### Template Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `$datasource` | Prometheus datasource selector | `global-metrics` |
| `$model` | Model name filter for evaluation panels (multi-select) | All |
| `$training_job` | Auto-populated job name for training panels | Hidden |

### Conditional Display

Training panels only show data when `training_epoch > 0`. Evaluation panels
are always visible because those metrics persist in Pushgateway.

---

## Pushing Metrics from Training Jobs

### Via the SDK (`client.prometheus`)

The SHML SDK exposes a `PrometheusReporter` through the unified client:

```python
from shml import Client

client = Client()

# Check connectivity
assert client.prometheus.healthy()

# Push arbitrary metrics
client.prometheus.report_metrics({
    "training_mAP50": 0.82,
    "training_recall": 0.78,
    "training_precision": 0.91,
})

# Push epoch-level metrics (adds epoch counter automatically)
client.prometheus.report_epoch(
    epoch=42,
    total_epochs=200,
    metrics={"training_loss": 0.34, "training_lr": 0.0005},
    duration_seconds=1180.0,
)
```

Under the hood `PrometheusReporter` creates `prometheus_client.Gauge` objects,
sets their values, and calls `push_to_gateway()` against the Pushgateway URL
from `PlatformConfig` (default `shml-pushgateway:9091`).

!!! tip "Install the training extra"
    ```bash
    pip install shml-sdk[training]   # pulls prometheus-client
    ```

### Direct Pushgateway Usage

Training scripts that don't use the SDK (e.g. the YOLO `TrainingMetricsCallback`
in `ray_compute/jobs/training/phase1_foundation.py`) push via raw HTTP:

```python
# POST metrics to pushgateway
import urllib.request, urllib.parse

url = "http://shml-pushgateway:9091/metrics/job/face_detection_training"
data = "training_mAP50 0.82\ntraining_recall 0.78\n"
req = urllib.request.Request(url, data=data.encode(), method="POST")
urllib.request.urlopen(req)
```

### Metric Naming Conventions

| Phase | Prefix | Job label | Example |
|-------|--------|-----------|---------|
| Training (live) | `training_*` | `face_detection_training` | `training_mAP50`, `training_loss` |
| Evaluation (post) | `face_detection_*` | `face_detection_evaluation` | `face_detection_map50`, `face_detection_f1` |

---

## Training Metrics Reference

### Real-Time (pushed every epoch)

| Metric | Description |
|--------|-------------|
| `training_epoch` | Current epoch number |
| `training_mAP50` | mAP @ IoU 0.5 |
| `training_recall` | Detection recall |
| `training_precision` | Detection precision |
| `training_loss` | Total training loss |
| `training_box_loss` | Bounding-box regression loss |
| `training_cls_loss` | Classification loss |
| `training_dfl_loss` | Distribution Focal Loss |
| `training_lr` | Learning rate |
| `training_curriculum_stage` | Curriculum stage (1–4) |
| `training_epoch_duration_seconds` | Wall-clock seconds per epoch |
| `training_gpu_memory_used_bytes` | GPU VRAM usage |

### Evaluation (pushed after eval pipeline)

| Metric | Description | KPI Target |
|--------|-------------|------------|
| `face_detection_map50` | mAP @ 0.5 | > 94 % |
| `face_detection_recall` | Recall | > 95 % |
| `face_detection_precision` | Precision | > 90 % |
| `face_detection_f1` | F1 score | — |
| `face_detection_map50_95` | mAP @ 0.5:0.95 | — |
| `face_detection_*_gap` | Distance to KPI target | ≤ 0 |
| `face_detection_meets_targets` | 1 if all KPIs met | 1 |

---

## SLO Monitoring

The **ML SLO Exporter** (`monitoring/ml-slo-exporter/slo_exporter.py`) runs as
a sidecar container, polling MLflow and Ray every 60 s to compute:

| Metric | Description | Alert threshold |
|--------|-------------|-----------------|
| `ml_model_freshness_days` | Days since last @champion registration | > 14 d warning, > 30 d critical |
| `ml_training_success_rate_7d` | 7-day training job success rate | < 90 % |
| `ml_error_budget_remaining_pct` | Monthly error-budget burn-down (target 99 %) | < 20 % |
| `ml_eval_completeness_ratio` | Fraction of models with eval results | < 95 % |
| `ml_inference_latency_p99_ms` | P99 inference latency | — |
| `ml_feature_freshness_minutes` | Feature materialization staleness | > 120 min |

These are scraped by Global Prometheus and visualised in the **ML SLO Overview**
dashboard.

---

## Alerting

Alert rules live in `monitoring/prometheus/alerts/` and are evaluated by
Global Prometheus every 15 s.

### ML SLO Alerts (`ml-slos.yml`)

| Alert | Expression | Severity |
|-------|-----------|----------|
| `ModelStale` | `ml_model_freshness_days > 14` (1 h) | warning |
| `ModelVeryStale` | `ml_model_freshness_days > 30` (1 h) | critical |
| `TrainingSuccessRateLow` | `ml_training_success_rate_7d < 0.90` (30 m) | warning |
| `ErrorBudgetExhausted` | `ml_error_budget_remaining_pct < 20` (15 m) | critical |
| `EvalIncomplete` | `ml_eval_completeness_ratio < 0.95` (2 h) | warning |
| `FeatureFreshnessBreached` | `ml_feature_freshness_minutes > 120` (30 m) | warning |

### Infrastructure Alerts (`platform-alerts.yml`)

| Alert | Expression | Severity |
|-------|-----------|----------|
| `HighCPUUsage` | CPU > 80 % for 5 m | warning |
| `HighMemoryUsage` | Memory > 85 % for 5 m | warning |
| `DiskSpaceLow` | Root filesystem < 15 % free for 5 m | warning |
| `ContainerDown` | Any core container unreachable for 2 m | critical |
| `ContainerHighMemory` | Container > 90 % of memory limit for 5 m | warning |
| `MLflowServerDown` | MLflow tracking server unreachable 1 m | critical |

---

## Data Flow — End to End

```
┌─────────────────────────┐
│  Training Job (Ray)     │
│  phase1_foundation.py   │
│  or SDK client.prometheus│
└───────────┬─────────────┘
            │  POST /metrics/job/…
            ▼
┌─────────────────────────┐
│  Pushgateway :9091      │   ◀── persists last-pushed value per metric
└───────────┬─────────────┘
            │  scraped every 15 s (honor_labels: true)
            ▼
┌─────────────────────────┐
│  Global Prometheus :9090│   ◀── also federates MLflow & Ray Prometheus
│  + alert rule evaluation│       + scrapes node/cAdvisor/DCGM/SLO/Traefik
└───────────┬─────────────┘
            │  PromQL queries
            ▼
┌─────────────────────────┐
│  Unified Grafana :3000  │   ◀── datasource uid: global-metrics
│  Dashboards (provisioned)│
└─────────────────────────┘
```

---

## Accessing Dashboards

### URLs

| Dashboard | Tailscale Funnel | Local |
|-----------|-----------------|-------|
| Unified Training | `/grafana/d/face-detection-unified/` | `http://localhost/grafana/d/face-detection-unified/` |
| ML SLO Overview | `/grafana/d/<uid>/` | via Grafana home → ML SLOs |
| GPU Monitoring | `/grafana/d/<uid>/` | via Grafana home → Platform |
| Prometheus UI | `/prometheus/` | `http://localhost:9090/` |
| Pushgateway UI | `/pushgateway/` | `http://localhost:9091/` |

!!! tip "Quick verification"
    ```bash
    # Check pushgateway has metrics
    curl -s http://localhost:9091/metrics | grep training_

    # Check Prometheus can reach pushgateway
    docker exec global-prometheus wget -qO- http://shml-pushgateway:9091/metrics | head

    # List Grafana datasources
    curl -s http://localhost/grafana/api/datasources | python3 -m json.tool
    ```

### Useful PromQL Queries

```promql
# Latest mAP50 across all evaluated models
face_detection_map50

# Training loss trend (last 6 hours)
training_loss[6h]

# GPU utilization (DCGM)
DCGM_FI_DEV_GPU_UTIL

# Model freshness SLO
ml_model_freshness_days

# Error budget burn rate
ml_error_budget_remaining_pct
```

---

## Configuration Files Reference

| File | Purpose |
|------|---------|
| `monitoring/global-prometheus.yml` | Global Prometheus scrape & federation config |
| `monitoring/prometheus/prometheus.yml` | Service-level Prometheus config |
| `monitoring/prometheus/alerts/ml-slos.yml` | ML SLO alert rules |
| `monitoring/prometheus/alerts/platform-alerts.yml` | Infrastructure alert rules |
| `monitoring/grafana/datasources.yml` | Grafana datasource provisioning |
| `monitoring/grafana/dashboards.yml` | Grafana dashboard provisioning paths |
| `monitoring/grafana/dashboards/` | All dashboard JSON files |
| `monitoring/ml-slo-exporter/slo_exporter.py` | ML SLO metric exporter |
| `docker-compose.infra.yml` | Container definitions for monitoring stack |
