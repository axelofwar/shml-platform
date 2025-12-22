#!/usr/bin/env python3
"""
Ray Job Submission Script for Face Detection Training

Submits the SOTA face detection training job to the Ray cluster
via the SHML Platform API (authenticated) so it appears in the Ray Compute UI.

Usage:
    # Dry run to verify configuration
    python submit_face_detection_job.py --dry-run --api-key YOUR_KEY

    # Submit enhanced training from Phase 1 checkpoint
    python submit_face_detection_job.py --resume-phase1 --sapo --hard-mining

    # Submit with custom config
    python submit_face_detection_job.py --epochs 50 --batch-size 6

    # Check job status
    python submit_face_detection_job.py --status <job_id>

Author: SHML Platform
Date: December 2025
"""

import os
import sys
import json
import time
import argparse
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# Add libs to path for SHML client
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "libs" / "client"))

try:
    from shml.client import Client as SHMLClient
    from shml.client import SHMLError, AuthenticationError

    SHML_SDK_AVAILABLE = True
except ImportError:
    SHML_SDK_AVAILABLE = False

# Also support direct Ray submission as fallback
try:
    from ray.job_submission import JobSubmissionClient

    RAY_DIRECT_AVAILABLE = True
except ImportError:
    RAY_DIRECT_AVAILABLE = False


# Configuration - Traefik-first approach for remote compatibility
# These URLs work locally, remotely via Tailscale, and via Tailscale Funnel
DEFAULT_API_URL = os.getenv("SHML_API_URL", "https://shml-platform.tail38b60a.ts.net")
DEFAULT_API_KEY = os.getenv("SHML_API_KEY", "")

# Phase 1 checkpoint location (best model from curriculum training)
PHASE1_CHECKPOINT = (
    "/tmp/ray/checkpoints/face_detection/phase_1_phase_1/weights/best.pt"
)

# Ray cluster addresses for direct submission (fallback only)
RAY_ADDRESSES = [
    "http://ray-head:8265",
    "http://172.30.0.23:8265",
    "http://localhost:8265",
]


def get_authenticated_client(
    api_key: Optional[str] = None, local: bool = False
) -> SHMLClient:
    """
    Create an authenticated SHML client.

    Args:
        api_key: API key for authentication (from env SHML_API_KEY if not provided)
        local: If True, try direct container access first (faster but local-only)

    Returns:
        Configured SHML client

    Note:
        By default uses Traefik URLs which work:
        - Locally on the server
        - Remotely via Tailscale VPN
        - Remotely via Tailscale Funnel (public access)
    """
    key = api_key or DEFAULT_API_KEY

    if not key:
        print(
            "⚠ No API key provided. Set SHML_API_KEY environment variable or use --api-key"
        )
        print(
            "  Get API keys from: https://shml-platform.tail38b60a.ts.net/ray/ui/settings"
        )
        print("  Or use admin key from: ray_compute/.env (CICD_ADMIN_KEY)")
        sys.exit(1)

    # Traefik-first: works everywhere (local, Tailscale, Funnel)
    # Direct container: faster but local-only
    api_urls = [
        # Traefik via Tailscale (works everywhere)
        ("https://shml-platform.tail38b60a.ts.net", "/api/ray"),
        # Traefik via localhost (local only)
        ("http://localhost", "/api/ray"),
    ]

    # If local mode, prepend direct container access
    if local:
        api_urls = [
            ("http://172.30.0.25:8000", "/api/v1"),  # Direct to container (fastest)
            ("http://localhost:8266", "/api/v1"),  # Port forward
        ] + api_urls

    import requests

    for base_url, api_prefix in api_urls:
        try:
            # Test health endpoint
            health_url = (
                f"{base_url}{api_prefix.replace('/api/ray', '')}/health"
                if "api/ray" in api_prefix
                else f"{base_url}/health"
            )
            if "/api/ray" in api_prefix:
                health_url = f"{base_url}/api/ray/health"

            response = requests.get(
                health_url, timeout=5, verify=base_url.startswith("https")
            )
            if response.status_code == 200:
                print(f"✓ API connected: {base_url}{api_prefix}")
                return SHMLClient(
                    base_url=base_url,
                    api_key=key,
                    api_prefix=api_prefix,
                    timeout=120.0,  # Longer timeout for large script uploads
                )
        except Exception as e:
            continue

    raise ConnectionError(
        "Could not connect to Ray Compute API. Tried:\n"
        + "\n".join(f"  - {url}{prefix}" for url, prefix in api_urls)
        + "\n\nCheck that the platform is running: ./check_platform_status.sh"
    )


