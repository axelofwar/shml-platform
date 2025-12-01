#!/usr/bin/env python3
"""
Test script for Ray job submission server
Tests GPU availability and basic job execution
"""

import requests
import json
import time
from pathlib import Path

# Configuration
API_URL = "http://localhost:8266"

def test_health():
    """Test health endpoint"""
    print("Testing health endpoint...")
    resp = requests.get(f"{API_URL}/health")
    print(f"Status: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    return resp.status_code == 200

def test_resources():
    """Test resources endpoint"""
    print("\nTesting resources endpoint...")
    resp = requests.get(f"{API_URL}/resources")
    print(f"Status: {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    return resp.status_code == 200

def submit_gpu_test_job():
    """Submit a simple GPU test job"""
    print("\nSubmitting GPU test job...")
    
    job_data = {
        "name": "gpu-test",
        "job_type": "custom",
        "code": """
import torch
import os

print("=" * 50)
print("GPU Test Job")
print("=" * 50)

# Check PyTorch CUDA availability
cuda_available = torch.cuda.is_available()
print(f"CUDA Available: {cuda_available}")

if cuda_available:
    print(f"CUDA Version: {torch.version.cuda}")
    print(f"Number of GPUs: {torch.cuda.device_count()}")
    
    for i in range(torch.cuda.device_count()):
        print(f"\\nGPU {i}: {torch.cuda.get_device_name(i)}")
        print(f"  Memory Allocated: {torch.cuda.memory_allocated(i) / 1024**2:.2f} MB")
        print(f"  Memory Reserved: {torch.cuda.memory_reserved(i) / 1024**2:.2f} MB")
    
    # Simple tensor operation on GPU
    print("\\nPerforming simple GPU operation...")
    x = torch.randn(1000, 1000).cuda()
    y = torch.randn(1000, 1000).cuda()
    z = torch.matmul(x, y)
    print(f"Matrix multiplication result shape: {z.shape}")
    print(f"Result device: {z.device}")
    print("GPU operation completed successfully!")
else:
    print("No GPU available - running on CPU")

print("\\n" + "=" * 50)
print("Test completed!")
print("=" * 50)
""",
        "requirements": {
            "cpu": 2,
            "memory_gb": 4,
            "gpu": 1,
            "timeout_minutes": 10
        },
        "mlflow_experiment": "gpu-tests",
        "mlflow_tags": {
            "test_type": "gpu_availability",
            "automated": "true"
        },
        "env_vars": {},
        "return_artifacts": True,
        "cleanup_after": False  # Keep artifacts for inspection
    }
    
    resp = requests.post(f"{API_URL}/jobs/submit", json=job_data)
    print(f"Status: {resp.status_code}")
    
    if resp.status_code == 200:
        job_info = resp.json()
        print(f"Job submitted successfully!")
        print(f"Job ID: {job_info['job_id']}")
        print(f"Status: {job_info['status']}")
        return job_info['job_id']
    else:
        print(f"Error: {resp.text}")
        return None

def wait_for_job(job_id, timeout=300):
    """Wait for job to complete"""
    print(f"\nWaiting for job {job_id} to complete...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        resp = requests.get(f"{API_URL}/jobs/{job_id}")
        if resp.status_code == 200:
            job_info = resp.json()
            status = job_info['status']
            print(f"Status: {status}")
            
            if status in ['SUCCEEDED', 'FAILED', 'STOPPED']:
                return job_info
        
        time.sleep(5)
    
    print("Timeout waiting for job")
    return None

def get_job_logs(job_id):
    """Get job logs"""
    print(f"\nFetching logs for job {job_id}...")
    resp = requests.get(f"{API_URL}/jobs/{job_id}/logs")
    
    if resp.status_code == 200:
        logs = resp.json()['logs']
        print("\n" + "=" * 80)
        print("JOB LOGS")
        print("=" * 80)
        print(logs)
        print("=" * 80)
    else:
        print(f"Failed to get logs: {resp.status_code}")

def main():
    """Run all tests"""
    print("=" * 80)
    print("Ray Job Submission Server Test Suite")
    print("=" * 80)
    
    # Test health
    if not test_health():
        print("\nHealth check failed - server may not be ready")
        return
    
    # Test resources
    test_resources()
    
    # Submit GPU test job
    job_id = submit_gpu_test_job()
    if not job_id:
        print("\nJob submission failed")
        return
    
    # Wait for completion
    job_info = wait_for_job(job_id)
    if not job_info:
        return
    
    print(f"\nJob completed with status: {job_info['status']}")
    
    # Get logs
    get_job_logs(job_id)
    
    print("\n" + "=" * 80)
    print("Test suite completed!")
    print("=" * 80)

if __name__ == "__main__":
    main()
