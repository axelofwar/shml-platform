# Client Reference

::: shml.client.Client
    options:
      show_source: false

The `Client` class is the primary entry point for interacting with the SHML Platform API. It handles authentication, job lifecycle, GPU management, and provides lazy access to integration sub-clients.

## Constructor

```python
class Client:
    def __init__(
        self,
        auth: AuthConfig | None = None,
        platform: PlatformConfig | None = None,
        timeout: float = 30.0,
        api_prefix: str = "/api/ray",
    ):
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `auth` | `AuthConfig \| None` | `None` | Authentication config. Reads env / credentials file if omitted. |
| `platform` | `PlatformConfig \| None` | `None` | Platform config. Reads env if omitted. |
| `timeout` | `float` | `30.0` | HTTP request timeout in seconds. |
| `api_prefix` | `str` | `"/api/ray"` | API path prefix (Traefik routing). |

## Context Manager

The client implements the context manager protocol for clean resource lifecycle:

```python
from shml import Client
from shml.config import AuthConfig

# Auto-resolve credentials from env / ~/.shml/credentials
with Client() as c:
    job = c.submit_training("balanced")

# Explicit auth
with Client(auth=AuthConfig(api_key="shml_xxx")) as c:
    print(c.whoami())
```

Calling `close()` or exiting the `with` block closes the underlying `httpx.Client`.

---

## Job Operations

### `submit_training`

```python
def submit_training(
    self,
    profile: str | None = None,
    config: TrainingConfig | None = None,
    **overrides: Any,
) -> Job:
```

Submit a training job from a named profile or explicit `TrainingConfig`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `profile` | `str \| None` | Named profile (e.g. `"balanced"`, `"quick-test"`). |
| `config` | `TrainingConfig \| None` | Explicit config (takes priority over profile). |
| `**overrides` | `Any` | Override any `TrainingConfig` field. |

**Returns:** `Job` — lightweight handle with `job_id`, `name`, `status`.

```python
# From profile
job = c.submit_training("balanced", epochs=20)

# From explicit config
from shml.config import TrainingConfig
cfg = TrainingConfig(model="yolo11l.pt", epochs=5, batch=8)
job = c.submit_training(config=cfg)
```

### `submit_script`

```python
def submit_script(
    self,
    script_path: str,
    args: list[str] | None = None,
    name: str | None = None,
    gpu: float = 0.0,
    cpu: int = 4,
    memory_gb: int = 16,
    timeout_hours: int = 4,
    requirements: list[str] | None = None,
    **kwargs: Any,
) -> Job:
```

Submit an arbitrary Python script as a job. The script is base64-encoded and sent to the platform.

```python
job = c.submit_script(
    "scripts/evaluate.py",
    args=["--model", "best.pt"],
    gpu=1.0,
    requirements=["torch>=2.0", "ultralytics"],
)
```

### `job_status`

```python
def job_status(self, job_id: str) -> Job:
```

Returns the current `Job` state for the given ID.

```python
job = c.job_status("abc123")
print(job.status)  # "RUNNING", "SUCCEEDED", "FAILED", etc.
```

### `job_logs`

```python
def job_logs(self, job_id: str) -> str:
```

Returns the full log output for a job as a string.

```python
logs = c.job_logs("abc123")
print(logs)
```

### `cancel_job`

```python
def cancel_job(self, job_id: str, reason: str | None = None) -> Job:
```

Cancel a running or pending job.

```python
job = c.cancel_job("abc123", reason="Superseded by new run")
print(job.status)  # "CANCELLED"
```

### `list_jobs`

```python
def list_jobs(
    self,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> list[Job]:
```

List jobs with optional pagination and status filtering.

```python
running = c.list_jobs(status="RUNNING")
for job in running:
    print(f"{job.job_id}: {job.name} [{job.status}]")
```

### `wait_for_job`

```python
def wait_for_job(
    self,
    job_id: str,
    poll_interval: float = 10.0,
    timeout: float = 3600.0,
) -> Job:
```

Block until a job reaches a terminal state (`SUCCEEDED`, `FAILED`, `STOPPED`, `CANCELLED`).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `job_id` | `str` | — | Job to wait for. |
| `poll_interval` | `float` | `10.0` | Seconds between status polls. |
| `timeout` | `float` | `3600.0` | Maximum seconds to wait. |

**Raises:** `JobTimeoutError` if the job doesn't finish within the timeout.

```python
job = c.submit_training("balanced")
final = c.wait_for_job(job.job_id, timeout=7200)
if final.status == "SUCCEEDED":
    print("Training complete!")
```

---

## GPU Management

### `gpu_status`

```python
def gpu_status(self) -> list[dict[str, Any]]:
```

Returns GPU status from the platform. Returns an empty list on failure.

```python
gpus = c.gpu_status()
for gpu in gpus:
    print(f"GPU {gpu['id']}: {gpu['utilization']}% util")
```

### `gpu_yield`

```python
def gpu_yield(self, gpu_ids: list[int] | None = None) -> dict[str, Any]:
```

Yield GPU resources for training by stopping inference containers. Optionally specify which GPU IDs to yield.

```python
c.gpu_yield()             # Yield all GPUs
c.gpu_yield(gpu_ids=[0])  # Yield only GPU 0
```

### `gpu_reclaim`

```python
def gpu_reclaim(self) -> dict[str, Any]:
```

Reclaim GPU resources by restarting inference containers after training completes.

```python
c.gpu_reclaim()
```

---

## Integration Sub-Clients

Integration clients are created **lazily** on first access. Each property imports and instantiates the corresponding integration client with the current `PlatformConfig`.

| Property | Type | Description |
|----------|------|-------------|
| `client.mlflow` | `MLflowClient` | Experiment tracking, model registry |
| `client.nessie` | `NessieClient` | Iceberg catalog branching |
| `client.fiftyone` | `FiftyOneClient` | Dataset visualization |
| `client.features` | `FeatureClient` | Feature store access |
| `client.prometheus` | `PrometheusReporter` | Metrics push to Pushgateway |

```python
with Client() as c:
    # MLflow — setup experiment and log params
    run_id = c.mlflow.setup_experiment("face-detection-v2")
    c.mlflow.log_params({"epochs": 10, "batch": 4})

    # Nessie — create versioned branch
    branch = c.nessie.create_experiment_branch("exp-1")

    # FiftyOne — check availability
    if c.fiftyone.available:
        c.fiftyone.load_dataset("wider-face")
```

!!! note "Import Cost"
    Integration clients are imported lazily to avoid requiring all
    dependencies upfront. If an integration package is not installed,
    the import will fail only when that property is accessed.

---

## Platform Health

### `health_check`

```python
def health_check(self) -> dict[str, bool]:
```

Check the health of all integrated services. Returns a dict mapping each service name to a boolean.

```python
health = c.health_check()
# {'mlflow': True, 'nessie': True, 'fiftyone': False, 'features': True, 'prometheus': True}

unhealthy = [k for k, v in health.items() if not v]
if unhealthy:
    print(f"Unhealthy services: {unhealthy}")
```

---

## Job Handle

The `Job` class is a lightweight data object returned by submission and status methods:

```python
class Job:
    def __init__(self, job_id: str, name: str, status: str, **extra: Any):
        self.job_id = job_id
        self.name = name
        self.status = status
        self.extra = extra
```

Terminal statuses: `SUCCEEDED`, `FAILED`, `STOPPED`, `CANCELLED`.
