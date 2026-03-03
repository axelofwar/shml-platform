# Configuration

The SHML Platform uses a layered configuration system built on Python dataclasses,
YAML profiles, and environment variables. Everything resolves through a clear
priority chain so you always know which value wins.

---

## Resolution Order

Values are resolved from **highest to lowest** priority:

1. **Constructor arguments / CLI flags** — `--epochs 5`
2. **Environment variables** — `SHML_*`, `MLFLOW_*`, `RAY_*`
3. **Credentials file** — `~/.shml/credentials` (INI format)
4. **Config file** — `config/platform.env` or YAML profile
5. **Built-in defaults** — Docker-internal service discovery

---

## Platform Environment — `config/platform.env`

This file contains **non-sensitive** service-discovery variables consumed by every
container via `env_file` in Docker Compose. It maps 1:1 to a Kubernetes ConfigMap
for future migration.

!!! warning "No secrets here"

    Passwords, tokens, and API keys belong in `secrets/` files — never in `platform.env`.

### Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `postgres` | PostgreSQL hostname (Docker DNS) |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `REDIS_HOST` | `redis` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `MLFLOW_TRACKING_URI` | `http://mlflow-nginx:80` | MLflow server URL |
| `MLFLOW_REGISTRY_MODEL_NAME` | `face-detection-yolov8l-p2` | Default model registry name |
| `MLFLOW_ARTIFACT_ROOT` | `/mlflow/artifacts` | Artifact storage path |
| `RAY_HEAD_ADDRESS` | `ray-head:6379` | Ray GCS address |
| `RAY_ADDRESS` | `http://ray-head:8265` | Ray dashboard / Jobs API |
| `PROMETHEUS_HOST` | `global-prometheus` | Prometheus hostname |
| `GRAFANA_HOST` | `unified-grafana` | Grafana hostname |
| `LOKI_HOST` | `loki` | Log aggregation host |
| `TEMPO_HOST` | `tempo` | Distributed tracing host |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | OpenTelemetry collector |
| `FUSIONAUTH_HOST` | `fusionauth` | Identity provider host |
| `PLATFORM_VERSION` | `2.0` | Platform release version |
| `PLATFORM_ENV` | `production` | Environment tag |
| `PLATFORM_PREFIX` | `shml` | Namespace prefix |

### Loading in Python

```python
from shml.config import PlatformConfig

# Reads env vars → platform.env → defaults
platform = PlatformConfig.from_env()

print(platform.mlflow_uri)       # http://mlflow-nginx:80
print(platform.ray_head_address) # ray-head:6379
```

`PlatformConfig` is a **frozen dataclass** — immutable after creation.

---

## Training Profiles

Profiles are YAML files in `config/profiles/` that bundle hyperparameters,
augmentation settings, and integration toggles into reusable presets.

### Built-in Profiles

| Profile | Epochs | Image Size | Use Case |
|---------|--------|-----------|----------|
| `quick-test` | 2 | 640 | Pipeline validation, CI smoke tests |
| `balanced` | 10 | 1280 | Production training, good time/quality tradeoff |
| `foundation` | — | — | Base model pre-training |
| `full-finetune` | — | — | Exhaustive fine-tuning |

### Profile Anatomy

```yaml title="config/profiles/balanced.yaml"
# Core hyperparameters
model: yolo11x.pt
data_yaml: wider_face_yolo/data.yaml
epochs: 10
batch_size: 4
imgsz: 1280
patience: 10
optimizer: AdamW
lr0: 0.0005
lrf: 0.01
weight_decay: 0.001
warmup_epochs: 2.0

# Platform integrations to activate
integrations:
  - mlflow
  - nessie
  - fiftyone
  - features
  - prometheus

mlflow_experiment: balanced-training
nessie_branch_prefix: experiment

# Augmentation block
augmentation:
  mosaic: 0.8
  mixup: 0.1
  copy_paste: 0.05
  fliplr: 0.5
  erasing: 0.2
  # ... see AugmentationConfig for all fields

# GPU resource management
gpu_yield: true
```

