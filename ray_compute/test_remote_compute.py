#!/usr/bin/env python3
"""
Remote Job Validation Test
Run this on your REMOTE MACHINE (training/dev machine) to test the compute server
"""

import sys
import os
from pathlib import Path

# Add API client to path
sys.path.insert(0, str(Path(__file__).parent / "api"))

from client_remote import RemoteComputeClient, submit_training_job


def test_connection(server_url: str):
    """Test basic connectivity"""
    print(f"\n{'='*60}")
    print("1. Testing Connection")
    print('='*60)
    
    client = RemoteComputeClient(server_url)
    
    try:
        health = client.health_check()
        print(f"✓ Server health: {health['status']}")
        print(f"  - Ray: {health['ray']}")
        print(f"  - MLflow: {health['mlflow']}")
        return True
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False


def test_resources(server_url: str):
    """Test resource availability"""
    print(f"\n{'='*60}")
    print("2. Checking Available Resources")
    print('='*60)
    
    client = RemoteComputeClient(server_url)
    
    try:
        resources = client.get_resources()
        
        print("\nCluster Resources:")
        print(f"  - CPU: {resources['cluster_total']['cpu']} cores total, "
              f"{resources['available']['cpu']} available")
        print(f"  - Memory: {resources['cluster_total']['memory_bytes'] / 1e9:.1f} GB total, "
              f"{resources['available']['memory_bytes'] / 1e9:.1f} GB available")
        print(f"  - GPU: {resources['cluster_total']['gpu']} total, "
              f"{resources['available']['gpu']} available")
        
        if resources['gpus']:
            print("\nGPU Details:")
            for gpu in resources['gpus']:
                print(f"  [{gpu['id']}] {gpu['name']}")
                print(f"      Memory: {gpu['memory_used_mb']}/{gpu['memory_total_mb']} MB")
                print(f"      Utilization: {gpu['gpu_utilization']:.1f}%")
        
        return True
    except Exception as e:
        print(f"✗ Failed to get resources: {e}")
        return False


