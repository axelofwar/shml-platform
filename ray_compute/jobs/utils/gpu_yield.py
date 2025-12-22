"""
GPU Yield Utilities for Training Scripts.

This module provides standalone GPU yield functions that can be imported
BEFORE torch/CUDA to ensure GPU memory is freed.

CRITICAL: Import this module BEFORE importing torch!

Usage:
    # At the TOP of your training script (before torch import):
    from ray_compute.jobs.utils.gpu_yield import yield_gpu_for_training, reclaim_gpu_after_training

    # Yield GPU before importing torch
    job_id = os.environ.get("RAY_JOB_ID", "training-001")
    yield_gpu_for_training(gpu_id=0, job_id=job_id)

    # Now safe to import torch
    import torch
    from ultralytics import YOLO

    # ... training code ...

    # At the end of training
    reclaim_gpu_after_training(gpu_id=0, job_id=job_id)

For context manager usage, see libs/training/gpu_manager.py
"""

import os
import sys
import json as json_module
import urllib.request
import urllib.error
from typing import List, Optional, Dict, Any


# Service endpoints
NEMOTRON_MANAGER_URLS = [
    "http://nemotron-manager:8000",  # Inside Docker network
    "http://localhost:8011",  # Host access
]

Z_IMAGE_URLS = [
    "http://z-image-api:8000",  # Inside Docker network
    "http://localhost:8002",  # Host access
]


def yield_gpu_for_training(
    gpu_id: int = 0,
    job_id: Optional[str] = None,
    timeout: int = 60,
    yield_z_image: bool = True,
    verbose: bool = True,
) -> bool:
    """
    Request inference services to yield GPU for training.

    This function contacts nemotron-manager and optionally z-image to
    unload their models and free GPU VRAM. Call this BEFORE importing
    torch to ensure GPU memory is available.

    Args:
        gpu_id: GPU device ID (default 0 = RTX 3090 Ti)
        job_id: Training job identifier (auto-generated if not provided)
        timeout: Max seconds to wait for yield
        yield_z_image: Also yield z-image service (default True)
        verbose: Print progress messages

    Returns:
        True if at least one service yielded successfully
    """
    if job_id is None:
        job_id = os.environ.get("RAY_JOB_ID", f"training-{os.getpid()}")

    success = False

    # Prepare yield request payload
    payload = json_module.dumps(
        {
            "job_id": job_id,
            "gpus": [gpu_id],
            "priority": 10,
            "wait_for_yield": True,
            "timeout_seconds": timeout,
            "metadata": {
                "script": os.path.basename(sys.argv[0]) if sys.argv else "unknown"
            },
        }
    ).encode("utf-8")

    if verbose:
        print(f"═══════════════════════════════════════════════════════════════")
        print(f"🔄 Requesting GPU {gpu_id} yield for training job: {job_id}")
        print(f"═══════════════════════════════════════════════════════════════")

    # 1. Yield Nemotron (LLM on RTX 3090)
    for base_url in NEMOTRON_MANAGER_URLS:
        try:
            url = f"{base_url}/training/start"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            if verbose:
                print(f"  → Requesting Nemotron yield from {base_url}...")

            with urllib.request.urlopen(req, timeout=timeout + 5) as response:
                result = json_module.loads(response.read().decode("utf-8"))

                if result.get("status") == "ready":
                    if verbose:
                        print(f"    ✓ Nemotron yielded successfully")
                        if result.get("gpu_memory_before_mb") and result.get(
                            "gpu_memory_after_mb"
                        ):
                            freed_mb = (
                                result["gpu_memory_before_mb"]
                                - result["gpu_memory_after_mb"]
                            )
                            print(f"    VRAM freed: {freed_mb}MB")
                    success = True
                    break
                else:
                    if verbose:
                        print(f"    ⚠ Response: {result}")
                    success = result.get("model_yielded", False)
                    if success:
                        break

        except urllib.error.URLError as e:
            if verbose:
                print(f"    Could not reach {base_url}: {e}")
        except Exception as e:
            if verbose:
                print(f"    Error with {base_url}: {e}")

    # 2. Optionally yield Z-Image (image gen on RTX 3090)
    if yield_z_image and gpu_id == 0:
        for base_url in Z_IMAGE_URLS:
            try:
                url = f"{base_url}/yield-to-training"
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                if verbose:
                    print(f"  → Requesting Z-Image yield from {base_url}...")

                with urllib.request.urlopen(req, timeout=30) as response:
                    result = json_module.loads(response.read().decode("utf-8"))
                    if verbose:
                        print(f"    ✓ Z-Image yielded: {result.get('status', 'ok')}")
                    break

            except urllib.error.URLError:
                if verbose:
                    print(
                        f"    Z-Image not reachable at {base_url} (may not be running)"
                    )
            except Exception as e:
                if verbose:
                    print(f"    Z-Image error: {e}")

    if verbose:
        if success:
            print(f"✅ GPU {gpu_id} ready for training")
        else:
            print(f"⚠️ Could not contact inference services - proceeding anyway")
            print(
                f"   If you see OOM errors, manually run: ./inference/scripts/yield_to_training.sh"
            )

    return success