def build_training_args(args) -> List[str]:
    """Build command-line arguments for the training script."""
    cmd_args = []

    # Model and basic config
    cmd_args.extend(["--model", args.model])
    cmd_args.extend(["--epochs", str(args.epochs)])
    cmd_args.extend(["--batch-size", str(args.batch_size)])
    cmd_args.extend(["--imgsz", str(args.imgsz)])
    cmd_args.extend(["--device", args.device])
    cmd_args.extend(["--data-dir", args.data_dir])

    # MLflow
    cmd_args.extend(["--experiment", args.experiment])
    if args.run_name:
        cmd_args.extend(["--run-name", args.run_name])

    # Resume from checkpoint
    if args.resume:
        cmd_args.extend(["--resume", args.resume])
    elif args.resume_phase1:
        cmd_args.extend(["--resume", PHASE1_CHECKPOINT])
        if args.start_phase is None:
            args.start_phase = 2

    if args.start_phase:
        cmd_args.extend(["--start-phase", str(args.start_phase)])

    # Training modes
    if args.no_multiscale:
        cmd_args.append("--no-multiscale")

    if args.recall_focused:
        cmd_args.append("--recall-focused")

    # SOTA features
    if args.curriculum:
        cmd_args.append("--curriculum")
    elif args.no_curriculum:
        cmd_args.append("--no-curriculum")

    if args.sapo:
        cmd_args.append("--sapo")
    elif args.no_sapo:
        cmd_args.append("--no-sapo")

    if args.hard_mining:
        cmd_args.append("--hard-mining")
        if args.hard_mining_ratio != 0.3:
            cmd_args.extend(["--hard-mining-ratio", str(args.hard_mining_ratio)])
    elif args.no_hard_mining:
        cmd_args.append("--no-hard-mining")

    if args.enhanced_multiscale:
        cmd_args.append("--enhanced-multiscale")
    elif args.no_enhanced_multiscale:
        cmd_args.append("--no-enhanced-multiscale")

    # Analysis
    if args.analyze_failures:
        cmd_args.append("--analyze-failures")

    if args.tta_validation:
        cmd_args.append("--tta-validation")

    # Dataset
    if args.download_dataset:
        cmd_args.append("--download-dataset")

    return cmd_args


def find_ray_cluster() -> str:
    """Find available Ray cluster."""
    import requests

    for addr in RAY_ADDRESSES:
        try:
            response = requests.get(f"{addr}/api/version", timeout=3)
            if response.status_code == 200:
                print(f"✓ Ray cluster found at: {addr}")
                return addr
        except Exception:
            continue

    raise ConnectionError("No Ray cluster found. Please start the cluster first.")