def test_cpu_job(server_url: str):
    """Test simple CPU job"""
    print(f"\n{'='*60}")
    print("3. Testing CPU Job Submission")
    print('='*60)
    
    code = """
import time
import os
from pathlib import Path

print("Starting CPU test job...")

# Get output directory from environment
output_dir = Path(os.environ.get('JOB_OUTPUT_DIR', '.'))

# Simple computation
result = sum(range(1000000))
print(f"Computation result: {result}")

# Create output file
with open(output_dir / 'cpu_result.txt', 'w') as f:
    f.write(f"Result: {result}\\n")
    f.write(f"Test completed successfully!\\n")

print(f"Output saved to {output_dir / 'cpu_result.txt'}")
print("CPU test job completed!")
"""
    
    client = RemoteComputeClient(server_url)
    
    try:
        # Submit job
        job_id = client.submit_job(
            name="remote_cpu_test",
            code=code,
            cpu=2,
            memory_gb=2,
            gpu=0,
            mlflow_experiment="remote-validation",
            cleanup_after=False  # Keep artifacts for verification
        )
        print(f"✓ Job submitted: {job_id}")
        
        # Wait for completion
        print("  Waiting for job to complete...")
        job = client.wait_for_job(job_id, timeout=300, poll_interval=5)
        
        print(f"✓ Job completed with status: {job['status']}")
        print(f"  MLflow Run ID: {job.get('mlflow_run_id', 'N/A')}")
        
        # Get logs
        logs = client.get_logs(job_id)
        print("\nJob Logs (last 500 chars):")
        print("-" * 60)
        print(logs[-500:])
        
        # Download artifacts
        if job['status'] == 'SUCCEEDED' and job.get('artifacts_ready'):
            print("\n  Downloading artifacts...")
            artifact_path = client.download_artifacts(job_id, output_dir="./test_results")
            print(f"✓ Artifacts downloaded to: {artifact_path}")
            
            # Verify artifact content
            result_file = artifact_path / "cpu_result.txt"
            if result_file.exists():
                print("\n  Artifact contents:")
                print("-" * 60)
                print(result_file.read_text())
                return True
            else:
                print("✗ Expected artifact not found")
                return False
        else:
            print(f"✗ Job failed: {job.get('error', 'Unknown error')}")
            return False
    
    except Exception as e:
        print(f"✗ CPU job test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gpu_job(server_url: str):
    """Test GPU job with PyTorch"""
    print(f"\n{'='*60}")
    print("4. Testing GPU Job Submission")
    print('='*60)
    
    code = """
import torch
import os
from pathlib import Path

print("Starting GPU test job...")
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"CUDA version: {torch.version.cuda}")
    print(f"GPU device: {torch.cuda.get_device_name(0)}")
    print(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
    
    # Simple GPU computation
    x = torch.randn(1000, 1000, device='cuda')
    y = torch.randn(1000, 1000, device='cuda')
    z = torch.matmul(x, y)
    
    result = z.sum().item()
    print(f"GPU computation result: {result}")
    
    # Get output directory
    output_dir = Path(os.environ.get('JOB_OUTPUT_DIR', '.'))
    
    # Save result
    with open(output_dir / 'gpu_result.txt', 'w') as f:
        f.write(f"PyTorch version: {torch.__version__}\\n")
        f.write(f"CUDA version: {torch.version.cuda}\\n")
        f.write(f"GPU: {torch.cuda.get_device_name(0)}\\n")
        f.write(f"Computation result: {result}\\n")
    
    print(f"Output saved to {output_dir / 'gpu_result.txt'}")
    print("GPU test job completed!")
else:
    print("ERROR: CUDA not available!")
    raise RuntimeError("CUDA not available")
"""
    
    client = RemoteComputeClient(server_url)
    
    try:
        # Submit job
        job_id = client.submit_job(
            name="remote_gpu_test",
            code=code,
            cpu=4,
            memory_gb=4,
            gpu=1,
            mlflow_experiment="remote-validation",
            cleanup_after=False  # Keep artifacts for verification
        )
        print(f"✓ Job submitted: {job_id}")
        
        # Wait for completion
        print("  Waiting for job to complete...")
        job = client.wait_for_job(job_id, timeout=300, poll_interval=5)
        
        print(f"✓ Job completed with status: {job['status']}")
        print(f"  MLflow Run ID: {job.get('mlflow_run_id', 'N/A')}")
        
        # Get logs
        logs = client.get_logs(job_id)
        print("\nJob Logs (last 500 chars):")
        print("-" * 60)
        print(logs[-500:])
        
        # Download artifacts
        if job['status'] == 'SUCCEEDED' and job.get('artifacts_ready'):
            print("\n  Downloading artifacts...")
            artifact_path = client.download_artifacts(job_id, output_dir="./test_results")
            print(f"✓ Artifacts downloaded to: {artifact_path}")
            
            # Verify artifact content
            result_file = artifact_path / "gpu_result.txt"
            if result_file.exists():
                print("\n  Artifact contents:")
                print("-" * 60)
                print(result_file.read_text())
                return True
            else:
                print("✗ Expected artifact not found")
                return False
        else:
            print(f"✗ Job failed: {job.get('error', 'Unknown error')}")
            return False
    
    except Exception as e:
        print(f"✗ GPU job test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all validation tests"""
    print("\n" + "="*60)
    print("Remote Ray Compute Server Validation")
    print("="*60)
    
    # Get server URL from environment or argument
    tailscale_ip = os.getenv("TAILSCALE_IP", "localhost")
    default_url = f"http://{tailscale_ip}:8266"
    
    if len(sys.argv) > 1:
        server_url = sys.argv[1]
    else:
        print(f"\nUsing default server URL: {default_url}")
        print("(Override with: python test_remote_compute.py <server_url>)")
        server_url = default_url
    
    print(f"\nServer: {server_url}")
    
    # Run tests
    results = {
        "Connection": test_connection(server_url),
        "Resources": test_resources(server_url),
        "CPU Job": test_cpu_job(server_url),
        "GPU Job": test_gpu_job(server_url)
    }
    
    # Summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print('='*60)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*60)
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
        print("Remote compute server is ready for production use.")
    else:
        print("⚠️  SOME TESTS FAILED")
        print("Please review the errors above.")
    print("="*60 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
