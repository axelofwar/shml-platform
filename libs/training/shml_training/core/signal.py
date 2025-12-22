#!/usr/bin/env python3
"""
Training Signal Context Manager for SHML Platform.

Use this module to signal training start/stop to the inference service
so it can yield GPU resources properly.

Supports multiple signaling methods:
1. HTTP API (recommended for containerized inference)
2. File-based signals (works across containers with shared volume)

Usage:
    # As a context manager
    from shml_training.signal import training_context, signal_config

    # Configure the signal endpoint
    signal_config.inference_url = "http://localhost:8000"

    with training_context(job_id="my-training-run", gpus=[0]):
        # Your training code here
        model = train_model(...)

    # Or with decorators
    @requires_gpu(job_id="my-training", gpus=[0])
    def train():
        ...
"""

import os
import sys
import uuid
import json
import time
import signal
import atexit
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from contextlib import contextmanager
from functools import wraps

logger = logging.getLogger(__name__)


@dataclass
class SignalConfig:
    """Configuration for training signal system."""

    # HTTP signaling (primary method for containerized inference)
    # Primary: nemotron-manager service (for llama.cpp models)
    inference_url: str = "http://nemotron-manager:8000"
    fallback_inference_url: str = "http://localhost:8011"

    # Secondary: z-image service (for image generation on RTX 3090)
    z_image_url: str = "http://z-image-api:8000"
    z_image_fallback_url: str = "http://localhost:8002"

    # File-based signaling (backup method)
    signal_dir: str = "/tmp/shml/training-signals"

    # Timing
    yield_wait_seconds: float = 15.0  # Wait for inference to yield
    poll_interval: float = 1.0
    max_wait_retries: int = 30

    # Behavior
    use_http: bool = True
    use_file: bool = True
    fail_on_yield_timeout: bool = False  # If True, abort if inference doesn't yield
    yield_z_image: bool = True  # Whether to also yield z-image (RTX 3090 image gen)


# Global config - can be modified before training
signal_config = SignalConfig()