def submit_via_sdk(client: SHMLClient, args) -> str:
    """Submit training job via SHML SDK (appears in Ray Compute UI)."""

    script_path = Path(__file__).parent / "face_detection_training.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Training script not found: {script_path}")

    # Build training arguments
    training_args = build_training_args(args)

    # Build entrypoint command
    entrypoint = f"python face_detection_training.py {' '.join(training_args)}"

    print("\n" + "=" * 70)
    print("SUBMITTING FACE DETECTION TRAINING JOB VIA SHML SDK")
    print("=" * 70)
    print(f"\n  API: {client.config.base_url}{client.api_prefix}")
    print(f"  Script: {script_path}")
    print(f"  Entrypoint: {entrypoint}")
    print(f"\n  Configuration:")
    print(f"    Model: {args.model}")
    print(f"    Epochs: {args.epochs}")
    print(f"    Batch Size: {args.batch_size}")
    print(f"    Image Size: {args.imgsz}px")
    print(f"    GPU: {args.gpu}")
    print(f"    Multi-scale: {not args.no_multiscale}")
    print(f"    Curriculum: {args.curriculum}")
    print(f"    SAPO: {args.sapo}")
    print(f"    Hard Mining: {args.hard_mining}")
    print(f"    Enhanced Multi-Scale: {args.enhanced_multiscale}")

    if args.resume_phase1:
        print(f"    Resume from: Phase 1 ({PHASE1_CHECKPOINT})")
    elif args.resume:
        print(f"    Resume from: {args.resume}")

    if args.dry_run:
        print("\n  🔍 DRY RUN MODE - No job will be submitted")
        print("=" * 70)

        # Validate we can read the script
        script_content = script_path.read_text()
        print(f"  ✓ Script readable ({len(script_content)} bytes)")

        # Test API connection
        try:
            user = client.me()
            print(f"  ✓ API authenticated as: {user.username} ({user.role})")

            quota = client.quota()
            print(
                f"  ✓ Quota: GPU {quota.max_gpu_fraction}, Timeout {quota.max_job_timeout_hours}h"
            )

            # Validate GPU request
            if args.gpu > float(quota.max_gpu_fraction):
                print(
                    f"  ⚠ Warning: GPU {args.gpu} exceeds quota {quota.max_gpu_fraction}"
                )

        except AuthenticationError as e:
            print(f"  ✗ Authentication failed: {e}")
            return None
        except Exception as e:
            print(f"  ✗ API error: {e}")
            return None

        print("\n  ✓ Dry run successful - job would be submitted")
        print("  Run without --dry-run to actually submit the job")
        return "dry-run-success"

    print()

    # Prepare requirements
    requirements = [
        "ultralytics>=8.3.0",
        "mlflow>=3.0.0",
        "prometheus-client>=0.19.0",
        "gdown",
        "tqdm",
        "Pillow",
        "requests",
    ]

    # Submit the job via SDK
    response = client.submit(
        name=args.run_name
        or f"face-detection-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        description=f"SOTA Face Detection Training - {args.epochs} epochs, {args.model}",
        job_type="training",
        script_path=str(script_path),
        entrypoint_args=training_args,
        cpu=args.cpu,
        memory_gb=args.memory_gb,
        gpu=args.gpu,
        timeout_hours=args.timeout_hours,
        no_timeout=args.no_timeout,
        priority=args.priority,
        requirements=requirements,
        tags=["face-detection", "yolov8", "sota"],
        mlflow_experiment=args.experiment,
    )

    print(f"✓ Job submitted: {response.job_id}")
    print(f"  Name: {response.name}")
    print(f"  Status: {response.status}")
    print(
        f"\n  Monitor in Ray Compute UI: http://localhost:3002/jobs/{response.job_id}"
    )
    print(
        f"  Check status: python submit_face_detection_job.py --status {response.job_id}"
    )
    print(f"  View logs: python submit_face_detection_job.py --logs {response.job_id}")

    return response.job_id


def submit_via_direct_ray(args) -> str:
    """Fallback: Submit directly to Ray cluster (won't appear in UI tracking)."""

    ray_address = find_ray_cluster()
    client = JobSubmissionClient(ray_address)

    print(f"⚠ Using direct Ray submission (job won't appear in SHML UI tracking)")
    print(f"  Ray cluster: {ray_address}")

    # Build command
    training_args = build_training_args(args)
    entrypoint = f"python face_detection_training.py {' '.join(training_args)}"

    print("\n" + "=" * 70)
    print("SUBMITTING FACE DETECTION TRAINING JOB (DIRECT RAY)")
    print("=" * 70)
    print(f"\n  Ray Cluster: {ray_address}")
    print(f"  Entrypoint: {entrypoint}")
    print(f"\n  Configuration:")
    print(f"    Model: {args.model}")
    print(f"    Epochs: {args.epochs}")
    print(f"    Batch Size: {args.batch_size}")
    print(f"    Image Size: {args.imgsz}px")
    print(f"    Multi-scale: {not args.no_multiscale}")
    print()

    # Runtime environment
    runtime_env = {
        "working_dir": str(Path(__file__).parent),
        "pip": [
            "ultralytics>=8.3.0",
            "mlflow>=3.0.0",
            "prometheus-client>=0.19.0",
            "gdown",
            "tqdm",
            "Pillow",
            "requests",
        ],
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://mlflow-nginx:80",
            "CUDA_VISIBLE_DEVICES": "0",
        },
    }

    # Submit job
    job_id = client.submit_job(
        entrypoint=entrypoint,
        runtime_env=runtime_env,
        entrypoint_num_gpus=1,
        entrypoint_num_cpus=8,
        entrypoint_memory=32 * 1024 * 1024 * 1024,
    )

    print(f"✓ Job submitted (direct): {job_id}")
    print(f"\n  Monitor at: {ray_address.replace(':8265', '')}/ray/#/jobs/{job_id}")
    print(
        f"  Check status: python submit_face_detection_job.py --status {job_id} --direct-ray"
    )
    print(
        f"  View logs: python submit_face_detection_job.py --logs {job_id} --direct-ray"
    )

    # Optionally wait for completion
    if args.wait:
        print(f"\n  Waiting for job completion...")
        wait_for_direct_job(client, job_id)

    return job_id


