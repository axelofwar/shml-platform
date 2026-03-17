"""
SHML Platform SDK
=================

Unified CLI, client library, and config-driven ML workflows.

Usage::

    # CLI
    shml train --profile balanced --epochs 5
    shml status <job_id>
    shml gpu status

    # Python SDK
    from shml import Client
    client = Client()
    job = client.submit_training(profile="balanced", epochs=5)
    print(client.status(job.job_id))

    # Config
    from shml.config import PlatformConfig, TrainingConfig
    cfg = PlatformConfig.from_env()
    print(cfg.mlflow_uri)
"""

__version__ = "1.0.0"

from shml.client import Client
from shml.config import (
    PlatformConfig,
    TrainingConfig,
    JobConfig,
    AuthConfig,
    DataConfig,
)
from shml.exceptions import (
    SHMLError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    JobError,
    ConfigError,
    IntegrationError,
)
from shml.training.runner import TrainingRunner

__all__ = [
    "Client",
    "PlatformConfig",
    "TrainingConfig",
    "JobConfig",
    "AuthConfig",
    "DataConfig",
    "TrainingRunner",
    "SHMLError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "JobError",
    "ConfigError",
    "IntegrationError",
]
