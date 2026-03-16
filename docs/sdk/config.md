# Configuration Reference

The `shml.config` module provides dataclass-driven configuration with YAML serialization and environment variable resolution.

!!! abstract "Resolution Order (highest → lowest)"
    1. Constructor arguments / CLI flags
    2. Environment variables (`SHML_*`, `MLFLOW_*`, `NESSIE_*`, etc.)
    3. Credentials file (`~/.shml/credentials`, INI format)
    4. Config file (`config/platform.env` or YAML profile)
    5. Built-in defaults (Docker-internal service discovery)

---

## PlatformConfig

```python
@dataclass(frozen=True)
class PlatformConfig:
```

Infrastructure and service discovery configuration. Maps 1:1 to `config/platform.env`. All defaults assume Docker-internal DNS names.

### Fields

| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `postgres_host` | `str` | `"postgres"` | `POSTGRES_HOST` |
| `postgres_port` | `int` | `5432` | `POSTGRES_PORT` |
| `redis_host` | `str` | `"redis"` | `REDIS_HOST` |
| `redis_port` | `int` | `6379` | `REDIS_PORT` |
| `mlflow_uri` | `str` | `"http://mlflow-nginx:80"` | `MLFLOW_TRACKING_URI` |
| `mlflow_experiment` | `str` | `"Face-Detection"` | `MLFLOW_EXPERIMENT_NAME` |
| `mlflow_registry_model` | `str` | `"face-detection-yolov8"` | `MLFLOW_REGISTRY_MODEL_NAME` |
| `mlflow_artifact_root` | `str` | `"/tmp/ray/mlflow-artifacts"` | `MLFLOW_ARTIFACT_ROOT` |
| `ray_head_address` | `str` | `"ray-head:6379"` | `RAY_HEAD_ADDRESS` |
| `ray_dashboard_host` | `str` | `"ray-head"` | `RAY_DASHBOARD_HOST` |
| `ray_dashboard_port` | `int` | `8265` | `RAY_DASHBOARD_PORT` |
| `nessie_uri` | `str` | `"http://nessie:19120"` | `NESSIE_URI` |
| `nessie_api_version` | `str` | `"v1"` | — |
| `fiftyone_uri` | `str` | `"http://fiftyone:5151"` | — |
| `fiftyone_db_uri` | `str` | `"mongodb://fiftyone-mongodb:27017"` | `FIFTYONE_DATABASE_URI` |
| `prometheus_host` | `str` | `"prometheus"` | `PROMETHEUS_HOST` |
| `prometheus_port` | `int` | `9090` | `PROMETHEUS_PORT` |
| `grafana_host` | `str` | `"grafana"` | `GRAFANA_HOST` |
| `grafana_port` | `int` | `3000` | `GRAFANA_PORT` |
| `pushgateway_url` | `str` | `"shml-pushgateway:9091"` | `PUSHGATEWAY_URL` |
| `loki_host` | `str` | `"loki"` | `LOKI_HOST` |
| `loki_port` | `int` | `3100` | `LOKI_PORT` |
| `tempo_host` | `str` | `"tempo"` | `TEMPO_HOST` |
| `tempo_port` | `int` | `3200` | `TEMPO_PORT` |
| `otel_collector_host` | `str` | `"otel-collector"` | `OTEL_COLLECTOR_HOST` |
| `otel_exporter_endpoint` | `str` | `"http://otel-collector:4317"` | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| `fusionauth_host` | `str` | `"fusionauth"` | `FUSIONAUTH_HOST` |
| `fusionauth_port` | `int` | `9011` | `FUSIONAUTH_PORT` |
| `oauth2_proxy_host` | `str` | `"oauth2-proxy"` | — |
| `oauth2_proxy_port` | `int` | `4180` | — |
| `platform_version` | `str` | `"2.0"` | `PLATFORM_VERSION` |
| `platform_env` | `str` | `"production"` | `PLATFORM_ENV` |
| `platform_prefix` | `str` | `"shml"` | `PLATFORM_PREFIX` |

### `from_env()`

```python
@classmethod
def from_env(cls) -> PlatformConfig:
```

Build config from environment variables. Reads `SHML_*` and service-specific env vars, falls back to defaults. Also reads `config/platform.env` if present.

```python
from shml.config import PlatformConfig

platform = PlatformConfig.from_env()
print(platform.mlflow_uri)     # from MLFLOW_TRACKING_URI or default
print(platform.nessie_uri)     # from NESSIE_URI or default
```

!!! tip "Internal URI Override"
    The env var `MLFLOW_TRACKING_URI_INTERNAL` takes priority over
    `MLFLOW_TRACKING_URI` — used inside Docker containers where the
    internal DNS name differs from the external URL.

