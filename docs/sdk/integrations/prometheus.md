# Prometheus Metrics

The `PrometheusReporter` pushes training metrics to a [Prometheus Pushgateway](https://prometheus.io/docs/instrumenting/pushing/) for real-time monitoring in Grafana dashboards.

!!! info "Non-fatal by Design"
    All push operations are wrapped in try/except — metrics failures will
    **never** crash a training run. Methods silently return when
    `prometheus_client` is not installed.

---

## Class Reference

```python
class PrometheusReporter:
    def __init__(
        self,
        config: PlatformConfig | None = None,
        job_name: str = "training",
        grouping_key: dict[str, str] | None = None,
    )
```

| Parameter | Default | Description |
|---|---|---|
| `config` | `None` | Platform config; auto-detected from env if omitted |
| `job_name` | `"training"` | Pushgateway job label |
| `grouping_key` | `None` | Extra grouping labels (e.g., `{"model": "yolov8"}`) |

| Property | Type | Description |
|---|---|---|
| `available` | `bool` | `True` if `prometheus_client` is installed |

### Health Check

```python
def healthy(self) -> bool
```

Returns `True` if the Pushgateway's `/metrics` endpoint responds with 200.

### Metric Reporting

```python
def report_metric(self, name: str, value: float, description: str = "") -> None
def report_metrics(self, metrics: dict[str, float]) -> None
```

`report_metric` sets a single Gauge and pushes immediately.
`report_metrics` sets multiple Gauges and pushes once.

!!! note "Name Sanitization"
    Metric names are automatically sanitized: `.`, `-`, and `/` are replaced
    with `_` to comply with Prometheus naming rules.

### Epoch Reporting

```python
def report_epoch(
    self,
    epoch: int,
    total_epochs: int,
    metrics: dict[str, float],
    duration_seconds: float | None = None,
) -> None
```

Sets `training_epoch`, `training_total_epochs`, optional
`training_epoch_duration_seconds`, plus all provided metrics, then pushes.

### Training Lifecycle

```python
def report_training_start(
    self,
    experiment_name: str,
    total_epochs: int,
    batch_size: int,
    model: str = "",
) -> None

def report_training_end(
    self,
    success: bool = True,
    final_metrics: dict[str, float] | None = None,
) -> None
```

| Gauge | Set by | Values |
|---|---|---|
| `training_active` | `start` / `end` | `1` (running) or `0` (done) |
| `training_total_epochs` | `start` | Total epoch count |
| `training_batch_size` | `start` | Batch size |
| `training_start_time` | `start` | Unix timestamp |
| `training_end_time` | `end` | Unix timestamp |
| `training_success` | `end` | `1` (success) or `0` (failure) |

### GPU Metrics

```python
def report_gpu_metrics(
    self,
    gpu_id: int,
    utilization: float,
    memory_used_mb: float,
    memory_total_mb: float,
    temperature: float | None = None,
) -> None
```

Reports per-GPU gauges with the naming pattern `gpu_{id}_{metric}`.

### Cleanup

```python
def delete_metrics(self) -> None
```

Deletes all metrics for this job/grouping-key from the Pushgateway.

---

## Pushgateway Integration

All metrics are pushed via `prometheus_client.push_to_gateway`. The gateway
address is read from `PlatformConfig.pushgateway_uri` and the `http://` /
`https://` scheme prefix is stripped automatically.

Each `PrometheusReporter` instance maintains its own `CollectorRegistry`,
so multiple reporters (e.g., one per GPU) won't collide.

---

## Usage Examples

### Full Training Loop

```python
from shml import SHMLClient

client = SHMLClient()
prom = client.prometheus

prom.report_training_start(
    experiment_name="yolo-v8-coco",
    total_epochs=100,
    batch_size=16,
    model="yolov8n",
)

for epoch in range(100):
    # ... train ...
    prom.report_epoch(
        epoch=epoch,
        total_epochs=100,
        metrics={"loss": 0.35, "mAP50": 0.80},
        duration_seconds=42.5,
    )

prom.report_training_end(
    success=True,
    final_metrics={"best_mAP50": 0.85},
)
prom.delete_metrics()  # clean up Pushgateway
```

---

## Error Handling

Push failures are silently ignored. Use `healthy()` to verify Pushgateway
connectivity before training if you need early warning.