def wait_for_direct_job(client, job_id: str):
    print(f"  Check status: python submit_face_detection_job.py --status {job_id}")
    print(f"  View logs: python submit_face_detection_job.py --logs {job_id}")

    # Optionally wait for completion
    if args.wait:
        print(f"\n  Waiting for job completion...")
        wait_for_job(client, job_id)

    return job_id


def wait_for_direct_job(client, job_id: str):
    """Wait for job completion with status updates (direct Ray)."""
    from ray.job_submission import JobStatus

    start_time = time.time()
    last_status = None

    while True:
        status = client.get_job_status(job_id)

        if status != last_status:
            elapsed = time.time() - start_time
            print(f"  [{elapsed/60:.1f}m] Status: {status}")
            last_status = status

        if status in [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.STOPPED]:
            break

        time.sleep(10)

    elapsed = time.time() - start_time
    print(f"\n  Job finished in {elapsed/3600:.2f} hours with status: {status}")

    if status == JobStatus.FAILED:
        logs = client.get_job_logs(job_id)
        print("\n  === Job Logs (last 50 lines) ===")
        print("\n".join(logs.split("\n")[-50:]))


def check_job_status_sdk(client: SHMLClient, job_id: str):
    """Check job status via SDK."""
    try:
        job = client.status(job_id)
        print(f"\nJob: {job.job_id}")
        print(f"  Name: {job.name}")
        print(f"  Status: {job.status}")
        print(f"  Created: {job.created_at}")
        if hasattr(job, "started_at") and job.started_at:
            print(f"  Started: {job.started_at}")
        if hasattr(job, "ended_at") and job.ended_at:
            print(f"  Ended: {job.ended_at}")
        print(
            f"  Resources: {job.cpu_requested} CPU, {job.memory_gb_requested}GB RAM, {job.gpu_requested} GPU"
        )
        if hasattr(job, "mlflow_run_id") and job.mlflow_run_id:
            print(f"  MLflow Run: {job.mlflow_run_id}")
        if hasattr(job, "error_message") and job.error_message:
            print(f"  Error: {job.error_message}")
    except Exception as e:
        print(f"Error getting job status: {e}")


def check_job_status_direct(job_id: str):
    """Check job status via direct Ray."""
    ray_address = find_ray_cluster()
    client = JobSubmissionClient(ray_address)

    status = client.get_job_status(job_id)
    info = client.get_job_info(job_id)

    print(f"\nJob ID: {job_id}")
    print(f"Status: {status}")

    if info:
        print(f"Entrypoint: {info.entrypoint}")
        if info.start_time:
            print(f"Started: {datetime.fromtimestamp(info.start_time/1000)}")
        if info.end_time:
            print(f"Ended: {datetime.fromtimestamp(info.end_time/1000)}")


def get_job_logs_sdk(client: SHMLClient, job_id: str, tail: int = 100):
    """Get job logs via SDK."""
    try:
        logs = client.logs(job_id)
        lines = logs.split("\n")

        if tail and len(lines) > tail:
            print(f"... (showing last {tail} lines) ...")
            lines = lines[-tail:]

        print("\n".join(lines))
    except Exception as e:
        print(f"Error getting logs: {e}")


def get_job_logs_direct(job_id: str, tail: int = 100):
    """Get job logs via direct Ray."""
    ray_address = find_ray_cluster()
    client = JobSubmissionClient(ray_address)

    logs = client.get_job_logs(job_id)
    lines = logs.split("\n")

    if tail and len(lines) > tail:
        print(f"... (showing last {tail} lines) ...")
        lines = lines[-tail:]

    print("\n".join(lines))


def list_jobs_sdk(client: SHMLClient, limit: int = 10):
    """List recent jobs via SDK."""
    try:
        jobs = client.list_jobs(page_size=limit)

        print(f"\nRecent Jobs (last {limit}):")
        print("-" * 80)

        for job in jobs:
            status_emoji = {
                "PENDING": "⏳",
                "RUNNING": "🔄",
                "SUCCEEDED": "✓",
                "FAILED": "✗",
                "STOPPED": "⏹",
            }.get(job.status, "?")

            print(
                f"  {status_emoji} {job.job_id[:20]} | {job.status:10} | {job.name[:40]}..."
            )
    except Exception as e:
        print(f"Error listing jobs: {e}")