def reclaim_gpu_after_training(
    gpu_id: int = 0, job_id: Optional[str] = None, verbose: bool = True
) -> bool:
    """
    Notify inference services that training is complete.

    Call this at the end of training to allow Nemotron and other
    inference services to reload their models.

    Args:
        gpu_id: GPU device ID
        job_id: Training job identifier
        verbose: Print progress messages

    Returns:
        True if services were notified successfully
    """
    if job_id is None:
        job_id = os.environ.get("RAY_JOB_ID", f"training-{os.getpid()}")

    if verbose:
        print(f"═══════════════════════════════════════════════════════════════")
        print(f"🏁 Training complete - reclaiming GPU {gpu_id} for job: {job_id}")
        print(f"═══════════════════════════════════════════════════════════════")

    payload = json_module.dumps({"job_id": job_id}).encode("utf-8")
    success = False

    # Notify Nemotron Manager
    for base_url in NEMOTRON_MANAGER_URLS:
        try:
            url = f"{base_url}/training/end"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            if verbose:
                print(f"  → Notifying Nemotron at {base_url}...")

            with urllib.request.urlopen(req, timeout=120) as response:
                result = json_module.loads(response.read().decode("utf-8"))

                if result.get("status") in ["started", "running"]:
                    if verbose:
                        print(
                            f"    ✓ Nemotron restarting: {result.get('message', 'ok')}"
                        )
                    success = True
                    break
                else:
                    if verbose:
                        print(f"    Response: {result}")

        except urllib.error.URLError as e:
            if verbose:
                print(f"    Could not reach {base_url}: {e}")
        except Exception as e:
            if verbose:
                print(f"    Error with {base_url}: {e}")

    # Notify Z-Image (it will auto-reload on next request)
    for base_url in Z_IMAGE_URLS:
        try:
            url = f"{base_url}/reclaim-from-training"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            if verbose:
                print(f"  → Notifying Z-Image at {base_url}...")

            with urllib.request.urlopen(req, timeout=10) as response:
                if verbose:
                    print(f"    ✓ Z-Image notified")
                break

        except:
            pass  # Z-Image may not be running

    if verbose:
        if success:
            print(f"✅ GPU {gpu_id} released, inference services notified")
        else:
            print(f"⚠️ Could not notify inference services")
            print(f"   To restart manually: docker start nemotron-coding")

    return success


def check_gpu_status(gpu_id: int = 0) -> Dict[str, Any]:
    """
    Check GPU status from inference services.

    Returns:
        Dict with service statuses
    """
    status = {"gpu_id": gpu_id, "services": {}}

    # Check Nemotron
    for base_url in NEMOTRON_MANAGER_URLS:
        try:
            url = f"{base_url}/status"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json_module.loads(response.read().decode("utf-8"))
                status["services"]["nemotron"] = {"reachable": True, "status": result}
                break
        except Exception as e:
            status["services"]["nemotron"] = {"reachable": False, "error": str(e)}

    # Check Z-Image
    for base_url in Z_IMAGE_URLS:
        try:
            url = f"{base_url}/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json_module.loads(response.read().decode("utf-8"))
                status["services"]["z_image"] = {"reachable": True, "status": result}
                break
        except Exception as e:
            status["services"]["z_image"] = {"reachable": False, "error": str(e)}

    return status


# Convenience: Auto-yield on import if environment variable set
if os.environ.get("SHML_AUTO_GPU_YIELD", "").lower() == "true":
    _auto_device = int(os.environ.get("SHML_GPU_DEVICE", "0"))
    if _auto_device == 0:  # Only yield RTX 3090, not RTX 2070
        yield_gpu_for_training(gpu_id=_auto_device, verbose=True)


__all__ = [
    "yield_gpu_for_training",
    "reclaim_gpu_after_training",
    "check_gpu_status",
]
