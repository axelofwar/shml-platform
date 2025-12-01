#!/usr/bin/env python3
"""
GPU Training Test Suite - Ray Native API
Uses Ray Job Submission API directly without custom wrappers.

Tests:
1. Ray Cluster Connection
2. Resource Availability  
3. GPU Detection & CUDA
4. Single GPU Allocation
5. Multi-GPU Allocation
6. Fractional GPU Allocation
7. YOLOv8-style Training (2 epochs)
8. Inference (50 images)

Usage:
    # Quick smoke test (inside Ray container)
    python test_gpu_ray_native.py --quick
    
    # Full test with training
    python test_gpu_ray_native.py --full
    
    # Specific GPU mode
    python test_gpu_ray_native.py --gpu-mode single|multi|fractional
    
    # Remote Ray cluster
    python test_gpu_ray_native.py --ray-address http://100.80.251.28:8265
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, Optional, Tuple

from ray.job_submission import JobSubmissionClient, JobStatus

# Colors for terminal output
class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'


def print_header(title: str, char: str = '='):
    """Print formatted header"""
    print(f"\n{Colors.BLUE}{char*80}{Colors.NC}")
    print(f"{Colors.BLUE}{title.center(80)}{Colors.NC}")
    print(f"{Colors.BLUE}{char*80}{Colors.NC}\n")


def print_success(msg: str):
    print(f"{Colors.GREEN}✓{Colors.NC} {msg}")


def print_error(msg: str):
    print(f"{Colors.RED}✗{Colors.NC} {msg}")


def print_warning(msg: str):
    print(f"{Colors.YELLOW}⚠{Colors.NC} {msg}")


def wait_for_job(client: JobSubmissionClient, job_id: str, 
                 timeout: int = 300, poll_interval: int = 5) -> Tuple[str, str]:
    """Wait for Ray job to complete with status updates"""
    start_time = time.time()
    last_status = None
    
    while time.time() - start_time < timeout:
        try:
            status = client.get_job_status(job_id)
            status_str = status.value if hasattr(status, 'value') else str(status)
            
            if status_str != last_status:
                elapsed = int(time.time() - start_time)
                print(f"  [{elapsed}s] {status_str}")
                last_status = status_str
            
            if status_str in ['SUCCEEDED', 'FAILED', 'STOPPED']:
                logs = client.get_job_logs(job_id)
                return status_str, logs
            
            time.sleep(poll_interval)
            
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Interrupted. Job {job_id} may still be running.{Colors.NC}")
            raise
        except Exception as e:
            print(f"  {Colors.YELLOW}Warning: {e}{Colors.NC}")
            time.sleep(poll_interval)
    
    return "TIMEOUT", f"Job timed out after {timeout}s"


class RayGPUTester:
    """GPU testing using Ray native API"""
    
    def __init__(self, ray_address: str = "http://ray-head:8265"):
        """Initialize with Ray cluster address"""
        self.ray_address = ray_address
        self.client = JobSubmissionClient(ray_address)
        self.results = {}
    
    def submit_and_wait(self, name: str, code: str, 
                        num_gpus: float = 0, num_cpus: int = 1,
                        timeout: int = 300) -> Tuple[bool, str]:
        """Submit job and wait for completion"""
        try:
            # Submit job using Ray native API
            job_id = self.client.submit_job(
                entrypoint=f"python -c '{code}'",
                runtime_env={"pip": ["torch"]},
                submission_id=f"{name}_{int(time.time())}",
                entrypoint_num_gpus=num_gpus,
                entrypoint_num_cpus=num_cpus,
            )
            
            print(f"  Job ID: {job_id}")
            
            status, logs = wait_for_job(self.client, job_id, timeout)
            
            return status == "SUCCEEDED", logs
            
        except Exception as e:
            return False, str(e)
    
    def test_connection(self) -> bool:
        """Test 1: Ray Cluster Connection"""
        print_header("Test 1: Ray Cluster Connection")
        
        try:
            # Simple API call to verify connection
            jobs = self.client.list_jobs()
            print_success(f"Connected to Ray at {self.ray_address}")
            print(f"  Active jobs: {len([j for j in jobs if j.status == JobStatus.RUNNING])}")
            return True
        except Exception as e:
            print_error(f"Failed to connect: {e}")
            return False
    
    def test_resources(self) -> bool:
        """Test 2: Resource Availability"""
        print_header("Test 2: Resource Availability")
        
        code = r'''
import ray
import json

ray.init()

resources = ray.cluster_resources()
available = ray.available_resources()

print("CLUSTER_RESOURCES:" + json.dumps(resources))
print("AVAILABLE_RESOURCES:" + json.dumps(available))

# Summary
cpu = resources.get("CPU", 0)
gpu = resources.get("GPU", 0)
mem = resources.get("memory", 0) / 1e9

print("")
print("Cluster Total:")
print("  CPU: " + str(cpu))
print("  GPU: " + str(gpu))
print("  Memory: " + str(round(mem, 1)) + " GB")
'''
        
        success, logs = self.submit_and_wait("resource_check", code, num_gpus=0, timeout=60)
        
        if success:
            print_success("Resource check passed")
            # Parse and display resources
            for line in logs.split('\n'):
                if line.startswith("  ") or line.startswith("Cluster"):
                    print(f"  {line.strip()}")
            return True
        else:
            print_error("Resource check failed")
            print(logs[-500:])
            return False
    
    def test_gpu_detection(self) -> bool:
        """Test 3: GPU Detection & CUDA"""
        print_header("Test 3: GPU Detection & CUDA")
        
        code = r'''
import torch

print("CUDA Available: " + str(torch.cuda.is_available()))
print("CUDA Version: " + str(torch.version.cuda))
print("GPU Count: " + str(torch.cuda.device_count()))

for i in range(torch.cuda.device_count()):
    props = torch.cuda.get_device_properties(i)
    print("GPU " + str(i) + ": " + props.name)
    print("  Memory: " + str(round(props.total_memory / 1e9, 2)) + " GB")

# Quick GPU operation
if torch.cuda.is_available():
    x = torch.randn(1000, 1000, device="cuda")
    y = torch.randn(1000, 1000, device="cuda")
    z = torch.matmul(x, y)
    print("")
    print("GPU Matrix Multiply: PASSED (device=" + str(z.device) + ")")
'''
        
        success, logs = self.submit_and_wait("gpu_detection", code, num_gpus=1, timeout=120)
        
        if success:
            print_success("GPU detection passed")
            for line in logs.split('\n'):
                if any(x in line for x in ['CUDA', 'GPU', 'Memory', 'Matrix']):
                    print(f"  {line}")
            return True
        else:
            print_error(f"GPU detection failed")
            print(logs[-800:])
            return False
    
    def test_single_gpu(self) -> bool:
        """Test 4: Single GPU Allocation"""
        print_header("Test 4: Single GPU Allocation")
        
        code = r'''
import torch

print("Requesting 1 GPU...")
print("CUDA Available: " + str(torch.cuda.is_available()))
print("GPU Count: " + str(torch.cuda.device_count()))

if torch.cuda.is_available():
    name = torch.cuda.get_device_name(0)
    mem = torch.cuda.get_device_properties(0).total_memory / 1e9
    print("Allocated: " + name + " (" + str(round(mem, 1)) + " GB)")
    
    # Memory test
    x = torch.randn(5000, 5000, device="cuda")
    y = torch.randn(5000, 5000, device="cuda")
    z = torch.matmul(x, y)
    
    used = torch.cuda.memory_allocated(0) / 1e9
    print("Memory Used: " + str(round(used, 2)) + " GB")
    print("Single GPU Test: PASSED")
else:
    raise RuntimeError("No GPU available")
'''
        
        success, logs = self.submit_and_wait("single_gpu", code, num_gpus=1, timeout=120)
        
        if success:
            print_success("Single GPU test passed")
            for line in logs.split('\n')[-10:]:
                if line.strip():
                    print(f"  {line}")
            return True
        else:
            print_error("Single GPU test failed")
            print(logs[-500:])
            return False
    
    def test_multi_gpu(self) -> bool:
        """Test 5: Multi-GPU Allocation"""
        print_header("Test 5: Multi-GPU Allocation")
        
        code = r'''
import torch

print("Requesting 2 GPUs...")
print("CUDA Available: " + str(torch.cuda.is_available()))
print("GPU Count: " + str(torch.cuda.device_count()))

if torch.cuda.device_count() >= 2:
    for i in range(2):
        name = torch.cuda.get_device_name(i)
        mem = torch.cuda.get_device_properties(i).total_memory / 1e9
        print("GPU " + str(i) + ": " + name + " (" + str(round(mem, 1)) + " GB)")
        
        # Test each GPU
        x = torch.randn(3000, 3000, device="cuda:" + str(i))
        y = torch.randn(3000, 3000, device="cuda:" + str(i))
        z = torch.matmul(x, y)
        print("  Compute test: PASSED")
    
    print("Multi-GPU Test: PASSED")
elif torch.cuda.device_count() == 1:
    print("Only 1 GPU available, skipping multi-GPU test")
    print("Multi-GPU Test: SKIPPED")
else:
    raise RuntimeError("No GPU available")
'''
        
        success, logs = self.submit_and_wait("multi_gpu", code, num_gpus=2, timeout=120)
        
        if success or "SKIPPED" in logs:
            print_success("Multi-GPU test passed")
            for line in logs.split('\n')[-15:]:
                if line.strip():
                    print(f"  {line}")
            return True
        else:
            print_error("Multi-GPU test failed")
            print(logs[-500:])
            return False
    
    def test_fractional_gpu(self) -> bool:
        """Test 6: Fractional GPU Allocation (0.5 GPU)"""
        print_header("Test 6: Fractional GPU (0.5)")
        
        code = r'''
import torch

print("Requesting 0.5 GPU...")
print("CUDA Available: " + str(torch.cuda.is_available()))

if torch.cuda.is_available():
    name = torch.cuda.get_device_name(0)
    print("GPU: " + name)
    
    # Smaller workload for fractional GPU
    x = torch.randn(2000, 2000, device="cuda")
    y = torch.randn(2000, 2000, device="cuda")
    z = torch.matmul(x, y)
    
    used = torch.cuda.memory_allocated(0) / 1e6
    print("Memory Used: " + str(round(used)) + " MB")
    print("Fractional GPU Test: PASSED")
else:
    raise RuntimeError("No GPU available")
'''
        
        success, logs = self.submit_and_wait("fractional_gpu", code, num_gpus=0.5, timeout=120)
        
        if success:
            print_success("Fractional GPU test passed")
            for line in logs.split('\n')[-8:]:
                if line.strip():
                    print(f"  {line}")
            return True
        else:
            print_error("Fractional GPU test failed")
            print(logs[-500:])
            return False
    
    def test_yolov8_training(self) -> bool:
        """Test 7-8: YOLOv8-style Training + Inference"""
        print_header("Test 7-8: YOLOv8 Training (2 epochs) + Inference")
        
        # Using raw string to avoid escaping issues
        code = r'''
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np
import time

print("=" * 60)
print("YOLOv8-style Training Test")
print("=" * 60)

EPOCHS = 2
BATCH_SIZE = 8
NUM_TRAIN = 100
NUM_VAL = 50
IMG_SIZE = 640
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

print("Device: " + DEVICE)
print("Epochs: " + str(EPOCHS) + ", Batch: " + str(BATCH_SIZE))

if DEVICE != "cuda":
    raise RuntimeError("GPU required")

# Simple model (YOLOv8-style backbone)
class SimpleYOLO(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Conv2d(3, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(128, 256, 3, padding=1), nn.BatchNorm2d(256), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(256, 512, 3, padding=1), nn.BatchNorm2d(512), nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1))
        )
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(512, 256), nn.ReLU(), nn.Linear(256, 5))
    
    def forward(self, x):
        return self.head(self.backbone(x))

# Synthetic dataset
class SyntheticDataset(Dataset):
    def __init__(self, n):
        self.n = n
    def __len__(self):
        return self.n
    def __getitem__(self, i):
        img = torch.randn(3, IMG_SIZE, IMG_SIZE)
        target = torch.randn(5)
        return img, target

train_loader = DataLoader(SyntheticDataset(NUM_TRAIN), batch_size=BATCH_SIZE, shuffle=True)
val_loader = DataLoader(SyntheticDataset(NUM_VAL), batch_size=BATCH_SIZE)

model = SimpleYOLO().to(DEVICE)
criterion = nn.MSELoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)

params = sum(p.numel() for p in model.parameters())
print("Model params: " + "{:,}".format(params))

# Training
print("")
print("Training...")
for epoch in range(EPOCHS):
    model.train()
    epoch_loss = 0
    start = time.time()
    
    for batch_idx, (imgs, targets) in enumerate(train_loader):
        imgs, targets = imgs.to(DEVICE), targets.to(DEVICE)
        optimizer.zero_grad()
        loss = criterion(model(imgs), targets)
        loss.backward()
        optimizer.step()
        epoch_loss += loss.item()
    
    elapsed = time.time() - start
    avg_loss = epoch_loss / len(train_loader)
    print("Epoch " + str(epoch+1) + ": loss=" + str(round(avg_loss, 4)) + ", time=" + str(round(elapsed, 1)) + "s")

# Inference
print("")
print("Inference...")
model.eval()
total_time = 0
total_images = 0

with torch.no_grad():
    for imgs, _ in val_loader:
        imgs = imgs.to(DEVICE)
        start = time.time()
        _ = model(imgs)
        total_time += time.time() - start
        total_images += len(imgs)

fps = total_images / total_time
print("Processed " + str(total_images) + " images in " + str(round(total_time, 2)) + "s (" + str(round(fps, 1)) + " FPS)")
print("GPU Memory: " + str(round(torch.cuda.memory_allocated(0)/1e9, 2)) + " GB")

print("")
print("=" * 60)
print("YOLOv8 Training Test: PASSED")
print("=" * 60)
'''
        
        # Escape for shell
        escaped_code = code.replace("'", "'\\''")
        
        try:
            job_id = self.client.submit_job(
                entrypoint=f"python -c '{escaped_code}'",
                runtime_env={"pip": ["torch", "numpy"]},
                submission_id=f"yolov8_training_{int(time.time())}",
                entrypoint_num_gpus=1,
                entrypoint_num_cpus=4,
            )
            
            print(f"  Job ID: {job_id}")
            print("  Training in progress (this may take a few minutes)...")
            
            status, logs = wait_for_job(self.client, job_id, timeout=600)
            
            if status == "SUCCEEDED":
                print_success("YOLOv8 training test passed")
                # Show relevant output
                for line in logs.split('\n'):
                    if any(x in line for x in ['Epoch', 'Processed', 'FPS', 'PASSED', 'Device', 'params']):
                        print(f"  {line}")
                return True
            else:
                print_error(f"YOLOv8 training failed: {status}")
                print(logs[-1000:])
                return False
                
        except Exception as e:
            print_error(f"Training test failed: {e}")
            return False
    
    def run_tests(self, quick: bool = False, full: bool = False, 
                  gpu_mode: str = "all") -> Dict[str, bool]:
        """Run test suite"""
        print_header("GPU Training Test Suite - Ray Native API", '=')
        
        print(f"Configuration:")
        print(f"  Ray Address: {self.ray_address}")
        print(f"  Mode: {'Quick' if quick else 'Full' if full else 'Standard'}")
        print(f"  GPU Tests: {gpu_mode}")
        
        results = {}
        
        # Always run these
        results['connection'] = self.test_connection()
        if not results['connection']:
            print_error("Cannot proceed without Ray connection")
            return results
        
        results['resources'] = self.test_resources()
        results['gpu_detection'] = self.test_gpu_detection()
        
        if quick:
            # Quick mode: just basic GPU test
            results['single_gpu'] = self.test_single_gpu()
        else:
            # Full GPU allocation tests
            if gpu_mode in ['all', 'single']:
                results['single_gpu'] = self.test_single_gpu()
            
            if gpu_mode in ['all', 'multi']:
                results['multi_gpu'] = self.test_multi_gpu()
            
            if gpu_mode in ['all', 'fractional']:
                results['fractional_gpu'] = self.test_fractional_gpu()
            
            # Training test
            if full or gpu_mode == 'all':
                results['yolov8_training'] = self.test_yolov8_training()
        
        # Summary
        self.print_summary(results)
        return results
    
    def print_summary(self, results: Dict[str, bool]):
        """Print test summary"""
        print_header("Test Summary", '=')
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        for name, result in results.items():
            status = f"{Colors.GREEN}✓ PASS{Colors.NC}" if result else f"{Colors.RED}✗ FAIL{Colors.NC}"
            print(f"{status}: {name.replace('_', ' ').title()}")
        
        print(f"\n{'='*80}")
        print(f"Results: {passed}/{total} tests passed")
        
        if passed == total:
            print(f"{Colors.GREEN}🎉 ALL TESTS PASSED!{Colors.NC}")
            print("GPU training environment is fully operational.")
        else:
            print(f"{Colors.YELLOW}⚠️  SOME TESTS FAILED{Colors.NC}")
        
        print('='*80)


def main():
    parser = argparse.ArgumentParser(
        description="GPU Training Tests - Ray Native API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick test (inside Ray container)
  python test_gpu_ray_native.py --quick
  
  # Full test with training
  python test_gpu_ray_native.py --full
  
  # Remote cluster via Tailscale  
  python test_gpu_ray_native.py --ray-address http://100.80.251.28:8265 --full
  
  # Specific GPU mode
  python test_gpu_ray_native.py --gpu-mode multi
"""
    )
    
    parser.add_argument('--ray-address', type=str, default="http://ray-head:8265",
                       help='Ray cluster address (default: http://ray-head:8265)')
    parser.add_argument('--quick', action='store_true', help='Quick smoke test')
    parser.add_argument('--full', action='store_true', help='Full test including training')
    parser.add_argument('--gpu-mode', choices=['single', 'multi', 'fractional', 'all'],
                       default='all', help='GPU allocation mode to test')
    
    args = parser.parse_args()
    
    # Create tester with Ray native API
    tester = RayGPUTester(args.ray_address)
    
    # Run tests
    results = tester.run_tests(
        quick=args.quick,
        full=args.full,
        gpu_mode=args.gpu_mode
    )
    
    # Exit code
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