def list_jobs_direct(limit: int = 10):
    """List recent jobs via direct Ray."""
    from ray.job_submission import JobStatus

    ray_address = find_ray_cluster()
    client = JobSubmissionClient(ray_address)

    jobs = client.list_jobs()

    print(f"\nRecent Jobs (last {limit}):")
    print("-" * 80)

    for job in jobs[:limit]:
        status_emoji = {
            JobStatus.PENDING: "⏳",
            JobStatus.RUNNING: "🔄",
            JobStatus.SUCCEEDED: "✓",
            JobStatus.FAILED: "✗",
            JobStatus.STOPPED: "⏹",
        }.get(job.status, "?")

        print(
            f"  {status_emoji} {job.submission_id[:20]} | {job.status.name:10} | {job.entrypoint[:40]}..."
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Submit Face Detection Training to Ray via SHML SDK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to verify configuration (works remotely via Tailscale)
  python submit_face_detection_job.py --dry-run --api-key YOUR_KEY

  # Submit from local server (faster, direct container access)
  python submit_face_detection_job.py --local --api-key YOUR_KEY

  # Submit enhanced training from Phase 1 checkpoint
  python submit_face_detection_job.py --resume-phase1 --sapo --hard-mining

  # Submit full training with all SOTA features
  python submit_face_detection_job.py --epochs 100 --curriculum --sapo --hard-mining --recall-focused

Environment Variables:
  SHML_API_KEY    API key for authentication (or use --api-key)
  SHML_API_URL    Override default API URL (https://shml-platform.tail38b60a.ts.net)

API Keys:
  Admin key: See ray_compute/.env (CICD_ADMIN_KEY)
  User keys: Generate at https://shml-platform.tail38b60a.ts.net/ray/ui/settings
        """,
    )

    # API / Authentication
    api_group = parser.add_argument_group("API & Authentication")
    api_group.add_argument(
        "--api-key",
        type=str,
        default=DEFAULT_API_KEY,
        help="SHML API key for authentication (env: SHML_API_KEY)",
    )
    api_group.add_argument(
        "--local",
        action="store_true",
        help="Use direct container access (faster, local server only)",
    )
    api_group.add_argument(
        "--direct-ray",
        action="store_true",
        help="Bypass SHML API, submit directly to Ray (no UI tracking)",
    )
    api_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without submitting",
    )

    # Job management
    job_group = parser.add_argument_group("Job Management")
    job_group.add_argument(
        "--status", type=str, metavar="JOB_ID", help="Check status of a job"
    )
    job_group.add_argument(
        "--logs", type=str, metavar="JOB_ID", help="Get logs for a job"
    )
    job_group.add_argument("--list", action="store_true", help="List recent jobs")
    job_group.add_argument(
        "--wait", action="store_true", help="Wait for job completion"
    )

    # Training: Model & Basic Config
    parser.add_argument(
        "--download-dataset", action="store_true", help="Download WIDER Face dataset"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolov8l.pt",
        help="Model (yolov8n.pt, yolov8m.pt, yolov8l.pt, yolov8x.pt)",
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--device", type=str, default="cuda:0")
    parser.add_argument("--data-dir", type=str, default="/opt/ray/job_workspaces/data")

    # Training: Resume
    parser.add_argument(
        "--resume", type=str, metavar="CHECKPOINT", help="Resume from checkpoint path"
    )
    parser.add_argument(
        "--resume-phase1",
        action="store_true",
        help=f"Resume from Phase 1 best checkpoint ({PHASE1_CHECKPOINT})",
    )
    parser.add_argument(
        "--start-phase", type=int, help="Start from phase N (1-indexed)"
    )

    # Training: Modes
    parser.add_argument(
        "--no-multiscale", action="store_true", help="Disable multi-scale training"
    )
    parser.add_argument(
        "--recall-focused", action="store_true", help="Use recall-focused config"
    )

    # Training: SOTA Features
    parser.add_argument(
        "--curriculum",
        action="store_true",
        default=True,
        help="Enable curriculum learning",
    )
    parser.add_argument(
        "--no-curriculum", action="store_true", help="Disable curriculum learning"
    )

    parser.add_argument(
        "--sapo", action="store_true", default=True, help="Enable SAPO optimizer"
    )
    parser.add_argument("--no-sapo", action="store_true", help="Disable SAPO optimizer")

    parser.add_argument(
        "--hard-mining",
        action="store_true",
        default=True,
        help="Enable hard negative mining",
    )
    parser.add_argument(
        "--no-hard-mining", action="store_true", help="Disable hard negative mining"
    )
    parser.add_argument(
        "--hard-mining-ratio",
        type=float,
        default=0.3,
        help="Hard sample ratio (default: 0.3)",
    )

    parser.add_argument(
        "--enhanced-multiscale",
        action="store_true",
        default=True,
        help="Enable enhanced multi-scale augmentation",
    )
    parser.add_argument(
        "--no-enhanced-multiscale",
        action="store_true",
        help="Disable enhanced multi-scale augmentation",
    )

    # Training: Analysis
    parser.add_argument(
        "--analyze-failures", action="store_true", help="Enable failure analysis"
    )
    parser.add_argument(
        "--tta-validation", action="store_true", help="Enable TTA validation"
    )

    # Resource Allocation
    parser.add_argument("--gpu", type=float, default=1.0, help="GPU fraction (0.0-1.0)")
    parser.add_argument("--cpu", type=int, default=8, help="CPU cores")
    parser.add_argument("--memory-gb", type=int, default=32, help="Memory in GB")
    parser.add_argument(
        "--timeout-hours", type=int, default=24, help="Job timeout in hours"
    )
    parser.add_argument(
        "--no-timeout", action="store_true", help="Disable timeout (admin only)"
    )
    parser.add_argument(
        "--priority",
        type=str,
        default="normal",
        choices=["low", "normal", "high", "critical"],
    )

    # MLflow
    parser.add_argument(
        "--experiment",
        type=str,
        default="Face-Detection-SOTA",
        help="MLflow experiment name",
    )
    parser.add_argument("--run-name", type=str, default=None, help="MLflow run name")

    return parser.parse_args()


def main():
    args = parse_args()

    # Handle --no-* flags
    if args.no_curriculum:
        args.curriculum = False
    if args.no_sapo:
        args.sapo = False
    if args.no_hard_mining:
        args.hard_mining = False
    if args.no_enhanced_multiscale:
        args.enhanced_multiscale = False

    # Decide between SDK and direct Ray
    use_direct = args.direct_ray

    if use_direct:
        if not RAY_DIRECT_AVAILABLE:
            print("Error: Ray not available. Install with: pip install ray[default]")
            sys.exit(1)

        # Handle direct Ray commands
        if args.status:
            check_job_status_direct(args.status)
        elif args.logs:
            get_job_logs_direct(args.logs)
        elif args.list:
            list_jobs_direct()
        else:
            submit_via_direct_ray(args)
        return

    # Use SHML SDK
    if not SHML_SDK_AVAILABLE:
        print("⚠ SHML SDK not available, falling back to direct Ray submission")
        print("  Install from: libs/client/ or use --direct-ray explicitly\n")

        if not RAY_DIRECT_AVAILABLE:
            print("Error: Neither SHML SDK nor Ray available.")
            sys.exit(1)

        # Fallback to direct
        if args.status:
            check_job_status_direct(args.status)
        elif args.logs:
            get_job_logs_direct(args.logs)
        elif args.list:
            list_jobs_direct()
        else:
            submit_via_direct_ray(args)
        return

    # SDK mode
    try:
        client = get_authenticated_client(api_key=args.api_key, local=args.local)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error creating client: {e}")
        sys.exit(1)

    # Handle SDK commands
    if args.status:
        check_job_status_sdk(client, args.status)
    elif args.logs:
        get_job_logs_sdk(client, args.logs)
    elif args.list:
        list_jobs_sdk(client)
    else:
        try:
            job_id = submit_via_sdk(client, args)

            if args.wait and job_id and job_id != "dry-run-success":
                print("\nWaiting for job completion...")
                while True:
                    job = client.status(job_id)
                    if job.status in ["SUCCEEDED", "FAILED", "STOPPED"]:
                        print(f"\nJob finished with status: {job.status}")
                        if hasattr(job, "error_message") and job.error_message:
                            print(f"Error: {job.error_message}")
                        break
                    time.sleep(10)

        except AuthenticationError as e:
            print(f"\n❌ Authentication failed: {e}")
            print("\nTo fix:")
            print("  1. Get your API key from Ray Compute UI → Settings → API Keys")
            print("  2. Set SHML_API_KEY environment variable:")
            print("     export SHML_API_KEY='your-api-key'")
            print("  3. Or pass it directly: --api-key 'your-api-key'")
            sys.exit(1)
        except SHMLError as e:
            print(f"\n❌ API Error: {e}")
            if hasattr(e, "status_code") and e.status_code == 403:
                print(
                    "  You may not have permission to submit jobs with these settings."
                )
            sys.exit(1)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
