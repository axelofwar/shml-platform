# MLflow — Experiment Tracking & Model Registry

SHML Platform uses [MLflow](https://mlflow.org/) as its central experiment
tracker and model registry. Every training run—SDK, CLI, or Ray job—logs
metrics, parameters, and artifacts to a single MLflow instance backed by
PostgreSQL.

---

## Architecture

```
┌──────────────┐      ┌───────────────┐      ┌────────────┐
│  SDK / CLI   │─────▶│  mlflow-nginx │─────▶│  MLflow    │
│  Ray Jobs    │ :80  │  (reverse     │      │  Server    │
│  Notebooks   │      │   proxy)      │      │            │
└──────────────┘      └───────────────┘      └─────┬──────┘
                                                   │
                                    ┌──────────────┴──────────────┐
                                    │                             │
                              ┌─────▼─────┐             ┌────────▼────────┐
                              │ PostgreSQL │             │ Artifact Store  │
                              │ (metadata) │             │ /mlflow/        │
                              └───────────┘             │  artifacts/     │
                                                        └─────────────────┘
```

| Component | Role |
|-----------|------|
| **mlflow-nginx** | Nginx reverse proxy, listens on port **80** inside the Docker network |
| **MLflow Server** | Tracking API + Model Registry API |
| **PostgreSQL** | Persistent backend store (experiments, runs, params, metrics, tags) |
| **Artifact volume** | `/mlflow/artifacts/{experiment_id}/{run_id}/` — models, checkpoints, plots |

!!! warning "Tracking URI conflict with Ultralytics"
    Ultralytics (YOLOv8) ships its own MLflow callback that sets the tracking
    URI to a local `./mlruns` directory. SHML always overrides the URI **before**
    training starts:

    ```python
    mlflow.set_tracking_uri("http://mlflow-nginx:80")
    ```

    If you see runs landing in a local `mlruns/` folder, the override was
    skipped. Ensure the URI is set before any `ultralytics` import triggers
    auto-logging.

---

## Quick Start

### SDK

```python
from shml import Client

client = Client()

# The MLflow sub-client is pre-configured with the correct tracking URI
client.mlflow.set_experiment("my-experiment")

with client.mlflow.start_run(run_name="baseline"):
    client.mlflow.log_params({"lr": 0.001, "epochs": 100})
    # ... training loop ...
    client.mlflow.log_metrics({"mAP50": 94.2, "recall": 82.1})
    client.mlflow.log_artifact("best.pt")
```

### CLI

```bash
# Auto-logs hyperparameters, metrics, and artifacts to MLflow
shml train --profile balanced
```

The `balanced` profile maps to curated hyperparameters. The CLI creates (or
reuses) an experiment and starts an MLflow run automatically.

### Direct MLflow API

```python
import mlflow

mlflow.set_tracking_uri("http://mlflow-nginx:80")
mlflow.set_experiment("Face-Detection-Training")

with mlflow.start_run(run_name="yolov8l-200ep"):
    mlflow.log_params({"model": "yolov8l", "epochs": 200, "imgsz": 1280})
    # ... train ...
    mlflow.log_metric("mAP50", 94.2, step=200)
    mlflow.log_artifact("runs/detect/weights/best.pt")
```

!!! tip
    `mlflow.set_experiment()` is idempotent—it creates the experiment on the
    first call and reuses it on subsequent calls. No duplicate experiments are
    created.

---

## Experiment Tracking

### Parameters

Log hyperparameters once per run. They are immutable and searchable.

```python
mlflow.log_params({
    "model": "yolov8l-face-lindevs.pt",
    "epochs": 200,
    "batch_size": 4,
    "imgsz": 1280,
    "optimizer": "AdamW",
    "lr0": 0.001,
    "label_smoothing": 0.1,
    "multiscale_enabled": True,
})
```

### Metrics

Log time-series metrics with a `step` argument for epoch-level granularity.

```python
for epoch in range(epochs):
    # ... training step ...
    mlflow.log_metrics({
        "mAP50": map50,
        "recall": recall,
        "precision": precision,
        "train_loss": train_loss,
        "val_loss": val_loss,
        "learning_rate": lr,
    }, step=epoch)
```

### Tags

Attach free-form metadata to runs for filtering in the UI.

```python
mlflow.set_tags({
    "model_type": "face_detection",
    "architecture": "yolov8l",
    "dataset": "wider_face",
    "purpose": "privacy_protection",
})
```

### Comparing Runs

```python
from mlflow.tracking import MlflowClient

client = MlflowClient()
runs = client.search_runs(
    experiment_ids=["28"],
    filter_string="params.epochs = '200'",
    order_by=["metrics.mAP50 DESC"],
)

for run in runs[:5]:
    print(f"{run.info.run_name}: mAP50={run.data.metrics['mAP50']:.2f}%")
```

---

## Model Registry

The Model Registry provides versioning, aliasing, and lifecycle management.

### Registering a Model

```python
model_uri = f"runs:/{run_id}/model"
mlflow.register_model(model_uri, name="face-detection-yolov8l")
```

Each call creates a new **version** under the registered model name.

### Lifecycle Stages

| Stage | Meaning |
|-------|---------|
| **None** | Just registered, not yet evaluated |
| **Staging** | Under evaluation / QA |
| **Production** | Serving live traffic |
| **Archived** | Superseded; kept for lineage |

```python
client = MlflowClient()

# Promote to Production (archives previous Production version)
client.transition_model_version_stage(
    name="face-detection-yolov8l",
    version=2,
    stage="Production",
    archive_existing_versions=True,
)
```

### Aliases

Aliases provide mutable pointers to a specific version.

```python
client.set_registered_model_alias("face-detection-yolov8l", "champion", "2")
model = mlflow.pyfunc.load_model("models:/face-detection-yolov8l@champion")
```

---

## Artifact Management

Artifacts are stored at `/mlflow/artifacts/{experiment_id}/{run_id}/artifacts/`.

### Typical Artifact Tree

```
{run_id}/artifacts/
├── model/               # Serialized model (PyTorch, ONNX, etc.)
├── checkpoints/         # Intermediate training checkpoints
├── plots/               # Metrics visualisations
├── exports/
│   ├── best.onnx        # ONNX export
│   └── best.engine      # TensorRT FP16
└── analysis/
    └── failure_analysis.json
```

### Logging & Retrieving

```python
# Log
mlflow.log_artifact("best.pt")
mlflow.log_artifacts("exports/", artifact_path="exports")

# Retrieve
best_run = client.search_runs(
    experiment_ids=["28"],
    order_by=["metrics.mAP50 DESC"],
    max_results=1,
)[0]
checkpoint = f"runs:/{best_run.info.run_id}/artifacts/best.pt"
```

---

## Monitoring & UI

### Accessing the UI

| Network | URL |
|---------|-----|
| Internal (Docker) | `http://mlflow-nginx:80` |
| Tailscale Funnel | `https://shml-platform.tail38b60a.ts.net/mlflow/` |

The UI surfaces experiments, run details (parameter tables, metric charts,
artifact browser), comparison views, and the Model Registry.

---

## Platform Integration Details

### How Training Jobs Use MLflow

Training scripts (e.g. `ray_compute/jobs/training/phase1_foundation.py`)
follow a standard pattern:

```python
mlflow.set_tracking_uri("http://mlflow-nginx:80")   # 1. Point to server
mlflow.set_experiment("Phase1-WIDER-Balanced")       # 2. Create / reuse experiment
run = mlflow.start_run(run_name=run_name, tags=tags) # 3. Open run
mlflow.log_params(hyperparameters)                   # 4. Record config

# During training — every epoch
mlflow.log_metric("mAP50", value, step=epoch)

# After training
mlflow.log_artifact("best.pt")
mlflow.register_model(model_uri, "yolov8l-face-phase1")
mlflow.end_run()
```

!!! note "No custom wrappers required"
    All tracking uses the native MLflow Python API. The SHML SDK
    (`client.mlflow`) is a thin convenience layer that pre-sets the tracking
    URI and adds default tags—it does **not** replace any MLflow functions.

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MLFLOW_TRACKING_URI` | `http://mlflow-nginx:80` | Server address |
| `MLFLOW_EXPERIMENT_NAME` | `Development-Training` | Default experiment |

---

## Design Decisions

!!! info "Research basis"
    The decisions below are informed by a survey of governance patterns at
    Databricks, AWS SageMaker, Azure ML, and open-source MLflow deployments
    (Netflix, Uber, Airbnb style wrappers). Full analysis in
    `docs/internal/MLFLOW_GOVERNANCE_ANALYSIS.md`.

### Why no server-side naming enforcement?

No major provider enforces strict experiment naming at the MLflow API level.
Industry practice relies on:

1. **Workspace / namespace isolation** — users see only their own experiments.
2. **Tag-based organisation** — required tags for filtering and cost allocation.
3. **Client-side wrappers** — friendly validation before the API call.
4. **Post-creation governance** — audit logs, cleanup policies.

SHML follows this pattern: the SDK wrapper validates names and tags
client-side, while PostgreSQL constraints provide a safety net at the data
layer.

### Governance layers (defence in depth)

```
SDK / CLI wrapper      →  friendly validation + auto-tags
Nginx reverse proxy    →  route-level access control
MLflow auth plugin     →  permission checks (FusionAuth OAuth)
PostgreSQL             →  data-integrity constraints, audit triggers
```

### Model registry over loose artifacts

All production models **must** be registered in the Model Registry rather than
stored as plain run artifacts. Registration provides:

- Automatic version numbering
- Stage lifecycle (Staging → Production → Archived)
- Alias pointers (`@champion`, `@challenger`)
- Lineage back to the training run, dataset, and parameters

### Dataset lineage

Datasets are logged via `mlflow.log_input()` so that every model version
records which data it was trained on. A dedicated `Dataset-Registry`
experiment stores versioned dataset artifacts when full traceability is
needed.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Runs appear in local `mlruns/` | Tracking URI not set before Ultralytics import | Set `mlflow.set_tracking_uri()` **first** |
| `ConnectionError` to MLflow | `mlflow-nginx` container not running | `docker compose up -d mlflow-nginx` |
| Duplicate experiments | Different casing or trailing slash | Use exact, consistent names |
| Artifact upload fails | Artifact volume not mounted | Check Docker volume mount for `/mlflow/artifacts` |
| Model registration 403 | Missing permissions | Verify FusionAuth token / OAuth scope |
