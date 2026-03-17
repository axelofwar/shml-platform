"""
Prometheus Metrics Callback
License: Apache 2.0

Callback for exporting training metrics to Prometheus Pushgateway.

Enhanced (2025-12-11):
- Added SAPO soft gating metrics (soft_weight, temperature)
- Added advantage filter metrics (skip_rate, hard_batch_rate)
- Added PII gap metrics (gap_to_target_recall, gap_to_target_map50)
- Added training alerts support

Usage:
    from shml_training.integrations import PrometheusCallback
    from shml_training.core import UltralyticsTrainer

    callback = PrometheusCallback(
        pushgateway_url="http://localhost:9091",
        job_name="face-detection-training",
        pii_targets={"recall": 0.95, "map50": 0.94},
    )

    trainer = UltralyticsTrainer(
        config=config,
        callbacks=[callback],
    )

    results = trainer.train()
"""

import time
from typing import Dict, Any, Optional

try:
    from prometheus_client import CollectorRegistry, Gauge, Counter, push_to_gateway

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

from ..core.callbacks import TrainingCallback


class PrometheusCallback(TrainingCallback):
    """
    Prometheus metrics export callback with SAPO and PII support.

    Pushes training metrics to Prometheus Pushgateway for monitoring
    and visualization in Grafana dashboards.

    Features:
    - Standard training metrics (loss, mAP50, recall, precision)
    - SAPO soft gating metrics (soft_weight, temperature)
    - Advantage filter metrics (skip_rate, hard_batch_rate)
    - PII gap metrics (gap_to_target_recall, gap_to_target_map50)
    - Curriculum stage tracking
    """

    def __init__(
        self,
        pushgateway_url: str = "http://localhost:9091",
        job_name: str = "training",
        instance: Optional[str] = None,
        push_interval: int = 1,  # Push every N epochs
        pii_targets: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize Prometheus callback.

        Args:
            pushgateway_url: Prometheus Pushgateway URL
            job_name: Job name for metrics grouping
            instance: Instance identifier (defaults to hostname)
            push_interval: Push metrics every N epochs
            pii_targets: PII target thresholds {"recall": 0.95, "map50": 0.94, "precision": 0.90}
        """
        if not PROMETHEUS_AVAILABLE:
            raise ImportError(
                "prometheus_client is not installed. "
                "Install with: pip install prometheus-client"
            )

        self.pushgateway_url = pushgateway_url
        self.job_name = job_name
        self.instance = instance or "default"
        self.push_interval = push_interval
        self.pii_targets = pii_targets or {
            "recall": 0.95,
            "map50": 0.94,
            "precision": 0.90,
        }

        # Create registry
        self.registry = CollectorRegistry()

        # Define metrics - Standard training
        self.metrics = {
            "epoch": Gauge(
                "training_epoch",
                "Current training epoch",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "loss": Gauge(
                "training_loss",
                "Training loss",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "learning_rate": Gauge(
                "training_learning_rate",
                "Current learning rate",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "mAP50": Gauge(
                "training_mAP50",
                "mAP at IoU 0.5",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "recall": Gauge(
                "training_recall",
                "Recall",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "precision": Gauge(
                "training_precision",
                "Precision",
                ["job_name", "model"],
                registry=self.registry,
            ),
            # SAPO Soft Gating metrics
            "soft_weight": Gauge(
                "training_soft_weight",
                "SAPO soft gating average weight [0-1]",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "temperature": Gauge(
                "training_temperature",
                "SAPO soft gating temperature",
                ["job_name", "model"],
                registry=self.registry,
            ),
            # Advantage Filter metrics
            "skip_rate": Gauge(
                "training_skip_rate",
                "Advantage filter batch skip rate",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "hard_batch_rate": Gauge(
                "training_hard_batch_rate",
                "Percentage of hard batches processed",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "compute_savings": Gauge(
                "training_compute_savings",
                "Compute savings from advantage filtering (%)",
                ["job_name", "model"],
                registry=self.registry,
            ),
            # PII Gap metrics
            "gap_to_target_recall": Gauge(
                "training_gap_to_target_recall",
                "Gap to target recall (negative = above target)",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "gap_to_target_map50": Gauge(
                "training_gap_to_target_map50",
                "Gap to target mAP50 (negative = above target)",
                ["job_name", "model"],
                registry=self.registry,
            ),
            # Curriculum tracking
            "curriculum_stage": Gauge(
                "training_curriculum_stage",
                "Current curriculum stage (1-4)",
                ["job_name", "model"],
                registry=self.registry,
            ),
        }

        # Counters
        self.counters = {
            "epochs_completed": Counter(
                "training_epochs_completed_total",
                "Total epochs completed",
                ["job_name", "model"],
                registry=self.registry,
            ),
            "batches_skipped": Counter(
                "training_batches_skipped_total",
                "Total batches skipped by advantage filter",
                ["job_name", "model"],
                registry=self.registry,
            ),
        }

        self.model_name = "unknown"
        self.last_push_epoch = -1

        print(f"✅ PrometheusCallback initialized")
        print(f"   Pushgateway: {pushgateway_url}")
        print(f"   Job: {job_name}")
        print(f"   Instance: {self.instance}")
        print(
            f"   PII Targets: Recall={self.pii_targets.get('recall', 0.95):.0%}, mAP50={self.pii_targets.get('map50', 0.94):.0%}"
        )

    def on_run_start(self, trainer, config: Dict[str, Any]):
        """Initialize model name from config."""
        self.model_name = config.get("model", "unknown")
        print(f"📊 Prometheus metrics enabled for: {self.model_name}")

    def on_epoch_end(self, trainer, epoch: int, metrics: Dict[str, Any]):
        """Push epoch metrics to Prometheus."""
        # Check if should push this epoch
        if (epoch - self.last_push_epoch) < self.push_interval:
            return

        # Update metrics
        labels = {"job_name": self.job_name, "model": self.model_name}

        # Standard metrics
        self.metrics["epoch"].labels(**labels).set(epoch)
        self.counters["epochs_completed"].labels(**labels).inc()

        if "loss" in metrics:
            self.metrics["loss"].labels(**labels).set(metrics["loss"])

        if "lr" in metrics:
            self.metrics["learning_rate"].labels(**labels).set(metrics["lr"])

        if "mAP50" in metrics:
            self.metrics["mAP50"].labels(**labels).set(metrics["mAP50"])
            # Calculate PII gap
            gap = self.pii_targets.get("map50", 0.94) - metrics["mAP50"]
            self.metrics["gap_to_target_map50"].labels(**labels).set(gap)

        if "recall" in metrics:
            self.metrics["recall"].labels(**labels).set(metrics["recall"])
            # Calculate PII gap
            gap = self.pii_targets.get("recall", 0.95) - metrics["recall"]
            self.metrics["gap_to_target_recall"].labels(**labels).set(gap)

        if "precision" in metrics:
            self.metrics["precision"].labels(**labels).set(metrics["precision"])

        # SAPO Soft Gating metrics
        if "soft_weight" in metrics:
            self.metrics["soft_weight"].labels(**labels).set(metrics["soft_weight"])

        if "temperature" in metrics:
            self.metrics["temperature"].labels(**labels).set(metrics["temperature"])

        # Advantage Filter metrics
        if "skip_rate" in metrics:
            self.metrics["skip_rate"].labels(**labels).set(metrics["skip_rate"])

        if "hard_batch_rate" in metrics:
            self.metrics["hard_batch_rate"].labels(**labels).set(
                metrics["hard_batch_rate"]
            )

        if "compute_savings" in metrics:
            # Convert string like "15.2%" to float 15.2
            savings = metrics["compute_savings"]
            if isinstance(savings, str) and savings.endswith("%"):
                savings = float(savings[:-1])
            self.metrics["compute_savings"].labels(**labels).set(savings)

        if "batches_skipped" in metrics:
            # This should be incremental, but we'll set the counter value
            self.counters["batches_skipped"].labels(**labels)._value.set(
                metrics["batches_skipped"]
            )

        # Curriculum stage
        if "curriculum_stage" in metrics:
            stage = metrics["curriculum_stage"]
            # Convert stage name to number
            stage_map = {
                "presence_detection": 1,
                "localization": 2,
                "occlusion_handling": 3,
                "edge_cases": 4,
                "multi_scale": 4,
            }
            if isinstance(stage, str):
                stage = stage_map.get(stage, 0)
            self.metrics["curriculum_stage"].labels(**labels).set(stage)

        # Push to gateway
        try:
            push_to_gateway(
                self.pushgateway_url,
                job=self.job_name,
                registry=self.registry,
            )
            self.last_push_epoch = epoch
        except Exception as e:
            print(f"⚠ Failed to push metrics to Prometheus: {e}")

    def on_run_end(self, trainer, metrics: Dict[str, Any]):
        """Push final metrics."""
        # Push one last time with final metrics
        labels = {"job_name": self.job_name, "model": self.model_name}

        if "mAP50" in metrics:
            self.metrics["mAP50"].labels(**labels).set(metrics["mAP50"])

        if "recall" in metrics:
            self.metrics["recall"].labels(**labels).set(metrics["recall"])

        if "precision" in metrics:
            self.metrics["precision"].labels(**labels).set(metrics["precision"])

        try:
            push_to_gateway(
                self.pushgateway_url,
                job=self.job_name,
                registry=self.registry,
            )
            print(f"📊 Final metrics pushed to Prometheus")
        except Exception as e:
            print(f"⚠ Failed to push final metrics: {e}")


__all__ = ["PrometheusCallback"]
