"""Multi-Source Training Detection for GPU Yielding.

Detects training jobs from multiple sources to ensure inference models
yield GPU resources regardless of how training is initiated:

1. Ray Jobs API - Official Ray training jobs
2. File Signal - Simple file-based lock mechanism
3. HTTP Endpoint - RESTful training notification
4. GPU Memory Pressure - Detect external GPU usage
5. Redis/PubSub - Event-driven notification (optional)

This makes the system robust for:
- Ray-submitted training
- Local/direct training scripts
- External training pipelines
- CI/CD triggered training
"""

import os
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Set
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class TrainingSource(Enum):
    """Source that detected training activity."""

    RAY_JOB = "ray_job"
    FILE_SIGNAL = "file_signal"
    HTTP_SIGNAL = "http_signal"
    GPU_PRESSURE = "gpu_pressure"
    REDIS_PUBSUB = "redis_pubsub"
    MANUAL = "manual"


@dataclass
class TrainingSignal:
    """Information about detected training activity."""

    source: TrainingSource
    active: bool
    job_id: Optional[str] = None
    gpu_ids: List[int] = field(default_factory=list)
    priority: int = 0  # Higher = more urgent
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class TrainingDetector(ABC):
    """Base class for training detection strategies."""

    @abstractmethod
    async def detect(self) -> Optional[TrainingSignal]:
        """Check for training activity. Returns signal if detected."""
        pass

    @abstractmethod
    async def cleanup(self):
        """Clean up resources."""
        pass


class RayJobDetector(TrainingDetector):
    """Detect training via Ray Dashboard API."""

    def __init__(self, ray_address: str, http_client: httpx.AsyncClient):
        self.ray_address = ray_address
        self._http = http_client
        # Keywords to identify training jobs by entrypoint
        self._training_keywords = [
            "train",
            "fit",
            "ray.train",
            "pytorch",
            "tensorflow",
            "ultralytics",
            "yolo",
            "fine",
            "tune",
            "epoch",
            "pii-pro",
            "shml",
        ]

    async def detect(self) -> Optional[TrainingSignal]:
        try:
            # Check running jobs
            resp = await self._http.get(f"{self.ray_address}/api/jobs/")
            if resp.status_code == 200:
                jobs = resp.json()
                for job in jobs:
                    if job.get("status") == "RUNNING":
                        entrypoint = job.get("entrypoint", "").lower()
                        if any(kw in entrypoint for kw in self._training_keywords):
                            return TrainingSignal(
                                source=TrainingSource.RAY_JOB,
                                active=True,
                                job_id=job.get("job_id"),
                                priority=10,
                                metadata={"entrypoint": entrypoint},
                            )

            # Check GPU allocation in cluster
            resp = await self._http.get(f"{self.ray_address}/api/cluster_status")
            if resp.status_code == 200:
                status = resp.json()
                # Try loadMetricsReport first (newer Ray versions)
                data = status.get("data", status)
                cluster_status = data.get("clusterStatus", data)
                load_metrics = cluster_status.get("loadMetricsReport", {})
                resources = load_metrics.get("usage", {})

                # Fall back to autoscaler_report (older Ray versions)
                if not resources:
                    resources = cluster_status.get("autoscalerReport", {}).get(
                        "usage", {}
                    )

                # GPU usage is [used, total]
                gpu_usage = resources.get("GPU", [0, 0])
                gpu_used = gpu_usage[0] if isinstance(gpu_usage, list) else 0

                if gpu_used > 0:
                    return TrainingSignal(
                        source=TrainingSource.RAY_JOB,
                        active=True,
                        priority=10,
                        metadata={"gpus_allocated": gpu_used},
                    )

            return None

        except Exception as e:
            logger.debug(f"Ray detection error: {e}")
            return None

    async def cleanup(self):
        pass


