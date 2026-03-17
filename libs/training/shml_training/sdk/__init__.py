"""
SHML Training SDK
License: Apache 2.0

Python SDK for remote training via SHML Platform API.

Example:
    from shml_training.sdk import TrainingClient, TrainingConfig

    client = TrainingClient(api_key="your-key")

    config = TrainingConfig(
        name="face-detection-v1",
        model="yolov8l",
        dataset="wider_face",
        epochs=100,
        use_curriculum_learning=True
    )

    job_id = client.submit_training(config)
    status = client.wait_for_completion(job_id)
"""

from .client import (
    TrainingClient,
    TrainingConfig,
    JobStatus,
    QueueStatus,
    QuotaInfo,
    SDKError,
    APIError,
    AuthError,
    JobError,
    QuotaError,
    save_credentials,
)

__all__ = [
    # Client
    "TrainingClient",
    # Data models
    "TrainingConfig",
    "JobStatus",
    "QueueStatus",
    "QuotaInfo",
    # Exceptions
    "SDKError",
    "APIError",
    "AuthError",
    "JobError",
    "QuotaError",
    # Helpers
    "save_credentials",
]