def _send_http_signal(
    action: str,
    job_id: str,
    gpus: Optional[List[int]] = None,
    priority: int = 10,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Send HTTP signal to inference services.

    Signals both nemotron-manager (LLM) and z-image (image gen) services
    to yield GPU resources for training.
    """
    import httpx

    success = False

    # Primary inference services to signal
    services = [
        {
            "name": "nemotron-manager",
            "urls": [signal_config.inference_url, signal_config.fallback_inference_url],
            "start_endpoint": "/training/start",
            "stop_endpoint": "/training/end",
        },
    ]

    # Optionally include z-image
    if signal_config.yield_z_image:
        services.append(
            {
                "name": "z-image",
                "urls": [signal_config.z_image_url, signal_config.z_image_fallback_url],
                "start_endpoint": "/yield-to-training",
                "stop_endpoint": "/reclaim-from-training",
            }
        )

    for service in services:
        service_success = False
        for base_url in service["urls"]:
            if not base_url:
                continue
            try:
                if action == "start":
                    url = f"{base_url}{service['start_endpoint']}"
                    response = httpx.post(
                        url,
                        json={
                            "job_id": job_id,
                            "gpus": gpus,
                            "priority": priority,
                            "metadata": metadata or {},
                        },
                        timeout=30.0,  # Increased for model unloading
                    )
                elif action == "stop":
                    url = f"{base_url}{service['stop_endpoint']}"
                    response = httpx.post(
                        url,
                        json={"job_id": job_id},
                        timeout=10.0,
                    )
                else:
                    logger.error(f"Unknown action: {action}")
                    continue

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except:
                        data = {"status": "ok"}
                    logger.info(
                        f"Training signal ({action}) to {service['name']}: {data}"
                    )
                    service_success = True
                    success = True  # At least one service responded
                    break
                else:
                    logger.warning(
                        f"Signal to {service['name']} failed ({response.status_code}): {response.text}"
                    )

            except Exception as e:
                logger.debug(
                    f"HTTP signal to {base_url} ({service['name']}) failed: {e}"
                )
                continue

        if not service_success:
            logger.warning(
                f"Could not signal {service['name']} - service may be unavailable"
            )

    return success


def _create_file_signal(
    job_id: str,
    gpus: Optional[List[int]] = None,
    priority: int = 10,
) -> Optional[Path]:
    """Create file-based signal."""
    try:
        signal_dir = Path(signal_config.signal_dir)
        signal_dir.mkdir(parents=True, exist_ok=True)

        signal_file = signal_dir / f"{job_id}.signal"
        signal_data = {
            "job_id": job_id,
            "gpus": gpus or [],
            "priority": priority,
            "started": datetime.now().isoformat(),
            "pid": os.getpid(),
        }
        signal_file.write_text(json.dumps(signal_data))
        logger.info(f"Created signal file: {signal_file}")
        return signal_file

    except Exception as e:
        logger.warning(f"Failed to create signal file: {e}")
        return None


def _remove_file_signal(job_id: str):
    """Remove file-based signal."""
    try:
        signal_dir = Path(signal_config.signal_dir)
        signal_file = signal_dir / f"{job_id}.signal"
        if signal_file.exists():
            signal_file.unlink()
            logger.info(f"Removed signal file: {signal_file}")
    except Exception as e:
        logger.warning(f"Failed to remove signal file: {e}")


def _wait_for_gpu_resources(timeout: float = 15.0) -> bool:
    """Wait for GPU resources to become available.

    After signaling training start, the inference service needs time
    to unload its model and free GPU memory.
    """
    import subprocess

    start = time.time()
    check_interval = 1.0

    while time.time() - start < timeout:
        try:
            # Check GPU memory using nvidia-smi
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.free,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                for i, line in enumerate(lines):
                    parts = line.split(",")
                    if len(parts) >= 2:
                        free_mb = int(parts[0].strip())
                        total_mb = int(parts[1].strip())
                        free_pct = free_mb / total_mb

                        # Consider GPU available if > 50% free
                        if free_pct > 0.5:
                            logger.info(
                                f"GPU {i} available: {free_mb}MB free "
                                f"({free_pct*100:.1f}%)"
                            )
                            return True

        except Exception as e:
            logger.debug(f"GPU check failed: {e}")

        time.sleep(check_interval)

    logger.warning(f"Timed out waiting for GPU resources after {timeout}s")
    return False


def signal_training_start(
    job_id: str,
    gpus: Optional[List[int]] = None,
    priority: int = 10,
    wait_for_yield: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Signal that training is about to start.

    Call this BEFORE initializing PyTorch/CUDA to allow the inference
    service to yield GPU resources first.

    Args:
        job_id: Unique identifier for this training run
        gpus: List of GPU indices needed (None = all)
        priority: Higher priority = more urgent
        wait_for_yield: Whether to wait for GPU resources to free up
        metadata: Additional metadata for the signal

    Returns:
        True if signaling succeeded and resources are available
    """
    success = False

    # Try HTTP signal first
    if signal_config.use_http:
        success = _send_http_signal("start", job_id, gpus, priority, metadata)

    # Create file signal as backup
    if signal_config.use_file:
        _create_file_signal(job_id, gpus, priority)
        if not success:
            success = True  # File signal created

    if not success:
        logger.warning("Could not signal training start to inference service")
        if signal_config.fail_on_yield_timeout:
            return False

    # Wait for inference to yield GPU
    if wait_for_yield:
        logger.info(
            f"Waiting up to {signal_config.yield_wait_seconds}s for GPU resources..."
        )
        resources_available = _wait_for_gpu_resources(
            timeout=signal_config.yield_wait_seconds
        )
        if not resources_available:
            logger.warning("GPU resources may still be in use by inference")
            if signal_config.fail_on_yield_timeout:
                return False

    return True


def signal_training_stop(job_id: str) -> bool:
    """
    Signal that training has completed.

    Call this after training finishes (success or failure) to allow
    the inference service to reclaim GPU resources.

    Args:
        job_id: The same job_id used in signal_training_start

    Returns:
        True if signaling succeeded
    """
    success = False

    # Send HTTP signal
    if signal_config.use_http:
        success = _send_http_signal("stop", job_id)

    # Remove file signal
    if signal_config.use_file:
        _remove_file_signal(job_id)
        if not success:
            success = True

    return success


@contextmanager
def training_context(
    job_id: Optional[str] = None,
    gpus: Optional[List[int]] = None,
    priority: int = 10,
    wait_for_yield: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
):
    """
    Context manager for training that handles GPU yielding signals.

    Usage:
        with training_context(job_id="my-run", gpus=[0]) as ctx:
            # GPU resources are available here
            train_model(...)

    The context manager will:
    1. Signal training start to inference service
    2. Wait for GPU resources to become available
    3. Yield control to your training code
    4. Signal training stop when done (even on exception)

    Args:
        job_id: Unique job identifier (auto-generated if not provided)
        gpus: List of GPU indices needed
        priority: Signal priority (higher = more urgent)
        wait_for_yield: Whether to wait for GPU resources
        metadata: Additional metadata
    """
    job_id = job_id or f"training-{uuid.uuid4().hex[:8]}"
    signal_file = None

    try:
        # Signal training start
        logger.info(f"Starting training context: {job_id}")
        signal_training_start(
            job_id=job_id,
            gpus=gpus,
            priority=priority,
            wait_for_yield=wait_for_yield,
            metadata=metadata,
        )

        # Register cleanup handlers
        def cleanup(*args):
            signal_training_stop(job_id)

        # Handle signals for graceful shutdown
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        def signal_handler(signum, frame):
            cleanup()
            # Call original handler
            if signum == signal.SIGINT and original_sigint:
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and original_sigterm:
                original_sigterm(signum, frame)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Also register atexit for abnormal exits
        atexit.register(cleanup)

        # Yield context info
        yield {
            "job_id": job_id,
            "gpus": gpus,
        }

    finally:
        # Clean up
        logger.info(f"Ending training context: {job_id}")
        signal_training_stop(job_id)

        # Remove atexit handler
        try:
            atexit.unregister(cleanup)
        except Exception:
            pass


def requires_gpu(
    job_id: Optional[str] = None,
    gpus: Optional[List[int]] = None,
    priority: int = 10,
    wait_for_yield: bool = True,
):
    """
    Decorator for functions that require GPU resources.

    Usage:
        @requires_gpu(gpus=[0])
        def train_model():
            # GPU is available here
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _job_id = job_id or f"{func.__name__}-{uuid.uuid4().hex[:8]}"
            with training_context(
                job_id=_job_id,
                gpus=gpus,
                priority=priority,
                wait_for_yield=wait_for_yield,
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================================
# CLI for manual signaling
# ============================================================================


def main():
    """CLI for manual training signals."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Signal training start/stop to inference service"
    )
    parser.add_argument(
        "action",
        choices=["start", "stop", "status"],
        help="Action to perform",
    )
    parser.add_argument(
        "--job-id",
        default=f"manual-{uuid.uuid4().hex[:8]}",
        help="Job identifier",
    )
    parser.add_argument(
        "--gpus",
        type=int,
        nargs="*",
        help="GPU indices to request",
    )
    parser.add_argument(
        "--priority",
        type=int,
        default=10,
        help="Signal priority (higher = more urgent)",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Inference service URL",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for GPU resources",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    signal_config.inference_url = args.url
    signal_config.fallback_inference_url = args.url

    if args.action == "start":
        success = signal_training_start(
            job_id=args.job_id,
            gpus=args.gpus,
            priority=args.priority,
            wait_for_yield=not args.no_wait,
        )
        print(f"Job ID: {args.job_id}")
        print(f"Signal sent: {'success' if success else 'failed'}")

    elif args.action == "stop":
        success = signal_training_stop(args.job_id)
        print(f"Signal sent: {'success' if success else 'failed'}")

    elif args.action == "status":
        import httpx

        try:
            response = httpx.get(f"{args.url}/training/status", timeout=5.0)
            print(json.dumps(response.json(), indent=2))
        except Exception as e:
            print(f"Failed to get status: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
