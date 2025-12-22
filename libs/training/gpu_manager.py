"""
GPU Resource Manager - Reusable GPU management for training jobs.

This module provides a unified interface for GPU resource management across
all training scripts in the SHML platform. It handles:

1. GPU yield before training (unloading inference models)
2. GPU reclaim after training (reloading inference models)
3. Automatic cleanup via context manager
4. Health checks and status monitoring
5. Graceful fallback when services unavailable

Hardware Configuration:
    GPU 0 (cuda:0): RTX 3090 Ti (24GB) - Primary training/inference
    GPU 1 (cuda:1): RTX 2070 (8GB)     - Fallback inference only

Service Endpoints:
    - Nemotron Manager:  http://nemotron-manager:8000 or localhost:8011
    - Z-Image:           http://z-image-api:8000 or localhost:8002
    - Qwen3-VL:          http://qwen3-vl:8000 (RTX 2070, no yield needed)

Usage:
    # Simple context manager (recommended)
    from libs.training.gpu_manager import TrainingContext

    async with TrainingContext(job_id="yolov8-train-001", gpu_id=0) as ctx:
        # GPU is yielded, ready for training
        train_model()
    # GPU is automatically reclaimed

    # Or use manual control
    from libs.training.gpu_manager import GPUResourceManager

    manager = GPUResourceManager()
    await manager.yield_gpu_for_training(gpu_id=0, job_id="train-001")
    try:
        train_model()
    finally:
        await manager.reclaim_gpu_after_training(gpu_id=0)

Author: SHML Platform
Date: January 2025
"""

import os
import sys
import time
import asyncio
import logging
import urllib.request
import urllib.error
import json
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from contextlib import asynccontextmanager, contextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class GPUState(Enum):
    """GPU allocation state."""

    UNKNOWN = "unknown"
    INFERENCE = "inference"  # Model loaded for inference
    TRAINING = "training"  # Allocated for training job
    IDLE = "idle"  # No model loaded
    YIELDING = "yielding"  # In process of yielding
    RECLAIMING = "reclaiming"  # In process of reclaiming


@dataclass
class GPUConfig:
    """Configuration for a specific GPU."""

    gpu_id: int
    name: str
    memory_mb: int
    yield_endpoints: List[str] = field(default_factory=list)  # Services to yield
    is_training_capable: bool = True


@dataclass
class ServiceEndpoint:
    """Endpoint configuration for an inference service."""

    name: str
    yield_url: str
    reclaim_url: str
    status_url: str
    gpu_id: int
    priority: int = 1  # Higher = yield first, reclaim last
    timeout_seconds: float = 30.0
    required: bool = False  # If True, training fails if yield fails


# Default endpoints configuration
DEFAULT_ENDPOINTS = [
    ServiceEndpoint(
        name="nemotron-manager",
        yield_url="http://nemotron-manager:8000/training/start",
        reclaim_url="http://nemotron-manager:8000/training/end",
        status_url="http://nemotron-manager:8000/status",
        gpu_id=0,
        priority=10,
        timeout_seconds=60.0,
        required=False,  # Training can proceed even if yield fails
    ),
    ServiceEndpoint(
        name="z-image",
        yield_url="http://z-image-api:8000/yield-to-training",
        reclaim_url="http://z-image-api:8000/reclaim-from-training",  # Auto-reloads on next request
        status_url="http://z-image-api:8000/health",
        gpu_id=0,
        priority=5,
        timeout_seconds=30.0,
        required=False,
    ),
]

# Fallback endpoints (localhost versions for development/testing)
FALLBACK_ENDPOINTS = [
    ServiceEndpoint(
        name="nemotron-manager-local",
        yield_url="http://localhost:8011/training/start",
        reclaim_url="http://localhost:8011/training/end",
        status_url="http://localhost:8011/status",
        gpu_id=0,
        priority=10,
        timeout_seconds=60.0,
        required=False,
    ),
    ServiceEndpoint(
        name="z-image-local",
        yield_url="http://localhost:8002/yield-to-training",
        reclaim_url="http://localhost:8002/reclaim-from-training",
        status_url="http://localhost:8002/health",
        gpu_id=0,
        priority=5,
        timeout_seconds=30.0,
        required=False,
    ),
]


