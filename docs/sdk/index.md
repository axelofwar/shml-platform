# SDK Overview

The SHML Python SDK provides a unified interface for job submission, training configuration, GPU management, and platform integrations — all from Python or the CLI.

!!! info "Version"
    Current SDK version: **1.0.0**

## Installation

=== "Standard"

    ```bash
    pip install -e sdk/
    ```

=== "With Training Extras"

    ```bash
    pip install -e "sdk/[training]"
    ```

    The `[training]` extra installs Ultralytics, MLflow, and other dependencies
    required for local `TrainingRunner` execution.

## Quick Start

### Submit a training job

```python
from shml import Client

with Client() as c:
    job = c.submit_training("balanced", epochs=10)
    print(job)  # Job(id='abc123', name='train-yolo11x-...', status='PENDING')

    final = c.wait_for_job(job.job_id, timeout=7200)
    print(c.job_logs(final.job_id))
```

### Load and customize a training config

```python
from shml.config import TrainingConfig

cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml", epochs=20)
print(cfg.to_ultralytics_dict())  # flat dict for YOLO model.train()
```

### Run training locally with integrations

```python
from shml.config import TrainingConfig
from shml.training.runner import TrainingRunner

cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml")
runner = TrainingRunner(cfg)
results = runner.run()
# Automatically wires MLflow, Nessie, FiftyOne, Prometheus
```

### Access integration sub-clients

```python
from shml import Client

with Client() as c:
    c.mlflow.setup_experiment("my-experiment")
    c.nessie.create_experiment_branch("exp-1")
    health = c.health_check()
    print(health)
    # {'mlflow': True, 'nessie': True, 'fiftyone': True, ...}
```

### Check GPU status

```python
from shml import Client

with Client() as c:
    gpus = c.gpu_status()
    for gpu in gpus:
        print(gpu)

    c.gpu_yield()   # Free GPU from inference for training
    c.gpu_reclaim() # Restart inference after training
```

## Module Overview

| Module | Description |
|--------|-------------|
| `shml.client` | API client — job submission, GPU ops, integration access |
| `shml.config` | Dataclass configs — `PlatformConfig`, `TrainingConfig`, `JobConfig`, `AuthConfig` |
| `shml.training.runner` | Declarative training runner with integration lifecycle |
| `shml.exceptions` | Typed exception hierarchy (`SHMLError` and subclasses) |
| `shml.integrations.mlflow` | MLflow experiment tracking and model registry |
| `shml.integrations.nessie` | Nessie catalog branching for Iceberg tables |
| `shml.integrations.fiftyone` | FiftyOne dataset visualization and analysis |
| `shml.integrations.features` | Feature store client |
| `shml.integrations.prometheus` | Prometheus/Pushgateway metrics reporting |

## Exception Hierarchy

All SDK exceptions inherit from `SHMLError`:

```
SHMLError
├── AuthenticationError      (401)
├── PermissionDeniedError    (403)
├── NotFoundError            (404)
├── RateLimitError           (429)
├── JobError
│   ├── JobSubmissionError
│   ├── JobTimeoutError
│   └── JobCancelledError
├── ConfigError
│   ├── ProfileNotFoundError
│   └── ValidationError
└── IntegrationError
    ├── MLflowError
    ├── NessieError
    ├── FiftyOneError
    └── FeatureStoreError
```

!!! tip "Broad vs. Narrow Catches"
    Catch `SHMLError` for all SDK errors, or use specific subclasses for
    targeted handling. Integration errors are **non-fatal** — training
    continues even when an integration is unavailable.

## Configuration Resolution Order

The SDK resolves configuration from multiple sources (highest priority first):

1. **Constructor arguments** / CLI flags
2. **Environment variables** (`SHML_*`, `MLFLOW_*`, `NESSIE_*`, etc.)
3. **Credentials file** (`~/.shml/credentials`, INI format)
4. **Config file** (`config/platform.env` or YAML profile)
5. **Built-in defaults** (Docker-internal service discovery)