### Creating a Custom Profile

1. Copy an existing profile:

    ```bash
    cp config/profiles/balanced.yaml config/profiles/my-experiment.yaml
    ```

2. Edit the YAML — all fields from `TrainingConfig` are valid top-level keys.

3. Run it:

    ```bash
    shml train --profile my-experiment
    ```

!!! tip "CLI overrides always win"

    Any flag passed on the command line overrides the profile value:

    ```bash
    shml train --profile balanced --epochs 20 --batch 2
    ```

### Loading Profiles in Python

```python
from shml.config import TrainingConfig, JobConfig

# Load profile
cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml")

# Load with overrides
cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml", epochs=5, batch=2)

# Full job config (training + platform + resources)
job = JobConfig.from_profile("balanced", epochs=5)
print(job.training.lr0)       # 0.0005  (from profile)
print(job.training.epochs)    # 5       (override)
print(job.platform.mlflow_uri)  # resolved from env
```

---

## Authentication — `AuthConfig`

`AuthConfig` manages credentials for remote access to the platform via
the Tailscale-exposed API.

### Resolution Order

1. **Constructor arguments**
2. **Environment variables** — `SHML_API_KEY`, `SHML_OAUTH_TOKEN`, `SHML_BASE_URL`
3. **Credentials file** — `~/.shml/credentials`
4. **Defaults**

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SHML_BASE_URL` | Platform URL (default: Tailscale HTTPS endpoint) |
| `SHML_API_KEY` | API key for key-based auth |
| `SHML_OAUTH_TOKEN` | OAuth2 bearer token |
| `SHML_API_PREFIX` | API route prefix (default: `/api/ray`) |
| `SHML_INTERNAL` | Set to `true` to bypass auth and use Docker DNS |

### Credentials File

Store credentials in `~/.shml/credentials` (INI format, mode `0600`):

```ini title="~/.shml/credentials"
[default]
base_url = https://shml-platform.tail38b60a.ts.net
api_key = your-api-key-here

[staging]
base_url = https://staging.example.com
oauth_token = eyJhbGciOi...
```

#### Save credentials programmatically:

```python
from shml.config import AuthConfig

auth = AuthConfig(
    base_url="https://shml-platform.tail38b60a.ts.net",
    api_key="sk-my-key-here",
)
auth.save()  # writes to ~/.shml/credentials with 0600 permissions
```

#### Load credentials:

```python
auth = AuthConfig.from_env()               # default profile
auth = AuthConfig.from_env("staging")       # named profile

print(auth.effective_base_url)  # respects SHML_INTERNAL
print(auth.auth_headers)        # {"X-API-Key": "..."} or {"Authorization": "Bearer ..."}
```

!!! note "Internal mode"

    When running **inside** the platform (e.g., in a Ray worker), set
    `SHML_INTERNAL=true` to skip authentication and route directly via
    Docker DNS to `http://ray-compute-api:8000`.

---

## Summary

```
┌─────────────────────────────────────────────────────┐
│                   Configuration                     │
├───────────────────┬─────────────────────────────────┤
│ PlatformConfig    │ Service discovery & infra        │
│                   │ Source: platform.env + env vars  │
├───────────────────┼─────────────────────────────────┤
│ TrainingConfig    │ Hyperparameters & augmentation   │
│                   │ Source: YAML profiles + CLI      │
├───────────────────┼─────────────────────────────────┤
│ JobConfig         │ Resources + training + platform  │
│                   │ Source: profiles + auto-resolve  │
├───────────────────┼─────────────────────────────────┤
│ AuthConfig        │ Remote access credentials        │
│                   │ Source: env + ~/.shml/credentials│
└───────────────────┴─────────────────────────────────┘
```