---

## TrainingConfig

```python
@dataclass
class TrainingConfig:
```

Training hyperparameters and model configuration. Can be loaded from YAML profiles or constructed programmatically. All defaults are tuned for fine-tuning on RTX 3090 Ti.

### Core Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `epochs` | `int` | `10` | Number of training epochs |
| `batch` | `int` | `4` | Batch size |
| `imgsz` | `int` | `1280` | Image size (pixels) |
| `device` | `str` | `"cuda:0"` | Training device |
| `optimizer` | `str` | `"AdamW"` | Optimizer name |

### Learning Rate Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `lr0` | `float` | `0.0001` | Initial learning rate |
| `lrf` | `float` | `0.01` | Final LR factor (`lr0 * lrf`) |
| `warmup_epochs` | `float` | `1.0` | Warmup epochs |
| `warmup_momentum` | `float` | `0.8` | Warmup momentum |
| `warmup_bias_lr` | `float` | `0.01` | Warmup bias LR |
| `momentum` | `float` | `0.937` | SGD momentum / Adam beta1 |
| `weight_decay` | `float` | `0.0005` | Weight decay |

### Loss Weights

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `box` | `float` | `7.5` | Box loss weight |
| `cls` | `float` | `0.5` | Classification loss weight |
| `dfl` | `float` | `1.5` | Distribution focal loss weight |

### Runtime Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `workers` | `int` | `4` | Dataloader workers |
| `patience` | `int` | `0` | Early stopping patience (0 = disabled) |
| `save_period` | `int` | `1` | Save checkpoint every N epochs |
| `nbs` | `int` | `64` | Nominal batch size |
| `single_cls` | `bool` | `True` | Single-class mode |
| `exist_ok` | `bool` | `True` | Overwrite existing output |
| `verbose` | `bool` | `True` | Verbose output |
| `val` | `bool` | `True` | Run validation |
| `plots` | `bool` | `True` | Generate plots |
| `deterministic` | `bool` | `True` | Deterministic training |
| `amp` | `bool` | `True` | Automatic mixed precision |
| `cache` | `bool` | `False` | Cache images in RAM |
| `rect` | `bool` | `False` | Rectangular training |
| `cos_lr` | `bool` | `False` | Cosine LR scheduler |
| `close_mosaic` | `int` | `10` | Disable mosaic last N epochs |
| `pretrained` | `bool` | `True` | Use pretrained weights |

### Model & Integration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `str` | `"yolo11x.pt"` | Model weights path |
| `checkpoint` | `str \| None` | `None` | Checkpoint to fine-tune from |
| `integrations` | `list[str]` | `["mlflow", "nessie", "fiftyone", "features", "prometheus"]` | Enabled integrations |
| `gpu_yield` | `bool` | `True` | Yield/reclaim GPU from inference |
| `mlflow_experiment` | `str` | `"Face-Detection"` | MLflow experiment name |
| `nessie_branch_prefix` | `str` | `"experiment"` | Nessie branch prefix |
| `data_yaml` | `str` | `"/tmp/ray/data/wider_face_yolo/data.yaml"` | Dataset YAML path |
| `augmentation` | `AugmentationConfig` | *(see below)* | Augmentation settings |

### Validation

`TrainingConfig.__post_init__()` validates:

- `batch >= 1`
- `lr0 > 0`
- `epochs >= 1`
- `imgsz >= 32`

### Methods

#### `from_yaml()`

```python
@classmethod
def from_yaml(cls, path: str | Path, **overrides: Any) -> TrainingConfig:
```

Load from a YAML profile file. Overrides are applied on top of the profile values (CLI flags take priority).

```python
cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml")
cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml", epochs=5, batch=2)
```

!!! note "Alias Handling"
    `batch_size` in YAML is automatically mapped to the `batch` field.

#### `to_yaml()`

```python
def to_yaml(self, path: str | Path | None = None) -> str:
```

Serialize to YAML string. Optionally writes to file (creates parent directories).

```python
yaml_str = cfg.to_yaml()
cfg.to_yaml("my-profile.yaml")  # writes to disk
```

#### `to_ultralytics_dict()`

```python
def to_ultralytics_dict(self) -> dict[str, Any]:
```

Convert to the flat dict that `YOLO.model.train()` expects. Augmentation fields are flattened into the top-level dict.

```python
train_args = cfg.to_ultralytics_dict()
model = YOLO("yolo11x.pt")
model.train(**train_args)
```