class FileSignalDetector(TrainingDetector):
    """Detect training via file-based signals.

    Training scripts create a file to signal they need GPU resources.
    This is the simplest integration method for external scripts.

    Signal file format (JSON):
    {
        "job_id": "training-123",
        "gpus": [0, 1],
        "priority": 5,
        "started": "2025-12-05T10:30:00"
    }
    """

    DEFAULT_SIGNAL_DIR = "/tmp/shml/training-signals"

    def __init__(self, signal_dir: Optional[str] = None):
        self.signal_dir = Path(
            signal_dir or os.getenv("TRAINING_SIGNAL_DIR", self.DEFAULT_SIGNAL_DIR)
        )
        self.signal_dir.mkdir(parents=True, exist_ok=True)

    async def detect(self) -> Optional[TrainingSignal]:
        try:
            import json

            # Look for any .signal files
            signals = list(self.signal_dir.glob("*.signal"))
            if not signals:
                return None

            # Return highest priority signal
            best_signal = None
            best_priority = -1

            for signal_file in signals:
                try:
                    data = json.loads(signal_file.read_text())
                    priority = data.get("priority", 5)

                    # Check if signal is stale (> 5 minutes old)
                    started = data.get("started")
                    if started:
                        start_time = datetime.fromisoformat(started)
                        if datetime.now() - start_time > timedelta(hours=24):
                            # Stale signal, remove it
                            signal_file.unlink()
                            continue

                    if priority > best_priority:
                        best_priority = priority
                        best_signal = TrainingSignal(
                            source=TrainingSource.FILE_SIGNAL,
                            active=True,
                            job_id=data.get("job_id", signal_file.stem),
                            gpu_ids=data.get("gpus", []),
                            priority=priority,
                            metadata=data,
                        )

                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Invalid signal file {signal_file}: {e}")

            return best_signal

        except Exception as e:
            logger.debug(f"File signal detection error: {e}")
            return None

    async def cleanup(self):
        pass

    @staticmethod
    def create_signal(
        job_id: str,
        gpus: Optional[List[int]] = None,
        priority: int = 5,
        signal_dir: Optional[str] = None,
    ) -> Path:
        """Create a training signal file. Call this from training scripts."""
        import json

        signal_dir = Path(
            signal_dir
            or os.getenv("TRAINING_SIGNAL_DIR", FileSignalDetector.DEFAULT_SIGNAL_DIR)
        )
        signal_dir.mkdir(parents=True, exist_ok=True)

        signal_file = signal_dir / f"{job_id}.signal"
        signal_data = {
            "job_id": job_id,
            "gpus": gpus or [],
            "priority": priority,
            "started": datetime.now().isoformat(),
        }
        signal_file.write_text(json.dumps(signal_data))
        logger.info(f"Created training signal: {signal_file}")
        return signal_file

    @staticmethod
    def remove_signal(job_id: str, signal_dir: Optional[str] = None):
        """Remove a training signal file. Call when training completes."""
        signal_dir = Path(
            signal_dir
            or os.getenv("TRAINING_SIGNAL_DIR", FileSignalDetector.DEFAULT_SIGNAL_DIR)
        )
        signal_file = signal_dir / f"{job_id}.signal"
        if signal_file.exists():
            signal_file.unlink()
            logger.info(f"Removed training signal: {signal_file}")


class GPUPressureDetector(TrainingDetector):
    """Detect training by monitoring GPU memory pressure.

    If GPU memory usage increases significantly from external processes,
    this indicates training has started outside our control.
    """

    def __init__(self, threshold_percent: float = 0.85, our_pid: Optional[int] = None):
        self.threshold = threshold_percent
        self.our_pid = our_pid or os.getpid()
        self._baseline_usage: Optional[float] = None

    async def detect(self) -> Optional[TrainingSignal]:
        try:
            import subprocess
            import re

            # Get GPU memory info via nvidia-smi
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,used_memory",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return None

            external_memory = 0
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    pid = int(parts[0].strip())
                    memory_mb = int(parts[1].strip())

                    # Skip our own process
                    if pid != self.our_pid:
                        external_memory += memory_mb

            # If significant external GPU usage detected
            if external_memory > 1000:  # > 1GB external usage
                return TrainingSignal(
                    source=TrainingSource.GPU_PRESSURE,
                    active=True,
                    priority=3,  # Lower priority - might be false positive
                    metadata={"external_memory_mb": external_memory},
                )

            return None

        except Exception as e:
            logger.debug(f"GPU pressure detection error: {e}")
            return None

    async def cleanup(self):
        pass


