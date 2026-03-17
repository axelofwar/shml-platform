"""
SHML Training - Integrations Module
License: Apache 2.0

Integration adapters for third-party platforms and protocols.

Modules:
    ray              - Ray Compute integration (job submission, distributed training)
    progress         - AG-UI protocol for real-time progress streaming
    orchestrator     - ToolOrchestra-style job orchestration
    mlflow_callback  - MLflow experiment tracking
    prometheus_callback - Prometheus metrics export

Planned:
    tensorboard - TensorBoard logging

All integrations are open source under Apache 2.0.
"""

# from .ray import (
#     # Will be populated during Phase P1.4
# )

from .progress import (
    ProgressReporter,
    AGUIEventEmitter,
    AGUIEventType,
    AGUIEvent,
    print_progress_bar,
)

from .orchestrator import (
    JobOrchestrator,
    JobSpec,
    JobResult,
    JobStatus,
    JobPriority,
    Backend,
    run_training_job,
)

from .mlflow_callback import MLflowCallback
from .prometheus_callback import PrometheusCallback

__all__ = [
    # Progress
    "ProgressReporter",
    "AGUIEventEmitter",
    "AGUIEventType",
    "AGUIEvent",
    "print_progress_bar",
    # Orchestrator
    "JobOrchestrator",
    "JobSpec",
    "JobResult",
    "JobStatus",
    "JobPriority",
    "Backend",
    "run_training_job",
    # Callbacks
    "MLflowCallback",
    "PrometheusCallback",
]