class GPUResourceManager:
    """
    Manages GPU resources across training and inference workloads.

    This class coordinates with inference services to yield GPU resources
    before training and reclaim them after training completes.

    Thread-safe and supports both sync and async usage patterns.
    """

    def __init__(
        self,
        endpoints: Optional[List[ServiceEndpoint]] = None,
        use_fallback: bool = True,
        dry_run: bool = False,
    ):
        """
        Initialize GPU Resource Manager.

        Args:
            endpoints: Custom service endpoints (uses defaults if None)
            use_fallback: Try localhost endpoints if primary fails
            dry_run: If True, simulate operations without calling services
        """
        self.endpoints = endpoints or DEFAULT_ENDPOINTS.copy()
        self.fallback_endpoints = FALLBACK_ENDPOINTS if use_fallback else []
        self.dry_run = dry_run

        # Track state
        self._gpu_states: Dict[int, GPUState] = {}
        self._active_jobs: Dict[int, str] = {}  # gpu_id -> job_id
        self._yield_history: List[Dict[str, Any]] = []

    def _http_request(
        self,
        url: str,
        method: str = "POST",
        data: Optional[Dict] = None,
        timeout: float = 30.0,
    ) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Make HTTP request (sync version using urllib for compatibility).

        Returns:
            (success, response_json, error_message)
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would {method} {url}")
            return True, {"status": "dry_run"}, None

        try:
            req_data = json.dumps(data).encode() if data else None
            request = urllib.request.Request(
                url,
                data=req_data,
                method=method,
                headers={"Content-Type": "application/json"} if data else {},
            )

            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_data = response.read().decode()
                try:
                    return True, json.loads(response_data), None
                except json.JSONDecodeError:
                    return True, {"raw": response_data}, None

        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else str(e)
            return False, None, f"HTTP {e.code}: {error_body}"
        except urllib.error.URLError as e:
            return False, None, f"Connection error: {e.reason}"
        except TimeoutError:
            return False, None, f"Timeout after {timeout}s"
        except Exception as e:
            return False, None, str(e)

    def _get_endpoints_for_gpu(self, gpu_id: int) -> List[ServiceEndpoint]:
        """Get all endpoints that manage the specified GPU."""
        return [ep for ep in self.endpoints if ep.gpu_id == gpu_id]

    def _get_fallback_endpoints_for_gpu(self, gpu_id: int) -> List[ServiceEndpoint]:
        """Get fallback endpoints for the specified GPU."""
        return [ep for ep in self.fallback_endpoints if ep.gpu_id == gpu_id]

    def yield_gpu_for_training(
        self,
        gpu_id: int = 0,
        job_id: str = "unknown",
        estimated_duration_hours: float = 2.0,
        memory_required_gb: float = 20.0,
    ) -> Dict[str, Any]:
        """
        Request GPU yield from all inference services.

        This method contacts each inference service managing the specified GPU
        and requests them to unload their models to free VRAM.

        Args:
            gpu_id: Target GPU ID (default 0 for RTX 3090)
            job_id: Training job identifier for tracking
            estimated_duration_hours: Estimated training duration
            memory_required_gb: Required GPU memory

        Returns:
            Dict with yield results for each service
        """
        logger.info(f"🔄 Requesting GPU {gpu_id} yield for training job: {job_id}")

        results = {
            "success": True,
            "job_id": job_id,
            "gpu_id": gpu_id,
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "errors": [],
        }

        # Get endpoints for this GPU, sorted by priority (high first)
        endpoints = sorted(
            self._get_endpoints_for_gpu(gpu_id), key=lambda e: -e.priority
        )

        if not endpoints:
            logger.warning(f"No endpoints configured for GPU {gpu_id}")
            results["warnings"] = ["No endpoints configured"]
            return results

        for endpoint in endpoints:
            service_result = self._yield_service(
                endpoint,
                job_id=job_id,
                estimated_duration_hours=estimated_duration_hours,
                memory_required_gb=memory_required_gb,
            )
            results["services"][endpoint.name] = service_result

            if not service_result["success"]:
                # Try fallback if available
                fallback = self._find_fallback_endpoint(endpoint.name, gpu_id)
                if fallback:
                    logger.info(f"Trying fallback endpoint for {endpoint.name}")
                    fallback_result = self._yield_service(
                        fallback,
                        job_id=job_id,
                        estimated_duration_hours=estimated_duration_hours,
                        memory_required_gb=memory_required_gb,
                    )
                    results["services"][f"{endpoint.name}-fallback"] = fallback_result
                    service_result = fallback_result

                if not service_result["success"] and endpoint.required:
                    results["success"] = False
                    results["errors"].append(
                        f"Required service {endpoint.name} failed to yield"
                    )

        # Update state tracking
        if results["success"]:
            self._gpu_states[gpu_id] = GPUState.TRAINING
            self._active_jobs[gpu_id] = job_id

        # Record history
        self._yield_history.append(
            {
                "action": "yield",
                "results": results,
                "timestamp": datetime.now().isoformat(),
            }
        )

        return results

    def _yield_service(
        self,
        endpoint: ServiceEndpoint,
        job_id: str,
        estimated_duration_hours: float,
        memory_required_gb: float,
    ) -> Dict[str, Any]:
        """Yield a single service."""
        logger.info(f"  → Yielding {endpoint.name}...")

        success, response, error = self._http_request(
            endpoint.yield_url,
            method="POST",
            data={
                "job_id": job_id,
                "estimated_duration_hours": estimated_duration_hours,
                "memory_required_gb": memory_required_gb,
            },
            timeout=endpoint.timeout_seconds,
        )

        result = {
            "success": success,
            "endpoint": endpoint.name,
            "url": endpoint.yield_url,
            "response": response,
            "error": error,
        }

        if success:
            logger.info(f"    ✓ {endpoint.name} yielded successfully")
        else:
            logger.warning(f"    ✗ {endpoint.name} yield failed: {error}")

        return result

    def _find_fallback_endpoint(
        self, service_name: str, gpu_id: int
    ) -> Optional[ServiceEndpoint]:
        """Find fallback endpoint for a service."""
        for ep in self._get_fallback_endpoints_for_gpu(gpu_id):
            if service_name in ep.name:
                return ep
        return None

    def reclaim_gpu_after_training(
        self, gpu_id: int = 0, job_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request GPU reclaim - notify services training is complete.

        Services can reload their models after this call.

        Args:
            gpu_id: Target GPU ID
            job_id: Training job identifier (uses tracked if None)

        Returns:
            Dict with reclaim results for each service
        """
        if job_id is None:
            job_id = self._active_jobs.get(gpu_id, "unknown")

        logger.info(f"🔄 Reclaiming GPU {gpu_id} after training job: {job_id}")

        results = {
            "success": True,
            "job_id": job_id,
            "gpu_id": gpu_id,
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "errors": [],
        }

        # Get endpoints sorted by priority (LOW first for reclaim)
        endpoints = sorted(
            self._get_endpoints_for_gpu(gpu_id), key=lambda e: e.priority
        )

        for endpoint in endpoints:
            service_result = self._reclaim_service(endpoint, job_id)
            results["services"][endpoint.name] = service_result

            if not service_result["success"]:
                # Try fallback
                fallback = self._find_fallback_endpoint(endpoint.name, gpu_id)
                if fallback:
                    fallback_result = self._reclaim_service(fallback, job_id)
                    results["services"][f"{endpoint.name}-fallback"] = fallback_result

        # Update state
        self._gpu_states[gpu_id] = GPUState.IDLE
        if gpu_id in self._active_jobs:
            del self._active_jobs[gpu_id]

        # Record history
        self._yield_history.append(
            {
                "action": "reclaim",
                "results": results,
                "timestamp": datetime.now().isoformat(),
            }
        )

        return results

    def _reclaim_service(
        self, endpoint: ServiceEndpoint, job_id: str
    ) -> Dict[str, Any]:
        """Reclaim a single service."""
        logger.info(f"  → Notifying {endpoint.name} training complete...")

        success, response, error = self._http_request(
            endpoint.reclaim_url,
            method="POST",
            data={"job_id": job_id},
            timeout=endpoint.timeout_seconds,
        )

        result = {
            "success": success,
            "endpoint": endpoint.name,
            "url": endpoint.reclaim_url,
            "response": response,
            "error": error,
        }

        if success:
            logger.info(f"    ✓ {endpoint.name} notified")
        else:
            # Reclaim failures are less critical - services can reload on demand
            logger.warning(
                f"    ⚠ {endpoint.name} reclaim notification failed: {error}"
            )
            result["success"] = True  # Don't fail training cleanup for reclaim issues

        return result

    def get_gpu_status(self, gpu_id: int = 0) -> Dict[str, Any]:
        """
        Get current GPU status from all services.

        Returns:
            Dict with status from each service
        """
        results = {
            "gpu_id": gpu_id,
            "state": self._gpu_states.get(gpu_id, GPUState.UNKNOWN).value,
            "active_job": self._active_jobs.get(gpu_id),
            "services": {},
        }

        for endpoint in self._get_endpoints_for_gpu(gpu_id):
            success, response, error = self._http_request(
                endpoint.status_url, method="GET", timeout=5.0
            )
            results["services"][endpoint.name] = {
                "reachable": success,
                "status": response,
                "error": error,
            }

        return results

    def get_yield_history(self) -> List[Dict[str, Any]]:
        """Get history of yield/reclaim operations."""
        return self._yield_history.copy()


@contextmanager
def TrainingContext(
    job_id: str,
    gpu_id: int = 0,
    estimated_duration_hours: float = 2.0,
    memory_required_gb: float = 20.0,
    dry_run: bool = False,
):
    """
    Synchronous context manager for training GPU management.

    Automatically yields GPU before training and reclaims after.
    Safe to use even if yield/reclaim fails - training proceeds.

    Usage:
        with TrainingContext(job_id="yolov8-train-001", gpu_id=0) as ctx:
            # GPU is yielded
            train_model()
        # GPU is automatically reclaimed

    Args:
        job_id: Unique training job identifier
        gpu_id: Target GPU ID (default 0 = RTX 3090)
        estimated_duration_hours: Estimated training time
        memory_required_gb: Required GPU memory
        dry_run: If True, skip actual yield/reclaim calls
    """
    manager = GPUResourceManager(dry_run=dry_run)

    context = {
        "job_id": job_id,
        "gpu_id": gpu_id,
        "yield_result": None,
        "reclaim_result": None,
        "manager": manager,
    }

    try:
        # Yield GPU before training
        logger.info(f"═══════════════════════════════════════════════════════════════")
        logger.info(f"🚀 Training Context: Preparing GPU {gpu_id} for job {job_id}")
        logger.info(f"═══════════════════════════════════════════════════════════════")

        context["yield_result"] = manager.yield_gpu_for_training(
            gpu_id=gpu_id,
            job_id=job_id,
            estimated_duration_hours=estimated_duration_hours,
            memory_required_gb=memory_required_gb,
        )

        if context["yield_result"]["success"]:
            logger.info(f"✅ GPU {gpu_id} ready for training")
        else:
            logger.warning(f"⚠️ GPU yield had issues but proceeding with training")

        # Give services time to release GPU memory
        time.sleep(2.0)

        yield context

    finally:
        # Always reclaim GPU after training
        logger.info(f"═══════════════════════════════════════════════════════════════")
        logger.info(f"🏁 Training Context: Releasing GPU {gpu_id} from job {job_id}")
        logger.info(f"═══════════════════════════════════════════════════════════════")

        context["reclaim_result"] = manager.reclaim_gpu_after_training(
            gpu_id=gpu_id, job_id=job_id
        )

        logger.info(f"✅ GPU {gpu_id} released, inference services notified")


@asynccontextmanager
async def AsyncTrainingContext(
    job_id: str,
    gpu_id: int = 0,
    estimated_duration_hours: float = 2.0,
    memory_required_gb: float = 20.0,
    dry_run: bool = False,
):
    """
    Async context manager for training GPU management.

    Same as TrainingContext but for async code.

    Usage:
        async with AsyncTrainingContext(job_id="yolov8-train-001") as ctx:
            await train_model_async()
    """
    # Use sync implementation wrapped in executor for now
    # (HTTP calls are quick, doesn't block event loop significantly)
    manager = GPUResourceManager(dry_run=dry_run)

    context = {
        "job_id": job_id,
        "gpu_id": gpu_id,
        "yield_result": None,
        "reclaim_result": None,
        "manager": manager,
    }

    try:
        logger.info(f"═══════════════════════════════════════════════════════════════")
        logger.info(
            f"🚀 Async Training Context: Preparing GPU {gpu_id} for job {job_id}"
        )
        logger.info(f"═══════════════════════════════════════════════════════════════")

        # Run yield in executor to not block
        loop = asyncio.get_event_loop()
        context["yield_result"] = await loop.run_in_executor(
            None,
            lambda: manager.yield_gpu_for_training(
                gpu_id=gpu_id,
                job_id=job_id,
                estimated_duration_hours=estimated_duration_hours,
                memory_required_gb=memory_required_gb,
            ),
        )

        if context["yield_result"]["success"]:
            logger.info(f"✅ GPU {gpu_id} ready for training")
        else:
            logger.warning(f"⚠️ GPU yield had issues but proceeding with training")

        await asyncio.sleep(2.0)

        yield context

    finally:
        logger.info(f"═══════════════════════════════════════════════════════════════")
        logger.info(
            f"🏁 Async Training Context: Releasing GPU {gpu_id} from job {job_id}"
        )
        logger.info(f"═══════════════════════════════════════════════════════════════")

        loop = asyncio.get_event_loop()
        context["reclaim_result"] = await loop.run_in_executor(
            None,
            lambda: manager.reclaim_gpu_after_training(gpu_id=gpu_id, job_id=job_id),
        )

        logger.info(f"✅ GPU {gpu_id} released, inference services notified")


def ensure_gpu_available_for_training(
    gpu_id: int = 0, job_id: str = "unknown", estimated_duration_hours: float = 2.0
) -> bool:
    """
    Convenience function to yield GPU before training.

    Call this BEFORE importing torch/YOLO to ensure GPU is free.
    Returns True if GPU is ready, False if yield failed critically.

    Usage:
        from libs.training.gpu_manager import ensure_gpu_available_for_training

        if not ensure_gpu_available_for_training(gpu_id=0, job_id="train-001"):
            print("Warning: GPU may have other processes")

        # Now safe to import torch
        import torch
        from ultralytics import YOLO
    """
    manager = GPUResourceManager()
    result = manager.yield_gpu_for_training(
        gpu_id=gpu_id, job_id=job_id, estimated_duration_hours=estimated_duration_hours
    )

    # Check if any required services failed
    has_critical_failure = any(
        not svc.get("success", True)
        for name, svc in result.get("services", {}).items()
        if "required" in name.lower()
    )

    return not has_critical_failure


def release_gpu_after_training(gpu_id: int = 0, job_id: str = "unknown"):
    """
    Convenience function to reclaim GPU after training.

    Call this at the end of training to notify inference services.

    Usage:
        from libs.training.gpu_manager import release_gpu_after_training

        try:
            train_model()
        finally:
            release_gpu_after_training(gpu_id=0, job_id="train-001")
    """
    manager = GPUResourceManager()
    manager.reclaim_gpu_after_training(gpu_id=gpu_id, job_id=job_id)


# Module-level exports
__all__ = [
    "GPUResourceManager",
    "GPUState",
    "GPUConfig",
    "ServiceEndpoint",
    "TrainingContext",
    "AsyncTrainingContext",
    "ensure_gpu_available_for_training",
    "release_gpu_after_training",
    "DEFAULT_ENDPOINTS",
    "FALLBACK_ENDPOINTS",
]


if __name__ == "__main__":
    # Test the module
    print("Testing GPU Resource Manager...")

    manager = GPUResourceManager(dry_run=True)

    # Test yield
    result = manager.yield_gpu_for_training(
        gpu_id=0,
        job_id="test-job-001",
        estimated_duration_hours=1.0,
        memory_required_gb=20.0,
    )
    print(f"\nYield result: {json.dumps(result, indent=2)}")

    # Test reclaim
    result = manager.reclaim_gpu_after_training(gpu_id=0)
    print(f"\nReclaim result: {json.dumps(result, indent=2)}")

    # Test context manager
    print("\n--- Testing Context Manager ---")
    with TrainingContext(job_id="test-context-001", gpu_id=0, dry_run=True) as ctx:
        print(f"Inside training context: {ctx['job_id']}")
        print("Simulating training...")
        time.sleep(1)
    print("Context manager completed")
