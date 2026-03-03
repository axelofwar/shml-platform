"""
Prometheus / Pushgateway Integration Client
=============================================

Push training metrics to Prometheus Pushgateway for real-time
monitoring via Grafana dashboards.
"""

from __future__ import annotations

import time
from typing import Any

from shml.config import PlatformConfig
from shml.exceptions import IntegrationError


class PrometheusReporter:
    """Push training metrics to Prometheus Pushgateway."""

    def __init__(
        self,
        config: PlatformConfig | None = None,
        job_name: str = "training",
        grouping_key: dict[str, str] | None = None,
    ):
        self._config = config or PlatformConfig.from_env()
        self._pushgw = self._config.pushgateway_uri
        self._job_name = job_name
        self._grouping_key = grouping_key or {}
        self._registry = None
        self._gauges: dict[str, Any] = {}
        self._available = False
        self._init()

    def _init(self) -> None:
        """Try to import prometheus_client."""
        try:
            from prometheus_client import CollectorRegistry

            self._registry = CollectorRegistry()
            self._available = True
        except ImportError:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def healthy(self) -> bool:
        """Check if Pushgateway is reachable."""
        if not self._available:
            return False
        try:
            import requests

            resp = requests.get(f"{self._pushgw}/metrics", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _get_gauge(self, name: str, description: str = "") -> Any:
        """Get or create a Gauge metric."""
        if name not in self._gauges:
            from prometheus_client import Gauge

            safe_name = name.replace(".", "_").replace("-", "_").replace("/", "_")
            self._gauges[name] = Gauge(
                safe_name,
                description or f"Training metric: {name}",
                registry=self._registry,
            )
        return self._gauges[name]

    def report_metric(self, name: str, value: float, description: str = "") -> None:
        """Set a single metric value and push to gateway."""
        if not self._available:
            return

        gauge = self._get_gauge(name, description)
        gauge.set(value)
        self._push()

    def report_metrics(self, metrics: dict[str, float]) -> None:
        """Set multiple metric values and push once."""
        if not self._available:
            return

        for name, value in metrics.items():
            gauge = self._get_gauge(name)
            gauge.set(value)
        self._push()

    def report_epoch(
        self,
        epoch: int,
        total_epochs: int,
        metrics: dict[str, float],
        duration_seconds: float | None = None,
    ) -> None:
        """Report epoch-level metrics with context.

        Sets epoch, total_epochs, and all provided metrics,
        then pushes to gateway.
        """
        if not self._available:
            return

        self._get_gauge("training_epoch", "Current epoch").set(epoch)
        self._get_gauge("training_total_epochs", "Total epochs").set(total_epochs)

        if duration_seconds is not None:
            self._get_gauge("training_epoch_duration_seconds", "Epoch duration").set(
                duration_seconds
            )

        for name, value in metrics.items():
            self._get_gauge(name).set(value)

        self._push()

    def report_training_start(
        self,
        experiment_name: str,
        total_epochs: int,
        batch_size: int,
        model: str = "",
    ) -> None:
        """Report training start event."""
        if not self._available:
            return

        self._get_gauge("training_active").set(1)
        self._get_gauge("training_total_epochs").set(total_epochs)
        self._get_gauge("training_batch_size").set(batch_size)
        self._get_gauge("training_start_time").set(time.time())
        self._push()

    def report_training_end(
        self,
        success: bool = True,
        final_metrics: dict[str, float] | None = None,
    ) -> None:
        """Report training completion."""
        if not self._available:
            return

        self._get_gauge("training_active").set(0)
        self._get_gauge("training_end_time").set(time.time())
        self._get_gauge("training_success").set(1 if success else 0)

        if final_metrics:
            for name, value in final_metrics.items():
                self._get_gauge(name).set(value)

        self._push()

    def report_gpu_metrics(
        self,
        gpu_id: int,
        utilization: float,
        memory_used_mb: float,
        memory_total_mb: float,
        temperature: float | None = None,
    ) -> None:
        """Report GPU utilization metrics."""
        if not self._available:
            return

        prefix = f"gpu_{gpu_id}"
        self._get_gauge(f"{prefix}_utilization").set(utilization)
        self._get_gauge(f"{prefix}_memory_used_mb").set(memory_used_mb)
        self._get_gauge(f"{prefix}_memory_total_mb").set(memory_total_mb)
        if temperature is not None:
            self._get_gauge(f"{prefix}_temperature").set(temperature)

        self._push()

    def _push(self) -> None:
        """Push all metrics to the Pushgateway."""
        try:
            from prometheus_client import push_to_gateway

            push_to_gateway(
                self._pushgw.replace("http://", "").replace("https://", ""),
                job=self._job_name,
                registry=self._registry,
                grouping_key=self._grouping_key,
            )
        except Exception:
            # Non-fatal: don't crash training for metrics failures
            pass

    def delete_metrics(self) -> None:
        """Delete all metrics for this job from the Pushgateway."""
        try:
            from prometheus_client import delete_from_gateway

            delete_from_gateway(
                self._pushgw.replace("http://", "").replace("https://", ""),
                job=self._job_name,
                grouping_key=self._grouping_key,
            )
        except Exception:
            pass
