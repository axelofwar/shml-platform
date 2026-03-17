# MLflow Integration

The `MLflowClient` is a thin wrapper around the `mlflow` package that manages tracking URI lifecycle and solves the **Ultralytics MLflow URI conflict**.

!!! warning "Ultralytics Conflict"
    YOLO's built-in MLflow integration reads `MLFLOW_TRACKING_URI` and attempts
    to log to a local file store, colliding with the platform's remote tracking
    server. `MLflowClient` provides explicit helpers to blank and restore the
    URI around `model.train()` calls.

---

## Class Reference

```python
class MLflowClient:
    def __init__(self, config: PlatformConfig | None = None)
```

| Property | Type | Description |
|---|---|---|
| `run_id` | `str \| None` | Active MLflow run ID |
| `experiment_id` | `str \| None` | Active experiment ID |

### Experiment Setup

```python
def setup_experiment(
    self,
    experiment_name: str,
    run_name: str,
    tags: dict[str, str] | None = None,
) -> str | None
```

Creates or retrieves an experiment and starts a new run. Returns the `run_id`.

### Logging

```python
def log_params(self, params: dict[str, Any]) -> None
def log_metric(self, key: str, value: float, step: int | None = None) -> None
def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None
def log_artifact(self, local_path: str, artifact_path: str | None = None) -> None
```

!!! info
    Parameter values are truncated to 250 characters. Metric logging failures
    are silently swallowed to avoid crashing a training loop.

### Model Registry

```python
def register_model(self, model_uri: str, name: str) -> Any
```

Registers a model in the MLflow model registry and returns the `ModelVersion` object.

### Run Lifecycle

```python
def end_run(self, status: str = "FINISHED") -> None
```

Ends the active run with the given status (`FINISHED`, `FAILED`, `KILLED`).

---

## URI Conflict Management

These two methods bracket an Ultralytics `model.train()` call to prevent YOLO
from hijacking the tracking URI.

```python
def suppress_for_ultralytics(self) -> str
def restore_after_ultralytics(self, original_uri: str = "") -> None
```

| Method | When to Call | Returns |
|---|---|---|
| `suppress_for_ultralytics` | **Before** `model.train()` | Original URI string |
| `restore_after_ultralytics` | **After** `model.train()` | `None` |

---

## Usage Examples

### Basic Experiment

```python
from shml import SHMLClient

client = SHMLClient()
mlflow = client.mlflow

mlflow.setup_experiment("yolo-detection", run_name="run-001")
mlflow.log_params({"epochs": 100, "batch_size": 16, "imgsz": 640})

for epoch in range(100):
    mlflow.log_metrics({"loss": 0.42, "mAP50": 0.78}, step=epoch)

mlflow.log_artifact("runs/detect/train/weights/best.pt")
mlflow.register_model(f"runs:/{mlflow.run_id}/model", "yolo-detector")
mlflow.end_run()
```

### With Ultralytics YOLO

```python
from ultralytics import YOLO
from shml import SHMLClient

client = SHMLClient()
mlflow = client.mlflow

# 1. Set up experiment BEFORE suppressing
mlflow.setup_experiment("yolo-v8", run_name="train-001")

# 2. Suppress URI so YOLO doesn't conflict
original_uri = mlflow.suppress_for_ultralytics()

# 3. Train — YOLO won't touch MLflow
model = YOLO("yolov8n.pt")
results = model.train(data="coco128.yaml", epochs=50)

# 4. Restore and log our own metrics
mlflow.restore_after_ultralytics(original_uri)
mlflow.log_metrics({"final_mAP50": 0.85})
mlflow.end_run()
```

!!! tip
    The internal `_ensure_tracking_uri()` method is called before every logging
    operation as an extra safety net — if the URI drifts it is silently corrected.

---

## Error Handling

All methods raise `shml.exceptions.MLflowError` on failure, except
`log_metric` / `log_metrics` which are intentionally silent to avoid
interrupting training loops.