class HTTPSignalReceiver:
    """HTTP endpoint to receive training signals.

    Training scripts can POST to /training/start and /training/stop
    to signal their GPU needs.
    """

    def __init__(self):
        self._active_signals: Dict[str, TrainingSignal] = {}
        self._lock = asyncio.Lock()

    async def signal_start(
        self,
        job_id: str,
        gpus: Optional[List[int]] = None,
        priority: int = 5,
        metadata: Optional[Dict] = None,
    ):
        """Called when training starts."""
        async with self._lock:
            self._active_signals[job_id] = TrainingSignal(
                source=TrainingSource.HTTP_SIGNAL,
                active=True,
                job_id=job_id,
                gpu_ids=gpus or [],
                priority=priority,
                metadata=metadata or {},
            )
        logger.info(f"Training signal received: {job_id}")

    async def signal_stop(self, job_id: str):
        """Called when training stops."""
        async with self._lock:
            self._active_signals.pop(job_id, None)
        logger.info(f"Training complete signal: {job_id}")

    async def get_signal(self) -> Optional[TrainingSignal]:
        """Get highest priority active signal."""
        async with self._lock:
            if not self._active_signals:
                return None

            return max(self._active_signals.values(), key=lambda s: s.priority)

    def get_active_jobs(self) -> List[str]:
        """Get list of active training job IDs."""
        return list(self._active_signals.keys())


class HTTPSignalDetector(TrainingDetector):
    """Wrapper around HTTPSignalReceiver for uniform interface."""

    def __init__(self, receiver: HTTPSignalReceiver):
        self.receiver = receiver

    async def detect(self) -> Optional[TrainingSignal]:
        return await self.receiver.get_signal()

    async def cleanup(self):
        pass


class MultiSourceTrainingDetector:
    """Aggregates multiple training detection sources.

    Monitors all configured sources and returns the highest priority
    training signal detected from any source.
    """

    def __init__(
        self,
        ray_address: Optional[str] = None,
        enable_file_signals: bool = True,
        enable_gpu_pressure: bool = False,  # Can cause false positives
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self._detectors: List[TrainingDetector] = []
        self._http_receiver = HTTPSignalReceiver()
        self._http_client = http_client
        self._owns_client = http_client is None

        # Set up detectors
        if ray_address:
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(timeout=5.0)
            self._detectors.append(RayJobDetector(ray_address, self._http_client))

        if enable_file_signals:
            self._detectors.append(FileSignalDetector())

        if enable_gpu_pressure:
            self._detectors.append(GPUPressureDetector())

        # Always enable HTTP receiver
        self._detectors.append(HTTPSignalDetector(self._http_receiver))

    @property
    def http_receiver(self) -> HTTPSignalReceiver:
        """Access the HTTP signal receiver for FastAPI integration."""
        return self._http_receiver

    async def is_training_active(self) -> bool:
        """Check if any training is active."""
        signal = await self.detect()
        return signal is not None and signal.active

    async def detect(self) -> Optional[TrainingSignal]:
        """Check all sources and return highest priority signal."""
        best_signal = None
        best_priority = -1

        # Check all detectors in parallel
        tasks = [d.detect() for d in self._detectors]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            if result is not None and result.active:
                if result.priority > best_priority:
                    best_priority = result.priority
                    best_signal = result

        return best_signal

    async def cleanup(self):
        """Clean up all detectors."""
        for detector in self._detectors:
            await detector.cleanup()

        if self._owns_client and self._http_client:
            await self._http_client.aclose()

    def get_status(self) -> Dict[str, Any]:
        """Get status of all detection sources."""
        return {
            "detectors": [type(d).__name__ for d in self._detectors],
            "http_active_jobs": self._http_receiver.get_active_jobs(),
        }


# Convenience functions for training scripts
def signal_training_start(
    job_id: str, gpus: Optional[List[int]] = None, priority: int = 5
) -> Path:
    """Signal that training is starting (creates file signal)."""
    return FileSignalDetector.create_signal(job_id, gpus, priority)


def signal_training_stop(job_id: str):
    """Signal that training is complete (removes file signal)."""
    FileSignalDetector.remove_signal(job_id)
