#!/usr/bin/env python3
"""Simple CUDA test in Ray job."""
import torch

print(f"PyTorch: {torch.__version__}")
print(f"CUDA compiled: {torch.version.cuda}")
print(f"CUDA available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"CUDA device count: {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        print(f"GPU {i}: {props.name} ({props.total_memory / 1e9:.1f} GB)")

    # Test actual CUDA operation
    x = torch.randn(100, 100).cuda()
    y = torch.randn(100, 100).cuda()
    z = torch.matmul(x, y)
    print(f"\n✅ CUDA tensor operation successful!")
    print(f"Result device: {z.device}")
else:
    print("\n⚠️  CUDA not available - will use CPU")
