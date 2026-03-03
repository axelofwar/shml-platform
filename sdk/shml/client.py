"""
SHML Platform Client
=====================

Unified client for the SHML platform — job submission, status,
GPU management, and integration sub-clients.

Usage:
    from shml import Client, TrainingConfig

    # Minimal — reads env / credentials automatically
    with Client() as c:
        job = c.submit_training("balanced", epochs=10)
        print(c.job_status(job.job_id))

    # Explicit config
    from shml.config import AuthConfig, PlatformConfig
    with Client(auth=AuthConfig(api_key="shml_xxx")) as c:
        c.mlflow.setup_experiment("my-exp")
"""

from __future__ import annotations

import base64
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from shml.config import AuthConfig, JobConfig, PlatformConfig, TrainingConfig
from shml.exceptions import (
    AuthenticationError,
    JobSubmissionError,
    JobTimeoutError,
    NotFoundError,
    PermissionDeniedError,
    SHMLError,
    raise_for_status,
)


class Job:
    """Lightweight job handle returned after submission."""

    def __init__(self, job_id: str, name: str, status: str, **extra: Any):
        self.job_id = job_id
        self.name = name
        self.status = status
        self.extra = extra

    def __repr__(self) -> str:
        return f"Job(id={self.job_id!r}, name={self.name!r}, status={self.status!r})"


