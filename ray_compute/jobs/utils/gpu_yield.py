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

    # --- OR use the context manager for guaranteed reclaim ---
    from ray_compute.jobs.utils.gpu_yield import GPUTrainingSession

    with GPUTrainingSession(gpu_id=0) as session:
        import torch
        # ... training code ...
        # GPU is automatically reclaimed on exit (even on crash/exception)

For context manager usage, see libs/training/gpu_manager.py
"""

import atexit
import os
import subprocess
import sys
import json as json_module
import urllib.request
import urllib.error
from typing import List, Optional, Dict, Any


# Service endpoints — unified GPU manager (preferred) + individual managers
GPU_MANAGER_URLS = [
    "http://gpu-manager:8000",  # Inside Docker network (unified)
    "http://localhost:8012",  # Host access (unified)
]

NEMOTRON_MANAGER_URLS = [
    "http://nemotron-manager:8000",  # Inside Docker network
    "http://localhost:8011",  # Host access
]

Z_IMAGE_URLS = [
    "http://z-image-api:8000",  # Inside Docker network
    "http://localhost:8002",  # Host access
]

# Host-side LLM server (llama.cpp) — runs outside Docker
LLM_CONTROL_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "scripts", "llm_control.sh",
)

# Track active yields for atexit safety net
_active_yields: Dict[int, str] = {}  # gpu_id -> job_id


def _yield_host_llm(verbose: bool = True) -> bool:
    """
    Stop the host-side llama-server to free GPU 0 for training.

    The llama-server runs outside Docker (host process), so the
    GPU manager cannot manage it. We call llm_control.sh directly.
    """
    if not os.path.isfile(LLM_CONTROL_SCRIPT):
        if verbose:
            print(f"  ℹ LLM control script not found at {LLM_CONTROL_SCRIPT} — skipping")
        return False

    try:
        if verbose:
            print(f"  → Yielding host LLM server (llama-server)...")
        result = subprocess.run(
            [LLM_CONTROL_SCRIPT, "yield"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            if verbose:
                print(f"    ✓ llama-server stopped, GPU 0 freed")
            return True
        else:
            if verbose:
                stderr_tail = result.stderr.strip().split("\n")[-2:] if result.stderr else []
                print(f"    ⚠ llm_control.sh yield exited with code {result.returncode}")
                for line in stderr_tail:
                    print(f"      {line}")
            return False
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"    ⚠ llm_control.sh yield timed out after 60s")
        return False
    except Exception as e:
        if verbose:
            print(f"    ⚠ Failed to yield host LLM: {e}")
        return False


def _restore_host_llm(verbose: bool = True) -> bool:
    """
    Restart llama-server after training is complete.
    """
    if not os.path.isfile(LLM_CONTROL_SCRIPT):
        if verbose:
            print(f"  ℹ LLM control script not found — skipping restore")
        return False

    try:
        if verbose:
            print(f"  → Restoring host LLM server (llama-server)...")
        result = subprocess.run(
            [LLM_CONTROL_SCRIPT, "restore"],
            capture_output=True,
            text=True,
            timeout=360,  # Model loading can take minutes
        )
        if result.returncode == 0:
            if verbose:
                print(f"    ✓ llama-server restored and healthy")
            return True
        else:
            if verbose:
                stderr_tail = result.stderr.strip().split("\n")[-2:] if result.stderr else []
                print(f"    ⚠ llm_control.sh restore exited with code {result.returncode}")
                for line in stderr_tail:
                    print(f"      {line}")
            return False
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"    ⚠ llm_control.sh restore timed out (model may still be loading)")
        return False
    except Exception as e:
        if verbose:
            print(f"    ⚠ Failed to restore host LLM: {e}")
        return False


def yield_gpu_for_training(
    gpu_id: int = 0,
    job_id: Optional[str] = None,
    timeout: int = 60,
    yield_z_image: bool = True,
    verbose: bool = True,
) -> bool:
    """
    Request inference services to yield GPU for training.

    This function contacts the unified GPU manager (preferred) or
    individual service managers to unload models and free GPU VRAM.
    Call this BEFORE importing torch to ensure GPU memory is available.

    Registers an atexit handler to guarantee GPU reclaim even on crash.

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
            "activate_fallback": True,
            "metadata": {
                "script": os.path.basename(sys.argv[0]) if sys.argv else "unknown"
            },
        }
    ).encode("utf-8")

    if verbose:
        print(f"═══════════════════════════════════════════════════════════════")
        print(f"🔄 Requesting GPU {gpu_id} yield for training job: {job_id}")
        print(f"═══════════════════════════════════════════════════════════════")

    # 1. Try unified GPU manager first (handles all services atomically)
    for base_url in GPU_MANAGER_URLS:
        try:
            url = f"{base_url}/training/start"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            if verbose:
                print(f"  → Requesting yield from unified GPU manager ({base_url})...")

            with urllib.request.urlopen(req, timeout=timeout + 5) as response:
                result = json_module.loads(response.read().decode("utf-8"))

                if result.get("status") == "ready":
                    stopped = result.get("services_stopped", [])
                    started = result.get("services_started", [])
                    if verbose:
                        print(f"    ✓ GPU manager yielded successfully")
                        if stopped:
                            print(f"    Stopped: {', '.join(stopped)}")
                        if started:
                            print(f"    Started: {', '.join(started)}")
                        freed = result.get("gpu_0_memory_freed_mb")
                        if freed:
                            print(f"    VRAM freed: {freed}MB")
                    success = True
                    break
                else:
                    if verbose:
                        print(
                            f"    ⚠ Response: {result.get('message', result.get('status'))}"
                        )

        except urllib.error.URLError as e:
            if verbose:
                print(f"    GPU manager not reachable at {base_url}: {e}")
        except Exception as e:
            if verbose:
                print(f"    GPU manager error at {base_url}: {e}")

    # 2. Fall back to individual Nemotron manager if unified not available
    if not success:
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

    # 3. Yield host-side LLM server (llama.cpp / llama-server) if on GPU 0
    if gpu_id == 0:
        _yield_host_llm(verbose=verbose)

    # 4. Optionally yield Z-Image (image gen on RTX 3090)
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

    # Register atexit safety net — guarantees reclaim even on unhandled exceptions
    if success:
        _active_yields[gpu_id] = job_id
        atexit.register(_atexit_reclaim, gpu_id, job_id)

    return success