#### `from_dict()`

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> TrainingConfig:
```

Create from a flat dictionary (e.g., from an API request). Handles `batch_size` alias and nested `augmentation` dict.

---

## AugmentationConfig

```python
@dataclass
class AugmentationConfig:
```

Data augmentation hyperparameters for YOLO training.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mosaic` | `float` | `1.0` | Mosaic augmentation probability |
| `mixup` | `float` | `0.15` | MixUp probability |
| `copy_paste` | `float` | `0.1` | Copy-paste probability |
| `degrees` | `float` | `10.0` | Rotation degrees |
| `translate` | `float` | `0.2` | Translation fraction |
| `scale` | `float` | `0.9` | Scale factor |
| `shear` | `float` | `0.0` | Shear degrees |
| `perspective` | `float` | `0.0` | Perspective transform |
| `flipud` | `float` | `0.0` | Vertical flip probability |
| `fliplr` | `float` | `0.5` | Horizontal flip probability |
| `hsv_h` | `float` | `0.015` | HSV hue augmentation |
| `hsv_s` | `float` | `0.7` | HSV saturation augmentation |
| `hsv_v` | `float` | `0.4` | HSV value augmentation |
| `erasing` | `float` | `0.0` | Random erasing probability |
| `crop_fraction` | `float` | `1.0` | Crop fraction |

```python
from shml.config import AugmentationConfig, TrainingConfig

aug = AugmentationConfig(mosaic=0.8, mixup=0.1, erasing=0.2)
cfg = TrainingConfig(augmentation=aug)
```

---

## JobConfig

```python
@dataclass
class JobConfig:
```

Job submission configuration — resources, metadata, and nested `TrainingConfig`.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gpu` | `int` | `1` | GPU count |
| `cpu` | `int` | `8` | CPU count |
| `memory_gb` | `float` | `32.0` | Memory in GB |
| `timeout_hours` | `float` | `24.0` | Max runtime hours |
| `priority` | `int` | `5` | Job priority (lower = higher priority) |
| `name` | `str \| None` | `None` | Job name |
| `description` | `str \| None` | `None` | Job description |
| `tags` | `dict[str, str]` | `{}` | Arbitrary key-value tags |
| `training` | `TrainingConfig` | *(defaults)* | Nested training configuration |
| `platform` | `PlatformConfig` | *(auto-resolved)* | Platform configuration |

### `from_profile()`

```python
@classmethod
def from_profile(
    cls,
    profile: str | Path,
    platform: PlatformConfig | None = None,
    **overrides: Any,
) -> JobConfig:
```

Load job configuration from a named profile. Profile resolution order:

1. Exact file path (if the path exists)
2. `config/profiles/{profile}.yaml`
3. `sdk/config/profiles/{profile}.yaml`

Job-level fields (`gpu`, `cpu`, `memory_gb`, etc.) are separated from training fields automatically.

```python
from shml.config import JobConfig

job = JobConfig.from_profile("balanced")
job = JobConfig.from_profile("balanced", epochs=5, gpu=2)
print(job.training.epochs)  # 5
print(job.gpu)              # 2
```

---

## AuthConfig

```python
@dataclass
class AuthConfig:
```

Authentication configuration with multi-source credential resolution.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_url` | `str` | `"https://${PUBLIC_DOMAIN}"` | Platform base URL |
| `api_key` | `str \| None` | `None` | API key (`shml_xxx`) |
| `oauth_token` | `str \| None` | `None` | OAuth2 bearer token |
| `profile` | `str` | `"default"` | Credentials file profile |
| `api_prefix` | `str` | `"/api/ray"` | API path prefix |
| `use_internal` | `bool` | `False` | Use Docker-internal DNS (skip auth) |

### Credential Resolution Chain

```
Constructor args → Env vars → ~/.shml/credentials → Defaults
```

| Source | Variables |
|--------|-----------|
| **Environment** | `SHML_BASE_URL`, `SHML_API_KEY`, `SHML_OAUTH_TOKEN`, `SHML_API_PREFIX`, `SHML_INTERNAL` |
| **Credentials file** | `~/.shml/credentials` (INI format, per-profile sections) |

### Properties

| Property | Returns | Description |
|----------|---------|-------------|
| `effective_base_url` | `str` | Returns internal URL (`http://ray-compute-api:8000`) when `use_internal=True` |
| `auth_headers` | `dict[str, str]` | `X-API-Key` header (API key) or `Authorization: Bearer` header (OAuth) |

### `save()`

```python
def save(self) -> None:
```

Persist credentials to `~/.shml/credentials` with `0600` permissions.

```python
from shml.config import AuthConfig

auth = AuthConfig(api_key="shml_abc123")
auth.save()  # Writes to ~/.shml/credentials [default] section
```

The credentials file uses INI format:

```ini
[default]
base_url = https://${PUBLIC_DOMAIN}
api_key = shml_abc123
```