class Client:
    """
    SHML Platform API Client.

    Supports API key and OAuth authentication, context-manager lifecycle,
    lazy integration sub-clients, and config-driven job submission.
    """

    def __init__(
        self,
        auth: AuthConfig | None = None,
        platform: PlatformConfig | None = None,
        timeout: float = 30.0,
        api_prefix: str = "/api/ray",
    ):
        """
        Args:
            auth: Authentication config (reads env / credentials if omitted).
            platform: Platform config (reads env if omitted).
            timeout: HTTP request timeout in seconds.
            api_prefix: API path prefix (Traefik routing).
        """
        self.auth = auth or AuthConfig()
        self.platform = platform or PlatformConfig.from_env()
        self.timeout = timeout
        self.api_prefix = api_prefix

        self._http: httpx.Client | None = None

        # Lazy integration sub-clients
        self._mlflow: Any = None
        self._nessie: Any = None
        self._fiftyone: Any = None
        self._features: Any = None
        self._prometheus: Any = None

    # ── HTTP client ──────────────────────────────────────────────────────

    @property
    def http(self) -> httpx.Client:
        """Lazy httpx client."""
        if self._http is None:
            base = self.auth.base_url or self.platform.gateway_url
            self._http = httpx.Client(base_url=base, timeout=self.timeout)
        return self._http

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        headers.update(self.auth.auth_headers)
        return headers

    def _handle(self, resp: httpx.Response) -> dict[str, Any]:
        """Handle response, raising typed exceptions on error."""
        if resp.status_code < 400:
            if resp.status_code == 204:
                return {}
            return resp.json()
        raise_for_status(resp.status_code, resp.text)
        return {}  # unreachable

    # ── Integration sub-clients (lazy) ───────────────────────────────────

    @property
    def mlflow(self):
        """MLflow integration client."""
        if self._mlflow is None:
            from shml.integrations.mlflow import MLflowClient

            self._mlflow = MLflowClient(self.platform)
        return self._mlflow

    @property
    def nessie(self):
        """Nessie integration client."""
        if self._nessie is None:
            from shml.integrations.nessie import NessieClient

            self._nessie = NessieClient(self.platform)
        return self._nessie

    @property
    def fiftyone(self):
        """FiftyOne integration client."""
        if self._fiftyone is None:
            from shml.integrations.fiftyone import FiftyOneClient

            self._fiftyone = FiftyOneClient(self.platform)
        return self._fiftyone

    @property
    def features(self):
        """Feature store integration client."""
        if self._features is None:
            from shml.integrations.features import FeatureClient

            self._features = FeatureClient(self.platform)
        return self._features

    @property
    def prometheus(self):
        """Prometheus/Pushgateway integration client."""
        if self._prometheus is None:
            from shml.integrations.prometheus import PrometheusReporter

            self._prometheus = PrometheusReporter(self.platform)
        return self._prometheus

    # ── Job Operations ───────────────────────────────────────────────────

    def submit_training(
        self,
        profile: str | None = None,
        config: TrainingConfig | None = None,
        **overrides: Any,
    ) -> Job:
        """Submit a training job from a profile name or TrainingConfig.

        Args:
            profile: Named profile (e.g. "balanced", "quick-test").
            config: Explicit TrainingConfig (takes priority over profile).
            **overrides: Override any TrainingConfig field.

        Returns:
            Job handle with job_id.
        """
        if config is None:
            if profile:
                job_cfg = JobConfig.from_profile(profile, overrides=overrides)
                config = job_cfg.training
            else:
                config = TrainingConfig(**overrides)

        name = f"train-{config.model}-{datetime.now():%Y%m%d-%H%M%S}"

        payload: dict[str, Any] = {
            "name": name,
            "job_type": "training",
            "cpu": 4,
            "memory_gb": 16,
            "gpu": 1.0,
            "timeout_hours": max(1, config.epochs),
            "priority": "normal",
        }

        # Build entrypoint from config
        entrypoint_args = config.to_ultralytics_dict()
        payload["entrypoint"] = (
            f'python -c "from ultralytics import YOLO; '
            f"m = YOLO('{config.model}'); "
            f"m.train(data='{config.data_yaml}', epochs={config.epochs}, "
            f'batch={config.batch}, imgsz={config.imgsz})"'
        )

        if config.mlflow_experiment:
            payload["mlflow_experiment"] = config.mlflow_experiment

        try:
            resp = self.http.post(
                f"{self.api_prefix}/jobs",
                json=payload,
                headers=self._headers(),
            )
            data = self._handle(resp)
            return Job(
                job_id=data.get("job_id", ""),
                name=data.get("name", name),
                status=data.get("status", "PENDING"),
            )
        except SHMLError:
            raise
        except Exception as e:
            raise JobSubmissionError(f"Training submission failed: {e}", job_id="")

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
        """Submit a Python script file as a job."""
        path = Path(script_path)
        if not path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")

        if not name:
            name = f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}"

        payload: dict[str, Any] = {
            "name": name,
            "job_type": kwargs.get("job_type", "training"),
            "cpu": cpu,
            "memory_gb": memory_gb,
            "gpu": gpu,
            "timeout_hours": timeout_hours,
            "priority": kwargs.get("priority", "normal"),
            "script_content": base64.b64encode(path.read_bytes()).decode(),
            "script_name": path.name,
        }

        if args:
            payload["entrypoint_args"] = args
        if requirements:
            payload["requirements"] = requirements

        resp = self.http.post(
            f"{self.api_prefix}/jobs",
            json=payload,
            headers=self._headers(),
        )
        data = self._handle(resp)
        return Job(
            job_id=data.get("job_id", ""),
            name=data.get("name", name),
            status=data.get("status", "PENDING"),
        )

    def job_status(self, job_id: str) -> Job:
        """Get current job status."""
        resp = self.http.get(
            f"{self.api_prefix}/jobs/{job_id}",
            headers=self._headers(),
        )
        data = self._handle(resp)
        return Job(**data)

    def job_logs(self, job_id: str) -> str:
        """Get job logs."""
        resp = self.http.get(
            f"{self.api_prefix}/jobs/{job_id}/logs",
            headers=self._headers(),
        )
        data = self._handle(resp)
        return data.get("logs", "")

    def cancel_job(self, job_id: str, reason: str | None = None) -> Job:
        """Cancel a running job."""
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason

        resp = self.http.post(
            f"{self.api_prefix}/jobs/{job_id}/cancel",
            json=payload,
            headers=self._headers(),
        )
        data = self._handle(resp)
        return Job(**data)

    def list_jobs(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> list[Job]:
        """List jobs with optional filtering."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status

        resp = self.http.get(
            f"{self.api_prefix}/jobs",
            params=params,
            headers=self._headers(),
        )
        data = self._handle(resp)
        return [Job(**j) for j in data.get("jobs", [])]

    def wait_for_job(
        self,
        job_id: str,
        poll_interval: float = 10.0,
        timeout: float = 3600.0,
    ) -> Job:
        """Block until a job completes or timeout.

        Returns the final Job state.
        Raises JobTimeoutError if the job doesn't finish in time.
        """
        start = time.monotonic()
        while True:
            job = self.job_status(job_id)
            if job.status in ("SUCCEEDED", "FAILED", "STOPPED", "CANCELLED"):
                return job
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                raise JobTimeoutError(
                    f"Job {job_id} did not complete within {timeout}s",
                    job_id=job_id,
                )
            time.sleep(poll_interval)

    # ── GPU Management ───────────────────────────────────────────────────

    def gpu_status(self) -> list[dict[str, Any]]:
        """Get GPU status from the platform."""
        try:
            resp = self.http.get(
                f"{self.api_prefix}/gpu/status",
                headers=self._headers(),
            )
            return self._handle(resp).get("gpus", [])
        except Exception:
            return []

    def gpu_yield(self, gpu_ids: list[int] | None = None) -> dict[str, Any]:
        """Yield GPU resources for training (stops inference containers)."""
        payload: dict[str, Any] = {}
        if gpu_ids:
            payload["gpu_ids"] = gpu_ids

        resp = self.http.post(
            f"{self.api_prefix}/gpu/yield",
            json=payload,
            headers=self._headers(),
        )
        return self._handle(resp)

    def gpu_reclaim(self) -> dict[str, Any]:
        """Reclaim GPU resources (restart inference containers)."""
        resp = self.http.post(
            f"{self.api_prefix}/gpu/reclaim",
            json={},
            headers=self._headers(),
        )
        return self._handle(resp)

    # ── User / Auth ──────────────────────────────────────────────────────

    def whoami(self) -> dict[str, Any]:
        """Get current user profile."""
        resp = self.http.get(
            f"{self.api_prefix}/user/me",
            headers=self._headers(),
        )
        return self._handle(resp)

    def quota(self) -> dict[str, Any]:
        """Get current user quota."""
        resp = self.http.get(
            f"{self.api_prefix}/user/quota",
            headers=self._headers(),
        )
        return self._handle(resp)

    # ── Platform Health ──────────────────────────────────────────────────

    def health_check(self) -> dict[str, bool]:
        """Check health of all integrated services."""
        results: dict[str, bool] = {}

        # MLflow
        try:
            results["mlflow"] = self.mlflow.healthy()
        except Exception:
            results["mlflow"] = False

        # Nessie
        try:
            results["nessie"] = self.nessie.healthy()
        except Exception:
            results["nessie"] = False

        # FiftyOne
        try:
            results["fiftyone"] = self.fiftyone.available and self.fiftyone.healthy()
        except Exception:
            results["fiftyone"] = False

        # Feature store
        try:
            results["features"] = self.features.available and self.features.healthy()
        except Exception:
            results["features"] = False

        # Prometheus
        try:
            results["prometheus"] = (
                self.prometheus.available and self.prometheus.healthy()
            )
        except Exception:
            results["prometheus"] = False

        return results

    # ── Lifecycle ────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the HTTP client and clean up."""
        if self._http:
            self._http.close()
            self._http = None

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        base = self.auth.base_url or self.platform.gateway_url
        return f"Client(base_url={base!r})"
