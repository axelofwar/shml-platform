"""
SHML Platform Configuration
============================

Python dataclass-driven configuration with YAML serialization.

Resolution order (highest to lowest priority):
    1. Constructor arguments / CLI flags
    2. Environment variables (SHML_*, MLFLOW_*, NESSIE_*, etc.)
    3. Credentials file (~/.shml/credentials, INI format)
    4. Config file (config/platform.env or YAML profile)
    5. Built-in defaults (Docker-internal service discovery)

Usage::

    # Auto-resolve from environment
    platform = PlatformConfig.from_env()

    # Load training profile
    training = TrainingConfig.from_yaml("config/profiles/balanced.yaml")

    # Override at runtime
    training = TrainingConfig.from_yaml("config/profiles/balanced.yaml", epochs=5, batch=2)

    # Full job config
    job = JobConfig.from_profile("balanced", epochs=5)
"""

from __future__ import annotations

import configparser
import os
import stat
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Any

import yaml


# =============================================================================
# PLATFORM CONFIG — service discovery & infrastructure
# =============================================================================


@dataclass(frozen=True)
class PlatformConfig:
    """Infrastructure and service discovery configuration.

    Maps 1:1 to config/platform.env and future K8s ConfigMap.
    All defaults assume Docker-internal DNS names.
    """

    # Core infrastructure
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    redis_host: str = "redis"
    redis_port: int = 6379

    # MLflow
    mlflow_uri: str = "http://mlflow-nginx:80"
    mlflow_experiment: str = "Face-Detection"
    mlflow_registry_model: str = "face-detection-yolov8l-p2"
    mlflow_artifact_root: str = "/mlflow/artifacts"

    # Ray
    ray_head_address: str = "ray-head:6379"
    ray_dashboard_host: str = "ray-head"
    ray_dashboard_port: int = 8265

    # Nessie / Iceberg
    nessie_uri: str = "http://nessie:19120"
    nessie_api_version: str = "v1"

    # FiftyOne
    fiftyone_uri: str = "http://fiftyone:5151"
    fiftyone_db_uri: str = "mongodb://fiftyone-mongodb:27017"

    # Monitoring
    prometheus_host: str = "prometheus"
    prometheus_port: int = 9090
    grafana_host: str = "grafana"
    grafana_port: int = 3000
    pushgateway_url: str = "shml-pushgateway:9091"

    # Logging & Tracing
    loki_host: str = "loki"
    loki_port: int = 3100
    tempo_host: str = "tempo"
    tempo_port: int = 3200
    otel_collector_host: str = "otel-collector"
    otel_exporter_endpoint: str = "http://otel-collector:4317"

    # Auth
    fusionauth_host: str = "fusionauth"
    fusionauth_port: int = 9011
    oauth2_proxy_host: str = "oauth2-proxy"
    oauth2_proxy_port: int = 4180

    # Platform metadata
    platform_version: str = "2.0"
    platform_env: str = "production"
    platform_prefix: str = "shml"

    @classmethod
    def from_env(cls) -> PlatformConfig:
        """Build config from environment variables.

        Reads SHML_* and service-specific env vars, falls back to defaults.
        Also reads config/platform.env if present.
        """
        env_map: dict[str, str] = {}

        # Try loading platform.env file
        platform_env_path = Path("config/platform.env")
        if not platform_env_path.exists():
            # Try relative to workspace
            for candidate in [
                Path("/home/axelofwar/Projects/shml-platform/config/platform.env"),
                Path.cwd() / "config" / "platform.env",
            ]:
                if candidate.exists():
                    platform_env_path = candidate
                    break

        if platform_env_path.exists():
            for line in platform_env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_map[key.strip()] = value.strip()

        def _get(env_key: str, fallback: str | None = None) -> str | None:
            return os.environ.get(env_key, env_map.get(env_key, fallback))

        kwargs: dict[str, Any] = {}

        # Map env vars to field names
        mappings = {
            "postgres_host": "POSTGRES_HOST",
            "postgres_port": "POSTGRES_PORT",
            "redis_host": "REDIS_HOST",
            "redis_port": "REDIS_PORT",
            "mlflow_uri": "MLFLOW_TRACKING_URI",
            "mlflow_experiment": "MLFLOW_EXPERIMENT_NAME",
            "mlflow_registry_model": "MLFLOW_REGISTRY_MODEL_NAME",
            "mlflow_artifact_root": "MLFLOW_ARTIFACT_ROOT",
            "ray_head_address": "RAY_HEAD_ADDRESS",
            "ray_dashboard_host": "RAY_DASHBOARD_HOST",
            "ray_dashboard_port": "RAY_DASHBOARD_PORT",
            "nessie_uri": "NESSIE_URI",
            "fiftyone_db_uri": "FIFTYONE_DATABASE_URI",
            "pushgateway_url": "PUSHGATEWAY_URL",
            "prometheus_host": "PROMETHEUS_HOST",
            "prometheus_port": "PROMETHEUS_PORT",
            "grafana_host": "GRAFANA_HOST",
            "grafana_port": "GRAFANA_PORT",
            "loki_host": "LOKI_HOST",
            "loki_port": "LOKI_PORT",
            "tempo_host": "TEMPO_HOST",
            "tempo_port": "TEMPO_PORT",
            "otel_collector_host": "OTEL_COLLECTOR_HOST",
            "otel_exporter_endpoint": "OTEL_EXPORTER_OTLP_ENDPOINT",
            "fusionauth_host": "FUSIONAUTH_HOST",
            "fusionauth_port": "FUSIONAUTH_PORT",
            "platform_version": "PLATFORM_VERSION",
            "platform_env": "PLATFORM_ENV",
            "platform_prefix": "PLATFORM_PREFIX",
        }

        # Also support MLFLOW_TRACKING_URI_INTERNAL (used inside containers)
        internal_uri = _get("MLFLOW_TRACKING_URI_INTERNAL")
        if internal_uri:
            kwargs["mlflow_uri"] = internal_uri

        for field_name, env_key in mappings.items():
            val = _get(env_key)
            if val is not None and field_name not in kwargs:
                # Coerce int fields
                fld = next(f for f in fields(cls) if f.name == field_name)
                if fld.type == "int":
                    kwargs[field_name] = int(val)
                else:
                    kwargs[field_name] = val

        return cls(**kwargs)


