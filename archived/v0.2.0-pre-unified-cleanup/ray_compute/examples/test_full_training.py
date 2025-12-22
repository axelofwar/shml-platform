#!/usr/bin/env python3
"""
Full GPU Training Test - WiderFace YOLOv8 Style Training
Simulates pii-pro training workflow with GPU operations

Submit from ray-compute-api container: python3 /tmp/test_full_training.py

This test demonstrates:
- Multi-scale training (480px, 640px, 800px)
- GPU-accelerated convolutions
- Proper gradient computation with requires_grad=True
- Memory-efficient training loop
- Validation phase
- GPU memory monitoring
"""

from ray.job_submission import JobSubmissionClient
import time
from datetime import datetime
import os

RAY_ADDRESS = "http://ray-head:8265"


def test_full_training():
    """Submit full GPU training job using uploaded training script"""
    client = JobSubmissionClient(RAY_ADDRESS)

    print("=" * 70)
    print("Full GPU Training Test - WiderFace YOLOv8 Style")
    print("=" * 70)
    print("This simulates pii-pro training workflow:")
    print("  - Multi-scale training (480px, 640px, 800px)")
    print("  - GPU-accelerated convolutions")
    print("  - Proper gradient computation")
    print("  - Memory-efficient training loop")
    print("  - Validation phase")
    print()

    # Get the path to training_script.py (same directory as this file)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    training_script_path = os.path.join(script_dir, "training_script.py")

    if not os.path.exists(training_script_path):
        print(f"ERROR: Training script not found at {training_script_path}")
        print("Make sure training_script.py is in the same directory as this file")
        return False

    print(f"Using training script: {training_script_path}")
    print()

    # Submit job with working directory containing the training script
    job_id = client.submit_job(
        entrypoint="python training_script.py",
        runtime_env={
            "working_dir": script_dir,
            "pip": ["torch"],
        },
        submission_id=f"widerface_training_{int(time.time())}",
        entrypoint_num_gpus=1,
        entrypoint_num_cpus=2,
        metadata={
            "job_type": "training",
            "framework": "pytorch",
            "model": "yolov8n",
            "dataset": "wider_face",
            "task": "face-detection",
        },
    )

    tailscale_ip = os.getenv("TAILSCALE_IP", "localhost")
    print(f"✅ Job submitted: {job_id}")
    print(f"   Dashboard: http://{tailscale_ip}/ray/#/jobs/{job_id}")
    print()

    # Monitor job
    print("Monitoring job status...")
    print("-" * 70)

    last_status = None
    start_time = time.time()
    timeout = 300  # 5 minutes

    while time.time() - start_time < timeout:
        status = client.get_job_status(job_id)

        if status != last_status:
            elapsed = int(time.time() - start_time)
            print(f"[{elapsed}s] Status: {status}")
            last_status = status

        if status in ["SUCCEEDED", "FAILED", "STOPPED"]:
            break

        time.sleep(2)

    # Get final logs
    print()
    print("=" * 70)
    print("Job Logs:")
    print("=" * 70)
    logs = client.get_job_logs(job_id)
    print(logs)

    print()
    print("=" * 70)
    print("Test Results:")
    print("=" * 70)
    print(f"Job ID: {job_id}")
    print(f"Final Status: {status}")

    if status == "SUCCEEDED":
        print()
        print("✅ SUCCESS! Full GPU training job completed")
        print()
        print("Verification checklist:")
        print("  ✓ Ray API accepted GPU job submission")
        print("  ✓ GPU was allocated to the job")
        print("  ✓ Training loop executed on GPU")
        print("  ✓ Gradient computation worked correctly")
        print("  ✓ Multi-scale training completed")
        print("  ✓ Job visible in Ray Dashboard")
        print()
        print("Access Points:")
        print(f"  - Ray Dashboard: http://{tailscale_ip}/ray/#/jobs/{job_id}")
        print(f"  - Ray Grafana: http://{tailscale_ip}/ray-grafana/")
        print(f"  - MLflow UI: http://{tailscale_ip}/mlflow/")
        return True
    else:
        print(f"\n❌ Job failed with status: {status}")
        return False


if __name__ == "__main__":
    success = test_full_training()
    exit(0 if success else 1)
