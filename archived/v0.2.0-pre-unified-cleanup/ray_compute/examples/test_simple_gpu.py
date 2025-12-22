#!/usr/bin/env python3
"""
Simple GPU Test - Verify Ray GPU allocation works
Submit from ray-compute-api container: python3 /workspace/examples/test_simple_gpu.py
"""

from ray.job_submission import JobSubmissionClient
import time

RAY_ADDRESS = "http://ray-head:8265"


def test_simple_gpu():
    """Test basic GPU availability and allocation"""
    client = JobSubmissionClient(RAY_ADDRESS)

    print("=" * 70)
    print("Simple GPU Test")
    print("=" * 70)

    job_id = client.submit_job(
        entrypoint="python -c \"import torch; print(f'GPU Available: {torch.cuda.is_available()}'); print(f'GPU Count: {torch.cuda.device_count()}'); [print(f'GPU {i}: {torch.cuda.get_device_name(i)}') for i in range(torch.cuda.device_count())]\"",
        runtime_env={"pip": ["torch"]},
        submission_id=f"test_simple_gpu_{int(time.time())}",
        entrypoint_num_gpus=1,
        entrypoint_num_cpus=1,
    )

    tailscale_ip = os.getenv("TAILSCALE_IP", "localhost")
    print(f"✅ Job submitted: {job_id}")
    print(f"   Dashboard: http://{tailscale_ip}/ray/#/jobs/{job_id}")
    print()

    # Wait for completion
    print("Waiting for job to complete...")
    for i in range(60):
        status = client.get_job_status(job_id)
        if i == 0 or i % 10 == 0:
            print(f"  [{i*2}s] Status: {status}")

        if status in ["SUCCEEDED", "FAILED", "STOPPED"]:
            break

        time.sleep(2)

    # Get logs
    print()
    print("=" * 70)
    print("Job Logs:")
    print("=" * 70)
    logs = client.get_job_logs(job_id)
    print(logs)

    print()
    print("=" * 70)
    print(f"Final Status: {status}")
    print("=" * 70)

    return status == "SUCCEEDED"


if __name__ == "__main__":
    success = test_simple_gpu()
    exit(0 if success else 1)