def _atexit_reclaim(gpu_id: int, job_id: str):
    """Safety net: reclaim GPU on process exit if not already reclaimed."""
    if gpu_id in _active_yields:
        print(
            f"\n⚠️  [atexit] GPU {gpu_id} not reclaimed — auto-reclaiming for job {job_id}"
        )
        reclaim_gpu_after_training(gpu_id=gpu_id, job_id=job_id, verbose=True)


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

    # Remove from active yields (prevents atexit double-reclaim)
    _active_yields.pop(gpu_id, None)

    if verbose:
        print(f"═══════════════════════════════════════════════════════════════")
        print(f"🏁 Training complete - reclaiming GPU {gpu_id} for job: {job_id}")
        print(f"═══════════════════════════════════════════════════════════════")

    payload = json_module.dumps({"job_id": job_id}).encode("utf-8")
    success = False

    # 1. Try unified GPU manager first
    for base_url in GPU_MANAGER_URLS:
        try:
            url = f"{base_url}/training/end"
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            if verbose:
                print(f"  → Notifying unified GPU manager at {base_url}...")

            with urllib.request.urlopen(req, timeout=120) as response:
                result = json_module.loads(response.read().decode("utf-8"))

                if result.get("status") in ["restored", "started", "running"]:
                    started = result.get("services_started", [])
                    if verbose:
                        print(
                            f"    ✓ GPU manager restored services: {', '.join(started) if started else 'ok'}"
                        )
                    success = True
                    break
                else:
                    if verbose:
                        print(f"    Response: {result.get('message', result)}")

        except urllib.error.URLError as e:
            if verbose:
                print(f"    GPU manager not reachable at {base_url}: {e}")
        except Exception as e:
            if verbose:
                print(f"    GPU manager error at {base_url}: {e}")

    # 2. Fall back to individual Nemotron Manager
    if not success:
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

    # 3. Restore host-side LLM server (llama.cpp / llama-server)
    if gpu_id == 0:
        _restore_host_llm(verbose=verbose)

    # 4. Notify Z-Image (it will auto-reload on next request)
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


class GPUTrainingSession:
    """
    Context manager for GPU yield/reclaim with guaranteed cleanup.

    Usage:
        with GPUTrainingSession(gpu_id=0) as session:
            import torch
            # ... training code ...
            # GPU is automatically reclaimed on exit (even on crash)

    The atexit handler provides a secondary safety net, but this context
    manager is more explicit and handles exceptions cleanly.
    """

    def __init__(
        self,
        gpu_id: int = 0,
        job_id: Optional[str] = None,
        timeout: int = 60,
        yield_z_image: bool = True,
        verbose: bool = True,
    ):
        self.gpu_id = gpu_id
        self.job_id = job_id or os.environ.get("RAY_JOB_ID", f"training-{os.getpid()}")
        self.timeout = timeout
        self.yield_z_image = yield_z_image
        self.verbose = verbose
        self.yielded = False

    def __enter__(self):
        self.yielded = yield_gpu_for_training(
            gpu_id=self.gpu_id,
            job_id=self.job_id,
            timeout=self.timeout,
            yield_z_image=self.yield_z_image,
            verbose=self.verbose,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.verbose and exc_type is not None:
            print(f"\n⚠️  Training exited with {exc_type.__name__}: {exc_val}")
        reclaim_gpu_after_training(
            gpu_id=self.gpu_id,
            job_id=self.job_id,
            verbose=self.verbose,
        )
        return False  # Don't suppress exceptions


def check_gpu_status(gpu_id: int = 0) -> Dict[str, Any]:
    """
    Check GPU status from inference services.

    Tries unified GPU manager first, falls back to individual managers.

    Returns:
        Dict with service statuses
    """
    status = {"gpu_id": gpu_id, "services": {}}

    # Try unified GPU manager first
    for base_url in GPU_MANAGER_URLS:
        try:
            url = f"{base_url}/status"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json_module.loads(response.read().decode("utf-8"))
                status["services"]["gpu_manager"] = {
                    "reachable": True,
                    "status": result,
                }
                return status  # Unified manager has everything
        except Exception as e:
            status["services"]["gpu_manager"] = {"reachable": False, "error": str(e)}

    # Fall back to individual services
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
    "GPUTrainingSession",
    "check_gpu_status",
    "_yield_host_llm",
    "_restore_host_llm",
]
