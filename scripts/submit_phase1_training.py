#!/usr/bin/env python3
"""
Submit Phase 1 Training Job to Ray Cluster via Job Submission API
Uses internal Docker network - bypasses OAuth for programmatic access
Can be run from any container on the platform network
"""

import os
import sys
from pathlib import Path

from ray.job_submission import JobSubmissionClient

# Ray cluster address (internal Docker network - no auth required)
RAY_ADDRESS = "http://ray-head:8265"


def submit_training_job():
    """Submit Phase 1 training job to Ray cluster"""

    print("=" * 70)
    print("Phase 1 Training Job Submission")
    print("=" * 70)
    print()

    # Create job submission client
    print(f"Connecting to Ray cluster: {RAY_ADDRESS}")
    client = JobSubmissionClient(RAY_ADDRESS)

    # Check cluster status
    try:
        print("✓ Connected to Ray cluster")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        return None

    # Read training script
    script_path = Path("ray_compute/jobs/training/phase1_foundation.py")
    if not script_path.exists():
        print(f"✗ Training script not found: {script_path}")
        return None

    with open(script_path, "r") as f:
        training_code = f.read()

    print(f"✓ Loaded training script: {script_path}")
    print(f"  Size: {len(training_code)} bytes")
    print()

    # Training configuration
    config = {
        "mode": "balanced",
        "epochs": 200,
        "model_name": "yolov8l-face-lindevs.pt",
        "dataset": "wider_face",
        "batch_size": 8,
        "imgsz": 1280,
        "mlflow_tracking_uri": "http://mlflow-nginx:80",
        "mlflow_experiment": "Phase1-WIDER-Balanced",
        "checkpoint_dir": "/tmp/ray/checkpoints/face_detection",
        "device": "cuda:0",
        # All SOTA features enabled
        "multiscale_enabled": True,
        "curriculum_enabled": True,
        "sapo_enabled": True,
        "hard_mining_enabled": True,
        "advantage_filter_enabled": True,
        "enhanced_multiscale_enabled": True,
        "failure_analysis_enabled": True,
        "dataset_audit_enabled": True,
        "tta_enabled": True,
        "label_smoothing": 0.1,
        "ema_enabled": True,
    }

    # Prepare entrypoint
    entrypoint = f"""
python3 -c "
import sys
sys.path.insert(0, '/tmp/ray_jobs')

# Import and run training
exec(open('/tmp/ray_jobs/phase1_foundation.py').read())

# Execute training
if __name__ == '__main__':
    config = TrainingConfig(
        mode='{config['mode']}',
        epochs={config['epochs']},
        model_name='{config['model_name']}',
        dataset='{config['dataset']}',
        batch_size={config['batch_size']},
        imgsz={config['imgsz']},
        mlflow_tracking_uri='{config['mlflow_tracking_uri']}',
        mlflow_experiment='{config['mlflow_experiment']}',
        checkpoint_dir='{config['checkpoint_dir']}',
        device='{config['device']}',
        multiscale_enabled={config['multiscale_enabled']},
        curriculum_enabled={config['curriculum_enabled']},
        sapo_enabled={config['sapo_enabled']},
        hard_mining_enabled={config['hard_mining_enabled']},
        advantage_filter_enabled={config['advantage_filter_enabled']},
        enhanced_multiscale_enabled={config['enhanced_multiscale_enabled']},
        failure_analysis_enabled={config['failure_analysis_enabled']},
        dataset_audit_enabled={config['dataset_audit_enabled']},
        tta_enabled={config['tta_enabled']},
        label_smoothing={config['label_smoothing']},
        ema_enabled={config['ema_enabled']},
    )

    train_face_detection_model(config)
"
"""

    # Runtime environment
    runtime_env = {
        "working_dir": "ray_compute/jobs/training",
        "pip": [
            "ultralytics==8.3.54",
            "mlflow==2.17.2",
            "opencv-python-headless==4.10.0.84",
            "torch==2.1.0",
            "torchvision==0.16.0",
            "pillow==10.4.0",
            "pyyaml==6.0.2",
            "tqdm==4.66.5",
        ],
        "env_vars": {
            "CUDA_VISIBLE_DEVICES": "0",
            "PYTHONUNBUFFERED": "1",
        },
    }

    print("Job Configuration:")
    print(f"  Mode: {config['mode']}")
    print(f"  Epochs: {config['epochs']}")
    print(f"  Model: {config['model_name']}")
    print(f"  Dataset: {config['dataset']}")
    print(f"  Batch Size: {config['batch_size']}")
    print(f"  Image Size: {config['imgsz']}px")
    print(f"  Device: {config['device']}")
    print(f"  MLflow Experiment: {config['mlflow_experiment']}")
    print()
    print("SOTA Features Enabled:")
    print(f"  ✓ Multi-Scale Training")
    print(f"  ✓ Curriculum Learning (4 stages)")
    print(f"  ✓ SAPO Optimizer")
    print(f"  ✓ Hard Negative Mining")
    print(f"  ✓ Advantage Filtering")
    print(f"  ✓ Enhanced Multi-Scale")
    print(f"  ✓ Failure Analysis (every 10 epochs)")
    print(f"  ✓ Dataset Audit (epochs 25, 50, 75)")
    print(f"  ✓ TTA Validation")
    print(f"  ✓ Label Smoothing (0.1)")
    print(f"  ✓ EMA (Exponential Moving Average)")
    print()

    # Submit job
    print("Submitting job to Ray cluster...")
    try:
        job_id = client.submit_job(
            entrypoint=entrypoint,
            runtime_env=runtime_env,
            metadata={
                "job_name": "phase1-wider-face-training",
                "phase": "1",
                "dataset": "wider_face",
                "epochs": str(config["epochs"]),
                "mode": config["mode"],
            },
        )

        print()
        print("=" * 70)
        print("✓ JOB SUBMITTED SUCCESSFULLY")
        print("=" * 70)
        print()
        print(f"Ray Job ID: {job_id}")
        print()
        print("Monitoring URLs:")
        print(f"  • Ray Dashboard: http://localhost/ray/")
        print(f"  • Grafana: http://localhost/grafana/d/face-detection-unified/")
        print(
            f"  • MLflow: http://localhost/mlflow/#/experiments/Phase1-WIDER-Balanced"
        )
        print()
        print("View Logs:")
        print(f"  ray job logs {job_id} --address {RAY_ADDRESS}")
        print()
        print("Expected Duration: 60-72 hours (200 epochs on RTX 3090 Ti)")
        print("Metrics will appear in Grafana after epoch 1 completes (~20 minutes)")
        print()

        return job_id

    except Exception as e:
        print(f"✗ Job submission failed: {e}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    job_id = submit_training_job()
    sys.exit(0 if job_id else 1)