# =============================================================================
# AUGMENTATION CONFIG
# =============================================================================


@dataclass
class AugmentationConfig:
    """Data augmentation hyperparameters for YOLO training."""

    mosaic: float = 1.0
    mixup: float = 0.15
    copy_paste: float = 0.1
    degrees: float = 10.0
    translate: float = 0.2
    scale: float = 0.9
    shear: float = 0.0
    perspective: float = 0.0
    flipud: float = 0.0
    fliplr: float = 0.5
    hsv_h: float = 0.015
    hsv_s: float = 0.7
    hsv_v: float = 0.4
    erasing: float = 0.0
    crop_fraction: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


# =============================================================================
# DATA CONFIG — dataset location, deduplication, privacy controls
# =============================================================================


@dataclass
class DataConfig:
    """Data location configuration — zero duplication, configurable paths.

    Supports local paths, HuggingFace datasets, and S3 URIs.
    Resolution chain checks existence before copying/downloading.

    Usage::

        # Use dataset already in Ray
        data = DataConfig(dataset="wider_face_yolo")

        # Stream from HuggingFace
        data = DataConfig(hf_dataset="wider_face")

        # Private S3 data (auto-cleanup after training)
        data = DataConfig(s3_uri="s3://bucket/datasets/wider_face/",
                          persist_remote_data=False)
    """

    # Base directories (inside Ray container)
    ray_data_dir: str = "/tmp/ray/data"
    ray_checkpoint_dir: str = "/tmp/ray/checkpoints/face_detection"

    # Dataset reference (resolved via chain)
    dataset: str = "wider_face_yolo"

    # Model artifact source
    checkpoint: str | None = None  # Phase checkpoint to fine-tune from

    # Remote sources
    hf_dataset: str | None = None  # e.g. "wider_face"
    s3_uri: str | None = None  # e.g. "s3://bucket/datasets/wider_face/"

    # Lifecycle controls
    persist_remote_data: bool = False  # If False, use temp cache for remote data
    auto_cleanup_after_hours: float = 0  # 0 = keep until evicted, >0 = auto-delete
    max_cache_gb: float = 50.0  # Auto-evict old cached datasets
    data_isolation: bool = True  # Each job gets isolated data view

    def resolve_data_yaml(self) -> str:
        """Resolve the actual data.yaml path, checking existence.

        Resolution chain:
            1. {ray_data_dir}/{dataset}/data.yaml — use directly if exists
            2. Absolute path in `dataset` field — use directly
            3. hf_dataset set — HuggingFace download
            4. s3_uri set — S3 mount/stream
            5. Fail with descriptive error
        """
        from pathlib import Path

        # 1. Check standard location
        standard = Path(self.ray_data_dir) / self.dataset / "data.yaml"
        if standard.exists():
            return str(standard)

        # 2. Check if dataset is an absolute path
        if Path(self.dataset).is_absolute() and Path(self.dataset).exists():
            return self.dataset

        # 3. HuggingFace dataset reference
        if self.hf_dataset:
            return f"hf://{self.hf_dataset}"

        # 4. S3 URI
        if self.s3_uri:
            return self.s3_uri

        # 5. Return standard path (let caller handle missing)
        return str(standard)

    def resolve_checkpoint(self) -> str | None:
        """Resolve checkpoint path.

        Resolution:
            - None → no checkpoint (train from scratch)
            - "latest" → glob checkpoint_dir, sort by mtime
            - "mlflow:{model}/{version}" → fetch from MLflow
            - "phase5" → glob phase_5_*/weights/best.pt
            - Absolute path → use directly
        """
        from pathlib import Path

        if self.checkpoint is None:
            return None

        if self.checkpoint == "latest":
            ckpt_dir = Path(self.ray_checkpoint_dir)
            if ckpt_dir.exists():
                candidates = sorted(
                    ckpt_dir.glob("*/weights/best.pt"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                return str(candidates[0]) if candidates else None
            return None

        if self.checkpoint.startswith("mlflow:"):
            return self.checkpoint  # Let caller resolve via MLflow client

        if not Path(self.checkpoint).is_absolute():
            # Treat as phase name: "phase5" → "phase_5_*/weights/best.pt"
            ckpt_dir = Path(self.ray_checkpoint_dir)
            phase_num = self.checkpoint.replace("phase", "").strip("_")
            candidates = sorted(
                ckpt_dir.glob(f"phase_{phase_num}_*/weights/best.pt"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return str(candidates[0]) if candidates else None

        return self.checkpoint

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataConfig:
        """Create DataConfig from a dictionary."""
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


# =============================================================================
# TRAINING CONFIG — hyperparameters & model settings
# =============================================================================


@dataclass
class TrainingConfig:
    """Training hyperparameters and model configuration.

    Can be loaded from YAML profiles or constructed programmatically.
    All fields have sensible defaults for fine-tuning on RTX 3090 Ti.
    """

    # Core
    epochs: int = 10
    batch: int = 4
    imgsz: int = 1280
    device: str = "cuda:0"
    optimizer: str = "AdamW"

    # Learning rate
    lr0: float = 0.0001
    lrf: float = 0.01
    warmup_epochs: float = 1.0
    warmup_momentum: float = 0.8
    warmup_bias_lr: float = 0.01
    momentum: float = 0.937
    weight_decay: float = 0.0005

    # Loss weights
    box: float = 7.5
    cls: float = 0.5
    dfl: float = 1.5

    # Augmentation
    augmentation: AugmentationConfig = field(default_factory=AugmentationConfig)

    # Runtime
    workers: int = 4
    patience: int = 0  # 0 = no early stopping
    save_period: int = 1
    nbs: int = 64
    single_cls: bool = True
    exist_ok: bool = True
    verbose: bool = True
    val: bool = True
    plots: bool = True
    deterministic: bool = True
    amp: bool = True
    cache: bool = False
    rect: bool = False
    cos_lr: bool = False
    close_mosaic: int = 10
    pretrained: bool = True

    # Model
    model: str = "yolo11x.pt"
    model_type: str = "ultralytics"  # "ultralytics" or "rfdetr"
    checkpoint: str | None = None  # Path to fine-tune from

    # RF-DETR specific (ignored for ultralytics)
    lr_encoder: float = 1.5e-5  # Lower LR for frozen DINOv2 encoder
    grad_accum_steps: int = 4  # Gradient accumulation steps

    # Integrations (declarative — which platform features to wire up)
    integrations: list[str] = field(
        default_factory=lambda: [
            "mlflow",
            "nessie",
            "fiftyone",
            "features",
            "prometheus",
        ]
    )

    # Platform features
    gpu_yield: bool = True  # Yield/reclaim GPU from inference services
    mlflow_experiment: str = "Face-Detection"
    nessie_branch_prefix: str = "experiment"

    # Dataset — use DataConfig for smart resolution
    data: DataConfig = field(default_factory=DataConfig)
    data_yaml: str = ""  # Resolved from data.resolve_data_yaml() if empty

    def __post_init__(self) -> None:
        """Validate configuration values and resolve data paths."""
        if self.batch < 1:
            raise ValueError(f"batch must be >= 1, got {self.batch}")
        if self.lr0 <= 0:
            raise ValueError(f"lr0 must be > 0, got {self.lr0}")
        if self.epochs < 1:
            raise ValueError(f"epochs must be >= 1, got {self.epochs}")
        if self.imgsz < 32:
            raise ValueError(f"imgsz must be >= 32, got {self.imgsz}")

        # Resolve data_yaml from DataConfig if not explicitly set
        if not self.data_yaml:
            self.data_yaml = self.data.resolve_data_yaml()

    def to_ultralytics_dict(self) -> dict[str, Any]:
        """Convert to the flat dict format that YOLO model.train() expects."""
        d: dict[str, Any] = {
            "epochs": self.epochs,
            "batch": self.batch,
            "imgsz": self.imgsz,
            "device": self.device,
            "optimizer": self.optimizer,
            "lr0": self.lr0,
            "lrf": self.lrf,
            "warmup_epochs": self.warmup_epochs,
            "warmup_momentum": self.warmup_momentum,
            "warmup_bias_lr": self.warmup_bias_lr,
            "momentum": self.momentum,
            "weight_decay": self.weight_decay,
            "box": self.box,
            "cls": self.cls,
            "dfl": self.dfl,
            "workers": self.workers,
            "patience": self.patience,
            "save_period": self.save_period,
            "nbs": self.nbs,
            "single_cls": self.single_cls,
            "exist_ok": self.exist_ok,
            "verbose": self.verbose,
            "val": self.val,
            "plots": self.plots,
            "deterministic": self.deterministic,
            "amp": self.amp,
            "cache": self.cache,
            "rect": self.rect,
            "cos_lr": self.cos_lr,
            "close_mosaic": self.close_mosaic,
            "pretrained": self.pretrained,
        }
        # Flatten augmentation into the dict
        d.update(self.augmentation.to_dict())
        return d

    def to_rfdetr_dict(self) -> dict[str, Any]:
        """Convert to the dict format that RF-DETR model.train() expects.

        RF-DETR uses COCO-format datasets and has different parameter names
        than Ultralytics. DINOv2 backbone uses a lower encoder LR.
        """
        return {
            "epochs": self.epochs,
            "batch_size": self.batch,
            "lr": self.lr0,
            "lr_encoder": self.lr_encoder,
            "weight_decay": self.weight_decay,
            "warmup_epochs": self.warmup_epochs,
            "grad_accum_steps": self.grad_accum_steps,
            "num_workers": self.workers,
            "device": self.device,
        }

    @classmethod
    def from_yaml(cls, path: str | Path, **overrides: Any) -> TrainingConfig:
        """Load from a YAML profile file with optional overrides.

        Usage::

            cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml")
            cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml", epochs=5, batch=2)
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Training profile not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Handle nested augmentation
        aug_data = data.pop("augmentation", {})
        if aug_data:
            data["augmentation"] = AugmentationConfig(**aug_data)

        # Handle nested data config
        data_config = data.pop("data", {})
        if isinstance(data_config, dict) and data_config:
            data["data"] = DataConfig.from_dict(data_config)

        # Handle common aliases
        if "batch_size" in data and "batch" not in data:
            data["batch"] = data.pop("batch_size")
        elif "batch_size" in data:
            data.pop("batch_size")

        # Handle integrations list
        if "integrations" in data and isinstance(data["integrations"], list):
            pass  # Already a list — keep as-is

        # Apply overrides (CLI flags take priority over profile)
        data.update(overrides)

        # Handle augmentation overrides
        if "augmentation" in overrides and isinstance(overrides["augmentation"], dict):
            data["augmentation"] = AugmentationConfig(**overrides["augmentation"])

        return cls(**data)

    def to_yaml(self, path: str | Path | None = None) -> str:
        """Serialize config to YAML string, optionally writing to file."""
        data = asdict(self)
        result = yaml.dump(data, default_flow_style=False, sort_keys=False)

        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                f.write(result)

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrainingConfig:
        """Create from a flat dictionary (e.g., from API request)."""
        # Handle common aliases
        if "batch_size" in data and "batch" not in data:
            data["batch"] = data.pop("batch_size")
        elif "batch_size" in data:
            data.pop("batch_size")

        aug_data = data.pop("augmentation", {})
        if isinstance(aug_data, dict) and aug_data:
            data["augmentation"] = AugmentationConfig(**aug_data)

        data_config = data.pop("data", {})
        if isinstance(data_config, dict) and data_config:
            data["data"] = DataConfig.from_dict(data_config)

        return cls(**data)


# =============================================================================
# JOB CONFIG — submission parameters
# =============================================================================


@dataclass
class JobConfig:
    """Job submission configuration — resources, metadata, and training config."""

    # Resource requests
    gpu: int = 1
    cpu: int = 8
    memory_gb: float = 32.0
    timeout_hours: float = 24.0
    priority: int = 5

    # Job metadata
    name: str | None = None
    description: str | None = None
    tags: dict[str, str] = field(default_factory=dict)

    # Training config (nested)
    training: TrainingConfig = field(default_factory=TrainingConfig)

    # Platform config (auto-resolved)
    platform: PlatformConfig = field(default_factory=PlatformConfig)

    @classmethod
    def from_profile(
        cls,
        profile: str | Path,
        platform: PlatformConfig | None = None,
        **overrides: Any,
    ) -> JobConfig:
        """Load job configuration from a named profile.

        Profile resolution:
            1. Exact path (if exists)
            2. config/profiles/{profile}.yaml
            3. sdk/config/profiles/{profile}.yaml

        Usage::

            job = JobConfig.from_profile("balanced")
            job = JobConfig.from_profile("balanced", epochs=5)
        """
        profile_path = _resolve_profile_path(profile)

        with open(profile_path) as f:
            data = yaml.safe_load(f) or {}

        # Separate job-level fields from training fields
        job_fields = {f.name for f in fields(cls)} - {"training", "platform"}
        job_kwargs: dict[str, Any] = {}
        training_data: dict[str, Any] = {}

        for key, value in data.items():
            if key == "training":
                training_data.update(value)
            elif key in job_fields:
                job_kwargs[key] = value
            else:
                # Assume it's a training field if not a job field
                training_data[key] = value

        # Apply overrides — check if they're job or training fields
        for key, value in overrides.items():
            if key in job_fields:
                job_kwargs[key] = value
            else:
                training_data[key] = value

        # Build nested configs
        training = (
            TrainingConfig.from_dict(training_data)
            if training_data
            else TrainingConfig()
        )
        if platform is None:
            platform = PlatformConfig.from_env()

        return cls(training=training, platform=platform, **job_kwargs)


# =============================================================================
# AUTH CONFIG — credentials and authentication
# =============================================================================

CREDENTIALS_DIR = Path.home() / ".shml"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials"


@dataclass
class AuthConfig:
    """Authentication configuration.

    Credentials are resolved in order:
        1. Constructor arguments
        2. Environment variables (SHML_API_KEY, SHML_OAUTH_TOKEN, SHML_BASE_URL)
        3. Credentials file (~/.shml/credentials, INI format)
        4. Defaults
    """

    base_url: str = "https://shml-platform.tail38b60a.ts.net"
    api_key: str | None = None
    oauth_token: str | None = None
    profile: str = "default"

    # Internal routing
    api_prefix: str = "/api/ray"
    use_internal: bool = False  # True = skip auth, use Docker DNS

    @classmethod
    def from_env(cls, profile: str = "default") -> AuthConfig:
        """Build auth config from environment and credentials file."""
        kwargs: dict[str, Any] = {"profile": profile}

        # Env vars (highest priority)
        env_mappings = {
            "SHML_BASE_URL": "base_url",
            "SHML_API_KEY": "api_key",
            "SHML_OAUTH_TOKEN": "oauth_token",
            "SHML_API_PREFIX": "api_prefix",
        }
        for env_key, field_name in env_mappings.items():
            val = os.environ.get(env_key)
            if val:
                kwargs[field_name] = val

        if os.environ.get("SHML_INTERNAL", "").lower() in ("1", "true", "yes"):
            kwargs["use_internal"] = True

        # Credentials file (lower priority — don't override env vars)
        if CREDENTIALS_FILE.exists():
            cp = configparser.ConfigParser()
            cp.read(CREDENTIALS_FILE)
            if cp.has_section(profile):
                for key in ("api_key", "base_url", "oauth_token"):
                    if key not in kwargs and cp.has_option(profile, key):
                        kwargs[key] = cp.get(profile, key)

        return cls(**kwargs)

    def save(self) -> None:
        """Persist credentials to ~/.shml/credentials (mode 0600)."""
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

        cp = configparser.ConfigParser()
        if CREDENTIALS_FILE.exists():
            cp.read(CREDENTIALS_FILE)

        if not cp.has_section(self.profile):
            cp.add_section(self.profile)

        cp.set(self.profile, "base_url", self.base_url)
        if self.api_key:
            cp.set(self.profile, "api_key", self.api_key)
        if self.oauth_token:
            cp.set(self.profile, "oauth_token", self.oauth_token)

        with open(CREDENTIALS_FILE, "w") as f:
            cp.write(f)

        CREDENTIALS_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600

    @property
    def effective_base_url(self) -> str:
        """Return the base URL for API calls, considering internal/external mode."""
        if self.use_internal:
            return "http://ray-compute-api:8000"
        return self.base_url

    @property
    def auth_headers(self) -> dict[str, str]:
        """Build authentication headers."""
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self.oauth_token:
            headers["Authorization"] = f"Bearer {self.oauth_token}"
        return headers


# =============================================================================
# HELPERS
# =============================================================================


def _resolve_profile_path(profile: str | Path) -> Path:
    """Resolve a profile name to a YAML file path.

    Searches:
        1. Exact path
        2. config/profiles/{profile}.yaml
        3. <workspace_root>/config/profiles/{profile}.yaml
    """
    path = Path(profile)
    if path.exists() and path.suffix in (".yaml", ".yml"):
        return path

    # Named profile — search standard locations
    candidates = [
        Path("config/profiles") / f"{profile}.yaml",
        Path("/home/axelofwar/Projects/shml-platform/config/profiles")
        / f"{profile}.yaml",
        Path(__file__).parent.parent.parent / "config" / "profiles" / f"{profile}.yaml",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Profile '{profile}' not found. Searched:\n"
        + "\n".join(f"  - {c}" for c in candidates)
        + "\n\nAvailable profiles: shml config list-profiles"
    )


def list_profiles() -> list[dict[str, Any]]:
    """List all available training profiles."""
    profiles = []
    search_dirs = [
        Path("config/profiles"),
        Path("/home/axelofwar/Projects/shml-platform/config/profiles"),
    ]

    seen: set[str] = set()
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for yml in sorted(search_dir.glob("*.yaml")):
            name = yml.stem
            if name in seen:
                continue
            seen.add(name)

            with open(yml) as f:
                data = yaml.safe_load(f) or {}

            profiles.append(
                {
                    "name": name,
                    "path": str(yml),
                    "description": data.get("description", ""),
                    "model": data.get("model", "?"),
                    "epochs": data.get(
                        "epochs", data.get("training", {}).get("epochs", "?")
                    ),
                    "batch": data.get(
                        "batch",
                        data.get(
                            "batch_size", data.get("training", {}).get("batch", "?")
                        ),
                    ),
                    "imgsz": data.get(
                        "imgsz", data.get("training", {}).get("imgsz", "?")
                    ),
                    "integrations": data.get(
                        "integrations",
                        data.get("training", {}).get("integrations", []),
                    ),
                }
            )

    return profiles
